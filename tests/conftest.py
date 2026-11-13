"""Shared fixtures. The password exists only in tests."""

from __future__ import annotations

from pathlib import Path

import pymupdf
import pytest

from wpd_compstat.admin import confirm_profile
from wpd_compstat.install import initialize_installation
from wpd_compstat.session import Session

PASSWORD = "Correcthorse1"
SYNTHETIC_BANNER = "SYNTHETIC FIXTURE — NOT A DEPARTMENT RECORD"


@pytest.fixture
def session(tmp_path: Path) -> Session:
    root = tmp_path / "WPD COMPSTAT"
    initialize_installation(root, launcher_dir=Path(__file__).resolve().parents[1] / "launcher")
    opened = Session(root)
    opened.setup_initial_admin("admin", PASSWORD)
    yield opened
    opened.close()


@pytest.fixture
def confirmed_session(session: Session) -> Session:
    confirm_profile(session, "generic-labeled-v1")
    return session


def write_pdf(path: Path, pages: list[str]) -> None:
    document = pymupdf.open()
    for text in pages:
        page = document.new_page(width=612, height=792)
        page.insert_textbox(
            pymupdf.Rect(36, 36, 576, 756),
            SYNTHETIC_BANNER + "\n" + text,
            fontsize=8,
        )
    document.save(path)
    document.close()
