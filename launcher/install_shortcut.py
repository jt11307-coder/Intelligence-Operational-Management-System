"""Desktop shortcut installer. The shortcut uses LOCALAPPDATA and no drive letter."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wpd_compstat.launcher.shortcut import local_launcher_dir, write_desktop_shortcuts


def install(desktop: Path | None = None) -> Path:
    local_dir = local_launcher_dir()
    local_dir.mkdir(parents=True, exist_ok=True)
    bootstrap = Path(__file__).with_name("bootstrap.py")
    if bootstrap.exists():
        shutil.copy2(bootstrap, local_dir / "bootstrap.py")
    readme = local_dir / "README.txt"
    readme.write_text(
        "This folder holds the local launcher only.\n"
        "The application and all operational data stay on the external drive.\n"
        "WPDCompstatLauncher.exe is produced by the Windows packaging script.\n",
        encoding="utf-8",
    )
    desktop_dir = desktop or _desktop()
    write_desktop_shortcuts(desktop_dir)
    return local_dir


def _desktop() -> Path:
    home = Path.home()
    for candidate in (home / "Desktop", home / "desktop"):
        if candidate.is_dir():
            return candidate
    return home


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    print(install(target))
