"""Generic labeled CAD profile and profile validation.

This profile is an interchange format for structural tests and for an
administrator who has confirmed that an export really uses these labels.
It is not a Warwick CAD layout.
"""

from __future__ import annotations

import json
import re

from wpd_compstat.errors import ValidationError

GENERIC_PROFILE: dict = {
    "id": "generic-labeled-v1",
    "name": "Generic labeled interchange v1",
    "banner": "WPD-COMPSTAT-PROFILE: generic-labeled-v1",
    "require_banner": True,
    "incident_start": "=== INCIDENT ===",
    "incident_end": "=== END INCIDENT ===",
    "date_order": "ISO",
    "declared_range_prefix": "DECLARED-RANGE:",
    "labels": {
        "cad_number": "CAD Number",
        "event_date": "Date",
        "event_time": "Time",
        "received_time": "Received",
        "call_type": "Call Type",
        "call_classification": "Call Classification",
        "call_source": "Call Source",
        "priority": "Priority",
        "disposition": "Disposition",
        "final_disposition": "Final Disposition",
        "call_taker": "Call Taker",
        "location": "Location",
        "business": "Business",
        "intersection": "Intersection",
        "primary_unit": "Primary Unit",
        "officers": "Officers",
        "dispatch_time": "Dispatch",
        "arrival_time": "Arrival",
        "clear_time": "Clear",
        "vehicles": "Vehicles",
        "citations": "Citations",
        "reports": "Reports",
        "persons": "Persons",
        "follow_up": "Follow Up",
    },
}


def validate_profile(definition: dict) -> dict:
    required = {"incident_start", "incident_end", "date_order", "labels", "require_banner"}
    missing = required - set(definition)
    if missing:
        raise ValidationError("The CAD profile is missing required keys.")
    if definition["date_order"] not in {"ISO", "MDY"}:
        raise ValidationError("Date order must be ISO or MDY.")
    labels = definition["labels"]
    if not isinstance(labels, dict) or "cad_number" not in labels or "event_date" not in labels:
        raise ValidationError("The profile must label the CAD number and the date.")
    for key, label in labels.items():
        if not isinstance(label, str) or not label.strip():
            raise ValidationError(f"The profile label for {key} is empty.")
        if re.search(r"[\r\n]", label):
            raise ValidationError("Profile labels cannot contain line breaks.")
    if not str(definition["incident_start"]).strip():
        raise ValidationError("The incident start marker is empty.")
    return definition


def profile_json(definition: dict) -> str:
    validate_profile(definition)
    return json.dumps(definition, indent=2, sort_keys=True)
