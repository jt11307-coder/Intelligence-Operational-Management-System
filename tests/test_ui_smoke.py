"""The window opens against an empty database."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from wpd_compstat.ui.main_window import NAV, MainWindow


def test_main_window_opens_without_fabricated_counts(session):
    application = QApplication.instance() or QApplication([])
    window = MainWindow(session)
    window.show()
    titles = [label for label, _key in NAV]
    assert "Executive Dashboard" in titles
    assert "PDF Import" in titles
    assert session.conn.execute("SELECT COUNT(*) AS n FROM incidents").fetchone()["n"] == 0
    window.close()
    application.processEvents()
