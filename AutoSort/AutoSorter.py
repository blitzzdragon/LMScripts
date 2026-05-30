#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import logging
import logging.handlers
import os
import shutil
import stat
import subprocess
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Optional

HOME = Path.home()
DOWNLOADS_DIR = HOME / "Downloads"
CONFIG_DIR = HOME / ".config" / "autosorter"
RULES_FILE = CONFIG_DIR / "rules.json"
LOCK_FILE = Path("/tmp") / "autosorter.lock"
LOG_DIR = HOME / ".local" / "share" / "autosorter"
LOG_FILE = LOG_DIR / "autosorter.log"
UNDO_FILE = LOG_DIR / "undo.json"
STATS_FILE = LOG_DIR / "stats.json"
SYSTEMD_UNIT = Path.home() / ".config" / "systemd" / "user" / "autosorter.service"
SYSTEMD_PATH_UNIT = (
    Path.home() / ".config" / "systemd" / "user" / "autosorter-path.service"
)

DEFAULT_RULES: dict[str, dict[str, list[str]]] = {
    "Pictures": {
        "extensions": [
            ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".bmp",
            ".tiff", ".tif", ".heic", ".heif", ".avif", ".raw", ".cr2",
            ".nef", ".arw", ".dng", ".ico", ".icns",
        ],
        "subfolders": {
            "Screenshots": ["screenshot", "screen shot", "screen capture"],
        },
    },
    "Videos": {
        "extensions": [
            ".mp4", ".mov", ".avi", ".mkv", ".wmv", ".flv", ".m4v",
            ".webm", ".ogv", ".ts", ".mts", ".m2ts", ".3gp",
        ],
        "subfolders": {},
    },
    "Music": {
        "extensions": [
            ".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a", ".opus",
            ".aiff", ".wma", ".alac", ".ac3", ".dts",
        ],
        "subfolders": {},
    },
    "Documents": {
        "extensions": [
            ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
            ".odt", ".ods", ".odp", ".epub", ".txt", ".md", ".csv",
            ".tsv", ".rtf", ".tex", ".bib", ".pages", ".numbers",
            ".key", ".ps", ".eps",
        ],
        "subfolders": {},
    },
    "Archives": {
        "extensions": [
            ".zip", ".tar", ".gz", ".bz2", ".xz", ".7z", ".rar",
            ".zst", ".tgz", ".tbz2",
        ],
        "subfolders": {},
    },
    "Code": {
        "extensions": [
            ".py", ".js", ".ts", ".html", ".css", ".scss", ".json",
            ".xml", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf",
            ".sh", ".bash", ".zsh", ".fish", ".ps1", ".bat", ".cmd",
            ".c", ".cpp", ".h", ".hpp", ".java", ".kt", ".swift",
            ".go", ".rs", ".rb", ".php", ".pl", ".lua", ".r", ".m",
            ".sql", ".sqlite", ".db",
        ],
        "subfolders": {},
    },
    "Disk Images": {
        "extensions": [".iso", ".img", ".vhd", ".vhdx", ".vmdk", ".qcow2", ".dmg"],
        "subfolders": {},
    },
    "Fonts": {
        "extensions": [".ttf", ".otf", ".woff", ".woff2", ".eot"],
        "subfolders": {},
    },
}

SAFELOCK_MIN_AGE = 30
SAFELOCK_MIN_SIZE = 1024
SAFELOCK_MAX_SIZE = 5_000_000_000
POLL_INTERVAL = 5

log = logging.getLogger("AutoSorter")


