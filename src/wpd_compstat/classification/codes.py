"""Agency code mentions. Meanings are never invented."""

from __future__ import annotations

import re

from wpd_compstat.errors import ValidationError


def scan_codes(call_type: str | None, narratives: list[str], codes: list[dict]) -> list[dict]:
    mentions: list[dict] = []
    haystacks = [call_type or ""] + list(narratives)
    for code in codes:
        token = str(code["code"])
        status = code.get("status") or "unconfirmed"
        match_json = code.get("match_json") or {}
        allow_narrative = bool(match_json.get("scan_narrative") or match_json.get("scan_text"))
        if allow_narrative and len(token) < 4:
            allow_narrative = False
        found = _exact_call_type(call_type, token)
        evidence = "Call type equals the code."
        if not found and len(token) >= 4 and (status == "unconfirmed" or allow_narrative):
            found, evidence = _token_scan(token, haystacks)
        if not found:
            continue
        mentions.append(
            {
                "code": token,
                "evidence": evidence,
                "status": "definition_unconfirmed" if status != "confirmed" else "definition_confirmed",
                "category": match_json.get("category") if status == "confirmed" else None,
            }
        )
    return mentions


def validate_match_rules(code: str, match_json: dict | None) -> dict | None:
    if not match_json:
        return None
    if match_json.get("scan_narrative") and len(code) < 4:
        raise ValidationError(
            f"The code {code} is too short to scan inside narratives. Use an exact call-type match."
        )
    category = match_json.get("category")
    if category is not None and not re.fullmatch(r"[a-z0-9_]+", str(category)):
        raise ValidationError("A code may only map to a category key, not a free-text meaning.")
    return match_json


def _exact_call_type(call_type: str | None, code: str) -> bool:
    if not call_type:
        return False
    return " ".join(call_type.split()).casefold() == code.casefold()


def _token_scan(code: str, texts: list[str]) -> tuple[bool, str]:
    # Times such as 02:00 or 0200 adjacent to a colon are not the code 0200.
    pattern = re.compile(rf"(?<![:\w]){re.escape(code)}(?![:\w])", re.IGNORECASE)
    for text in texts:
        if pattern.search(text or ""):
            return True, "The code appears as its own token. No meaning was assigned."
    return False, ""
