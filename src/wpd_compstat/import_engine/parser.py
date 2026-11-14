"""Parse text extracted from a PDF using an explicit profile. Unrecognized layouts yield no incidents.

The Warwick CAD call-log layout is parsed by call_log.py; this module parses the generic labeled profile.
"""

from __future__ import annotations

import re

from wpd_compstat.import_engine.call_log import LAYOUT as CALL_LOG_LAYOUT
from wpd_compstat.import_engine.call_log import parse_call_log
from wpd_compstat.import_engine.dates import parse_date, parse_time
from wpd_compstat.import_engine.model import (
    ParseOutput,
    ParsedCitation,
    ParsedIncident,
    ParsedNarrative,
    ParsedOfficer,
    ParsedPerson,
    ParsedReport,
    ParsedVehicle,
)
from wpd_compstat.import_engine.profile import validate_profile

REPORT_TYPES = {
    "ARREST": "arrest",
    "OFFENSE": "offense",
    "ACCIDENT": "accident",
    "SUPPLEMENTAL": "supplemental",
    "CITATION": "citation",
    "OTHER": "other",
}
_YES = {"yes", "true", "1", "y"}


def parse_pages(pages: list[tuple[int, str]], profile: dict) -> ParseOutput:
    profile = validate_profile(profile)
    if profile.get("layout") == CALL_LOG_LAYOUT:
        return parse_call_log(pages, profile)
    if not pages:
        return ParseOutput(False, [], ["The PDF has no pages."], [])
    joined, spans = _join(pages)
    warnings: list[str] = []
    if profile.get("require_banner"):
        banner = profile.get("banner") or ""
        if banner and banner not in pages[0][1] and banner not in joined:
            return ParseOutput(
                False,
                [],
                ["The document does not match the active CAD profile banner. Incidents were not guessed."],
                [],
            )
    declared_start, declared_end = _declared_range(joined, profile)
    start = profile["incident_start"]
    end = profile["incident_end"]
    incidents: list[ParsedIncident] = []
    errors: list[str] = []
    cursor = 0
    found_marker = False
    while True:
        begin = joined.find(start, cursor)
        if begin < 0:
            break
        found_marker = True
        body_start = begin + len(start)
        finish = joined.find(end, body_start)
        next_begin = joined.find(start, body_start)
        if finish < 0 or (next_begin >= 0 and next_begin < finish):
            errors.append("An incident block was missing its end marker and was not imported.")
            cursor = next_begin if next_begin >= 0 else len(joined)
            if next_begin < 0:
                break
            continue
        block = joined[body_start:finish]
        page = _page_for(begin, spans)
        incidents.append(_parse_block(block, page, profile, warnings))
        cursor = finish + len(end)
    if not found_marker:
        return ParseOutput(
            False,
            [],
            ["No incident blocks matched the active profile. Incidents were not guessed."],
            warnings,
            declared_start,
            declared_end,
        )
    return ParseOutput(True, incidents, errors, warnings, declared_start, declared_end)


def _join(pages: list[tuple[int, str]]) -> tuple[str, list[tuple[int, int, int]]]:
    chunks: list[str] = []
    spans: list[tuple[int, int, int]] = []
    cursor = 0
    for number, text in pages:
        marker = f"\n\x1ePAGE:{number}\x1e\n"
        chunks.append(marker)
        cursor += len(marker)
        start = cursor
        cleaned = (text or "").replace("\x00", "")
        chunks.append(cleaned)
        cursor += len(cleaned)
        spans.append((start, cursor, number))
    return "".join(chunks), spans


def _page_for(position: int, spans: list[tuple[int, int, int]]) -> int:
    for start, end, number in spans:
        if start <= position < end:
            return number
    return spans[-1][2] if spans else 1


def _declared_range(text: str, profile: dict) -> tuple[str | None, str | None]:
    prefix = profile.get("declared_range_prefix") or "DECLARED-RANGE:"
    for line in text.splitlines():
        if line.startswith(prefix):
            parts = line[len(prefix) :].strip().split()
            if len(parts) >= 2:
                start = parse_date(parts[0], "ISO")
                end = parse_date(parts[1], "ISO")
                return start, end
    return None, None


