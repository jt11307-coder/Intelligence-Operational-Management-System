"""Four-stage CAD import. A failed commit rolls back and leaves the previous incidents in place."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict
from pathlib import Path

from wpd_compstat.backup import create_backup
from wpd_compstat.classification.engine import Classifiable
from wpd_compstat.classification.service import load_codes, load_rules, store_system_classifications
from wpd_compstat.db.connection import transaction
from wpd_compstat.db.seed import get_setting
from wpd_compstat.errors import AppError, ValidationError
from wpd_compstat.import_engine.call_log import LAYOUT as CALL_LOG_LAYOUT
from wpd_compstat.import_engine.call_log import count_call_starts, is_call_log
from wpd_compstat.import_engine.extract import count_tables, extract_pages
from wpd_compstat.import_engine.merge import match_key, narrative_hash, person_hash, plan_merge
from wpd_compstat.import_engine.model import (
    ParsedCitation,
    ParsedIncident,
    ParsedNarrative,
    ParsedOfficer,
    ParsedPerson,
    ParsedReport,
    ParsedVehicle,
)
from wpd_compstat.import_engine.parser import parse_pages
from wpd_compstat.security.crypto import decrypt_field, encrypt_field, open_sealed_file, seal_file

_INTERSECTION = re.compile(
    r"([A-Z0-9.'-]+(?:\s+[A-Z0-9.'-]+){0,4}\s(?:ST|AVE|RD|BLVD|DR|LN|WAY|HWY))"
    r"\s+(?:AND|&|@)\s+"
    r"([A-Z0-9.'-]+(?:\s+[A-Z0-9.'-]+){0,4}\s(?:ST|AVE|RD|BLVD|DR|LN|WAY|HWY))",
    re.IGNORECASE,
)


def stage_select(session, paths: list[Path], *, ocr: bool = False) -> int:
    session.require("import_pdf")
    if not paths:
        raise ValidationError("Select at least one PDF.")
    cursor = session.conn.execute(
        """
        INSERT INTO import_batches(status, stage, created_at, created_by)
        VALUES ('staged', 'select', ?, ?)
        """,
        (session.stamp(), session.user["id"]),
    )
    batch_id = int(cursor.lastrowid)
    for path in paths:
        path = Path(path)
        if path.suffix.casefold() != ".pdf" or not path.is_file():
            raise ValidationError("Only PDF files can be imported.")
        with transaction(session.conn):
            _store_file(session, batch_id, path, ocr)
    session.audit("import_select", entity_type="batch", entity_id=batch_id, detail=f"files={len(paths)}")
    return batch_id


def _store_file(session, batch_id: int, path: Path, ocr: bool) -> None:
    """Seal one PDF and record its pages. The caller holds a transaction so a file is never half recorded."""
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    existing = session.conn.execute("SELECT * FROM source_pdfs WHERE sha256 = ?", (digest,)).fetchone()
    if existing is None:
        relative = f"Source PDFs/{digest}.pdf.enc"
        seal_file(session.paths.root / relative, session.dek, data)
        pages, warnings = extract_pages(path, ocr=ocr, work_dir=session.paths.temp)
        table_total = 0 if is_call_log(pages) else _safe_table_count(path)
        stored = session.conn.execute(
            """
            INSERT INTO source_pdfs(
                original_filename, sha256, byte_size, page_count, stored_relative_path, encrypted, first_stored_at
            ) VALUES (?, ?, ?, ?, ?, 1, ?)
            """,
            (path.name, digest, len(data), len(pages), relative, session.stamp()),
        )
        source_id = int(stored.lastrowid)
        for number, text in pages:
            session.conn.execute(
                """
                INSERT INTO source_pages(source_pdf_id, page_number, text_enc)
                VALUES (?, ?, ?)
                """,
                (source_id, number, encrypt_field(session.dek, "page_text", text)),
            )
        if table_total:
            warnings.append(
                f"{table_total} table(s) were detected and were not imported as incidents. No table profile is confirmed."
            )
        error = "; ".join(warnings) if warnings else None
    else:
        source_id = int(existing["id"])
        error = "This file was already stored. It can still be compared for overlapping incidents."
    session.conn.execute(
        """
        INSERT INTO import_files(batch_id, source_pdf_id, original_filename, sha256, page_count, status, error)
        VALUES (?, ?, ?, ?, ?, 'stored', ?)
        """,
        (
            batch_id,
            source_id,
            path.name,
            digest,
            existing["page_count"] if existing is not None else len(pages),
            error,
        ),
    )


def stage_extract(session, batch_id: int) -> dict:
    session.require("import_pdf")
    batch = _batch(session, batch_id)
    if batch["status"] not in {"staged", "extracted", "validated"}:
        raise AppError("This batch cannot be extracted from its current stage.")
    profile, confirmed = _active_profile(session)
    files = session.conn.execute("SELECT * FROM import_files WHERE batch_id = ?", (batch_id,)).fetchall()
    payload = {"files": []}
    for file_row in files:
        pages = _load_pages(session, file_row["source_pdf_id"])
        if not confirmed or profile is None:
            parsed = None
            entry = {
                "import_file_id": file_row["id"],
                "source_pdf_id": file_row["source_pdf_id"],
                "filename": file_row["original_filename"],
                "recognized": False,
                "errors": [
                    "No agency-confirmed CAD layout profile is active. The PDF was stored. Incidents were not guessed."
                ],
                "warnings": [],
                "declared_start": None,
                "declared_end": None,
                "page_count": len(pages),
                "incidents": [],
            }
        else:
            parsed = parse_pages(pages, profile)
            entry = {
                "import_file_id": file_row["id"],
                "source_pdf_id": file_row["source_pdf_id"],
                "filename": file_row["original_filename"],
                "recognized": parsed.recognized,
                "errors": parsed.errors,
                "warnings": parsed.warnings,
                "declared_start": parsed.declared_start,
                "declared_end": parsed.declared_end,
                "page_count": len(pages),
                "call_lines": count_call_starts(pages) if profile.get("layout") == CALL_LOG_LAYOUT else None,
                "incidents": [asdict(incident) for incident in parsed.incidents],
            }
            session.conn.execute(
                """
                UPDATE import_files
                SET declared_start = ?, declared_end = ?, page_count = ?, status = 'extracted'
                WHERE id = ?
                """,
                (parsed.declared_start, parsed.declared_end, len(pages), file_row["id"]),
            )
        payload["files"].append(entry)
    staging = session.paths.imports / "staging" / f"{batch_id}.json.enc"
    seal_file(staging, session.dek, json.dumps(payload).encode("utf-8"))
    session.conn.execute(
        "UPDATE import_batches SET status = 'extracted', stage = 'extract' WHERE id = ?",
        (batch_id,),
    )
    session.audit("import_extract", entity_type="batch", entity_id=batch_id)
    return _preview_counts(payload)


def stage_validate(session, batch_id: int) -> dict:
    session.require("import_pdf")
    payload = _load_staging(session, batch_id)
    summary = _reconcile_preview(session, payload)
    session.conn.execute(
        """
        UPDATE import_batches
        SET status = 'validated', stage = 'validate', summary_json = ?
        WHERE id = ?
        """,
        (json.dumps(summary), batch_id),
    )
    session.audit("import_validate", entity_type="batch", entity_id=batch_id)
    return summary


def stage_commit(session, batch_id: int, *, before_commit=None) -> dict:
    session.require("import_pdf")
    batch = _batch(session, batch_id)
    if batch["status"] == "committed":
        return json.loads(batch["summary_json"] or "{}")
    if batch["status"] not in {"extracted", "validated"}:
        raise AppError("Extract the batch before committing it.")
    payload = _load_staging(session, batch_id)
    create_backup(session, "Before PDF import", "pre_import", permission="import_pdf")
    rules = load_rules(session.conn)
    codes = load_codes(session.conn)
    try:
        with transaction(session.conn):
            summary = _apply_payload(session, batch_id, payload, rules, codes)
            if before_commit is not None:
                before_commit()
            session.conn.execute(
                """
                UPDATE import_batches
                SET status = 'committed', stage = 'complete', finished_at = ?, summary_json = ?, error = NULL
                WHERE id = ?
                """,
                (session.stamp(), json.dumps(summary), batch_id),
            )
    except Exception:
        session.conn.execute(
            "UPDATE import_batches SET error = ? WHERE id = ? AND status != 'committed'",
            ("The import commit was rolled back. The existing database was not changed.", batch_id),
        )
        session.audit("import_rollback", entity_type="batch", entity_id=batch_id, result="rolled_back")
        raise
    session.audit("import_commit", entity_type="batch", entity_id=batch_id)
    return summary


def materialize_source_pdf(session, source_pdf_id: int) -> Path:
    session.require("view_source_pdf")
    row = session.conn.execute("SELECT * FROM source_pdfs WHERE id = ?", (source_pdf_id,)).fetchone()
    if row is None:
        raise AppError("That source PDF is not in the database.")
    target = session.paths.working / "view" / f"{source_pdf_id}.pdf"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(open_sealed_file(session.paths.root / row["stored_relative_path"], session.dek))
    session.audit("view_source_pdf", entity_type="source_pdf", entity_id=source_pdf_id)
    return target


def _apply_payload(session, batch_id: int, payload: dict, rules, codes) -> dict:
    counts = {
        "new_incidents": 0,
        "updated": 0,
        "duplicates": 0,
        "conflicts": 0,
        "exceptions": 0,
        "low_confidence": 0,
        "missing_fields": 0,
        "parsing_errors": 0,
        "unclassified": 0,
        "extracted": 0,
    }
    files_out = []
    for file_entry in payload["files"]:
        counts["parsing_errors"] += len(file_entry["errors"])
        if not file_entry["recognized"]:
            _exception(
                session,
                batch_id,
                "unrecognized_layout",
                file_entry["errors"][0] if file_entry["errors"] else "The layout was not recognized.",
                None,
            )
            counts["exceptions"] += 1
        declared = {"start": file_entry.get("declared_start"), "end": file_entry.get("declared_end")}
        file_new = file_updated = file_duplicates = file_exceptions = 0
        for raw in file_entry["incidents"]:
            incident = _incident_from_dict(raw)
            counts["extracted"] += 1
            missing = _missing_fields(incident)
            counts["missing_fields"] += len(missing)
            if incident.low_confidence:
                counts["low_confidence"] += 1
            key = match_key(incident.cad_number, incident.event_date)
            if key is None:
                _exception(
                    session,
                    batch_id,
                    "missing_identifier",
                    f"A block on page {incident.source_page} is missing a CAD number or a valid date.",
                    raw,
                )
                counts["exceptions"] += 1
                file_exceptions += 1
                continue
            existing = _existing_snapshot(session, key)
            plan = plan_merge(existing, incident)
            if plan["action"] == "duplicate":
                counts["duplicates"] += 1
                file_duplicates += 1
                continue
            if plan["action"] == "insert":
                incident_id = _insert_incident(session, batch_id, file_entry, incident, key)
                counts["new_incidents"] += 1
                file_new += 1
            else:
                incident_id = existing["id"]
                _apply_update(session, batch_id, incident_id, plan, file_entry.get("source_pdf_id"))
                counts["updated"] += 1
                file_updated += 1
                if plan["conflicts"] or plan["omitted_officers"]:
                    counts["conflicts"] += len(plan["conflicts"]) + len(plan["omitted_officers"])
            _replace_system_reading(session, incident_id, incident, rules, codes)
            official = session.conn.execute(
                """
                SELECT COUNT(*) AS n FROM classifications
                WHERE incident_id = ? AND counts_officially = 1 AND status != 'rejected'
                """,
                (incident_id,),
            ).fetchone()["n"]
            if official == 0:
                counts["unclassified"] += 1
            if incident.low_confidence:
                _exception(
                    session,
                    batch_id,
                    "low_confidence",
                    f"CAD {incident.cad_number} was imported with low extraction confidence.",
                    None,
                    incident_id,
                )
                counts["exceptions"] += 1
        files_out.append(
            {
                "filename": file_entry["filename"],
                "pages": file_entry["page_count"],
                "declared_range": declared,
                "call_lines": file_entry.get("call_lines"),
                "extracted": len(file_entry["incidents"]),
                "new_incidents": file_new,
                "existing_updated": file_updated,
                "duplicates_skipped": file_duplicates,
                "exceptions": file_exceptions,
                "parsing_errors": len(file_entry["errors"]),
            }
        )
    _apply_geocode_reference(session.conn)
    total = session.conn.execute("SELECT COUNT(*) AS n FROM incidents WHERE excluded = 0").fetchone()["n"]
    coverage = session.conn.execute(
        """
        SELECT MIN(event_date) AS lo, MAX(event_date) AS hi
        FROM incidents WHERE excluded = 0 AND event_date IS NOT NULL
        """
    ).fetchone()
    summary = {
        "files": files_out,
        "records_extracted": counts["extracted"],
        "new_incidents": counts["new_incidents"],
        "existing_updated": counts["updated"],
        "duplicates_skipped": counts["duplicates"],
        "conflicting_records": counts["conflicts"],
        "unclassified_incidents": counts["unclassified"],
        "low_confidence_extractions": counts["low_confidence"],
        "missing_fields": counts["missing_fields"],
        "parsing_errors": counts["parsing_errors"],
        "exceptions": counts["exceptions"],
        "final_incident_count": total,
        "date_coverage": {"start": coverage["lo"], "end": coverage["hi"]},
        "coverage_gaps": _coverage_gaps(session.conn),
    }
    return summary


def _insert_incident(session, batch_id: int, file_entry: dict, incident: ParsedIncident, key: str) -> int:
    location_id = _location_id(session.conn, incident.location, incident.intersection, incident.business)
    cursor = session.conn.execute(
        """
        INSERT INTO incidents(
            cad_number, event_date, event_time, received_time, dispatch_time, arrival_time, clear_time,
            call_type, call_classification, call_source, priority, disposition, final_disposition,
            call_taker, location_id, business_landmark, extraction_confidence, review_status,
            source_pdf_id, source_page, first_batch_id, last_batch_id, match_key, follow_up,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            " ".join(incident.cad_number.split()).upper(),
            incident.event_date,
            incident.event_time,
            incident.received_time,
            incident.dispatch_time,
            incident.arrival_time,
            incident.clear_time,
            incident.call_type,
            incident.call_classification,
            incident.call_source,
            incident.priority,
            incident.disposition,
            incident.final_disposition,
            incident.call_taker,
            location_id,
            incident.business,
            incident.confidence,
            "needs_review" if incident.low_confidence else "unreviewed",
            file_entry["source_pdf_id"],
            incident.source_page,
            batch_id,
            batch_id,
            key,
            None if incident.follow_up is None else int(incident.follow_up),
            session.stamp(),
            session.stamp(),
        ),
    )
    incident_id = int(cursor.lastrowid)
    _add_children(session, incident_id, file_entry, incident, plan_merge(None, incident))
    return incident_id


