"""Structural import tests use a labeled synthetic fixture, not a department CAD PDF."""

from pathlib import Path

import pytest

from tests.conftest import write_pdf
from wpd_compstat.import_engine.pipeline import stage_commit, stage_extract, stage_select, stage_validate

PROFILE = "WPD-COMPSTAT-PROFILE: generic-labeled-v1\nDECLARED-RANGE: 2026-01-01 2026-01-31\n"


def _incident(cad: str, **overrides) -> str:
    fields = {
        "CAD Number": cad,
        "Date": "2026-01-15",
        "Time": "14:05",
        "Received": "14:02",
        "Call Type": "TRAFFIC STOP",
        "Call Classification": "",
        "Call Source": "OFFICER INITIATED",
        "Priority": "3",
        "Disposition": "WARNING",
        "Final Disposition": "WARNING",
        "Call Taker": "TA1",
        "Location": "100 MAIN ST",
        "Business": "",
        "Primary Unit": "3A12",
        "Officers": "1234 DOE, JANE | primary; 5678 SMITH, JOHN | assisting",
        "Dispatch": "14:03",
        "Arrival": "14:06",
        "Clear": "14:20",
        "Vehicles": "white sedan | role=involved | plate=ABC123 | state=RI",
        "Citations": "C-100 | verified=no | warning=yes",
        "Reports": "ARREST:AR-1",
        "Persons": "role=operator | name=ALEX EXAMPLE | dob=1990-01-01",
        "Follow Up": "no",
    }
    fields.update(overrides)
    lines = ["=== INCIDENT ==="]
    for label, value in fields.items():
        lines.append(f"{label}: {value}")
    lines.append("Narratives:")
    lines.append(overrides.get("_narrative", "[2026-01-15 14:10 | DOE] Conducted a traffic stop and issued a verbal warning."))
    lines.append("=== END INCIDENT ===")
    return "\n".join(lines)


def _import(session, path: Path, *, before_commit=None) -> dict:
    batch_id = stage_select(session, [path])
    stage_extract(session, batch_id)
    stage_validate(session, batch_id)
    return stage_commit(session, batch_id, before_commit=before_commit)


def test_fresh_database_has_no_incidents(session):
    assert session.conn.execute("SELECT COUNT(*) AS n FROM incidents").fetchone()["n"] == 0
    definitions = session.conn.execute("SELECT definition, status FROM agency_codes").fetchall()
    assert definitions
    assert all(row["definition"] is None and row["status"] == "unconfirmed" for row in definitions)


def test_unconfirmed_profile_stores_pdf_and_imports_nothing(session, tmp_path):
    path = tmp_path / "synthetic.pdf"
    write_pdf(path, [PROFILE + _incident("SYN-1")])
    summary = _import(session, path)
    assert summary["new_incidents"] == 0
    assert session.conn.execute("SELECT COUNT(*) AS n FROM incidents").fetchone()["n"] == 0
    assert session.conn.execute("SELECT COUNT(*) AS n FROM source_pdfs").fetchone()["n"] == 1


def test_decoy_text_is_not_turned_into_incidents(confirmed_session, tmp_path):
    path = tmp_path / "decoy.pdf"
    write_pdf(path, ["Assault and firearm were mentioned at 100 MAIN ST. Code 1500G appears here. This is not a CAD block."])
    summary = _import(confirmed_session, path)
    assert summary["new_incidents"] == 0
    assert confirmed_session.conn.execute("SELECT COUNT(*) AS n FROM incidents").fetchone()["n"] == 0


