"""Every sidebar tab switches the page, shows a visible heading, and never fails silently."""

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QMessageBox, QTextEdit

from wpd_compstat.ui.main_window import NAV, MainWindow


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


def test_clicking_every_tab_shows_its_page(app, session, monkeypatch):
    errors, boxes = [], []
    monkeypatch.setattr(sys, "excepthook", lambda *exc: errors.append(exc))
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: boxes.append(args[2]))
    window = MainWindow(session)
    window.resize(1536, 790)
    window.show()
    app.processEvents()
    for label, key in reversed(NAV):
        button = window._nav_buttons[key]
        QTest.mouseClick(button, Qt.MouseButton.LeftButton)
        app.processEvents()
        page = window._pages[key]
        assert window.stack.currentWidget() is page, label
        assert button.isChecked() and all(not other.isChecked() for name, other in window._nav_buttons.items() if name != key)
        titles = [item for item in page.findChildren(QLabel) if item.objectName() == "pageTitle"]
        assert titles and titles[0].isVisible() and titles[0].text().casefold() == label.casefold()
        output = getattr(page, "output", None)
        if isinstance(output, QTextEdit):
            assert output.toPlainText() or output.placeholderText(), f"{label} opens empty with no instructions"
        assert label in window.statusBar().currentMessage()
    assert errors == [] and boxes == []
    window.close()
    app.processEvents()


def test_page_errors_are_logged_without_details_and_shown(app, session, monkeypatch):
    boxes = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: boxes.append(args[2]))
    window = MainWindow(session)

    def broken():
        raise ValueError("SECRET-NARRATIVE-TEXT")

    window._pages["quality"].refresh_page = broken
    window.show_page("quality")
    assert window.stack.currentWidget() is window._pages["quality"]
    assert boxes and "application.log" in boxes[0] and "SECRET" not in boxes[0]
    for handler in session.logger.handlers:
        handler.flush()
    log = (session.paths.logs / "application.log").read_text(encoding="utf-8")
    assert "ValueError at" in log and "SECRET-NARRATIVE-TEXT" not in log
    window.close()
    app.processEvents()
