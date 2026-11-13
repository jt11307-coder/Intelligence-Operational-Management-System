"""Division workload. Raw totals are not performance findings."""

from __future__ import annotations

PERFORMANCE_NOTE = (
    "Raw activity totals are not indicators of individual or divisional performance, "
    "and they are not a basis for inferring misconduct or discipline."
)


def division_report(conn, division_id: int, start: str, end: str) -> dict:
    division = conn.execute("SELECT * FROM divisions WHERE id = ?", (division_id,)).fetchone()
    if division is None:
        return {"available": False, "qualification": "That organizational unit does not exist."}
    incident_rows = conn.execute(
        """
        SELECT DISTINCT i.id
        FROM incidents i
        JOIN incident_officers io ON io.incident_id = i.id
        JOIN officers o ON o.id = io.officer_id
        WHERE i.excluded = 0 AND i.event_date >= ? AND i.event_date <= ? AND o.division_id = ?
        """,
        (start, end, division_id),
    ).fetchall()
    officer_rows = conn.execute(
        """
        SELECT o.display_name AS officer, COUNT(io.id) AS assignment_rows, COUNT(DISTINCT i.id) AS incidents
        FROM incidents i
        JOIN incident_officers io ON io.incident_id = i.id
        JOIN officers o ON o.id = io.officer_id
        WHERE i.excluded = 0 AND i.event_date >= ? AND i.event_date <= ? AND o.division_id = ?
        GROUP BY o.id
        ORDER BY o.display_name
        """,
        (start, end, division_id),
    ).fetchall()
    staffing = conn.execute(
        """
        SELECT SUM(headcount) AS headcount, COUNT(*) AS rows
        FROM staffing
        WHERE division_id = ? AND on_date >= ? AND on_date <= ?
        """,
        (division_id, start, end),
    ).fetchone()
    assignments = conn.execute(
        """
        SELECT a.action_number, a.title, a.status, ad.participation
        FROM assignment_divisions ad
        JOIN assignments a ON a.id = ad.assignment_id
        WHERE ad.division_id = ?
        ORDER BY a.action_number
        """,
        (division_id,),
    ).fetchall()
    return {
        "available": True,
        "division": division["name"],
        "confirmed": bool(division["confirmed"]),
        "qualification": PERFORMANCE_NOTE
        if division["confirmed"]
        else PERFORMANCE_NOTE + " This unit name has not been confirmed by an administrator.",
        "incident_count": len(incident_rows),
        "incident_ids": [row["id"] for row in incident_rows],
        "officer_contributions": [dict(row) for row in officer_rows],
        "staffing_rows": staffing["rows"],
        "staffing_headcount_sum": staffing["headcount"],
        "rate_note": "Per-officer rates are not shown unless staffing rows exist for this period."
        if not staffing["rows"]
        else "Staffing rows exist. A rate is not calculated automatically from headcount.",
        "assignments": [dict(row) for row in assignments],
    }
