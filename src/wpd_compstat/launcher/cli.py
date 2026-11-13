"""Launcher command line."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from wpd_compstat.launcher.scan import find_installations, launch_plan


def drive_roots_from_environment() -> list[Path]:
    configured = os.environ.get("WPD_COMPSTAT_DRIVES")
    if configured:
        return [Path(item) for item in configured.split(os.pathsep) if item]
    if os.name == "nt":
        return [Path(f"{letter}:\\") for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ" if Path(f"{letter}:\\").exists()]
    roots = []
    for base in (Path("/media"), Path("/mnt"), Path("/run/media")):
        if base.is_dir():
            roots.extend(child for child in base.iterdir() if child.is_dir())
    return roots


def child_environment() -> dict[str, str]:
    """Give the source-mode child the directory that contains this package."""
    import wpd_compstat

    env = os.environ.copy()
    src = str(Path(wpd_compstat.__file__).resolve().parents[1])
    current = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = src if not current else os.pathsep.join((src, current))
    return env


def main(argv: list[str] | None = None, *, drives: list[Path] | None = None, selector=None, start: bool = True) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    found, _problems = find_installations(drives if drives is not None else drive_roots_from_environment())
    plan = launch_plan(
        found,
        selector=selector,
        allow_source=os.environ.get("WPD_COMPSTAT_ALLOW_SOURCE") == "1",
        python_executable=sys.executable,
    )
    if not plan["ok"]:
        print(plan["message"])
        for choice in plan.get("choices") or []:
            print(choice)
        return int(plan["code"])
    if not start or "--plan-only" in argv:
        print(" ".join(plan["argv"]))
        return 0
    subprocess.Popen(plan["argv"], env=child_environment())
    return 0
