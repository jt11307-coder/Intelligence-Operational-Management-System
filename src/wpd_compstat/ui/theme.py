"""Restrained light and dark themes."""

LIGHT = """
QWidget { background: #f4f6f8; color: #1b2430; font-size: 14px; }
QMainWindow, QDialog { background: #f4f6f8; }
QFrame#sidebar { background: #1f4e79; }
QPushButton.nav { background: #1f4e79; color: #f4f6f8; text-align: left; padding: 8px 12px; border: none; border-left: 5px solid transparent; }
QPushButton.nav:hover { background: #2a5f91; }
QPushButton.nav:checked { background: #f4f6f8; color: #1f4e79; font-weight: 700; border-left: 5px solid #f2a900; }
QPushButton { background: #1f4e79; color: white; padding: 6px 10px; border-radius: 4px; }
QPushButton:disabled { background: #9aa7b5; }
QLineEdit, QDateEdit, QComboBox, QPlainTextEdit, QTextEdit, QTableWidget, QListWidget {
    background: white; color: #1b2430; border: 1px solid #d5dbe3; padding: 4px;
}
QHeaderView::section { background: #e6edf4; color: #1b2430; padding: 4px; }
QLabel#banner { background: #fff6e8; color: #6a4a12; padding: 8px; border: 1px solid #ead7b0; }
QLabel#pageTitle { font-size: 24px; font-weight: 700; color: #1f4e79; padding: 4px 0 8px 0; }
QLabel#sectionTitle { font-size: 18px; font-weight: 700; color: #1f4e79; }
QLabel#explanation { color: #4a5868; font-size: 13px; }
QFrame#tile { background: white; border: 1px solid #d5dbe3; border-radius: 6px; }
QFrame#tile[awaiting="true"] { background: #fff6e8; border: 1px dashed #c79a3a; }
QFrame#tile QLabel { background: transparent; }
QLabel#tileTitle { font-weight: 700; }
QLabel#tileValue { font-size: 26px; font-weight: 700; color: #1f4e79; }
QLabel#tileAwaiting { color: #8a5a00; font-weight: 600; font-size: 13px; }
"""

DARK = """
QWidget { background: #12171d; color: #e7edf4; font-size: 14px; }
QFrame#sidebar { background: #0d1218; }
QPushButton.nav { background: #0d1218; color: #e7edf4; text-align: left; padding: 8px 12px; border: none; border-left: 5px solid transparent; }
QPushButton.nav:hover { background: #1c242e; }
QPushButton.nav:checked { background: #2c5278; color: white; font-weight: 700; border-left: 5px solid #f2a900; }
QPushButton { background: #2c5278; color: #e7edf4; padding: 6px 10px; border-radius: 4px; }
QPushButton:disabled { background: #3a4654; color: #9aa7b5; }
QLineEdit, QDateEdit, QComboBox, QPlainTextEdit, QTextEdit, QTableWidget, QListWidget {
    background: #1c242e; color: #e7edf4; border: 1px solid #2c3846; padding: 4px;
}
QHeaderView::section { background: #1c242e; color: #e7edf4; padding: 4px; }
QLabel#banner { background: #2a2418; color: #f0d7a4; padding: 8px; border: 1px solid #5a4a2a; }
QLabel#pageTitle { font-size: 24px; font-weight: 700; color: #9cc7f0; padding: 4px 0 8px 0; }
QLabel#sectionTitle { font-size: 18px; font-weight: 700; color: #9cc7f0; }
QLabel#explanation { color: #aab6c3; font-size: 13px; }
QFrame#tile { background: #1c242e; border: 1px solid #2c3846; border-radius: 6px; }
QFrame#tile[awaiting="true"] { background: #2a2418; border: 1px dashed #8a6a2a; }
QFrame#tile QLabel { background: transparent; }
QLabel#tileTitle { font-weight: 700; }
QLabel#tileValue { font-size: 26px; font-weight: 700; color: #9cc7f0; }
QLabel#tileAwaiting { color: #f0c46a; font-weight: 600; font-size: 13px; }
"""