def test_synthetic_profile_preserves_one_incident_for_many_officers_and_narratives(confirmed_session, tmp_path):
    page_one = PROFILE + _incident("SYN-1001").replace(
        "[2026-01-15 14:10 | DOE] Conducted a traffic stop and issued a verbal warning.\n=== END INCIDENT ===",
        "[2026-01-15 14:10 | DOE] Started on page one.",
    )
    page_two = (
        "[2026-01-15 14:20 | DOE] Continued on page two. No firearm located.\n=== END INCIDENT ===\n"
        + _incident(
            "SYN-1002",
            **{
                "Call Type": "SHOPLIFTING",
                "Officers": "2222 LEE, PAT | primary",
                "Citations": "",
                "Reports": "",
                "Persons": "",
                "Location": "50 OAK AVE",
                "_narrative": "[2026-01-15 15:00 | LEE] The person shoplifted merchandise.",
            },
        )
    )
    path = tmp_path / "synthetic-call-log.pdf"
    write_pdf(path, [page_one, page_two])
    summary = _import(confirmed_session, path)
    assert summary["new_incidents"] == 2
    assert summary["final_incident_count"] == 2
    officers = confirmed_session.conn.execute(
        """
        SELECT COUNT(*) AS n FROM incident_officers io
        JOIN incidents i ON i.id = io.incident_id
        WHERE i.cad_number = 'SYN-1001' AND io.role != 'primary_unit'
        """
    ).fetchone()["n"]
    narratives = confirmed_session.conn.execute(
        """
        SELECT COUNT(*) AS n FROM narratives n
        JOIN incidents i ON i.id = n.incident_id
        WHERE i.cad_number = 'SYN-1001'
        """
    ).fetchone()["n"]
    assert officers == 2
    assert narratives == 2
    assert confirmed_session.conn.execute(
        "SELECT COUNT(*) AS n FROM classifications WHERE category = 'verified_traffic_violation' AND counts_officially = 1"
    ).fetchone()["n"] == 0
    assert confirmed_session.conn.execute(
        "SELECT COUNT(*) AS n FROM classifications WHERE category = 'warning' AND counts_officially = 1"
    ).fetchone()["n"] == 1
    person = confirmed_session.conn.execute("SELECT payload_enc FROM sensitive_persons").fetchone()["payload_enc"]
    assert "ALEX EXAMPLE" not in person


def test_same_pdf_twice_does_not_double_incidents(confirmed_session, tmp_path):
    path = tmp_path / "once.pdf"
    write_pdf(path, [PROFILE + _incident("SYN-9")])
    first = _import(confirmed_session, path)
    second = _import(confirmed_session, path)
    assert first["new_incidents"] == 1
    assert second["new_incidents"] == 0
    assert second["duplicates_skipped"] == 1
    assert confirmed_session.conn.execute("SELECT COUNT(*) AS n FROM incidents").fetchone()["n"] == 1


def test_conflicting_disposition_is_kept_and_flagged(confirmed_session, tmp_path):
    first = tmp_path / "first.pdf"
    second = tmp_path / "second.pdf"
    write_pdf(first, [PROFILE + _incident("SYN-3")])
    write_pdf(second, [PROFILE + _incident("SYN-3", **{"Disposition": "ARREST", "_narrative": "[2026-01-15 16:00 | DOE] Supplemental note."})])
    _import(confirmed_session, first)
    summary = _import(confirmed_session, second)
    disposition = confirmed_session.conn.execute("SELECT disposition FROM incidents WHERE cad_number = 'SYN-3'").fetchone()["disposition"]
    assert disposition == "WARNING"
    assert summary["conflicting_records"] >= 1
    assert confirmed_session.conn.execute("SELECT COUNT(*) AS n FROM narratives n JOIN incidents i ON i.id = n.incident_id WHERE i.cad_number = 'SYN-3'").fetchone()["n"] == 2


def test_failed_commit_rolls_back(confirmed_session, tmp_path):
    path = tmp_path / "rollback.pdf"
    write_pdf(path, [PROFILE + _incident("SYN-4")])

    def explode():
        raise RuntimeError("forced failure")

    with pytest.raises(RuntimeError):
        _import(confirmed_session, path, before_commit=explode)
    assert confirmed_session.conn.execute("SELECT COUNT(*) AS n FROM incidents").fetchone()["n"] == 0


def test_missing_identifier_is_not_invented(confirmed_session, tmp_path):
    block = _incident("SYN-5").replace("CAD Number: SYN-5", "CAD Number: ")
    path = tmp_path / "missing.pdf"
    write_pdf(path, [PROFILE + block])
    summary = _import(confirmed_session, path)
    assert summary["new_incidents"] == 0
    assert summary["exceptions"] >= 1
