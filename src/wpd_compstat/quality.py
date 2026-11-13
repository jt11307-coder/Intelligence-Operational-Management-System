"""Data-quality counts and exception handling."""

from __future__ import annotations

import json

from wpd_compstat.errors import ValidationError
from wpd_compstat.security.crypto import decrypt_field, encrypt_field


def quality_summary(session) -> dict:
    session.require("data_quality")
    conn = session.conn
    coverage = conn.execute(
        "SELECT MIN(event_date) AS lo, MAX(event_date) AS hi FROM incidents WHERE excluded = 0"
    ).fetchone()
    last_import = conn.execute(
        "SELECT finished_at FROM import_batches WHERE status = 'committed' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    last_backup = conn.execute(
        "SELECT created_at, verified FROM backups ORDER BY id DESC LIMIT 1"
    ).fetchone()
    integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    return {
        "pdfs": conn.execute("SELECT COUNT(*) AS n FROM source_pdfs").fetchone()["n"],
        "incidents": conn.execute("SELECT COUNT(*) AS n FROM incidents WHERE excluded = 0").fetchone()["n"],
        "excluded": conn.execute("SELECT COUNT(*) AS n FROM incidents WHERE excluded = 1").fetchone()["n"],
        "coverage_start": coverage["lo"],
        "coverage_end": coverage["hi"],
        "open_duplicates_note": "Duplicate CAD keys are prevented by the match key. Skipped duplicates are in import summaries.",
        "open_conflicts": conn.execute("SELECT COUNT(*) AS n FROM incident_conflicts WHERE status = 'open'").fetchone()["n"],
        "open_exceptions": conn.execute("SELECT COUNT(*) AS n FROM exception_queue WHERE status = 'open'").fetchone()["n"],
        "unclassified": conn.execute(
            """
            SELECT COUNT(*) AS n FROM incidents i
            WHERE i.excluded = 0 AND NOT EXISTS (
                SELECT 1 FROM classifications c
                WHERE c.incident_id = i.id AND c.counts_officially = 1 AND c.status != 'rejected'
            )
            """
        ).fetchone()["n"],
        "missing_disposition": conn.execute(
            "SELECT COUNT(*) AS n FROM incidents WHERE excluded = 0 AND (disposition IS NULL OR TRIM(disposition) = '')"
        ).fetchone()["n"],
        "probable_reviews": conn.execute(
            "SELECT COUNT(*) AS n FROM classifications WHERE confidence = 'probable_review' AND status = 'system'"
        ).fetchone()["n"],
        "unconfirmed_codes": conn.execute(
            "SELECT COUNT(*) AS n FROM code_mentions WHERE status = 'definition_unconfirmed'"
        ).fetchone()["n"],
        "imports": conn.execute("SELECT COUNT(*) AS n FROM import_batches").fetchone()["n"],
        "integrity": integrity,
        "last_import": None if last_import is None else last_import["finished_at"],
        "last_backup": None if last_backup is None else last_backup["created_at"],
        "last_backup_verified": None if last_backup is None else bool(last_backup["verified"]),
    }


def resolve_exception(session, exception_id: int, resolution: str) -> None:
    session.require("resolve_exceptions")
    if not resolution.strip():
        raise ValidationError("A resolution note is required.")
    row = session.conn.execute("SELECT * FROM exception_queue WHERE id = ?", (exception_id,)).fetchone()
    if row is None:
        raise ValidationError("That exception does not exist.")
    session.conn.execute(
        """
        UPDATE exception_queue
        SET status = 'resolved', resolution = ?, resolved_by = ?, resolved_at = ?
        WHERE id = ?
        """,
        (resolution.strip(), session.user["id"], session.stamp(), exception_id),
    )
    session.audit("resolve_exception", entity_type="exception", entity_id=exception_id)


def create_incident_from_exception(session, exception_id: int, cad_number: str, event_date: str) -> int:
    """An authorized user can supply the missing identifier. The original extract is kept."""
    session.require("resolve_exceptions")
    row = session.conn.execute("SELECT * FROM exception_queue WHERE id = ?", (exception_id,)).fetchone()
    if row is None or not row["original_enc"]:
        raise ValidationError("That exception has no stored extract to correct.")
    raw = json.loads(decrypt_field(session.dek, "exception", row["original_enc"]))
    raw["cad_number"] = cad_number.strip().upper()
    raw["event_date"] = event_date
    from wpd_compstat.import_engine.pipeline import _incident_from_dict, _insert_incident, _replace_system_reading
    from wpd_compstat.classification.service import load_codes, load_rules
    from wpd_compstat.import_engine.merge import match_key

    incident = _incident_from_dict(raw)
    incident.cad_number = cad_number.strip().upper()
    incident.event_date = event_date
    key = match_key(incident.cad_number, incident.event_date)
    if key is None:
        raise ValidationError("A CAD number and an ISO date are required.")
    incident_id = _insert_incident(
        session,
        row["batch_id"],
        {"source_pdf_id": None},
        incident,
        key,
    )
    _replace_system_reading(session, incident_id, incident, load_rules(session.conn), load_codes(session.conn))
    session.conn.execute(
        """
        UPDATE exception_queue
        SET status = 'resolved', incident_id = ?, resolution = ?, resolved_by = ?, resolved_at = ?
        WHERE id = ?
        """,
        (incident_id, "Identifier supplied by an authorized user.", session.user["id"], session.stamp(), exception_id),
    )
    session.audit("exception_to_incident", entity_type="incident", entity_id=incident_id)
    return incident_id