def _apply_update(session, batch_id: int, incident_id: int, plan: dict, source_pdf_id: int | None) -> None:
    for field_name, value in plan["updates"].items():
        allowed = {
            "event_time",
            "received_time",
            "dispatch_time",
            "arrival_time",
            "clear_time",
            "call_type",
            "call_classification",
            "call_source",
            "priority",
            "disposition",
            "final_disposition",
            "call_taker",
            "business_landmark",
        }
        column = "business_landmark" if field_name == "business_landmark" else field_name
        if field_name == "location_text":
            current = session.conn.execute("SELECT location_id FROM incidents WHERE id = ?", (incident_id,)).fetchone()
            if current["location_id"] is None:
                location_id = _location_id(session.conn, value, None, None)
                _history(session, incident_id, "location_id", None, str(location_id), batch_id, "import_update")
                session.conn.execute(
                    "UPDATE incidents SET location_id = ?, updated_at = ? WHERE id = ?",
                    (location_id, session.stamp(), incident_id),
                )
            continue
        if field_name == "intersection" or column not in allowed:
            continue
        old = session.conn.execute(f"SELECT {column} AS value FROM incidents WHERE id = ?", (incident_id,)).fetchone()
        _history(session, incident_id, column, old["value"], value, batch_id, "import_update")
        session.conn.execute(
            f"UPDATE incidents SET {column} = ?, updated_at = ?, last_batch_id = ? WHERE id = ?",
            (value, session.stamp(), batch_id, incident_id),
        )
    for conflict in plan["conflicts"]:
        session.conn.execute(
            """
            INSERT INTO incident_conflicts(
                incident_id, batch_id, field_name, existing_value, incoming_value, status, created_at
            ) VALUES (?, ?, ?, ?, ?, 'open', ?)
            """,
            (
                incident_id,
                batch_id,
                conflict["field_name"],
                conflict.get("existing_value"),
                conflict.get("incoming_value"),
                session.stamp(),
            ),
        )
    for omitted in plan["omitted_officers"]:
        session.conn.execute(
            """
            INSERT INTO incident_conflicts(
                incident_id, batch_id, field_name, existing_value, incoming_value, status, created_at
            ) VALUES (?, ?, 'officers', ?, NULL, 'open', ?)
            """,
            (incident_id, batch_id, omitted, session.stamp()),
        )
    if plan["conflicts"] or plan["omitted_officers"]:
        session.conn.execute(
            "UPDATE incidents SET review_status = 'needs_review', last_batch_id = ?, updated_at = ? WHERE id = ?",
            (batch_id, session.stamp(), incident_id),
        )
    else:
        session.conn.execute(
            "UPDATE incidents SET last_batch_id = ?, updated_at = ? WHERE id = ?",
            (batch_id, session.stamp(), incident_id),
        )
    file_entry = {"source_pdf_id": source_pdf_id}
    incident = ParsedIncident(cad_number="x", event_date="2000-01-01")
    _add_children(session, incident_id, file_entry, incident, plan)


