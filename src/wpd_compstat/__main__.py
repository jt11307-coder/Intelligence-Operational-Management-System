"""Application entry point."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="wpd-compstat")
    parser.add_argument("--root", help="Path to the WPD COMPSTAT installation folder")
    args = parser.parse_args(argv)
    if args.root is None:
        print("Pass --root with the installation folder named 'WPD COMPSTAT'.", file=sys.stderr)
        return 2
    root = Path(args.root)
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
    from PySide6.QtWidgets import QApplication, QMessageBox

    from wpd_compstat.paths import use_install_temp
    from wpd_compstat.session import Session
    from wpd_compstat.ui.login import LoginDialog, SetupDialog
    from wpd_compstat.ui.main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("WPD COMPSTAT")
    session = Session(root)
    use_install_temp(session.paths)
    state = session.state()
    if state == "new":
        if not SetupDialog(session).exec():
            return 1
    elif state != "ready":
        QMessageBox.critical(
            None,
            "WPD COMPSTAT",
            "This installation is incomplete. Restore an encrypted backup or create a new installation folder. "
            "A second key will not be created for an existing database.",
        )
        return 1
    if session.locked:
        if not LoginDialog(session).exec():
            return 1
    window = MainWindow(session)
    window.show()
    code = app.exec()
    session.close()
    return int(code)


if __name__ == "__main__":
    raise SystemExit(main())
