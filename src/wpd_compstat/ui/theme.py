"""Restrained light and dark themes."""

LIGHT = """
QWidget { background: #f4f6f8; color: #1b2430; font-size: 14px; }
QMainWindow, QDialog { background: #f4f6f8; }
QFrame#sidebar { background: #1f4e79; }
QPushButton.nav { background: #1f4e79; color: #f4f6f8; text-align: left; padding: 8px 12px; border: none; }
QPushButton.nav:checked { background: #163a5c; }
QPushButton { background: #1f4e79; color: white; padding: 6px 10px; border-radius: 4px; }
QPushButton:disabled { background: #9aa7b5; }
QLineEdit, QDateEdit, QComboBox, QPlainTextEdit, QTableWidget, QListWidget {
    background: white; color: #1b2430; border: 1px solid #d5dbe3; padding: 4px;
}
QHeaderView::section { background: #e6edf4; color: #1b2430; padding: 4px; }
QLabel#banner { background: #fff6e8; color: #6a4a12; padding: 8px; border: 1px solid #ead7b0; }
"""

DARK = """
QWidget { background: #12171d; color: #e7edf4; font-size: 14px; }
QFrame#sidebar { background: #0d1218; }
QPushButton.nav { background: #0d1218; color: #e7edf4; text-align: left; padding: 8px 12px; border: none; }
QPushButton.nav:checked { background: #1c242e; }
QPushButton { background: #2c5278; color: #e7edf4; padding: 6px 10px; border-radius: 4px; }
QPushButton:disabled { background: #3a4654; color: #9aa7b5; }
QLineEdit, QDateEdit, QComboBox, QPlainTextEdit, QTableWidget, QListWidget {
    background: #1c242e; color: #e7edf4; border: 1px solid #2c3846; padding: 4px;
}
QHeaderView::section { background: #1c242e; color: #e7edf4; padding: 4px; }
QLabel#banner { background: #2a2418; color: #f0d7a4; padding: 8px; border: 1px solid #5a4a2a; }
"""