def _add_children(session, incident_id: int, file_entry: dict, incident: ParsedIncident, plan: dict) -> None:
    source_pdf_id = file_entry.get("source_pdf_id")
    sequence_row = session.conn.execute(
        "SELECT COALESCE(MAX(sequence), 0) AS n FROM narratives WHERE incident_id = ?",
        (incident_id,),
    ).fetchone()
    sequence = int(sequence_row["n"])
    for narrative in plan["narratives"]:
        sequence += 1
        session.conn.execute(
            """
            INSERT OR IGNORE INTO narratives(
                incident_id, sequence, narrative_time, author, body, body_sha256, source_pdf_id, source_page
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                incident_id,
                sequence,
                narrative.time_text,
                narrative.author,
                narrative.body,
                narrative_hash(narrative.body),
                source_pdf_id,
                narrative.page,
            ),
        )
    for officer in plan["officers"]:
        officer_id = None
        if officer.name or officer.badge:
            officer_id = _officer_id(session.conn, officer.badge, officer.name)
        if officer_id is None and not officer.unit:
            continue
        session.conn.execute(
            """
            INSERT INTO incident_officers(incident_id, officer_id, role, unit_call_sign)
            VALUES (?, ?, ?, ?)
            """,
            (incident_id, officer_id, officer.role or "assigned", officer.unit),
        )
    for report in plan["reports"]:
        session.conn.execute(
            """
            INSERT OR IGNORE INTO report_references(incident_id, ref_type, ref_number)
            VALUES (?, ?, ?)
            """,
            (incident_id, report.ref_type, report.ref_number),
        )
    for citation in plan["citations"]:
        session.conn.execute(
            """
            INSERT INTO citations(incident_id, citation_number, verified_violation, warning, source)
            VALUES (?, ?, ?, ?, 'cad_reference')
            """,
            (incident_id, citation.number, int(citation.verified), int(citation.warning)),
        )
    for vehicle in plan["vehicles"]:
        plate = None
        if vehicle.plate:
            plate = encrypt_field(session.dek, "vehicle_plate", vehicle.plate)
        session.conn.execute(
            """
            INSERT INTO vehicles(incident_id, role, description, state, plate_enc)
            VALUES (?, ?, ?, ?, ?)
            """,
            (incident_id, vehicle.role, vehicle.description, vehicle.state, plate),
        )
    for person in plan["persons"]:
        session.conn.execute(
            """
            INSERT INTO sensitive_persons(incident_id, role, payload_enc, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (
                incident_id,
                person.role,
                encrypt_field(session.dek, "person", json.dumps(person.payload)),
                session.stamp(),
            ),
        )


def _replace_system_reading(session, incident_id: int, incident: ParsedIncident, rules, codes) -> None:
    manual = {
        row["category"]
        for row in session.conn.execute(
            "SELECT category FROM classifications WHERE incident_id = ? AND status != 'system'",
            (incident_id,),
        )
    }
    session.conn.execute(
        "DELETE FROM classifications WHERE incident_id = ? AND status = 'system'",
        (incident_id,),
    )
    record = Classifiable(
        call_type=incident.call_type,
        call_classification=incident.call_classification,
        disposition=incident.disposition,
        final_disposition=incident.final_disposition,
        narratives=[item.body for item in incident.narratives],
        report_types=[item.ref_type for item in incident.reports],
        citation_numbers=[item.number for item in incident.citations if item.number],
        citation_verified=any(item.verified for item in incident.citations),
        citation_warning=any(item.warning for item in incident.citations),
        officer_slots=sum(1 for item in incident.officers if item.role != "primary_unit"),
        follow_up=incident.follow_up,
    )
    # Keep user decisions. Filter after classify by inserting only new categories.
    from wpd_compstat.classification.engine import classify

    proposals = [proposal for proposal in classify(record, rules) if proposal.category not in manual]
    for proposal in proposals:
        from wpd_compstat.classification.service import _insert_proposal

        _insert_proposal(session.conn, incident_id, proposal, session.stamp())
    from wpd_compstat.classification.codes import scan_codes

    session.conn.execute("DELETE FROM code_mentions WHERE incident_id = ?", (incident_id,))
    for mention in scan_codes(record.call_type, record.narratives, codes):
        session.conn.execute(
            """
            INSERT INTO code_mentions(incident_id, code, evidence, status)
            VALUES (?, ?, ?, ?)
            """,
            (incident_id, mention["code"], mention["evidence"], mention["status"]),
        )


def _existing_snapshot(session, key: str) -> dict | None:
    row = session.conn.execute("SELECT * FROM incidents WHERE match_key = ?", (key,)).fetchone()
    if row is None:
        return None
    location = None
    intersection = None
    if row["location_id"]:
        location_row = session.conn.execute(
            "SELECT * FROM locations WHERE id = ?",
            (row["location_id"],),
        ).fetchone()
        location = location_row["raw_address"]
        intersection = location_row["intersection"]
    narratives = session.conn.execute(
        "SELECT body_sha256 FROM narratives WHERE incident_id = ?",
        (row["id"],),
    ).fetchall()
    officers = session.conn.execute(
        """
        SELECT o.badge, o.display_name, io.role, io.unit_call_sign
        FROM incident_officers io
        LEFT JOIN officers o ON o.id = io.officer_id
        WHERE io.incident_id = ?
        """,
        (row["id"],),
    ).fetchall()
    reports = session.conn.execute(
        "SELECT ref_type, ref_number FROM report_references WHERE incident_id = ?",
        (row["id"],),
    ).fetchall()
    citations = session.conn.execute(
        "SELECT citation_number, verified_violation, warning FROM citations WHERE incident_id = ?",
        (row["id"],),
    ).fetchall()
    vehicles = session.conn.execute(
        "SELECT description, role, state FROM vehicles WHERE incident_id = ?",
        (row["id"],),
    ).fetchall()
    people = session.conn.execute(
        "SELECT role, payload_enc FROM sensitive_persons WHERE incident_id = ?",
        (row["id"],),
    ).fetchall()
    person_hashes = []
    for person in people:
        payload = json.loads(decrypt_field(session.dek, "person", person["payload_enc"]))
        person_hashes.append(person_hash(ParsedPerson(person["role"], payload)))
    from wpd_compstat.import_engine.merge import _officer_key

    return {
        "id": row["id"],
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
        "location_text": location,
        "intersection": intersection,
        "narrative_hashes": [item["body_sha256"] for item in narratives],
        "officer_keys": [
            _officer_key(item["badge"], item["display_name"], item["role"], item["unit_call_sign"])
            for item in officers
        ],
        "report_keys": [f"{item['ref_type']}|{item['ref_number']}" for item in reports],
        "citations": [
            {"number": item["citation_number"], "verified": item["verified_violation"], "warning": item["warning"]}
            for item in citations
        ],
        "vehicle_keys": [
            "|".join([item["description"] or "", item["role"] or "", item["state"] or ""]) for item in vehicles
        ],
        "person_hashes": person_hashes,
    }


def _reconcile_preview(session, payload: dict) -> dict:
    """Preview counts without writing incidents."""
    new = updated = duplicates = conflicts = exceptions = extracted = 0
    for file_entry in payload["files"]:
        if not file_entry["recognized"]:
            exceptions += 1
        for raw in file_entry["incidents"]:
            incident = _incident_from_dict(raw)
            extracted += 1
            key = match_key(incident.cad_number, incident.event_date)
            if key is None:
                exceptions += 1
                continue
            plan = plan_merge(_existing_snapshot(session, key), incident)
            if plan["action"] == "insert":
                new += 1
            elif plan["action"] == "duplicate":
                duplicates += 1
            elif plan["action"] == "update":
                updated += 1
                conflicts += len(plan["conflicts"])
    return {
        "records_extracted": extracted,
        "new_incidents": new,
        "existing_updated": updated,
        "duplicates_skipped": duplicates,
        "conflicting_records": conflicts,
        "exceptions": exceptions,
        "final_incident_count": session.conn.execute(
            "SELECT COUNT(*) AS n FROM incidents WHERE excluded = 0"
        ).fetchone()["n"],
        "note": "Preview only. The database has not been changed.",
    }


def _preview_counts(payload: dict) -> dict:
    return {
        "files": len(payload["files"]),
        "extracted": sum(len(item["incidents"]) for item in payload["files"]),
        "recognized_files": sum(1 for item in payload["files"] if item["recognized"]),
    }


def _load_staging(session, batch_id: int) -> dict:
    path = session.paths.imports / "staging" / f"{batch_id}.json.enc"
    if not path.exists():
        raise AppError("The staging file for this batch is missing. Select the PDFs again.")
    return json.loads(open_sealed_file(path, session.dek).decode("utf-8"))


def _load_pages(session, source_pdf_id: int) -> list[tuple[int, str]]:
    rows = session.conn.execute(
        "SELECT page_number, text_enc FROM source_pages WHERE source_pdf_id = ? ORDER BY page_number",
        (source_pdf_id,),
    ).fetchall()
    return [(row["page_number"], decrypt_field(session.dek, "page_text", row["text_enc"])) for row in rows]


def _active_profile(session) -> tuple[dict | None, bool]:
    profile_id = get_setting(session.conn, "active_profile_id", None)
    if not profile_id:
        return None, False
    row = session.conn.execute("SELECT * FROM cad_profiles WHERE id = ?", (profile_id,)).fetchone()
    if row is None:
        return None, False
    return json.loads(row["definition_json"]), row["confirmation"] == "agency_confirmed"


def _batch(session, batch_id: int):
    row = session.conn.execute("SELECT * FROM import_batches WHERE id = ?", (batch_id,)).fetchone()
    if row is None:
        raise AppError("That import batch does not exist.")
    return row


def _exception(session, batch_id: int, kind: str, detail: str, raw, incident_id: int | None = None) -> None:
    original = None
    if raw is not None:
        safe = dict(raw)
        safe.pop("persons", None)
        original = encrypt_field(session.dek, "exception", json.dumps(safe)[:4000])
    session.conn.execute(
        """
        INSERT INTO exception_queue(batch_id, incident_id, kind, detail, original_enc, status, created_at)
        VALUES (?, ?, ?, ?, ?, 'open', ?)
        """,
        (batch_id, incident_id, kind, detail[:240], original, session.stamp()),
    )


def _history(session, incident_id, field_name, old, new, batch_id, reason) -> None:
    session.conn.execute(
        """
        INSERT INTO incident_field_history(
            incident_id, field_name, old_value, new_value, batch_id, changed_at, changed_by, change_reason
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (incident_id, field_name, old, new, batch_id, session.stamp(), session.user["id"], reason),
    )


def _incident_from_dict(raw: dict) -> ParsedIncident:
    return ParsedIncident(
        cad_number=raw.get("cad_number"),
        event_date=raw.get("event_date"),
        event_time=raw.get("event_time"),
        received_time=raw.get("received_time"),
        dispatch_time=raw.get("dispatch_time"),
        arrival_time=raw.get("arrival_time"),
        clear_time=raw.get("clear_time"),
        call_type=raw.get("call_type"),
        call_classification=raw.get("call_classification"),
        call_source=raw.get("call_source"),
        priority=raw.get("priority"),
        disposition=raw.get("disposition"),
        final_disposition=raw.get("final_disposition"),
        call_taker=raw.get("call_taker"),
        location=raw.get("location"),
        business=raw.get("business"),
        intersection=raw.get("intersection"),
        primary_unit=raw.get("primary_unit"),
        follow_up=raw.get("follow_up"),
        source_page=raw.get("source_page") or 1,
        warnings=list(raw.get("warnings") or []),
        narratives=[ParsedNarrative(**item) for item in raw.get("narratives") or []],
        officers=[ParsedOfficer(**item) for item in raw.get("officers") or []],
        citations=[ParsedCitation(**item) for item in raw.get("citations") or []],
        reports=[ParsedReport(**item) for item in raw.get("reports") or []],
        vehicles=[ParsedVehicle(**item) for item in raw.get("vehicles") or []],
        persons=[ParsedPerson(**item) for item in raw.get("persons") or []],
        confidence=raw.get("confidence") or 0,
    )


def _missing_fields(incident: ParsedIncident) -> list[str]:
    values = {
        "cad_number": incident.cad_number,
        "event_date": incident.event_date,
        "event_time": incident.event_time,
        "call_type": incident.call_type,
        "disposition": incident.disposition,
        "location": incident.location,
    }
    return [name for name, value in values.items() if not value]


def _location_id(conn, raw: str | None, intersection: str | None, business: str | None) -> int | None:
    if not raw and not intersection and not business:
        return None
    normalized = " ".join((raw or intersection or business).upper().split())
    detected = intersection
    if not detected and raw:
        match = _INTERSECTION.search(raw.upper())
        if match:
            detected = f"{match.group(1)} AND {match.group(2)}"
    street = detected or (raw.split(",")[0].strip() if raw else None)
    found = conn.execute("SELECT id FROM locations WHERE normalized_address = ?", (normalized,)).fetchone()
    if found:
        return int(found["id"])
    cursor = conn.execute(
        """
        INSERT INTO locations(
            raw_address, normalized_address, street, intersection, business, coord_quality
        ) VALUES (?, ?, ?, ?, ?, 'none')
        """,
        (raw, normalized, street, detected, business),
    )
    return int(cursor.lastrowid)


def _officer_id(conn, badge: str | None, name: str | None) -> int | None:
    if badge:
        found = conn.execute("SELECT id FROM officers WHERE badge = ?", (badge,)).fetchone()
        if found:
            return int(found["id"])
    elif name:
        found = conn.execute(
            "SELECT id FROM officers WHERE badge IS NULL AND display_name = ? COLLATE NOCASE",
            (name,),
        ).fetchone()
        if found:
            return int(found["id"])
    display = name or (f"Badge {badge}" if badge else None)
    if not display:
        return None
    cursor = conn.execute(
        "INSERT INTO officers(badge, display_name, active) VALUES (?, ?, 1)",
        (badge, display),
    )
    return int(cursor.lastrowid)


def _apply_geocode_reference(conn) -> None:
    refs = conn.execute("SELECT * FROM geocode_reference").fetchall()
    for ref in refs:
        conn.execute(
            """
            UPDATE locations
            SET latitude = ?, longitude = ?, coord_quality = ?, coord_source = 'offline_reference'
            WHERE normalized_address = ?
              AND (
                    coord_quality = 'none'
                    OR (coord_quality = 'approximate' AND ? = 'exact')
                  )
            """,
            (ref["latitude"], ref["longitude"], ref["quality"], ref["address_key"], ref["quality"]),
        )


def _coverage_gaps(conn) -> list[dict]:
    rows = conn.execute(
        """
        SELECT declared_start, declared_end FROM import_files
        WHERE declared_start IS NOT NULL AND declared_end IS NOT NULL
        """
    ).fetchall()
    if len(rows) < 2:
        return []
    ranges = sorted((row["declared_start"], row["declared_end"]) for row in rows)
    gaps = []
    from datetime import date, timedelta

    cursor = date.fromisoformat(ranges[0][1])
    for start_text, end_text in ranges[1:]:
        start = date.fromisoformat(start_text)
        if start > cursor + timedelta(days=1):
            gaps.append({"start": (cursor + timedelta(days=1)).isoformat(), "end": (start - timedelta(days=1)).isoformat()})
        cursor = max(cursor, date.fromisoformat(end_text))
    return gaps


def _safe_table_count(path: Path) -> int:
    try:
        return count_tables(path)
    except Exception:
        return 0
