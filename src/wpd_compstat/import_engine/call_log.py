"""Warwick Police Department CAD call-log printouts ("Selective Search" and "Dispatch Log").

Each page starts with the agency banner, a page number, and the report title line
with the searched date range. A "For Date:" line sets the date for the calls that
follow. A call starts with its call number and HHMM time on one line, then the
"Source - Reason" line, the action line, and the priority. Labeled fields follow,
right-aligned so the colon falls at column 18 (column 24 for some "Refer To" lines).
Narrative entries are a labeled header followed by unindented text lines.
"""

from __future__ import annotations

import re

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

LAYOUT = "wpd_call_log"

CALL_LOG_PROFILE: dict = {
    "id": "wpd-cad-call-log-v1",
    "name": "Warwick CAD call log (Selective Search / Dispatch Log) v1",
    "layout": LAYOUT,
    "banner": "Warwick Police Department",
    "report_titles": ["Selective Search", "Dispatch Log"],
    "require_banner": True,
    "date_order": "MDY",
}

LABEL_COLUMNS = {18, 24}
PERSON_ROLES = {
    "Operator": "operator",
    "Owner": "owner",
    "Calling Party": "calling_party",
    "Involved Party": "involved_party",
    "Calling/Inv. Party": "calling_involved_party",
    "Arrest": "arrestee",
    "Summons": "summoned",
}
LOCATION_LABELS = {"Location/Address", "Location", "Vicinity of"}
VEHICLE_EXTRA_LABELS = {"Towed"}
PERSON_EXTRA_LABELS = {"Address", "Age", "Charges", "Insurance Co", "Policy No", "Liens", "Released To"}
OTHER_LABELS = {"Call Taker", "Call Source", "Call Closed By", "Location Change", "ID", "Vehicle", "Narrative", "Call Changes"}
KNOWN_LABELS = set(PERSON_ROLES) | LOCATION_LABELS | VEHICLE_EXTRA_LABELS | PERSON_EXTRA_LABELS | OTHER_LABELS
# Report-number suffixes as printed on the call log. A label is only mapped to a report
# type when the printed number carries the matching suffix.
REFER_TYPES = {
    ("Arrest", "AR"): "arrest",
    ("Summons", "AR"): "summons",
    ("Incident", "OF"): "offense",
    ("Accident", "AC"): "accident",
    ("Field Int", "FI"): "field_interview",
}
COLUMN_HEADINGS = {"Call  Number", "Call Number", "Time", "Call  Reason", "Call Reason", "Action", "Priority"}

_CALL = re.compile(r"^(\d{2}-\d{1,7})\s{2,}(\d{4})\s*$")
_REASON = re.compile(r"^\S.*? - ")
_FOR_DATE = re.compile(r"^For Date:\s+(\d{1,2}/\d{1,2}/\d{4})")
TITLE_RANGE = re.compile(
    r"From:\s+(\d{1,2}/\d{1,2}/\d{4})\s+Thru:\s+(\d{1,2}/\d{1,2}/\d{4})(?:\s+(\d{4})\s+-\s+(\d{4}))?"
)
_LABEL = re.compile(r"^(\s*)([A-Za-z][A-Za-z/ .]*?):(?:\s+(.*))?$")
_UNIT_TIME = re.compile(r"\b(Disp|Enrt|Arvd|Clrd)-(\d{2}:\d{2}:\d{2})\b")
_OFFICER = re.compile(r"^([A-Z0-9]{2,12})\s+-\s+(\S.*)$")
_STAMP = re.compile(r"^(\d{1,2}/\d{1,2}/\d{4})\s+(\d{4})\b\s*(.*)$")
_MODIFIED = re.compile(r"\s*\[Modified:\s*([^\]]*)\]\s*$")
_GEO_CODE = re.compile(r"^\[[^\]]*\]\s*")
_MERGE = re.compile(r"^Merge:\s*(\S+)(?:\s+By:\s*(\S+))?\s*(\d)?\s*$")
_ACTION_PRIORITY = re.compile(r"^(.*?)\s+(\d)$")
_PERSON_DETAIL = re.compile(r"\b(SSN|DOB|Race|Sex):\s*(\S*)")
_VEHICLE = re.compile(r"^(.*?)(?:\s+Reg:\s*(.*?))?(?:\s+VIN:\s*(\S*))?\s*$")


