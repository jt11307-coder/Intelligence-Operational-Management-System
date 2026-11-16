"""Drag-and-drop import of CAD PDFs and folders. Every record here is synthetic."""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl
from PySide6.QtGui import QDropEvent
from PySide6.QtWidgets import QApplication, QMessageBox

from tests.test_call_log import _pages, _write
from wpd_compstat.admin import confirm_profile
from wpd_compstat.import_engine.bulk import collect_pdfs, run_import
from wpd_compstat.import_engine.call_log import CALL_LOG_PROFILE
from wpd_compstat.ui.drop_import import DropBox
from wpd_compstat.ui.main_window import MainWindow


@pytest.fixture
def call_log_session(session):
    confirm_profile(session, CALL_LOG_PROFILE["id"])
    return session


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


def test_folders_are_searched_and_non_pdfs_are_named(tmp_path):
    folder = tmp_path / "November"
    (folder / "week 2").mkdir(parents=True)
    _write(folder / "a.pdf", _pages())
    _write(folder / "week 2" / "b.PDF", _pages())
    (folder / "notes.txt").write_text("ignored inside a folder", encoding="utf-8")
    loose = tmp_path / "c.pdf"
    _write(loose, _pages())
    word = tmp_path / "memo.docx"
    word.write_text("not a pdf", encoding="utf-8")
    pdfs, rejected = collect_pdfs([folder, loose, loose, word])
    assert sorted(path.name for path in pdfs) == ["a.pdf", "b.PDF", "c.pdf"]
    assert rejected == ["memo.docx"]


def test_dropped_pdfs_import_with_progress_and_counts(call_log_session, tmp_path):
    path = tmp_path / "daily.pdf"
    _write(path, _pages())
    seen = []
    totals = run_import(call_log_session, [path], lambda text, done, total: seen.append((done, total)))
    assert totals["new_incidents"] == 4 and totals["final_incident_count"] == 4
    assert seen[-1][0] == seen[-1][1] == 4
    assert [done for done, _total in seen] == sorted(done for done, _total in seen)
    again = run_import(call_log_session, [path])
    assert again["new_incidents"] == 0 and again["duplicates_skipped"] == 4


def test_drop_box_passes_dropped_paths(app, tmp_path):
    received = []
    box = DropBox(received.append)
    data = QMimeData()
    target = tmp_path / "daily.pdf"
    data.setUrls([QUrl.fromLocalFile(str(target))])
    event = QDropEvent(QPointF(5, 5), Qt.DropAction.CopyAction, data, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    box.dropEvent(event)
    assert [Path(path) for path in received[0]] == [target]


def test_window_rejects_non_pdfs_and_refreshes_after_import(app, call_log_session, tmp_path, monkeypatch):
    messages = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: messages.append(("warning", args[2])))
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: messages.append(("information", args[2])))
    window = MainWindow(call_log_session)
    dashboard = window._pages["dashboard"]
    assert dashboard.drop_box.acceptDrops() and window._pages["import"].drop_box.acceptDrops()
    text = tmp_path / "calls.xlsx"
    text.write_text("not a pdf", encoding="utf-8")
    assert window._import_dropped([str(text)]) is None
    assert messages[-1][0] == "warning" and "Only PDF files" in messages[-1][1] and "calls.xlsx" in messages[-1][1]
    assert call_log_session.conn.execute("SELECT COUNT(*) AS n FROM import_batches").fetchone()["n"] == 0
    path = tmp_path / "daily.pdf"
    _write(path, _pages())
    totals = window._import_dropped([str(path), str(text)])
    assert totals["new_incidents"] == 4
    kind, body = messages[-1]
    assert kind == "information" and "New calls: 4" in body and "Conflicts for review: 0" in body and "calls.xlsx" in body
    assert dashboard.banner.isHidden()
    window.close()
    app.processEvents()
