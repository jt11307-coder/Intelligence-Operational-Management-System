"""Operational assignments and the 14-day cycle."""

from __future__ import annotations

from datetime import date, timedelta

from wpd_compstat.constants import UNRESOLVED_ASSIGNMENT_STATUSES
from wpd_compstat.db.connection import transaction
from wpd_compstat.db.seed import get_setting, set_setting
from wpd_compstat.errors import ValidationError

TRANSITIONS = {
    "proposed": {"approved"},
    "approved": {"assigned"},
    "assigned": {"in_progress", "awaiting_resources"},
    "in_progress": {"awaiting_resources", "completed"},
    "awaiting_resources": {"in_progress"},
    "completed": {"effective", "partially_effective", "ineffective", "closed", "reopened"},
    "effective": {"closed", "reopened"},
    "partially_effective": {"closed", "reopened"},
    "ineffective": {"closed", "reopened"},
    "closed": {"reopened"},
    "reopened": {"in_progress"},
}
ASSESSMENTS = {"effective", "partially_effective", "ineffective"}


def create_assignment(session, title: str, description: str, **fields) -> int:
    session.require("assignments_propose")
    if not title.strip() or not description.strip():
        raise ValidationError("An assignment needs a title and a description.")
    number = _next_number(session)
    with transaction(session.conn):
        cursor = session.conn.execute(
            """
            INSERT INTO assignments(
                action_number, title, description, geographic_area, baseline_period,
                baseline_measurements, commander_officer_id, commander_user_id, objective,
                intervention, start_date, due_date, resources, planned_activity, success_metrics,
                status, cycle_id, urgent, recommendation_id, created_at, created_by, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'proposed', ?, ?, ?, ?, ?, ?)
            """,
            (
                number,
                title.strip(),
                description.strip(),
                fields.get("geographic_area"),
                fields.get("baseline_period"),
                fields.get("baseline_measurements"),
                fields.get("commander_officer_id"),
                fields.get("commander_user_id"),
                fields.get("objective"),
                fields.get("intervention"),
                fields.get("start_date"),
                fields.get("due_date"),
                fields.get("resources"),
                fields.get("planned_activity"),
                fields.get("success_metrics"),
                fields.get("cycle_id"),
                1 if fields.get("urgent") else 0,
                fields.get("recommendation_id"),
                session.stamp(),
                session.user["id"],
                session.stamp(),
            ),
        )
        assignment_id = int(cursor.lastrowid)
        for incident_id in fields.get("incident_ids") or []:
            session.conn.execute(
                "INSERT OR IGNORE INTO assignment_incidents(assignment_id, incident_id) VALUES (?, ?)",
                (assignment_id, incident_id),
            )
        for division_id in fields.get("supporting_division_ids") or []:
            session.conn.execute(
                """
                INSERT OR IGNORE INTO assignment_divisions(assignment_id, division_id, participation)
                VALUES (?, ?, 'supporting')
                """,
                (assignment_id, division_id),
            )
        session.audit("create_assignment", entity_type="assignment", entity_id=assignment_id)
    return assignment_id


def transition(session, assignment_id: int, new_status: str, note: str | None = None) -> None:
    row = _assignment(session, assignment_id)
    if new_status not in TRANSITIONS.get(row["status"], set()):
        raise ValidationError(f"Cannot move an assignment from {row['status']} to {new_status}.")
    if new_status in ASSESSMENTS:
        session.require("assignments_assess")
    elif new_status in {"approved", "assigned"}:
        session.require("assignments_approve")
    else:
        session.require("assignments_update")
    if new_status in {"approved", "assigned"} and not row["commander_officer_id"] and not row["commander_user_id"]:
        raise ValidationError("Name one accountable commander before approval or assignment.")
    with transaction(session.conn):
        session.conn.execute(
            "UPDATE assignments SET status = ?, updated_at = ? WHERE id = ?",
            (new_status, session.stamp(), assignment_id),
        )
        if note:
            add_note(session, assignment_id, "progress" if new_status not in ASSESSMENTS else "assessment", note)
        session.audit("assignment_status", entity_type="assignment", entity_id=assignment_id, detail=new_status)


def set_commander(session, assignment_id: int, *, officer_id: int | None = None, user_id: int | None = None) -> None:
    session.require("assignments_approve")
    if not officer_id and not user_id:
        raise ValidationError("One accountable commander is required.")
    _assignment(session, assignment_id)
    session.conn.execute(
        """
        UPDATE assignments
        SET commander_officer_id = ?, commander_user_id = ?, updated_at = ?
        WHERE id = ?
        """,
        (officer_id, user_id, session.stamp(), assignment_id),
    )
    session.audit("set_commander", entity_type="assignment", entity_id=assignment_id)