def is_call_log(pages: list[tuple[int, str]], profile: dict | None = None) -> bool:
    profile = profile or CALL_LOG_PROFILE
    if not pages:
        return False
    return _page_header_end(pages[0][1].split("\n"), profile) is not None


def parse_call_log(pages: list[tuple[int, str]], profile: dict) -> ParseOutput:
    if not pages:
        return ParseOutput(False, [], ["The PDF has no pages."], [])
    if not is_call_log(pages, profile):
        return ParseOutput(
            False,
            [],
            ["The document does not have the Warwick CAD call-log page header. Incidents were not guessed."],
            [],
        )
    warnings: list[str] = []
    declared_start = declared_end = None
    stream: list[tuple[int, str]] = []
    for number, text in pages:
        lines = (text or "").replace("\x00", "").split("\n")
        end = _page_header_end(lines, profile)
        if end is None:
            warnings.append(f"Page {number} did not carry the CAD page header. Its lines were still read.")
            body = lines
        else:
            if declared_start is None:
                match = TITLE_RANGE.search(lines[end - 1])
                if match:
                    declared_start = parse_date(match.group(1), "MDY")
                    declared_end = parse_date(match.group(2), "MDY")
            body = lines[end:]
        stream.extend((number, line) for line in body)
    incidents, errors = _parse_stream(stream, warnings)
    if not incidents:
        warnings.append("The call log header was found, but the document lists no calls.")
    return ParseOutput(True, incidents, errors, warnings, declared_start, declared_end)


def count_call_starts(pages: list[tuple[int, str]]) -> int:
    """Independent count of call-number lines, used to reconcile parsed totals."""
    total = 0
    for _number, text in pages:
        lines = (text or "").split("\n")
        for index, line in enumerate(lines):
            if _CALL.match(line) and _next_text(lines, index + 1, _REASON):
                total += 1
    return total


def _page_header_end(lines: list[str], profile: dict) -> int | None:
    banner = profile.get("banner") or CALL_LOG_PROFILE["banner"]
    titles = profile.get("report_titles") or CALL_LOG_PROFILE["report_titles"]
    seen_banner = False
    for index, line in enumerate(lines[:10]):
        text = line.strip()
        if text == banner:
            seen_banner = True
            continue
        if seen_banner and any(text.startswith(title) for title in titles) and "From:" in text:
            return index + 1
    return None


def _next_text(lines: list[str], start: int, pattern: re.Pattern) -> bool:
    for line in lines[start : start + 3]:
        if line.strip():
            return bool(pattern.match(line))
    return False


def _parse_stream(stream: list[tuple[int, str]], warnings: list[str]) -> tuple[list[ParsedIncident], list[str]]:
    incidents: list[ParsedIncident] = []
    errors: list[str] = []
    current_date: str | None = None
    block: list[tuple[int, str]] = []
    block_date: str | None = None
    skip_headings = False

    def flush() -> None:
        if block:
            incidents.append(_parse_call(block, block_date, warnings))

    for index, (page, line) in enumerate(stream):
        date_match = _FOR_DATE.match(line.strip())
        if date_match and not line.startswith(" " * 4):
            current_date = parse_date(date_match.group(1), "MDY")
            if current_date is None:
                errors.append(f"Page {page} has a For Date line that is not a valid date.")
            skip_headings = True
            continue
        if skip_headings:
            if line.strip() in COLUMN_HEADINGS:
                continue
            if line.strip():
                skip_headings = False
        if _CALL.match(line) and _stream_next_is_reason(stream, index + 1):
            flush()
            block = [(page, line)]
            block_date = current_date
            if current_date is None:
                errors.append(f"A call on page {page} appears before any For Date line.")
            continue
        if block:
            block.append((page, line))
        elif line.strip():
            warnings.append(f"Page {page} has text before the first call that was not read as a call.")
    flush()
    return incidents, errors


