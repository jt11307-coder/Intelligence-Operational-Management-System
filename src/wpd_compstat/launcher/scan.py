"""Find a COMPSTAT installation without a hardcoded drive letter."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from wpd_compstat.constants import INSTALL_FOLDER_NAME, MANIFEST_NAME, PRODUCT_NAME

DRIVE_LETTER = re.compile(r"^[A-Za-z]:[\\/]")


@dataclass
class Installation:
    root: Path
    manifest_path: Path
    installation_id: str
    packaging_status: str
    application_path: Path
    manifest: dict


def candidate_manifest(drive_root: Path) -> Path:
    return drive_root / INSTALL_FOLDER_NAME / MANIFEST_NAME


def inspect_manifest(manifest_path: Path) -> tuple[Installation | None, str | None]:
    if not manifest_path.is_file():
        return None, "manifest-missing"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None, "manifest-unreadable"
    if manifest.get("product") != PRODUCT_NAME:
        return None, "product-mismatch"
    relative = manifest.get("application_relative_path") or ""
    if not _safe_relative(relative):
        return None, "unsafe-application-path"
    root = manifest_path.parent
    application = root / relative
    if not application.is_file():
        return None, "application-missing"
    expected = (manifest.get("application_sha256") or "").casefold()
    actual = hashlib.sha256(application.read_bytes()).hexdigest()
    if not expected or actual != expected:
        return None, "hash-mismatch"
    installation_id = str(manifest.get("installation_id") or "")
    if len(installation_id) < 8:
        return None, "installation-id-missing"
    return (
        Installation(
            root=root,
            manifest_path=manifest_path,
            installation_id=installation_id,
            packaging_status=str(manifest.get("packaging_status") or ""),
            application_path=application,
            manifest=manifest,
        ),
        None,
    )


def find_installations(drive_roots: list[Path]) -> tuple[list[Installation], list[str]]:
    found: list[Installation] = []
    problems: list[str] = []
    for drive in drive_roots:
        installation, problem = inspect_manifest(candidate_manifest(drive))
        if installation:
            found.append(installation)
        elif problem and problem != "manifest-missing":
            problems.append(f"{drive}: {problem}")
    return found, problems


def launch_plan(installations: list[Installation], *, selector=None, allow_source: bool = False, python_executable: str = "python") -> dict:
    if not installations:
        return {
            "ok": False,
            "code": 2,
            "message": "The WPD COMPSTAT drive is not connected, or the installation manifest was not found.",
        }
    if len(installations) > 1:
        if selector is None:
            choices = [item.installation_id for item in installations]
            return {
                "ok": False,
                "code": 4,
                "message": "More than one WPD COMPSTAT installation is connected. Choose one.",
                "choices": choices,
            }
        chosen = selector(installations)
    else:
        chosen = installations[0]
    if chosen.packaging_status == "windows_executable":
        argv = [str(chosen.application_path)]
    elif chosen.packaging_status == "source" and allow_source:
        argv = [python_executable, "-m", "wpd_compstat", "--root", str(chosen.root)]
    else:
        return {
            "ok": False,
            "code": 3,
            "message": "This installation is not a verified Windows executable, so it was not started.",
        }
    return {"ok": True, "code": 0, "argv": argv, "root": str(chosen.root), "installation_id": chosen.installation_id}


def _safe_relative(value: str) -> bool:
    if not value or value.startswith(("/", "\\")) or DRIVE_LETTER.match(value):
        return False
    parts = Path(value).parts
    return ".." not in parts and parts[0] != ".."
