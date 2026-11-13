"""Rewrite the desktop shortcut. It does not invent a drive letter if the drive is missing."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wpd_compstat.launcher.cli import drive_roots_from_environment
from wpd_compstat.launcher.scan import find_installations
from wpd_compstat.launcher.shortcut import shortcut_text_has_drive_letter, write_desktop_shortcuts


def repair(desktop: Path, drives: list[Path] | None = None) -> int:
    found, problems = find_installations(drives if drives is not None else drive_roots_from_environment())
    if not found:
        print("The WPD COMPSTAT drive is not connected. The shortcut was not pointed at a drive letter.")
        for problem in problems:
            print(problem)
        return 2
    written = write_desktop_shortcuts(desktop)
    for path in written:
        text = path.read_text(encoding="utf-8")
        if shortcut_text_has_drive_letter(text):
            print("Refusing a shortcut that contains a hardcoded drive letter.")
            return 3
    print(f"Shortcut rewritten for installation {found[0].installation_id}.")
    if len(found) > 1:
        print("More than one installation is connected. The shortcut still starts the chooser.")
    return 0


if __name__ == "__main__":
    desktop = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.home() / "Desktop"
    raise SystemExit(repair(desktop))