def _stream_next_is_reason(stream: list[tuple[int, str]], start: int) -> bool:
    for _page, line in stream[start : start + 3]:
        if line.strip():
            return bool(_REASON.match(line))
    return False


def _label_of(line: str) -> tuple[str, str] | None:
    match = _LABEL.match(line)
    if not match:
        return None
    label = match.group(2).strip()
    column = len(match.group(1)) + len(match.group(2))
    if column not in LABEL_COLUMNS:
        return None
    if label in KNOWN_LABELS or label.startswith("Refer To "):
        return label, (match.group(3) or "").rstrip()
    return None


class _Call:
    def __init__(self, cad: str, time_text: str, page: int, event_date: str | None):
        self.incident = ParsedIncident(
            cad_number=cad,
            event_date=event_date,
            event_time=parse_time(f"{time_text[:2]}:{time_text[2:]}"),
            source_page=page,
        )
        self.closed_time: str | None = None
        self.unit_times: list[dict[str, str]] = []
        self.officer_names: set[str] = set()
        self.narrative: ParsedNarrative | None = None
        self.narrative_lines: list[str] = []
        self.person: ParsedPerson | None = None
        self.context: str | None = None
        self.location_changes: set[str] = set()
        self.pending: tuple[str, list[str], int] | None = None


def _parse_call(block: list[tuple[int, str]], event_date: str | None, warnings: list[str]) -> ParsedIncident:
    page, first = block[0]
    match = _CALL.match(first)
    call = _Call(match.group(1), match.group(2), page, event_date)
    incident = call.incident
    index = _parse_header(block, call)
    for page, raw in block[index:]:
        labeled = _label_of(raw)
        if labeled is not None:
            _close_narrative(call)
            label, value = labeled
            _apply_label(call, label, value, page)
            continue
        if not raw.strip():
            continue
        if call.context == "narrative":
            call.narrative_lines.append(raw.rstrip())
            continue
        if call.context == "pending" and call.pending is not None:
            call.pending[1].append(raw.strip())
            continue
        if not raw[:1].isspace() and call.person is None and call.context not in ("vehicle", "unit", "location"):
            incident.warnings.append("Unindented text outside a narrative entry was kept as an unstamped narrative.")
            call.narrative = ParsedNarrative(time_text=None, author=None, body="", page=page)
            call.narrative_lines = [raw.rstrip()]
            call.person = None
            call.context = "narrative"
            continue
        _apply_continuation(call, raw.strip())
    _close_narrative(call)
    _close_pending(call)
    _finish_times(call)
    incident.confidence = _confidence(incident)
    if incident.event_date is None:
        incident.warnings.append("The call had no valid For Date and was left without a date.")
    return incident


def _parse_header(block: list[tuple[int, str]], call: _Call) -> int:
    incident = call.incident
    header: list[str] = []
    index = 1
    while index < len(block):
        _page, raw = block[index]
        if _label_of(raw) is not None:
            break
        if raw.strip():
            header.append(raw.strip())
        index += 1
    if not header:
        incident.warnings.append("The call had no reason line.")
        return index
    source, _sep, reason = header[0].partition(" - ")
    incident.call_type = reason.strip() or None
    incident.call_classification = None
    reason_source = source.strip() or None
    actions: list[str] = []
    for text in header[1:]:
        merge = _MERGE.match(text)
        if merge:
            incident.reports.append(ParsedReport(ref_type="merged_with", ref_number=merge.group(1)))
            if merge.group(3):
                incident.priority = merge.group(3)
            continue
        if text.isdigit() and len(text) == 1:
            incident.priority = text
            continue
        priority = _ACTION_PRIORITY.match(text)
        if priority:
            actions.append(priority.group(1).strip())
            incident.priority = priority.group(2)
        else:
            actions.append(text)
    if actions:
        incident.disposition = " ".join(actions)
    if reason_source and incident.call_source is None:
        incident.call_source = reason_source
    return index


