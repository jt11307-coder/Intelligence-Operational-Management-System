"""Date and time parsing. Ambiguous values are left empty instead of guessed."""

from __future__ import annotations

import re
from datetime import date

ISO_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
MDY_DATE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})$")
TIME = re.compile(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?$")


def parse_date(value: str | None, order: str) -> str | None:
    if value is None:
        return None
    text = " ".join(value.strip().split())
    if not text:
        return None
    iso = ISO_DATE.match(text)
    if iso:
        return _valid(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))
    if order == "MDY":
        mdy = MDY_DATE.match(text)
        if mdy:
            return _valid(int(mdy.group(3)), int(mdy.group(1)), int(mdy.group(2)))
    return None


def parse_time(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    match = TIME.match(text)
    if not match:
        return None
    hour = int(match.group(1))
    minute = int(match.group(2))
    second = int(match.group(3) or 0)
    if hour > 23 or minute > 59 or second > 59:
        return None
    return f"{hour:02d}:{minute:02d}:{second:02d}"


def _valid(year: int, month: int, day: int) -> str | None:
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None
