"""Local PDF text extraction. No network calls."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pymupdf

from wpd_compstat.security.crypto import secure_unlink


def extract_pages(path: Path, *, ocr: bool, work_dir: Path) -> tuple[list[tuple[int, str]], list[str]]:
    warnings: list[str] = []
    document = pymupdf.open(path)
    pages: list[tuple[int, str]] = []
    try:
        for index, page in enumerate(document, start=1):
            text = page.get_text("text") or ""
            if ocr and len(text.strip()) < 20:
                ocr_text = _ocr_page(page, work_dir)
                if ocr_text:
                    text = ocr_text
                    warnings.append(f"Page {index} used local OCR because it had little embedded text.")
                elif shutil.which("tesseract") is None:
                    warnings.append(
                        f"Page {index} has little embedded text. OCR was requested but tesseract is not installed, so the page was not guessed."
                    )
            pages.append((index, text))
    finally:
        document.close()
    return pages, warnings


def count_tables(path: Path) -> int:
    import pdfplumber

    total = 0
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            tables = page.extract_tables() or []
            total += sum(1 for table in tables if table)
    return total


def _ocr_page(page, work_dir: Path) -> str | None:
    if shutil.which("tesseract") is None:
        return None
    work_dir.mkdir(parents=True, exist_ok=True)
    image = work_dir / "ocr-page.png"
    text_path = work_dir / "ocr-out.txt"
    try:
        pixmap = page.get_pixmap(dpi=150)
        pixmap.save(image)
        completed = subprocess.run(
            ["tesseract", str(image), str(work_dir / "ocr-out"), "--psm", "6"],
            check=False,
            capture_output=True,
        )
        if completed.returncode != 0 or not text_path.exists():
            return None
        return text_path.read_text(encoding="utf-8", errors="replace")
    finally:
        if image.exists():
            secure_unlink(image)
        if text_path.exists():
            secure_unlink(text_path)