def _apply_label(call: _Call, label: str, value: str, page: int) -> None:
    incident = call.incident
    call.context = None
    call.person = None if label not in PERSON_EXTRA_LABELS else call.person
    _close_pending(call)
    if label == "Call Taker":
        incident.call_taker = value or None
    elif label == "Call Source":
        if value:
            incident.call_source = value
    elif label == "Call Closed By":
        stamp = re.search(r"(\d{1,2}/\d{1,2}/\d{4})\s+(\d{4})\s*$", value)
        if stamp:
            call.closed_time = parse_time(f"{stamp.group(2)[:2]}:{stamp.group(2)[2:]}")
    elif label in LOCATION_LABELS:
        if incident.location is None and incident.intersection is None:
            _set_location(incident, value, label)
            call.context = "location"
    elif label in ("Location Change", "Call Changes"):
        call.pending = (label, [value] if value else [], page)
        call.context = "pending"
    elif label == "ID":
        call.unit_times.append({})
        _add_officer(call, value)
        call.context = "unit"
    elif label == "Vehicle":
        incident.vehicles.append(_vehicle(value))
        call.context = "vehicle"
    elif label in VEHICLE_EXTRA_LABELS:
        if incident.vehicles and value:
            vehicle = incident.vehicles[-1]
            vehicle.description = f"{vehicle.description} | {label}: {value}".strip(" |")
    elif label in PERSON_ROLES:
        call.person = ParsedPerson(role=PERSON_ROLES[label], payload={})
        if value:
            call.person.payload["name_address"] = value
        incident.persons.append(call.person)
        call.context = "person"
    elif label in PERSON_EXTRA_LABELS:
        _person_extra(call, label, value)
    elif label == "Narrative":
        stamp = _STAMP.match(value)
        time_text = author = None
        if stamp:
            time_text = f"{stamp.group(1)} {stamp.group(2)}"
            author = stamp.group(3).strip() or None
        elif value:
            author = value
        call.narrative = ParsedNarrative(time_text=time_text, author=author, body="", page=page)
        call.narrative_lines = []
        call.context = "narrative"
    elif label.startswith("Refer To "):
        _refer(incident, label[len("Refer To ") :].strip(), value.strip())


def _apply_continuation(call: _Call, text: str) -> None:
    incident = call.incident
    if call.context == "unit":
        times = _UNIT_TIME.findall(text)
        if times:
            call.unit_times[-1].update({kind: value for kind, value in times})
            return
        if _OFFICER.match(text):
            call.unit_times.append({})
            _add_officer(call, text)
            return
    if call.context == "vehicle" and incident.vehicles:
        vehicle = incident.vehicles[-1]
        vin = re.match(r"^VIN:\s*(\S+)\s*$", text)
        if vin:
            vehicle.plate = f"{vehicle.plate or ''} VIN {vin.group(1)}".strip()
        else:
            vehicle.description = f"{vehicle.description} {text}".strip()
        return
    if call.person is not None:
        details = _PERSON_DETAIL.findall(text)
        if details:
            for key, value in details:
                if value:
                    call.person.payload[key.casefold()] = value
            return
        key = "charges" if "charges" in call.person.payload else "continued"
        previous = call.person.payload.get(key)
        call.person.payload[key] = f"{previous}; {text}" if previous else text
        return
    if call.context == "location" and incident.location:
        incident.location = f"{incident.location} {text}"
        return
    incident.warnings.append("An indented line did not belong to a known field and was not stored.")


def _person_extra(call: _Call, label: str, value: str) -> None:
    if call.person is None:
        owners = [person for person in call.incident.persons if person.role in {"owner", "operator"}]
        if owners:
            call.person = owners[-1]
        elif value:
            call.incident.warnings.append(f"A {label} line had no person above it and was stored as unattributed.")
            call.person = ParsedPerson(role="unattributed", payload={})
            call.incident.persons.append(call.person)
        else:
            return
    if label == "Age":
        age, _sep, rest = value.partition("SSN:")
        if age.strip():
            call.person.payload["age"] = age.strip()
        if rest.strip():
            call.person.payload["ssn"] = rest.strip()
        call.context = "person"
        return
    if value:
        call.person.payload[label.casefold().replace(" ", "_")] = value
    call.context = "person"


