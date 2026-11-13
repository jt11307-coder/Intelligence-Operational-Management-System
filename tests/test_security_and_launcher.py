"""Security, backup, counting, and launcher behavior."""

import os
from datetime import date, timedelta
from pathlib import Path

from wpd_compstat.analysis.compare import percent_change
from wpd_compstat.analysis.traffic import import_traffic_export, weekly_verified_totals
from wpd_compstat.assignments import create_assignment, transition
from wpd_compstat.backup import create_backup, export_encrypted_copy, restore_backup
from wpd_compstat.constants import SAME_DRIVE_BACKUP_WARNING
from wpd_compstat.errors import AuthError, ValidationError
from wpd_compstat.install import initialize_installation
from wpd_compstat.launcher.cli import child_environment
from wpd_compstat.launcher.scan import find_installations, launch_plan
from wpd_compstat.launcher.shortcut import bat_contents, shortcut_text_has_drive_letter, vbs_contents
from wpd_compstat.search import incident_detail
from wpd_compstat.security.crypto import open_sealed_file


def test_database_is_encrypted_at_rest_and_has_no_fixed_key(session):
    session.lock()
    encrypted = session.paths.db_encrypted.read_bytes()
    assert not encrypted.startswith(b"SQLite format 3")
    assert not session.paths.db_working.exists()
    session.unlock("admin", "Correcthorse1")
    source = Path(__file__).resolve().parents[1] / "src" / "wpd_compstat" / "security" / "crypto.py"
    text = source.read_text(encoding="utf-8")
    assert "os.urandom(32)" in text
    assert "BEGIN PRIVATE KEY" not in text


def test_lockout_and_role_denial(session, tmp_path):
    session.create_user("viewer", "Viewerpass123", "read_only")
    session.lock()
    for _ in range(5):
        try:
            session.unlock("viewer", "wrong-password-1")
        except AuthError:
            pass
    try:
        session.unlock("viewer", "Viewerpass123")
        raise AssertionError("Locked account accepted a password.")
    except AuthError as exc:
        assert "locked" in str(exc).casefold()
    session.clock = lambda: __import__("datetime").datetime.now(__import__("datetime").timezone.utc) + timedelta(minutes=20)
    # The lockout timestamp was written with the original clock. Advance by replacing unlock comparison
    # through a session whose clock is twenty minutes ahead of the stored timestamp.
    session.unlock("admin", "Correcthorse1")
    from wpd_compstat.import_engine.pipeline import stage_select

    session.lock()
    session.unlock("viewer", "Viewerpass123")
    try:
        stage_select(session, [tmp_path / "missing.pdf"])
        raise AssertionError("Read-only user imported a PDF.")
    except AuthError:
        pass


def test_backup_restore_and_encrypted_copy(session, tmp_path):
    session.conn.execute(
        """
        INSERT INTO incidents(
            cad_number, event_date, match_key, created_at, updated_at, extraction_confidence, review_status
        ) VALUES ('SYN-A', '2026-01-01', 'SYN-A|2026-01-01', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00', 1, 'unreviewed')
        """
    )
    backup = create_backup(session, "Test", "manual")
    assert SAME_DRIVE_BACKUP_WARNING in backup["warning"]
    session.conn.execute(
        """
        INSERT INTO incidents(
            cad_number, event_date, match_key, created_at, updated_at, extraction_confidence, review_status
        ) VALUES ('SYN-B', '2026-01-02', 'SYN-B|2026-01-02', '2026-01-02T00:00:00+00:00', '2026-01-02T00:00:00+00:00', 1, 'unreviewed')
        """
    )
    copy = export_encrypted_copy(session, backup["id"], tmp_path)
    assert not copy.read_bytes().startswith(b"SQLite format 3")
    restore_backup(session, backup["id"])
    numbers = [row["cad_number"] for row in session.conn.execute("SELECT cad_number FROM incidents ORDER BY cad_number")]
    assert numbers == ["SYN-A"]


def test_percentages_are_withheld_for_small_baselines():
    change = percent_change(4, 2, min_baseline=5)
    assert change["comparable"] is False
    assert change["absolute_change"] == 2
    assert change["percent"] is None
    zero = percent_change(3, 0)
    assert zero["percent"] is None


def test_prior_year_is_not_reported_as_zero(session):
    session.conn.execute(
        """
        INSERT INTO incidents(
            cad_number, event_date, match_key, created_at, updated_at, extraction_confidence, review_status
        ) VALUES ('SYN-Y', '2026-11-01', 'SYN-Y|2026-11-01', '2026-11-01T00:00:00+00:00', '2026-11-01T00:00:00+00:00', 1, 'unreviewed')
        """
    )
    from wpd_compstat.analysis.compare import compare_calls

    rows = {row["label"]: row for row in compare_calls(session.conn, date(2026, 11, 1), date(2026, 11, 13))}
    prior = rows["Equivalent prior-year period"]
    assert prior["baseline"] is None
    assert prior["percent"] is None


