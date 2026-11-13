"""Create the external-drive folder layout and installation manifest."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

from wpd_compstat.constants import (
    ENTRY_RELATIVE_PATH,
    LAYOUT_VERSION,
    PRODUCT_NAME,
    SOURCE_PACKAGING,
)
from wpd_compstat.paths import InstallPaths, require_install_folder_name


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def initialize_installation(root: Path, *, docs_dir: Path | None = None, launcher_dir: Path | None = None) -> Path:
    root = require_install_folder_name(root)
    paths = InstallPaths(root)
    paths.ensure_folders()
    entry = root / ENTRY_RELATIVE_PATH
    entry.parent.mkdir(parents=True, exist_ok=True)
    entry.write_text(
        f"entry-version=1\nproduct={PRODUCT_NAME}\npackaging={SOURCE_PACKAGING}\n",
        encoding="utf-8",
    )
    try:
        os.chmod(entry, 0o600)
    except OSError:
        pass
    manifest = {
        "product": PRODUCT_NAME,
        "installation_id": str(uuid.uuid4()),
        "format_version": 1,
        "layout_version": LAYOUT_VERSION,
        "application_relative_path": ENTRY_RELATIVE_PATH,
        "application_sha256": file_sha256(entry),
        "packaging_status": SOURCE_PACKAGING,
        "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }
    paths.manifest.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (paths.application / "README.txt").write_text(
        "The Windows executable is placed in this folder by packaging/build_windows.ps1.\n"
        "This environment's manifest points at Application/ENTRY until that build is run.\n"
        "No operational data belongs in this folder.\n",
        encoding="utf-8",
    )
    if launcher_dir and launcher_dir.is_dir():
        for item in launcher_dir.iterdir():
            if item.is_file():
                shutil.copy2(item, paths.launcher / item.name)
        opener = launcher_dir / "Open WPD COMPSTAT.bat"
        if opener.is_file():
            shutil.copy2(opener, root / opener.name)
    (root / "README.txt").write_text(
        "This folder is the whole program. Keep it on the thumb drive.\n"
        "Copy the folder onto the Lexar drive as WPD COMPSTAT, then double-click\n"
        "Open WPD COMPSTAT.bat from that drive. Do not move the program to the Desktop.\n"
        "The database, PDFs, reports, and backups stay in this folder.\n",
        encoding="utf-8",
    )
    if docs_dir and docs_dir.is_dir():
        for item in docs_dir.glob("*.md"):
            shutil.copy2(item, paths.documentation / item.name)
    return root