def _parse_block(block: str, page: int, profile: dict, warnings: list[str]) -> ParsedIncident:
    labels = {name: label.casefold() for name, label in profile["labels"].items()}
    inverse = {label: name for name, label in labels.items()}
    fields: dict[str, str] = {}
    narratives: list[ParsedNarrative] = []
    mode = "fields"
    current: ParsedNarrative | None = None
    current_page = page
    for raw_line in block.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("\x1ePAGE:") and line.endswith("\x1e"):
            number = line[len("\x1ePAGE:") : -1]
            if number.isdigit():
                current_page = int(number)
            continue
        if line.casefold() == "narratives:":
            mode = "narratives"
            current = None
            continue
        if mode == "narratives":
            match = re.match(r"^\[(.+?)\]\s*(.*)$", line)
            if match:
                if current and current.body:
                    narratives.append(current)
                stamp, body = match.group(1), match.group(2)
                author = None
                time_text = stamp.strip()
                if "|" in stamp:
                    time_text, author = [part.strip() for part in stamp.split("|", 1)]
                current = ParsedNarrative(
                    time_text=time_text or None,
                    author=author or None,
                    body=body.strip(),
                    page=current_page,
                )
            elif current is not None:
                current.body = (current.body + " " + line).strip()
            else:
                warnings.append("A narrative line had no timestamp and was kept with the incident warning list only.")
            continue
        if ":" not in line:
            warnings.append("A line outside the narrative was not a labeled field and was ignored.")
            continue
        label, value = line.split(":", 1)
        key = inverse.get(label.strip().casefold())
        if not key:
            warnings.append("An unrecognized label was ignored.")
            continue
        fields[key] = value.strip()
    if current and current.body:
        narratives.append(current)
    order = profile["date_order"]
    incident = ParsedIncident(
        cad_number=_blank(fields.get("cad_number")),
        event_date=parse_date(fields.get("event_date"), order),
        event_time=parse_time(fields.get("event_time")),
        received_time=parse_time(fields.get("received_time")),
        dispatch_time=parse_time(fields.get("dispatch_time")),
        arrival_time=parse_time(fields.get("arrival_time")),
        clear_time=parse_time(fields.get("clear_time")),
        call_type=_blank(fields.get("call_type")),
        call_classification=_blank(fields.get("call_classification")),
        call_source=_blank(fields.get("call_source")),
        priority=_blank(fields.get("priority")),
        disposition=_blank(fields.get("disposition")),
        final_disposition=_blank(fields.get("final_disposition")),
        call_taker=_blank(fields.get("call_taker")),
        location=_blank(fields.get("location")),
        business=_blank(fields.get("business")),
        intersection=_blank(fields.get("intersection")),
        primary_unit=_blank(fields.get("primary_unit")),
        follow_up=_yes_no(fields.get("follow_up")),
        source_page=page,
        narratives=narratives,
        officers=_officers(fields.get("officers"), fields.get("primary_unit")),
        citations=_citations(fields.get("citations")),
        reports=_reports(fields.get("reports"), warnings),
        vehicles=_vehicles(fields.get("vehicles")),
        persons=_persons(fields.get("persons")),
    )
    if fields.get("event_date") and incident.event_date is None:
        incident.warnings.append("The date was present but not a valid unambiguous date.")
    for label, parsed in (
        ("event_time", incident.event_time),
        ("received_time", incident.received_time),
        ("dispatch_time", incident.dispatch_time),
        ("arrival_time", incident.arrival_time),
        ("clear_time", incident.clear_time),
    ):
        if fields.get(label) and parsed is None:
            incident.warnings.append(f"The {label} value was not a valid time and was left blank.")
    incident.confidence = _confidence(incident)
    return incident


