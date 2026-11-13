"""Decide how an incoming CAD record changes an existing incident. Nothing is merged silently."""

from __future__ import annotations

import hashlib
import json

from wpd_compstat.import_engine.model import ParsedIncident, ParsedPerson


def match_key(cad_number: str | None, event_date: str | None) -> str | None:
    if not cad_number or not event_date:
        return None
    return f"{' '.join(cad_number.split()).upper()}|{event_date}"


def narrative_hash(body: str) -> str:
    text = " ".join(body.split())
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def same_text(left: str | None, right: str | None) -> bool:
    return _norm(left) == _norm(right)


def _norm(value: str | None) -> str | None:
    if value is None:
        return None
    text = " ".join(value.split())
    return text.casefold() if text else None


def plan_merge(existing: dict | None, incoming: ParsedIncident) -> dict:
    """Return an action plan. existing is None when the match key is new."""
    if not incoming.cad_number or not incoming.event_date:
        return {"action": "exception", "reason": "missing_identifier"}
    if existing is None:
        return {
            "action": "insert",
            "updates": {},
            "conflicts": [],
            "narratives": list(incoming.narratives),
            "officers": list(incoming.officers),
            "reports": list(incoming.reports),
            "citations": list(incoming.citations),
            "vehicles": list(incoming.vehicles),
            "persons": list(incoming.persons),
        }
    updates: dict[str, str] = {}
    conflicts: list[dict] = []
    comparable = {
        "event_time": incoming.event_time,
        "received_time": incoming.received_time,
        "dispatch_time": incoming.dispatch_time,
        "arrival_time": incoming.arrival_time,
        "clear_time": incoming.clear_time,
        "call_type": incoming.call_type,
        "call_classification": incoming.call_classification,
        "call_source": incoming.call_source,
        "priority": incoming.priority,
        "disposition": incoming.disposition,
        "final_disposition": incoming.final_disposition,
        "call_taker": incoming.call_taker,
        "business_landmark": incoming.business,
        "location_text": incoming.location,
        "intersection": incoming.intersection,
    }
    for field_name, new_value in comparable.items():
        old_value = existing.get(field_name)
        if _norm(new_value) is None or same_text(old_value, new_value):
            continue
        if _norm(old_value) is None:
            updates[field_name] = new_value
        else:
            conflicts.append(
                {"field_name": field_name, "existing_value": old_value, "incoming_value": new_value}
            )
    known_hashes = set(existing.get("narrative_hashes") or [])
    narratives = [item for item in incoming.narratives if narrative_hash(item.body) not in known_hashes]
    known_officers = set(existing.get("officer_keys") or [])
    officers = []
    for officer in incoming.officers:
        key = _officer_key(officer.badge, officer.name, officer.role, officer.unit)
        if key not in known_officers:
            officers.append(officer)
    omitted = []
    incoming_keys = {
        _officer_key(officer.badge, officer.name, officer.role, officer.unit) for officer in incoming.officers
    }
    for key in known_officers:
        if key not in incoming_keys and "|primary_unit|" not in f"|{key}":
            omitted.append(key)
    known_reports = set(existing.get("report_keys") or [])
    reports = [item for item in incoming.reports if f"{item.ref_type}|{item.ref_number}" not in known_reports]
    known_citations = {item["number"]: item for item in existing.get("citations") or []}
    citations = []
    citation_conflicts = []
    for citation in incoming.citations:
        previous = known_citations.get(citation.number)
        if previous is None:
            citations.append(citation)
            continue
        if bool(previous["verified"]) != citation.verified or bool(previous["warning"]) != citation.warning:
            citation_conflicts.append(
                {
                    "field_name": "citation",
                    "existing_value": str(previous),
                    "incoming_value": f"{citation.number}|verified={citation.verified}|warning={citation.warning}",
                }
            )
    known_vehicles = set(existing.get("vehicle_keys") or [])
    vehicles = []
    for vehicle in incoming.vehicles:
        key = "|".join([vehicle.description or "", vehicle.role or "", vehicle.state or ""])
        if key not in known_vehicles:
            vehicles.append(vehicle)
    known_people = set(existing.get("person_hashes") or [])
    persons = [person for person in incoming.persons if person_hash(person) not in known_people]
    if updates or conflicts or narratives or officers or reports or citations or citation_conflicts or vehicles or omitted or persons:
        action = "update"
    else:
        action = "duplicate"
    return {
        "action": action,
        "updates": updates,
        "conflicts": conflicts + citation_conflicts,
        "narratives": narratives,
        "officers": officers,
        "reports": reports,
        "citations": citations,
        "vehicles": vehicles,
        "persons": persons,
        "omitted_officers": omitted,
    }


def person_hash(person: ParsedPerson) -> str:
    payload = {"role": person.role, "payload": person.payload}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _officer_key(badge: str | None, name: str | None, role: str | None, unit: str | None) -> str:
    return "|".join(
        [
            (badge or "").casefold(),
            " ".join((name or "").split()).casefold(),
            (role or "").casefold(),
            (unit or "").casefold(),
        ]
    )
