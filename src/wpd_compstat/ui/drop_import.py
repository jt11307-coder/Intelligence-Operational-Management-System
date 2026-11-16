"""A box that takes CAD PDFs or folders dragged from File Explorer, or a click to pick files."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFileDialog, QFrame, QLabel, QVBoxLayout

PROMPT = (
    "Drop CAD call-log PDFs or a folder here to import\n"
    "or click here to choose PDFs"
)

_STYLE = """
QFrame#dropBox { border: 3px dashed #2f6fb3; border-radius: 10px; background: rgba(47, 111, 179, 0.08); }
QFrame#dropBox[hover="true"] { border-color: #1d8a3a; background: rgba(29, 138, 58, 0.14); }
QFrame#dropBox QLabel { border: none; background: transparent; font-size: 16px; font-weight: 600; }
"""


class DropBox(QFrame):
    def __init__(self, on_paths: Callable[[list[str]], None], parent=None):
        super().__init__(parent)
        self.on_paths = on_paths
        self.setObjectName("dropBox")
        self.setAcceptDrops(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(110)
        self.setStyleSheet(_STYLE)
        layout = QVBoxLayout(self)
        self.label = QLabel(PROMPT)
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.setWordWrap(True)
        layout.addWidget(self.label)

    def _set_hover(self, value: bool) -> None:
        self.setProperty("hover", value)
        self.style().unpolish(self)
        self.style().polish(self)

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls() and any(url.isLocalFile() for url in event.mimeData().urls()):
            self._set_hover(True)
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragLeaveEvent(self, event) -> None:
        self._set_hover(False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event) -> None:
        self._set_hover(False)
        paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        event.acceptProposedAction()
        if paths:
            self.on_paths(paths)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            paths, _filter = QFileDialog.getOpenFileNames(self, "Choose CAD call-log PDFs", "", "PDF (*.pdf)")
            if paths:
                self.on_paths(paths)
        super().mouseReleaseEvent(event)
