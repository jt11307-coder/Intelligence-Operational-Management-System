"""Incident search and detail. Sensitive payloads stay encrypted until an authorized read."""

from __future__ import annotations

import json
import re

from wpd_compstat.errors import ValidationError
from wpd_compstat.security.crypto import decrypt_field
from wpd_compstat.security.permissions import has_permission


def search_incidents(session, filters: dict) -> list[dict]:
    session.require("search")
    clauses = ["i.excluded = 0"]
    params: list = []
    mapping = {
        "cad_number": "i.cad_number = ?",
        "call_type": "LOWER(i.call_type) LIKE ?",
        "disposition": "LOWER(i.disposition) LIKE ?",
        "business": "LOWER(COALESCE(i.business_landmark, '')) LIKE ?",
    }
    for key, sql in mapping.items():
        value = filters.get(key)
        if not value:
            continue
        if key == "cad_number":
            params.append(str(value).upper())
        else:
            params.append(f"%{str(value).casefold()}%")
        clauses.append(sql)
    if filters.get("date_start"):
        clauses.append("i.event_date >= ?")
        params.append(filters["date_start"])
    if filters.get("date_end"):
        clauses.append("i.event_date <= ?")
        params.append(filters["date_end"])
    if filters.get("street"):
        clauses.append("LOWER(COALESCE(l.street, '')) LIKE ?")
        params.append(f"%{filters['street'].casefold()}%")
    if filters.get("officer"):
        clauses.append(
            """
            EXISTS (
                SELECT 1 FROM incident_officers io
                JOIN officers o ON o.id = io.officer_id
                WHERE io.incident_id = i.id AND (
                    LOWER(o.display_name) LIKE ? OR LOWER(COALESCE(o.badge, '')) LIKE ?
                )
            )
            """
        )
        token = f"%{filters['officer'].casefold()}%"
        params.extend([token, token])
    if filters.get("division_id"):
        clauses.append(
            """
            EXISTS (
                SELECT 1 FROM incident_officers io
                JOIN officers o ON o.id = io.officer_id
                WHERE io.incident_id = i.id AND o.division_id = ?
            )
            """
        )
        params.append(int(filters["division_id"]))
    if filters.get("category"):
        clauses.append(
            """
            i.id IN (
                SELECT c.incident_id FROM classifications c
                WHERE c.category = ? AND c.counts_officially = 1 AND c.status != 'rejected'
            )
            """
        )
        params.append(filters["category"])
    if filters.get("narrative"):
        words = re.findall(r"[A-Za-z0-9]{2,}", filters["narrative"])
        if not words:
            raise ValidationError("Narrative search needs at least one word.")
        match = " AND ".join(f'"{word}"' for word in words)
        clauses.append(
            "i.id IN (SELECT n.incident_id FROM narratives n JOIN narratives_fts f ON f.rowid = n.id WHERE f MATCH ?)"
        )
        params.append(match)
    if filters.get("report_number"):
        clauses.append(
            "EXISTS (SELECT 1 FROM report_references r WHERE r.incident_id = i.id AND r.ref_number = ?)"
        )
        params.append(str(filters["report_number"]))
    rows = session.conn.execute(
        f"""
        SELECT i.id, i.cad_number, i.event_date, i.event_time, i.call_type, i.disposition, l.raw_address
        FROM incidents i
        LEFT JOIN locations l ON l.id = i.location_id
        WHERE {' AND '.join(clauses)}
        ORDER BY i.event_date, i.cad_number
        LIMIT 500
        """,
        tuple(params),
    ).fetchall()
    return [dict(row) for row in rows]


def save_search(session, name: str, filters: dict) -> None:
    session.require("search")
    session.conn.execute(
        """
        INSERT INTO saved_searches(user_id, name, filter_json, created_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(user_id, name) DO UPDATE SET filter_json = excluded.filter_json
        """,
        (session.user["id"], name.strip(), json.dumps(filters), session.stamp()),
    )


