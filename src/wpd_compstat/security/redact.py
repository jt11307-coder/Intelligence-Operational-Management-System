"""Keep passwords, keys, and narrative text out of logs and audit details."""

from __future__ import annotations

import re

_SECRET_LINE = re.compile(
    r"(?i)\b(password|passphrase|secret|dek|token|api[_-]?key)\b\s*[:=]\s*\S+"
)
_LONG_DIGIT = re.compile(r"\b\d{8,}\b")


def redact_for_log(value: object, limit: int = 240) -> str:
    text = "" if value is None else str(value)
    text = _SECRET_LINE.sub("[redacted]", text)
    text = text.replace("\r", " ").replace("\n", " ")
    text = " ".join(text.split())
    if len(text) > limit:
        text = text[: limit - 3] + "..."
    return text


def csv_formula_safe(value: object) -> str:
    """Stop spreadsheet applications from treating exported text as a formula."""
    if value is None:
        return ""
    text = str(value)
    if text.startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + text
    return text


def assert_no_marker(text: str, marker: str) -> None:
    if marker and marker in text:
        raise RuntimeError("Sensitive marker reached a log or export detail")
