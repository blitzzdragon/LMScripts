#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path

START = time.time()


def _get_size(path: str | Path) -> int:
    p = Path(path)
    if not p.exists():
        return 0
    if p.is_file() or p.is_symlink():
        try:
            return p.stat().st_size
        except OSError:
            return 0
    total = 0
    try:
        for entry in p.iterdir():
            try:
                if entry.is_dir() and not entry.is_symlink():
                    total += _get_size(entry)
                elif entry.is_file() or entry.is_symlink():
                    total += entry.stat().st_size
            except OSError:
                continue
    except (PermissionError, OSError):
        pass
    return total


def _human(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    elif n < 1024**2:
        return f"{n / 1024:.1f} KB"
    elif n < 1024**3:
        return f"{n / 1024**2:.1f} MB"
    return f"{n / 1024**3:.2f} GB"


def _clear_dir(path: Path, dry_run: bool = False) -> int:
    if not path.exists():
        return 0
    freed = 0
    try:
        for child in path.iterdir():
            try:
                freed += _get_size(child)
                if not dry_run:
                    if child.is_dir() and not child.is_symlink():
                        shutil.rmtree(child, ignore_errors=True)
                    else:
                        child.unlink(missing_ok=True)
            except OSError:
                continue
    except (PermissionError, OSError):
        pass
    return freed


def _rm(paths: list[Path | str], dry_run: bool = False) -> int:
    freed = 0
    for pattern in paths:
        p = Path(os.path.expanduser(str(pattern)))
        parts = str(p).split("*")
        if len(parts) > 1:
            base = Path(parts[0]).parent if "*" in str(p) else p
            if not base.exists():
                continue
            try:
                for match in base.glob(p.name if p.name else "*"):
                    freed += _get_size(match)
                    if not dry_run:
                        try:
                            if match.is_dir():
                                shutil.rmtree(match, ignore_errors=True)
                            else:
                                match.unlink(missing_ok=True)
                        except OSError:
                            pass
            except OSError:
                continue
        else:
            freed += _get_size(p)
            if not dry_run:
                try:
                    if p.is_dir():
                        shutil.rmtree(p, ignore_errors=True)
                    else:
                        p.unlink(missing_ok=True)
                except OSError:
                    pass
    return freed


USER = Path.home()


def clean_thumbnails(dry: bool) -> tuple[str, int]:
    freed = _clear_dir(USER / ".cache/thumbnails", dry)
    return ("Thumbnail caches", freed)


def clean_font_cache(dry: bool) -> tuple[str, int]:
    freed = _clear_dir(USER / ".cache/fontconfig", dry)
    return ("Font cache", freed)


def clean_pip_cache(dry: bool) -> tuple[str, int]:
    freed = _clear_dir(USER / ".cache/pip", dry)
    return ("Pip cache", freed)


def clean_flatpak_cache(dry: bool) -> tuple[str, int]:
    freed = _rm([Path("/var/tmp/flatpak-cache-*")], dry)
    freed += _rm([USER / ".local/share/flatpak/repo/tmp"], dry)
    return ("Flatpak cache", freed)


def clean_app_caches(dry: bool) -> tuple[str, int]:
    targets = [
        USER / ".cache/mozilla/firefox/*/cache2",
        USER / ".cache/google-chrome/Default/Cache",
        USER / ".cache/google-chrome/Default/Code Cache",
        USER / ".cache/chromium/Default/Cache",
        USER / ".cache/chromium/Default/Code Cache",
        USER / ".cache/brave-browser/Default/Cache",
        USER / ".cache/vivaldi/Default/Cache",
        USER / ".cache/microsoft-edge/Default/Cache",
        USER / ".cache/discord/Cache",
        USER / ".cache/slack/Cache",
        USER / ".config/slack/Cache",
        USER / ".cache/thunderbird/*/cache",
        USER / ".cache/evolution/mail",
        USER / ".cache/spotify/Data",
        USER / ".cache/spotify/Browser",
        USER / ".var/app/com.spotify.Client/cache",
        USER / ".cache/transmission",
        USER / ".cache/qbittorrent",
        USER / ".cache/vlc",
        USER / ".cache/thumbnails/large",
        USER / ".cache/thumbnails/normal",
        USER / ".cache/thumbnails/fail",
        USER / ".cache/doc",
        USER / ".cache/gstreamer-1.0",
    ]
    return ("App caches", _rm(targets, dry))


def clean_trash(dry: bool) -> tuple[str, int]:
    freed = 0
    targets = [
        USER / ".local/share/Trash/files",
        USER / ".local/share/Trash/expunged",
    ]
    if os.geteuid() == 0:
        targets.append(Path("/root/.local/share/Trash/files"))
    for trash in targets:
        freed += _clear_dir(trash, dry)
    return ("Trash", freed)


def clean_journal_logs(dry: bool) -> tuple[str, int]:
    if os.geteuid() != 0:
        return ("Journal logs (skipped — needs root)", 0)
    if dry:
        return ("Journal logs", 0)
    subprocess.run(
        ["journalctl", "--vacuum-time=3d"], capture_output=True, text=True, timeout=60
    )
    return ("Journal logs (>3d)", 0)


def clean_apt_cache(dry: bool) -> tuple[str, int]:
    if os.geteuid() != 0:
        return ("APT cache (skipped — needs root)", 0)
    if dry:
        return ("APT cache", 0)

    cache_dir = Path("/var/cache/apt/archives")
    before = _get_size(cache_dir)

    try:
        subprocess.run(
            ["apt-get", "clean"],
            capture_output=True,
            timeout=120,
        )
        subprocess.run(
            ["apt-get", "autoclean", "-y"],
            capture_output=True,
            timeout=120,
        )
        subprocess.run(
            ["apt-get", "autoremove", "-y"],
            capture_output=True,
            timeout=120,
        )
    except Exception as e:
        return (f"APT cache (error: {e})", 0)

    after = _get_size(cache_dir)
    freed = before - after
    return ("APT cache", max(0, freed))


def clean_snap_cache(dry: bool) -> tuple[str, int]:
    if os.geteuid() != 0:
        return ("Snap cache (skipped — needs root)", 0)
    if dry:
        return ("Snap cache", 0)
    try:
        subprocess.run(
            ["snap", "list", "--all"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        subprocess.run(
            ["snap", "set", "system", "refresh.retain=2"],
            capture_output=True,
            timeout=30,
        )
        subprocess.run(
            [
                "sh",
                "-c",
                'snap list --all | awk \'/disabled/{print $1, $3}\' | while read name rev; do snap remove "$name" --revision="$rev"; done',
            ],
            capture_output=True,
            timeout=120,
        )
    except Exception:
        pass
    return ("Snap old revisions", 0)


def clean_docker_cache(dry: bool) -> tuple[str, int]:
    if os.geteuid() != 0:
        return ("Docker cache (skipped — needs root)", 0)
    if not shutil.which("docker"):
        return ("Docker cache (not installed)", 0)
    if dry:
        return ("Docker cache", 0)
    try:
        r = subprocess.run(
            ["docker", "system", "prune", "-af", "--volumes"],
            capture_output=True,
            text=True,
            timeout=120,
        )
        freed = 0
        for line in r.stdout.splitlines():
            if "reclaimed" in line.lower():
                match = re.search(r"([\d.]+)\s*(KB|MB|GB)", line)
                if match:
                    val, unit = float(match.group(1)), match.group(2)
                    multipliers = {"KB": 1024, "MB": 1024**2, "GB": 1024**3}
                    freed = int(val * multipliers.get(unit, 1))
        return ("Docker prune", freed)
    except Exception:
        return ("Docker prune", 0)


def clean_tmp(dry: bool) -> tuple[str, int]:
    if os.geteuid() != 0:
        return ("/tmp (skipped — needs root)", 0)
    if dry:
        return ("/tmp (>1d)", 0)
    freed = 0
    tmp = Path("/tmp")
    now = time.time()
    try:
        for child in tmp.iterdir():
            try:
                stat = child.stat()
                age = now - stat.st_atime
                if age < 86400:
                    continue
                freed += _get_size(child)
                if child.is_dir():
                    shutil.rmtree(child, ignore_errors=True)
                else:
                    child.unlink(missing_ok=True)
            except OSError:
                continue
    except (PermissionError, OSError):
        pass
    return ("/tmp (>1d)", freed)


def clean_old_logs(dry: bool) -> tuple[str, int]:
    if os.geteuid() != 0:
        return ("Old logs (skipped — needs root)", 0)
    freed = 0
    varlog = Path("/var/log")
    patterns = ["*.gz", "*.1", "*.2", "*.3", "*.old", "*.bak"]
    for pattern in patterns:
        for match in varlog.glob(pattern):
            freed += _get_size(match)
            if not dry:
                try:
                    match.unlink(missing_ok=True)
                except OSError:
                    pass
    return ("Rotated logs", freed)


def clean_bash_history(dry: bool) -> tuple[str, int]:
    hist = USER / ".bash_history"
    if not hist.exists():
        return (".bash_history", 0)
    before = _get_size(hist)
    if dry:
        return (".bash_history", 0)
    try:
        lines = hist.read_text().splitlines()
        if len(lines) > 500:
            hist.write_text("\n".join(lines[-500:]) + "\n")
    except OSError:
        pass
    after = _get_size(hist)
    return (".bash_history", max(0, before - after))


def clean_mint_report_crashes(dry: bool) -> tuple[str, int]:
    freed = 0
    for d in [USER / ".local/share/cinnamon/crash", Path("/var/crash")]:
        freed += _clear_dir(d, dry)
    return ("Crash reports", freed)


def clean_spotify_ads(dry: bool) -> tuple[str, int]:
    targets = [
        USER / ".config/spotify/Users/*/ads-enabled",
        USER / ".var/app/com.spotify.Client/config/spotify/Users/*/ads-enabled",
    ]
    return ("Spotify ads", _rm(targets, dry))


def clean_flatpak_unused(dry: bool) -> tuple[str, int]:
    if os.geteuid() != 0:
        return ("Flatpak unused (skipped — needs root)", 0)
    if not shutil.which("flatpak"):
        return ("Flatpak unused (not installed)", 0)
    if dry:
        return ("Flatpak unused", 0)
    try:
        subprocess.run(
            ["flatpak", "uninstall", "--unused", "-y"],
            capture_output=True,
            timeout=120,
        )
    except Exception:
        pass
    return ("Flatpak unused", 0)


def clean_package_manager_lists(dry: bool) -> tuple[str, int]:
    if os.geteuid() != 0:
        return ("APT lists (skipped — needs root)", 0)
    freed = _clear_dir(Path("/var/lib/apt/lists"), dry)
    if not dry:
        subprocess.run(["apt-get", "update"], capture_output=True, timeout=120)
    return ("APT lists (re-downloaded)", freed)


CLEANERS = [
    clean_thumbnails,
    clean_font_cache,
    clean_pip_cache,
    clean_app_caches,
    clean_trash,
    clean_bash_history,
    clean_mint_report_crashes,
    clean_spotify_ads,
    clean_old_logs,
    clean_tmp,
    clean_apt_cache,
    clean_journal_logs,
    clean_snap_cache,
    clean_flatpak_cache,
    clean_flatpak_unused,
    clean_docker_cache,
    clean_package_manager_lists,
]

SUMMARY_FILE = USER / ".local/share/autocleaner/history.json"


def run_clean(dry_run: bool = False):
    results: list[dict] = []
    total = 0

    print(f"{'AutoCleaner'}{' (dry run)' if dry_run else ''}")
    print(f"{'=' * 50}")

    for cleaner in CLEANERS:
        label = cleaner.__name__.replace("clean_", "").replace("_", " ").title()
        try:
            actual_label, freed = cleaner(dry_run)
            total += freed
            if freed > 0 or "skipped" in actual_label.lower():
                print(f"  {actual_label:40s} {_human(freed):>8s}")
            results.append({"task": actual_label, "bytes_freed": freed})
        except Exception as e:
            print(f"  {label:40s} ERROR: {e}")
            results.append({"task": label, "bytes_freed": 0, "error": str(e)})

    elapsed = time.time() - START
    print(f"{'=' * 50}")
    print(f"  TOTAL RECLAIMED           {_human(total):>8s}")
    print(f"  Time: {elapsed:.1f}s")
    print()

    msg = f"Cleared {_human(total)} of junk. ({elapsed:.1f}s)"
    if not dry_run:
        subprocess.run(
            ["notify-send", "AutoCleaner", msg, "--hint=int:transient:1"],
            capture_output=True,
            timeout=5,
        )

    SUMMARY_FILE.parent.mkdir(parents=True, exist_ok=True)
    history = []
    if SUMMARY_FILE.exists():
        try:
            history = json.loads(SUMMARY_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            history = []
    history.append(
        {
            "timestamp": datetime.now().isoformat(),
            "dry_run": dry_run,
            "total_bytes": total,
            "elapsed_seconds": round(elapsed, 1),
            "tasks": results,
        }
    )
    SUMMARY_FILE.write_text(json.dumps(history[-90:], indent=2))

    return total


if __name__ == "__main__":
    import sys

    dry = "--dry-run" in sys.argv
    run_clean(dry_run=dry)