def incident_detail(session, incident_id: int, *, redact_persons: bool = False) -> dict:
    session.require("search")
    row = session.conn.execute("SELECT * FROM incidents WHERE id = ?", (incident_id,)).fetchone()
    if row is None:
        raise ValidationError("That incident does not exist.")
    location = None
    if row["location_id"]:
        location = dict(
            session.conn.execute("SELECT * FROM locations WHERE id = ?", (row["location_id"],)).fetchone()
        )
    detail = {
        "id": row["id"],
        "cad_number": row["cad_number"],
        "event_date": row["event_date"],
        "event_time": row["event_time"],
        "received_time": row["received_time"],
        "dispatch_time": row["dispatch_time"],
        "arrival_time": row["arrival_time"],
        "clear_time": row["clear_time"],
        "call_type": row["call_type"],
        "call_classification": row["call_classification"],
        "call_source": row["call_source"],
        "priority": row["priority"],
        "disposition": row["disposition"],
        "final_disposition": row["final_disposition"],
        "call_taker": row["call_taker"],
        "business_landmark": row["business_landmark"],
        "extraction_confidence": row["extraction_confidence"],
        "review_status": row["review_status"],
        "source_pdf_id": row["source_pdf_id"],
        "source_page": row["source_page"],
        "excluded": bool(row["excluded"]),
        "location": location,
        "officers": [
            dict(item)
            for item in session.conn.execute(
                """
                SELECT o.badge, o.display_name, io.role, io.unit_call_sign
                FROM incident_officers io LEFT JOIN officers o ON o.id = io.officer_id
                WHERE io.incident_id = ?
                """,
                (incident_id,),
            )
        ],
        "reports": [
            dict(item)
            for item in session.conn.execute(
                "SELECT ref_type, ref_number FROM report_references WHERE incident_id = ?",
                (incident_id,),
            )
        ],
        "citations": [
            dict(item)
            for item in session.conn.execute(
                """
                SELECT citation_number, verified_violation, warning, source
                FROM citations WHERE incident_id = ?
                """,
                (incident_id,),
            )
        ],
        "classifications": [
            dict(item)
            for item in session.conn.execute(
                """
                SELECT category, polarity, confidence, counts_officially, significant, status, evidence_json
                FROM classifications WHERE incident_id = ?
                """,
                (incident_id,),
            )
        ],
        "conflicts": [
            dict(item)
            for item in session.conn.execute(
                "SELECT field_name, existing_value, incoming_value, status FROM incident_conflicts WHERE incident_id = ?",
                (incident_id,),
            )
        ],
        "history": [
            dict(item)
            for item in session.conn.execute(
                """
                SELECT field_name, old_value, new_value, change_reason, changed_at
                FROM incident_field_history WHERE incident_id = ? ORDER BY id
                """,
                (incident_id,),
            )
        ],
        "code_mentions": [
            dict(item)
            for item in session.conn.execute(
                "SELECT code, evidence, status FROM code_mentions WHERE incident_id = ?",
                (incident_id,),
            )
        ],
    }
    if has_permission(session.user["role"], "view_narratives"):
        narratives = [
            dict(item)
            for item in session.conn.execute(
                """
                SELECT sequence, narrative_time, author, body, source_page
                FROM narratives WHERE incident_id = ? ORDER BY sequence
                """,
                (incident_id,),
            )
        ]
        if redact_persons and has_permission(session.user["role"], "view_sensitive"):
            replacements = _person_strings(session, incident_id)
            for narrative in narratives:
                for value in replacements:
                    narrative["body"] = re.sub(re.escape(value), "[person]", narrative["body"], flags=re.IGNORECASE)
        detail["narratives"] = narratives
    else:
        detail["narratives"] = []
        detail["narrative_note"] = "Narrative text is withheld for this role."
    if has_permission(session.user["role"], "view_sensitive"):
        people = []
        for item in session.conn.execute(
            "SELECT role, payload_enc FROM sensitive_persons WHERE incident_id = ?",
            (incident_id,),
        ):
            people.append({"role": item["role"], "payload": json.loads(decrypt_field(session.dek, "person", item["payload_enc"]))})
        detail["persons"] = people
        session.audit("view_sensitive", entity_type="incident", entity_id=incident_id, detail="person records viewed")
    else:
        detail["persons"] = []
        detail["person_note"] = "Person records are withheld for this role."
    return detail


def correct_field(session, incident_id: int, field_name: str, new_value: str, reason: str) -> None:
    session.require("classify")
    allowed = {
        "call_type",
        "call_classification",
        "call_source",
        "priority",
        "disposition",
        "final_disposition",
        "business_landmark",
    }
    if field_name not in allowed:
        raise ValidationError("That field cannot be corrected here.")
    if not reason.strip():
        raise ValidationError("A reason is required.")
    row = session.conn.execute(f"SELECT {field_name} AS value FROM incidents WHERE id = ?", (incident_id,)).fetchone()
    if row is None:
        raise ValidationError("That incident does not exist.")
    session.conn.execute(
        f"UPDATE incidents SET {field_name} = ?, updated_at = ?, review_status = 'needs_review' WHERE id = ?",
        (new_value, session.stamp(), incident_id),
    )
    session.conn.execute(
        """
        INSERT INTO incident_field_history(
            incident_id, field_name, old_value, new_value, changed_at, changed_by, change_reason
        ) VALUES (?, ?, ?, ?, ?, ?, 'manual_correction')
        """,
        (incident_id, field_name, row["value"], new_value, session.stamp(), session.user["id"]),
    )
    session.audit("correct_field", entity_type="incident", entity_id=incident_id, detail=field_name)


def exclude_incident(session, incident_id: int, reason: str) -> None:
    session.require("delete_records")
    if not reason.strip():
        raise ValidationError("A reason is required.")
    session.conn.execute(
        "UPDATE incidents SET excluded = 1, exclusion_reason = ?, review_status = 'excluded' WHERE id = ?",
        (reason.strip(), incident_id),
    )
    session.audit("exclude_incident", entity_type="incident", entity_id=incident_id)


def _person_strings(session, incident_id: int) -> list[str]:
    values = []
    for item in session.conn.execute(
        "SELECT payload_enc FROM sensitive_persons WHERE incident_id = ?",
        (incident_id,),
    ):
        payload = json.loads(decrypt_field(session.dek, "person", item["payload_enc"]))
        for value in payload.values():
            if isinstance(value, str) and len(value.strip()) > 2:
                values.append(value.strip())
    return values
