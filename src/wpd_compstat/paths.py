"""Installation paths. Operational files stay under the discovered installation root."""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from wpd_compstat.constants import FOLDERS, INSTALL_FOLDER_NAME, MANIFEST_NAME
from wpd_compstat.errors import AppError


@dataclass(frozen=True)
class InstallPaths:
    root: Path

    @property
    def application(self) -> Path:
        return self.root / "Application"

    @property
    def launcher(self) -> Path:
        return self.root / "Launcher"

    @property
    def database(self) -> Path:
        return self.root / "Database"

    @property
    def source_pdfs(self) -> Path:
        return self.root / "Source PDFs"

    @property
    def imports(self) -> Path:
        return self.root / "Imports"

    @property
    def reports(self) -> Path:
        return self.root / "Reports"

    @property
    def presentations(self) -> Path:
        return self.root / "Presentations"

    @property
    def maps(self) -> Path:
        return self.root / "Maps"

    @property
    def backups(self) -> Path:
        return self.root / "Backups"

    @property
    def audit(self) -> Path:
        return self.root / "Audit"

    @property
    def configuration(self) -> Path:
        return self.root / "Configuration"

    @property
    def documentation(self) -> Path:
        return self.root / "Documentation"

    @property
    def working(self) -> Path:
        return self.root / "Working"

    @property
    def logs(self) -> Path:
        return self.root / "Logs"

    @property
    def db_encrypted(self) -> Path:
        return self.database / "compstat.db.enc"

    @property
    def db_working(self) -> Path:
        return self.working / "compstat.db"

    @property
    def keystore(self) -> Path:
        return self.configuration / "keystore.json"

    @property
    def manifest(self) -> Path:
        return self.root / MANIFEST_NAME

    @property
    def ui_preferences(self) -> Path:
        return self.configuration / "ui.json"

    @property
    def profiles(self) -> Path:
        return self.configuration / "profiles"

    @property
    def temp(self) -> Path:
        return self.working / "tmp"

    def relative(self, path: Path) -> str:
        return path.resolve().relative_to(self.root.resolve()).as_posix()

    def ensure_folders(self) -> None:
        for name in FOLDERS:
            (self.root / name).mkdir(parents=True, exist_ok=True)
        self.temp.mkdir(parents=True, exist_ok=True)
        (self.working / "view").mkdir(parents=True, exist_ok=True)
        (self.imports / "staging").mkdir(parents=True, exist_ok=True)
        (self.imports / "traffic").mkdir(parents=True, exist_ok=True)


def require_install_folder_name(root: Path) -> Path:
    root = root.expanduser().resolve()
    if root.name != INSTALL_FOLDER_NAME:
        raise AppError(
            f"The installation folder must be named '{INSTALL_FOLDER_NAME}' "
            "so the drive-letter launcher can find it."
        )
    return root


def use_install_temp(paths: InstallPaths) -> None:
    """Point process temp directories at the external-drive working folder."""
    paths.temp.mkdir(parents=True, exist_ok=True)
    location = str(paths.temp)
    os.environ["TMP"] = location
    os.environ["TEMP"] = location
    os.environ["TMPDIR"] = location
    os.environ["MPLCONFIGDIR"] = str(paths.working / "mplconfig")
    (paths.working / "mplconfig").mkdir(parents=True, exist_ok=True)
    tempfile.tempdir = location
