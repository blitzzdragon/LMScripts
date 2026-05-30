import os
import re
import shutil
import subprocess
import tempfile
import time
from collections import defaultdict
from pathlib import Path


class DeepCleaner:
    def __init__(self, cli):
        self.cli = cli
        self.user_home = Path.home()
        self.warnings = []

    def run(self):
        self.cli.log("Starting deep system analysis...\n")
        results = {}

        results["disk_usage"] = self.analyze_disk_usage()
        results["large_files"] = self.find_large_files()
        results["temp_files"] = self.analyze_temp_files()
        results["duplicates"] = self.find_duplicates()
        results["old_kernels"] = self.check_old_kernels()
        results["broken_symlinks"] = self.find_broken_symlinks()
        results["empty_dirs"] = self.find_empty_dirs()
        results["dotfile_clutter"] = self.analyze_dotfile_clutter()
        results["flatpak_bloat"] = self.analyze_flatpak()
        results["snap_bloat"] = self.analyze_snap()
        results["pip_cache"] = self.analyze_pip()

        return results

    def analyze_disk_usage(self):
        self.cli.log("[1/11] Analyzing disk usage...")
        try:
            result = subprocess.run(
                ["df", "-h", "--output=source,fstype,size,used,avail,pcent,target"],
                capture_output=True, text=True, timeout=10
            )
            lines = result.stdout.strip().split("\n")
            return {"raw": result.stdout, "lines": lines}
        except Exception as e:
            return {"error": str(e)}

    def find_large_files(self, min_size_mb=100):
        self.cli.log(f"[2/11] Searching for files >{min_size_mb}MB...")
        large = []
        search_dirs = [
            self.user_home / "Downloads",
            self.user_home / "Desktop",
            self.user_home / "Documents",
            self.user_home / ".cache",
            self.user_home / ".local/share/Trash",
        ]
        for d in search_dirs:
            if not d.exists():
                continue
            try:
                for p in d.rglob("*"):
                    try:
                        if p.is_file() and p.stat().st_size > min_size_mb * 1024 * 1024:
                            large.append((p, p.stat().st_size))
                    except (OSError, PermissionError):
                        pass
            except (PermissionError, OSError):
                pass
        large.sort(key=lambda x: x[1], reverse=True)
        return large[:50]

    def analyze_temp_files(self):
        self.cli.log("[3/11] Scanning temp directories...")
        temp_dirs = ["/tmp", str(self.user_home / ".cache")]
        total_size = 0
        file_count = 0
        for d in temp_dirs:
            p = Path(d)
            if not p.exists():
                continue
            try:
                for f in p.rglob("*"):
                    try:
                        if f.is_file():
                            total_size += f.stat().st_size
                            file_count += 1
                    except (OSError, PermissionError):
                        pass
            except (PermissionError, OSError):
                pass
        return {"file_count": file_count, "total_size_bytes": total_size}

    def find_duplicates(self):
        self.cli.log("[4/11] Checking for duplicate files (name+size match)...")
        seen = defaultdict(list)
        dupes = []
        search_dirs = [
            self.user_home / "Downloads",
            self.user_home / "Desktop",
            self.user_home / "Pictures",
            self.user_home / "Documents",
        ]
        for d in search_dirs:
            if not d.exists():
                continue
            try:
                for p in d.rglob("*"):
                    try:
                        if p.is_file() and not p.is_symlink():
                            key = (p.name, p.stat().st_size)
                            seen[key].append(p)
                    except (OSError, PermissionError):
                        pass
            except (PermissionError, OSError):
                pass
        for key, paths in seen.items():
            if len(paths) > 1:
                dupes.append((key, paths))
        return dupes

    def check_old_kernels(self):
        self.cli.log("[5/11] Checking old kernel versions...")
        try:
            result = subprocess.run(
                ["dpkg", "--list"],
                capture_output=True, text=True, timeout=15
            )
            kernels = re.findall(r"linux-image-([\d.]+-[\d]+)", result.stdout)
            current = subprocess.run(
                ["uname", "-r"], capture_output=True, text=True, timeout=5
            ).stdout.strip()
            old = sorted(set(k for k in kernels if k != current))
            return {"current": current, "old": old}
        except Exception as e:
            return {"error": str(e)}

    def find_broken_symlinks(self):
        self.cli.log("[6/11] Finding broken symlinks...")
        broken = []
        search_dirs = [
            self.user_home,
            "/usr/local/bin",
            "/opt",
        ]
        for d in search_dirs:
            p = Path(d)
            if not p.exists():
                continue
            try:
                for f in p.rglob("*"):
                    try:
                        if f.is_symlink() and not f.exists():
                            broken.append(f)
                    except OSError:
                        pass
            except (PermissionError, OSError):
                pass
        return broken

    def find_empty_dirs(self):
        self.cli.log("[7/11] Finding empty directories...")
        empty = []
        search_dirs = [self.user_home / "Documents", self.user_home / "Downloads"]
        for d in search_dirs:
            if not d.exists():
                continue
            try:
                for p in d.rglob("*"):
                    try:
                        if p.is_dir() and not any(p.iterdir()):
                            empty.append(p)
                    except (PermissionError, OSError):
                        pass
            except (PermissionError, OSError):
                pass
        return empty

    def analyze_dotfile_clutter(self):
        self.cli.log("[8/11] Checking dotfile clutter in $HOME...")
        dotfiles = []
        try:
            for p in self.user_home.iterdir():
                if p.name.startswith(".") and p.is_file():
                    dotfiles.append(p)
        except (PermissionError, OSError):
            pass
        return dotfiles

    def analyze_flatpak(self):
        self.cli.log("[9/11] Checking Flatpak bloat...")
        if not shutil.which("flatpak"):
            return {"status": "not installed"}
        try:
            result = subprocess.run(
                ["flatpak", "list", "--columns=application,size"],
                capture_output=True, text=True, timeout=15
            )
            lines = result.stdout.strip().split("\n")[1:]
            apps = []
            for line in lines:
                parts = line.strip().split()
                if len(parts) >= 2:
                    apps.append({"name": parts[0], "size": " ".join(parts[1:])})
            return {"apps": apps}
        except Exception as e:
            return {"error": str(e)}

    def analyze_snap(self):
        self.cli.log("[10/11] Checking Snap bloat...")
        if not shutil.which("snap"):
            return {"status": "not installed"}
        try:
            result = subprocess.run(
                ["snap", "list"],
                capture_output=True, text=True, timeout=15
            )
            lines = result.stdout.strip().split("\n")
            return {"raw": result.stdout, "lines": lines}
        except Exception as e:
            return {"error": str(e)}

    def analyze_pip(self):
        self.cli.log("[11/11] Checking pip cache...")
        cache_dir = self.user_home / ".cache/pip"
        if not cache_dir.exists():
            return {"status": "no cache found"}
        total = 0
        count = 0
        try:
            for f in cache_dir.rglob("*"):
                if f.is_file():
                    total += f.stat().st_size
                    count += 1
        except OSError:
            pass
        return {"file_count": count, "size_bytes": total}

    def get_recommendations(self, summary):
        recs = []
        temp = summary.get("temp_files", {})
        if temp.get("total_size_bytes", 0) > 500 * 1024 * 1024:
            recs.append("Clean ~/.cache - it's over 500MB")
        if summary.get("old_kernels", {}).get("old", []):
            recs.append("Remove old kernels to free boot space")
        if summary.get("broken_symlinks", []):
            recs.append(f"Fix {len(summary['broken_symlinks'])} broken symlinks")
        if summary.get("duplicates"):
            total = sum(len(v) - 1 for _, v in summary["duplicates"])
            recs.append(f"Review {total} duplicate files for cleanup")
        if summary.get("empty_dirs"):
            recs.append(f"Remove {len(summary['empty_dirs'])} empty directories")
        return recs