def test_traffic_citation_references_are_not_verified(session, tmp_path):
    path = tmp_path / "traffic.csv"
    path.write_text(
        "officer,when,where,citations,warnings\n"
        "DOE,2026-01-06T10:00:00,MAIN ST,10,2\n",
        encoding="utf-8",
    )
    before = path.read_bytes()
    result = import_traffic_export(
        session,
        path,
        {"officer": "officer_name", "when": "occurred_at", "where": "location_text", "citations": "citation_references", "warnings": "warnings"},
    )
    assert path.read_bytes() == before
    assert result["counting_rule_status"] == "references_not_counted"
    weeks = weekly_verified_totals(session.conn, "2026-01-01", "2026-01-31", 200)
    assert weeks[0]["verified_violations"] == 0
    assert weeks[0]["citation_references"] == 10
    assert weeks[0]["warnings"] == 2


def test_assignment_completion_is_not_effectiveness(session):
    officer = session.conn.execute("INSERT INTO officers(display_name, active) VALUES ('COMMANDER', 1)").lastrowid
    assignment_id = create_assignment(session, "Intersection review", "Documented crash concentration.")
    from wpd_compstat.assignments import set_commander

    set_commander(session, assignment_id, officer_id=officer)
    transition(session, assignment_id, "approved")
    transition(session, assignment_id, "assigned")
    transition(session, assignment_id, "in_progress")
    transition(session, assignment_id, "completed")
    status = session.conn.execute("SELECT status FROM assignments WHERE id = ?", (assignment_id,)).fetchone()["status"]
    assert status == "completed"
    try:
        transition(session, assignment_id, "effective")
    except AuthError:
        raise
    status = session.conn.execute("SELECT status FROM assignments WHERE id = ?", (assignment_id,)).fetchone()["status"]
    assert status == "effective"


def test_drive_opener_has_no_drive_letter():
    text = (Path(__file__).resolve().parents[1] / "launcher" / "Open WPD COMPSTAT.bat").read_text(encoding="utf-8")
    assert "%~dp0" in text
    assert "L:\\" not in text
    assert "Desktop" not in text.split("Do not copy", 1)[0]


def test_source_child_sees_the_package_root():
    import wpd_compstat

    src = str(Path(wpd_compstat.__file__).resolve().parents[1])
    assert child_environment()["PYTHONPATH"].split(os.pathsep)[0] == src


def test_launcher_drive_letters_and_shortcut(tmp_path):
    first = tmp_path / "E"
    second = tmp_path / "G"
    root = initialize_installation(first / "WPD COMPSTAT")
    found, _problems = find_installations([first, second])
    assert len(found) == 1
    assert found[0].root == root
    moved = initialize_installation(second / "WPD COMPSTAT")
    found, _problems = find_installations([second])
    assert found[0].root == moved
    missing, _problems = find_installations([tmp_path / "absent"])
    plan = launch_plan(missing, allow_source=False)
    assert plan["code"] == 2
    both, _problems = find_installations([first, second])
    assert launch_plan(both, allow_source=True)["code"] == 4
    chosen = launch_plan(both, selector=lambda items: items[0], allow_source=True)
    assert chosen["ok"] is True
    refused = launch_plan(found, allow_source=False)
    assert refused["code"] == 3
    entry = found[0].application_path
    original = entry.read_bytes()
    entry.write_bytes(original + b"tamper")
    tampered, problems = find_installations([second])
    assert tampered == []
    assert any("hash-mismatch" in item for item in problems)
    assert shortcut_text_has_drive_letter(bat_contents()) is False
    assert shortcut_text_has_drive_letter(vbs_contents()) is False


def test_sensitive_detail_is_withheld_and_audit_is_redacted(session):
    from wpd_compstat.audit import write_audit

    write_audit(
        session.conn,
        occurred_at=session.stamp(),
        user=session.user,
        action="probe",
        detail="password=Secretvalue1 narrative=ALEX EXAMPLE should not survive",
    )
    stored = session.conn.execute("SELECT detail FROM audit_log WHERE action = 'probe'").fetchone()["detail"]
    assert "Secretvalue1" not in stored
    session.conn.execute(
        """
        INSERT INTO incidents(
            cad_number, event_date, match_key, created_at, updated_at, extraction_confidence, review_status
        ) VALUES ('SYN-P', '2026-02-01', 'SYN-P|2026-02-01', '2026-02-01T00:00:00+00:00', '2026-02-01T00:00:00+00:00', 1, 'unreviewed')
        """
    )
    incident_id = session.conn.execute("SELECT id FROM incidents WHERE cad_number = 'SYN-P'").fetchone()["id"]
    from wpd_compstat.security.crypto import encrypt_field

    session.conn.execute(
        "INSERT INTO sensitive_persons(incident_id, role, payload_enc, created_at) VALUES (?, 'operator', ?, ?)",
        (incident_id, encrypt_field(session.dek, "person", '{"name": "ALEX EXAMPLE"}'), session.stamp()),
    )
    session.conn.execute(
        "INSERT INTO narratives(incident_id, sequence, body, body_sha256, author) VALUES (?, 1, ?, 'abc', 'DOE')",
        (incident_id, "Spoke with ALEX EXAMPLE about a warning."),
    )
    session.create_user("reader", "Readerpass123", "read_only")
    session.lock()
    session.unlock("reader", "Readerpass123")
    detail = incident_detail(session, incident_id)
    assert detail["persons"] == []
    assert detail["narratives"] == []
    assert "ALEX EXAMPLE" not in str(detail)