def setup_logging(verbose: bool = False, quiet: bool = False):
    root = logging.getLogger()
    root.setLevel(
        logging.DEBUG if verbose else logging.WARNING if quiet else logging.INFO
    )

    fmt = logging.Formatter(
        "%(asctime)s %(levelname)-7s %(message)s", datefmt="%H:%M:%S"
    )

    ch = logging.StreamHandler()
    ch.setLevel(logging.DEBUG if verbose else logging.INFO)
    ch.setFormatter(fmt)
    root.addHandler(ch)

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    fh = logging.handlers.RotatingFileHandler(
        str(LOG_FILE), maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    root.addHandler(fh)


def acquire_lock() -> bool:
    try:
        if LOCK_FILE.exists():
            pid = int(LOCK_FILE.read_text().strip())
            try:
                os.kill(pid, 0)
                log.error("Another instance is already running (PID %d).", pid)
                return False
            except (OSError, ProcessLookupError):
                pass
        LOCK_FILE.write_text(str(os.getpid()))
        return True
    except OSError as e:
        log.warning("Could not acquire lock: %s", e)
        return True


def release_lock():
    try:
        LOCK_FILE.unlink(missing_ok=True)
    except OSError:
        pass


def safelock_check(path: Path) -> Optional[str]:
    try:
        st = path.stat()
    except OSError:
        return "cannot stat"

    name = path.name.lower()
    if name.startswith("."):
        return "hidden file"
    if any(
        name.endswith(sfx)
        for sfx in (
            ".part", ".crdownload", ".download", ".tmp", ".temp",
            ".!ut", ".partial",
        )
    ):
        return "partial download"
    if name.startswith("._"):
        return "AppleDouble metadata"

    age = time.time() - st.st_mtime
    if age < SAFELOCK_MIN_AGE:
        return f"too young ({age:.0f}s < {SAFELOCK_MIN_AGE}s)"

    if st.st_size < SAFELOCK_MIN_SIZE:
        return "too small"
    if st.st_size > SAFELOCK_MAX_SIZE:
        return "too large"

    try:
        before = st.st_size
        time.sleep(0.3)
        after = path.stat().st_size
        if after > before:
            return f"still growing ({before} -> {after} bytes)"
    except OSError:
        pass

    try:
        fd = os.open(path, os.O_RDONLY | os.O_EXLOCK)
        os.close(fd)
    except (OSError, AttributeError):
        try:
            fd = os.open(path, os.O_RDWR | os.O_EXCL | os.O_NONBLOCK)
            os.close(fd)
        except OSError:
            try:
                fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
                os.close(fd)
            except OSError:
                return "in use / locked"

    if st.st_mode & stat.S_IEXEC and path.suffix.lower() in (
        ".sh", ".bin", ".run", ".AppImage",
    ):
        log.debug("Executable detected: %s", path.name)

    return None


def load_rules() -> dict[str, dict]:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if RULES_FILE.exists():
        try:
            return json.loads(RULES_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    RULES_FILE.write_text(json.dumps(DEFAULT_RULES, indent=2))
    return dict(DEFAULT_RULES)


def build_ext_map(rules: dict) -> dict[str, tuple[str, Optional[str]]]:
    ext_map: dict[str, tuple[str, Optional[str]]] = {}
    for category, cfg in rules.items():
        for ext in cfg.get("extensions", []):
            ext_map[ext.lower()] = (category, None)
    return ext_map


def get_dest(path: Path, rules: dict, ext_map: dict) -> Optional[Path]:
    ext = path.suffix.lower()
    entry = ext_map.get(ext)
    if entry is None:
        return None

    category, _ = entry
    name_lower = path.stem.lower()

    subfolder = None
    for cat_cfg in rules.values():
        for sf_name, keywords in cat_cfg.get("subfolders", {}).items():
            if any(kw in name_lower for kw in keywords):
                subfolder = sf_name
                break

    base = HOME / category
    if subfolder:
        base = base / subfolder
    return base


class UndoLog:
    def __init__(self):
        self.entries: list[dict] = []

    def record(self, src: str, dst: str):
        self.entries.append(
            {"src": src, "dst": dst, "time": datetime.now().isoformat()}
        )

    def save(self):
        UNDO_FILE.parent.mkdir(parents=True, exist_ok=True)
        existing = []
        if UNDO_FILE.exists():
            try:
                existing = json.loads(UNDO_FILE.read_text())
            except (json.JSONDecodeError, OSError):
                existing = []
        existing.append({"run": datetime.now().isoformat(), "moves": self.entries})
        UNDO_FILE.write_text(json.dumps(existing[-50:], indent=2))

    @staticmethod
    def undo_last():
        if not UNDO_FILE.exists():
            log.info("No undo history found.")
            return 0
        try:
            history = json.loads(UNDO_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            log.info("Undo history corrupted.")
            return 0
        if not history:
            return 0
        last_run = history.pop()
        restored = 0
        for move in reversed(last_run["moves"]):
            src, dst = Path(move["dst"]), Path(move["src"])
            if not src.exists():
                log.debug("Cannot undo %s - no longer exists.", src.name)
                continue
            try:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src), str(dst))
                log.info("Undo: %s  <-  %s/", src.name, dst.parent.name)
                restored += 1
            except Exception as e:
                log.warning("Undo failed for %s: %s", src.name, e)
        UNDO_FILE.write_text(json.dumps(history, indent=2))
        log.info("Undo complete: %d files restored.", restored)
        return restored


def unique_dest(dest: Path, strategy: str = "rename") -> Optional[Path]:
    if not dest.exists():
        return dest
    if strategy == "skip":
        return None
    if strategy == "overwrite":
        return dest
    stem, suffix = dest.stem, dest.suffix
    for counter in range(1, 999):
        candidate = dest.with_name(f"{stem}_{counter}{suffix}")
        if not candidate.exists():
            return candidate
    return None


def sort_once(
    rules: dict,
    ext_map: dict,
    dry_run: bool = False,
    backup: bool = False,
    conflict: str = "rename",
) -> tuple[int, int, UndoLog]:
    if not DOWNLOADS_DIR.exists():
        log.warning("Downloads folder not found: %s", DOWNLOADS_DIR)
        return 0, 0, UndoLog()

    undo = UndoLog()
    moved = 0
    skipped = 0

    for item in sorted(DOWNLOADS_DIR.iterdir()):
        if item.is_dir():
            continue

        reason = safelock_check(item)
        if reason:
            log.debug("Safed %s: %s", item.name, reason)
            skipped += 1
            continue

        dest_dir = get_dest(item, rules, ext_map)
        if dest_dir is None:
            skipped += 1
            continue

        dest_path = unique_dest(dest_dir / item.name, conflict)
        if dest_path is None:
            log.debug("Conflict skip: %s", item.name)
            skipped += 1
            continue

        if dry_run:
            log.info("[DRY] %s  ->  %s/", item.name, dest_dir.name)
            moved += 1
            continue

        try:
            dest_dir.mkdir(parents=True, exist_ok=True)
            if backup:
                shutil.copy2(str(item), str(dest_path))
                log.info("Backup %s  ->  %s/", item.name, dest_dir.name)
            else:
                shutil.move(str(item), str(dest_path))
                log.info("Moved  %s  ->  %s/", item.name, dest_dir.name)
            undo.record(str(item), str(dest_path))
            moved += 1
        except PermissionError:
            log.debug("In use: %s", item.name)
            skipped += 1
        except Exception as e:
            log.warning("Failed %s: %s", item.name, e)
            skipped += 1

    return moved, skipped, undo


def update_stats(moved: int, skipped: int):
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    history = []
    if STATS_FILE.exists():
        try:
            history = json.loads(STATS_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            history = []
    today = datetime.now().strftime("%Y-%m-%d")
    if history and history[-1]["date"] == today:
        history[-1]["moved"] += moved
        history[-1]["skipped"] += skipped
    else:
        history.append({"date": today, "moved": moved, "skipped": skipped})
    STATS_FILE.write_text(json.dumps(history[-365:], indent=2))


def send_notification(title: str, msg: str):
    try:
        subprocess.run(
            ["notify-send", title, msg, "--hint=int:transient:1"],
            capture_output=True,
            timeout=5,
        )
    except Exception:
        pass


def watch_poll(
    rules: dict, ext_map: dict, backup: bool = False, conflict: str = "rename"
):
    log.info("Polling %s every %ds...", DOWNLOADS_DIR, POLL_INTERVAL)
    try:
        while True:
            moved, skipped, _ = sort_once(
                rules, ext_map, backup=backup, conflict=conflict
            )
            if moved:
                update_stats(moved, skipped)
                send_notification(
                    "AutoSorter", f"Moved {moved} file{'s' if moved != 1 else ''}."
                )
            time.sleep(POLL_INTERVAL)
    except KeyboardInterrupt:
        pass


def watch_inotify(
    rules: dict, ext_map: dict, backup: bool = False, conflict: str = "rename"
):
    try:
        from watchdog.events import FileSystemEventHandler
        from watchdog.observers import Observer
    except ImportError:
        log.warning(
            "watchdog not installed - falling back to polling. pip install watchdog"
        )
        watch_poll(rules, ext_map, backup, conflict)
        return

    class Handler(FileSystemEventHandler):
        def on_created(self, event):
            if event.is_directory:
                return
            time.sleep(2)
            moved, skipped, _ = sort_once(
                rules, ext_map, backup=backup, conflict=conflict
            )
            if moved:
                update_stats(moved, skipped)
                send_notification(
                    "AutoSorter", f"Moved {moved} file{'s' if moved != 1 else ''}."
                )

    observer = Observer()
    observer.schedule(Handler(), str(DOWNLOADS_DIR), recursive=False)
    observer.start()
    log.info("Watching %s via inotify...", DOWNLOADS_DIR)
    try:
        while observer.is_alive():
            observer.join(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()


def install_systemd(watch_mode: str = "poll"):
    script = os.path.abspath(__file__)
    venv = "/home/blitzzdrag0n/CustomComputerScripts/venv/bin/python3"
    interpreter = venv if Path(venv).exists() else sys.executable

    path = SYSTEMD_UNIT
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"""[Unit]
Description=AutoSorter - Downloads Organizer
After=network.target

[Service]
Type=simple
ExecStart={interpreter} {script} --{watch_mode}
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=default.target
""")

    subprocess.run(["systemctl", "--user", "daemon-reload"], timeout=10)
    subprocess.run(["systemctl", "--user", "enable", "autosorter.service"], timeout=10)
    subprocess.run(["systemctl", "--user", "start", "autosorter.service"], timeout=10)
    log.info("Systemd user service installed + started.")


def uninstall_systemd():
    for unit in ["autosorter.service", "autosorter-path.service"]:
        subprocess.run(
            ["systemctl", "--user", "stop", unit], stderr=subprocess.DEVNULL, timeout=10
        )
        subprocess.run(
            ["systemctl", "--user", "disable", unit],
            stderr=subprocess.DEVNULL,
            timeout=10,
        )
    for p in [SYSTEMD_UNIT, SYSTEMD_PATH_UNIT]:
        p.unlink(missing_ok=True)
    subprocess.run(["systemctl", "--user", "daemon-reload"], timeout=10)
    log.info("Systemd service uninstalled.")


def show_stats():
    print(f"\n{'=' * 50}")
    print(f"  AutoSorter Stats")
    print(f"{'=' * 50}")
    if STATS_FILE.exists():
        try:
            history = json.loads(STATS_FILE.read_text())
            total_moved = sum(h["moved"] for h in history)
            total_skipped = sum(h["skipped"] for h in history)
            recent = history[-7:] if len(history) >= 7 else history
            print(f"  All time: {total_moved} moved, {total_skipped} skipped")
            print(f"  Last 7 days:")
            for day in recent:
                print(
                    f"    {day['date']}: {day['moved']} moved, {day['skipped']} skipped"
                )
        except (json.JSONDecodeError, OSError) as e:
            print(f"  Error reading stats: {e}")
    else:
        print(f"  No stats yet.")
    print(f"{'=' * 50}\n")


def show_config():
    rules = load_rules()
    print(f"\n{'=' * 50}")
    print(f"  AutoSorter Config")
    print(f"{'=' * 50}")
    for category, cfg in rules.items():
        exts = cfg.get("extensions", [])
        subs = cfg.get("subfolders", {})
        dest = HOME / category
        print(f"\n  {category}  ->  {dest}/")
        for ext in exts[:5]:
            print(f"    {ext}")
        if len(exts) > 5:
            print(f"    ... and {len(exts) - 5} more")
        if subs:
            for sf, kws in subs.items():
                print(f"    {sf}/  (keywords: {', '.join(kws)})")
    print(f"{'=' * 50}\n")


def main():
    parser = argparse.ArgumentParser(
        description="AutoSorter - Downloads organizer with safelocks",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 AutoSorter.py              Watch (polling)
  python3 AutoSorter.py --watch      Watch (inotify, faster)
  python3 AutoSorter.py --once       Single pass
  python3 AutoSorter.py --dry-run    Preview
  python3 AutoSorter.py --undo       Reverse last run
  python3 AutoSorter.py --backup     Copy instead of move
  python3 AutoSorter.py --config     Show current rules
  python3 AutoSorter.py --stats      Show history
  python3 AutoSorter.py --install    Systemd service
  python3 AutoSorter.py --uninstall  Remove systemd service
        """,
    )
    parser.add_argument(
        "--watch", action="store_true", help="Watch with inotify (fast)"
    )
    parser.add_argument("--once", action="store_true", help="Single pass then exit")
    parser.add_argument("--dry-run", action="store_true", help="Preview only")
    parser.add_argument("--undo", action="store_true", help="Reverse last run")
    parser.add_argument("--backup", action="store_true", help="Copy instead of move")
    parser.add_argument(
        "--conflict",
        choices=["rename", "skip", "overwrite"],
        default="rename",
        help="Conflict resolution (default: rename)",
    )
    parser.add_argument("--config", action="store_true", help="Show config")
    parser.add_argument("--stats", action="store_true", help="Show stats")
    parser.add_argument(
        "--install", action="store_true", help="Install systemd service"
    )
    parser.add_argument(
        "--uninstall", action="store_true", help="Remove systemd service"
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Debug logging")
    parser.add_argument("-q", "--quiet", action="store_true", help="Suppress output")

    args = parser.parse_args()
    setup_logging(verbose=args.verbose, quiet=args.quiet)

    if args.config:
        show_config()
        return
    if args.stats:
        show_stats()
        return
    if args.install:
        install_systemd("watch" if args.watch else "poll")
        return
    if args.uninstall:
        uninstall_systemd()
        return

    rules = load_rules()
    ext_map = build_ext_map(rules)

    if args.undo:
        UndoLog.undo_last()
        return

    if args.dry_run:
        log.info("=== DRY RUN ===")
        moved, skipped, _ = sort_once(
            rules, ext_map, dry_run=True, backup=args.backup, conflict=args.conflict
        )
        log.info("Would move: %d | Would skip: %d", moved, skipped)
        return

    if args.once:
        if not acquire_lock():
            return
        moved, skipped, undo = sort_once(
            rules, ext_map, backup=args.backup, conflict=args.conflict
        )
        undo.save()
        update_stats(moved, skipped)
        if moved:
            send_notification(
                "AutoSorter", f"Moved {moved} file{'s' if moved != 1 else ''}."
            )
        log.info("Moved: %d | Skipped: %d", moved, skipped)
        release_lock()
        return

    if not acquire_lock():
        return
    try:
        if args.watch:
            watch_inotify(rules, ext_map, backup=args.backup, conflict=args.conflict)
        else:
            watch_poll(rules, ext_map, backup=args.backup, conflict=args.conflict)
    finally:
        release_lock()


if __name__ == "__main__":
    main()
