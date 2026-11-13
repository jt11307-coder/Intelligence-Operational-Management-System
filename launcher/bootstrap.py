"""Bootstrap copied onto the external drive and into the local launcher folder."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _prepare_path() -> None:
    source = os.environ.get("WPD_COMPSTAT_SOURCE")
    if source:
        src = Path(source) / "src"
        if src.is_dir():
            sys.path.insert(0, str(src))


def main() -> int:
    _prepare_path()
    from wpd_compstat.launcher.cli import main as cli_main

    return cli_main(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