def add_note(session, assignment_id: int, note_type: str, body: str) -> None:
    session.require("assignments_update")
    if note_type not in {"progress", "obstacle", "outcome", "assessment"}:
        raise ValidationError("Unknown note type.")
    if not body.strip():
        raise ValidationError("The note is empty.")
    session.conn.execute(
        """
        INSERT INTO assignment_notes(assignment_id, note_type, body, created_at, created_by)
        VALUES (?, ?, ?, ?, ?)
        """,
        (assignment_id, note_type, body.strip(), session.stamp(), session.user["id"]),
    )


def record_measurement(session, assignment_id: int, metric_name: str, baseline: str, current: str) -> None:
    session.require("assignments_update")
    session.conn.execute(
        """
        INSERT INTO outcome_measurements(
            assignment_id, metric_name, baseline_value, current_value, measured_at
        ) VALUES (?, ?, ?, ?, ?)
        """,
        (assignment_id, metric_name, baseline, current, session.stamp()),
    )


def overdue_assignments(conn, on_date: str) -> list[dict]:
    placeholders = ",".join("?" for _ in UNRESOLVED_ASSIGNMENT_STATUSES)
    rows = conn.execute(
        f"""
        SELECT * FROM assignments
        WHERE due_date IS NOT NULL AND due_date < ?
          AND status IN ({placeholders})
        ORDER BY due_date, action_number
        """,
        (on_date, *sorted(UNRESOLVED_ASSIGNMENT_STATUSES)),
    ).fetchall()
    return [dict(row) for row in rows]


def create_cycle(session, start_on: date) -> int:
    session.require("assignments_approve")
    end_on = start_on + timedelta(days=13)
    with transaction(session.conn):
        cursor = session.conn.execute(
            """
            INSERT INTO compstat_cycles(start_date, end_date, status, created_at)
            VALUES (?, ?, 'open', ?)
            """,
            (start_on.isoformat(), end_on.isoformat(), session.stamp()),
        )
        cycle_id = int(cursor.lastrowid)
        unresolved = session.conn.execute(
            f"""
            SELECT id, cycle_id FROM assignments
            WHERE status IN ({",".join("?" for _ in UNRESOLVED_ASSIGNMENT_STATUSES)})
            """,
            tuple(sorted(UNRESOLVED_ASSIGNMENT_STATUSES)),
        ).fetchall()
        for row in unresolved:
            session.conn.execute(
                "UPDATE assignments SET cycle_id = ?, updated_at = ? WHERE id = ?",
                (cycle_id, session.stamp(), row["id"]),
            )
            session.conn.execute(
                """
                INSERT INTO assignment_notes(assignment_id, note_type, body, created_at, created_by)
                VALUES (?, 'progress', ?, ?, ?)
                """,
                (
                    row["id"],
                    f"Carried forward from cycle {row['cycle_id']} into cycle {cycle_id}.",
                    session.stamp(),
                    session.user["id"],
                ),
            )
        session.audit("create_cycle", entity_type="cycle", entity_id=cycle_id)
    return cycle_id


def phase_for(start_on: date, end_on: date, on_date: date) -> str:
    if on_date < start_on or on_date > end_on:
        return "outside_cycle"
    day = (on_date - start_on).days + 1
    if day <= 2:
        return "intelligence_and_assignment"
    if day <= 10:
        return "operational_implementation"
    if day <= 12:
        return "performance_assessment"
    return "command_review"


def cycle_phase(conn, cycle_id: int, on_date: date) -> str:
    row = conn.execute("SELECT * FROM compstat_cycles WHERE id = ?", (cycle_id,)).fetchone()
    return phase_for(date.fromisoformat(row["start_date"]), date.fromisoformat(row["end_date"]), on_date)


def _assignment(session, assignment_id: int):
    row = session.conn.execute("SELECT * FROM assignments WHERE id = ?", (assignment_id,)).fetchone()
    if row is None:
        raise ValidationError("That assignment does not exist.")
    return row


def _next_number(session) -> str:
    seq = int(get_setting(session.conn, "next_action_seq", 1))
    set_setting(session.conn, "next_action_seq", seq + 1, session.stamp(), session.user["id"])
    year = session.now().year
    return f"AI-{year}-{seq:04d}"