def _refer(incident: ParsedIncident, kind: str, number: str) -> None:
    if not number:
        return
    if kind == "Citation":
        incident.citations.append(ParsedCitation(number=number, verified=False, warning=False))
        return
    suffix = number.rsplit("-", 1)[-1] if "-" in number else ""
    ref_type = REFER_TYPES.get((kind, suffix))
    if ref_type is None:
        incident.warnings.append(f"A Refer To {kind} reference had an unexpected number format and was stored as other.")
        ref_type = "other"
    incident.reports.append(ParsedReport(ref_type=ref_type, ref_number=number))


def _set_location(incident: ParsedIncident, value: str, label: str) -> None:
    text = _MODIFIED.sub("", _GEO_CODE.sub("", value)).strip()
    if not text:
        return
    if label == "Vicinity of":
        incident.location = text
        incident.warnings.append("The location is given as a vicinity, not an address.")
        return
    if " @ " in text:
        incident.intersection = text
        incident.location = text
        return
    business, sep, address = text.rpartition(" - ")
    if sep and address.strip():
        incident.business = " ".join(business.split()) or None
        incident.location = address.strip()
    else:
        incident.location = text


def _close_pending(call: _Call) -> None:
    """Store a Location Change or Call Changes block, including its wrapped lines, as source text."""
    if call.pending is None:
        return
    label, lines, page = call.pending
    call.pending = None
    if call.context == "pending":
        call.context = None
    if not lines:
        return
    if label == "Location Change":
        value = " ".join(" ".join(lines).split())
        if value in call.location_changes:
            return
        call.location_changes.add(value)
        modified = _MODIFIED.search(value)
        time_text = modified.group(1).strip() if modified else None
        body = f"Location Change: {value}"
    else:
        time_text = None
        body = "Call Changes: " + "\n".join(lines)
    call.incident.narratives.append(ParsedNarrative(time_text=time_text, author=None, body=body, page=page))


def _add_officer(call: _Call, value: str) -> None:
    text = " ".join(value.split())
    if not text or text in call.officer_names:
        return
    call.officer_names.add(text)
    role = "primary" if not call.incident.officers else "assisting"
    call.incident.officers.append(ParsedOfficer(badge=None, name=text, role=role))


def _vehicle(value: str) -> ParsedVehicle:
    match = _VEHICLE.match(value.strip())
    description = (match.group(1) or "").strip()
    registration = (match.group(2) or "").split()
    state = plate = None
    if len(registration) >= 3:
        description = f"{description} | Reg type {registration[0]}".strip(" |")
        state, plate = registration[1], " ".join(registration[2:])
    elif len(registration) == 2:
        state, plate = registration
    vin = match.group(3)
    if vin:
        plate = f"{plate or ''} VIN {vin}".strip()
    return ParsedVehicle(description=description, role=None, state=state, plate=plate)


def _close_narrative(call: _Call) -> None:
    if call.context != "narrative" or call.narrative is None:
        return
    body = "\n".join(call.narrative_lines).strip()
    if body:
        call.narrative.body = body
        call.incident.narratives.append(call.narrative)
    call.narrative = None
    call.narrative_lines = []
    call.context = None


def _finish_times(call: _Call) -> None:
    incident = call.incident
    for kind, attribute in (("Disp", "dispatch_time"), ("Arvd", "arrival_time")):
        for unit in call.unit_times:
            if unit.get(kind):
                setattr(incident, attribute, parse_time(unit[kind]))
                break
    if call.closed_time:
        incident.clear_time = call.closed_time
    else:
        cleared = [unit["Clrd"] for unit in call.unit_times if unit.get("Clrd")]
        if cleared:
            incident.clear_time = parse_time(cleared[-1])


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
