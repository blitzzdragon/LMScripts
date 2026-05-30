import shutil
from datetime import datetime


class Cli:
    def __init__(self):
        self.width = shutil.get_terminal_size().columns

    def show_header(self):
        print("=" * self.width)
        print(" DeepCleaner - System Analyzer".center(self.width))
        print(f" {datetime.now().strftime('%Y-%m-%d %H:%M')}".center(self.width))
        print("=" * self.width)
        print()

    def log(self, message):
        print(f"  >> {message}")

    def show_summary(self, results):
        print()
        print("=" * self.width)
        print(" SUMMARY".center(self.width))
        print("=" * self.width)
        self._print_disk_usage(results.get("disk_usage"))
        self._print_large_files(results.get("large_files", []))
        self._print_temp_files(results.get("temp_files", {}))
        self._print_duplicates(results.get("duplicates", []))
        self._print_old_kernels(results.get("old_kernels", {}))
        self._print_broken_symlinks(results.get("broken_symlinks", []))
        self._print_empty_dirs(results.get("empty_dirs", []))
        self._print_dotfiles(results.get("dotfile_clutter", []))
        self._print_flatpak(results.get("flatpak_bloat", {}))
        self._print_snap(results.get("snap_bloat", {}))
        self._print_pip(results.get("pip_cache", {}))
        print("=" * self.width)

    def _print_section(self, title, content_fn):
        if title:
            print(f"\n  [{title}]")
        content_fn()

    def _human(self, n):
        if n < 1024:
            return f"{n} B"
        elif n < 1024**2:
            return f"{n / 1024:.1f} KB"
        elif n < 1024**3:
            return f"{n / 1024**2:.1f} MB"
        return f"{n / 1024**3:.2f} GB"

    def _print_disk_usage(self, data):
        if not data or "error" in data:
            return
        self._print_section("", lambda: None)
        lines = data.get("lines", [])
        for line in lines[:2]:
            print(f"    {line}")
        for line in lines[2:]:
            parts = line.split()
            if len(parts) >= 6:
                print(f"    {parts[0]:20s} {parts[5]:>5s}  {parts[3]:>8s} / {parts[1]:>8s}")

    def _print_large_files(self, files):
        if not files:
            return
        self._print_section("Large Files", lambda: None)
        for path, size in files[:10]:
            print(f"    {self._human(size):>8s}  {path}")

    def _print_temp_files(self, data):
        if not data:
            return
        count = data.get("file_count", 0)
        size = data.get("total_size_bytes", 0)
        self._print_section("Temp / Cache", lambda: None)
        print(f"    {count} files, {self._human(size)}")

    def _print_duplicates(self, dupes):
        if not dupes:
            return
        self._print_section("Duplicates", lambda: None)
        for (name, size), paths in dupes[:5]:
            print(f"    {self._human(size):>8s}  {name} ({len(paths)} copies)")

    def _print_old_kernels(self, data):
        if "error" in data:
            return
        old = data.get("old", [])
        if not old:
            return
        self._print_section("Old Kernels", lambda: None)
        for k in old:
            print(f"    linux-image-{k}")

    def _print_broken_symlinks(self, links):
        if not links:
            return
        self._print_section("Broken Symlinks", lambda: None)
        for link in links[:10]:
            print(f"    {link}")

    def _print_empty_dirs(self, dirs):
        if not dirs:
            return
        self._print_section("Empty Directories", lambda: None)
        for d in dirs[:10]:
            print(f"    {d}")

    def _print_dotfiles(self, files):
        if not files:
            return
        self._print_section("Dotfiles in $HOME", lambda: None)
        for f in files[:10]:
            print(f"    {f.name}")

    def _print_flatpak(self, data):
        if not data or "status" in data:
            return
        apps = data.get("apps", [])
        if not apps:
            return
        self._print_section("Flatpak Apps", lambda: None)
        for app in apps:
            print(f"    {app['name']:40s} {app['size']}")

    def _print_snap(self, data):
        if not data or "status" in data:
            return
        if "error" in data:
            return

    def _print_pip(self, data):
        if not data or "status" in data:
            return
        size = data.get("size_bytes", 0)
        count = data.get("file_count", 0)
        self._print_section("Pip Cache", lambda: None)
        print(f"    {count} files, {self._human(size)}")

    def show_recommendations(self, recs):
        if not recs:
            return
        print()
        print("-" * self.width)
        print(" RECOMMENDATIONS".center(self.width))
        print("-" * self.width)
        for r in recs:
            print(f"  * {r}")
        print("-" * self.width)
        print()