def _blank(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    return text or None


def _yes_no(value: str | None) -> bool | None:
    if value is None or not value.strip():
        return None
    return value.strip().casefold() in _YES


def _confidence(incident: ParsedIncident) -> float:
    present = [
        incident.cad_number,
        incident.event_date,
        incident.event_time,
        incident.call_type,
        incident.disposition,
        incident.location,
    ]
    return round(sum(1 for item in present if item) / len(present), 2)


def _officers(text: str | None, primary_unit: str | None) -> list[ParsedOfficer]:
    officers: list[ParsedOfficer] = []
    if text:
        for part in text.split(";"):
            piece = part.strip()
            if not piece:
                continue
            role = "assigned"
            if "|" in piece:
                piece, role_text = [item.strip() for item in piece.split("|", 1)]
                if role_text:
                    role = role_text.casefold()
            badge = None
            name = piece
            tokens = piece.split()
            if tokens and any(character.isdigit() for character in tokens[0]):
                badge = tokens[0]
                name = " ".join(tokens[1:]).strip() or piece
            officers.append(ParsedOfficer(badge=badge, name=name, role=role))
    if primary_unit:
        officers.append(ParsedOfficer(badge=None, name="", role="primary_unit", unit=primary_unit))
    return officers


def _citations(text: str | None) -> list[ParsedCitation]:
    if not text:
        return []
    citations: list[ParsedCitation] = []
    for part in text.split(";"):
        piece = part.strip()
        if not piece:
            continue
        number = None
        verified = False
        warning = False
        for token in [item.strip() for item in piece.split("|")]:
            if "=" not in token:
                number = token or number
                continue
            key, value = [item.strip() for item in token.split("=", 1)]
            if key.casefold() == "verified":
                verified = value.casefold() in _YES
            elif key.casefold() == "warning":
                warning = value.casefold() in _YES
        citations.append(ParsedCitation(number=number, verified=verified, warning=warning))
    return citations


def _reports(text: str | None, warnings: list[str]) -> list[ParsedReport]:
    if not text:
        return []
    reports: list[ParsedReport] = []
    for part in text.split(";"):
        piece = part.strip()
        if not piece or ":" not in piece:
            continue
        label, number = [item.strip() for item in piece.split(":", 1)]
        ref_type = REPORT_TYPES.get(label.upper())
        if ref_type is None:
            warnings.append("A report label was not recognized and was stored as other.")
            ref_type = "other"
        if number:
            reports.append(ParsedReport(ref_type=ref_type, ref_number=number))
    return reports


def _vehicles(text: str | None) -> list[ParsedVehicle]:
    if not text:
        return []
    vehicles: list[ParsedVehicle] = []
    for part in text.split(";"):
        piece = part.strip()
        if not piece:
            continue
        role = None
        state = None
        plate = None
        description_parts: list[str] = []
        for token in [item.strip() for item in piece.split("|")]:
            if "=" not in token:
                description_parts.append(token)
                continue
            key, value = [item.strip() for item in token.split("=", 1)]
            lowered = key.casefold()
            if lowered == "role":
                role = value or None
            elif lowered == "state":
                state = value or None
            elif lowered == "plate":
                plate = value or None
            else:
                description_parts.append(token)
        vehicles.append(
            ParsedVehicle(
                description=" | ".join(part for part in description_parts if part),
                role=role,
                state=state,
                plate=plate,
            )
        )
    return vehicles


def _persons(text: str | None) -> list[ParsedPerson]:
    if not text:
        return []
    people: list[ParsedPerson] = []
    for part in text.split(";"):
        piece = part.strip()
        if not piece:
            continue
        payload: dict[str, str] = {}
        for token in [item.strip() for item in piece.split("|")]:
            if "=" not in token:
                continue
            key, value = [item.strip() for item in token.split("=", 1)]
            if key and value:
                payload[key.casefold()] = value
        role = payload.pop("role", "involved")
        if payload:
            people.append(ParsedPerson(role=role, payload=payload))
    return people
