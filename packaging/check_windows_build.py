"""Report whether a Windows executable can be produced here."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


def main() -> int:
    exe = Path("build/dist/WPDCompstat.exe")
    launcher = Path("build/dist/WPDCompstatLauncher.exe")
    print(f"platform={sys.platform}")
    print(f"wine={shutil.which('wine') is not None}")
    print(f"pyinstaller={shutil.which('pyinstaller') is not None}")
    print(f"application_exe_exists={exe.is_file()}")
    print(f"launcher_exe_exists={launcher.is_file()}")
    if os.name != "nt":
        print("Windows executables were not built. PyInstaller cross-compilation to Windows is not available.")
        return 2
    return 0 if exe.is_file() and launcher.is_file() else 2


if __name__ == "__main__":
    raise SystemExit(main())
