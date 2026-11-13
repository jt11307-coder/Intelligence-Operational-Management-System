"""First-run setup and sign-in. There is no default password."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from wpd_compstat.errors import AppError


class SetupDialog(QDialog):
    def __init__(self, session):
        super().__init__()
        self.session = session
        self.setWindowTitle("Create the administrator account")
        layout = QVBoxLayout(self)
        note = QLabel(
            "Create the first administrator. The password is not stored in the program. "
            "A recovery passphrase is optional. If you leave it blank, a lost password cannot be recovered."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        form = QFormLayout()
        self.username = QLineEdit()
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.confirm = QLineEdit()
        self.confirm.setEchoMode(QLineEdit.EchoMode.Password)
        self.recovery = QLineEdit()
        self.recovery.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("Username", self.username)
        form.addRow("Password", self.password)
        form.addRow("Confirm password", self.confirm)
        form.addRow("Recovery passphrase (optional)", self.recovery)
        layout.addLayout(form)
        buttons = QHBoxLayout()
        save = QPushButton("Create account")
        save.clicked.connect(self._save)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(save)
        buttons.addWidget(cancel)
        layout.addLayout(buttons)
        self.resize(520, 280)

    def _save(self) -> None:
        if self.password.text() != self.confirm.text():
            QMessageBox.warning(self, "WPD COMPSTAT", "The passwords do not match.")
            return
        recovery = self.recovery.text() or None
        try:
            self.session.setup_initial_admin(self.username.text().strip(), self.password.text(), recovery)
        except AppError as exc:
            QMessageBox.warning(self, "WPD COMPSTAT", str(exc))
            return
        self.accept()


class LoginDialog(QDialog):
    def __init__(self, session):
        super().__init__()
        self.session = session
        self.setWindowTitle("Sign in")
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("WPD COMPSTAT is offline. Sign in to open the database on this drive."))
        form = QFormLayout()
        self.username = QLineEdit()
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.recovery = QLineEdit()
        self.recovery.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("Username", self.username)
        form.addRow("Password", self.password)
        form.addRow("Recovery passphrase", self.recovery)
        layout.addLayout(form)
        hint = QLabel("Use the recovery field only when the account password is lost. That session can reset credentials.")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        buttons = QHBoxLayout()
        enter = QPushButton("Sign in")
        enter.clicked.connect(self._enter)
        recover = QPushButton("Use recovery passphrase")
        recover.clicked.connect(self._recover)
        buttons.addWidget(enter)
        buttons.addWidget(recover)
        layout.addLayout(buttons)
        self.resize(480, 240)

    def _enter(self) -> None:
        try:
            self.session.unlock(self.username.text().strip(), self.password.text())
        except AppError as exc:
            QMessageBox.warning(self, "WPD COMPSTAT", str(exc))
            return
        self.accept()

    def _recover(self) -> None:
        try:
            self.session.unlock_with_recovery(self.recovery.text())
        except AppError as exc:
            QMessageBox.warning(self, "WPD COMPSTAT", str(exc))
            return
        self.accept()
