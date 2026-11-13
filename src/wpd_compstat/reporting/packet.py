"""Command packets built only from stored records."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from wpd_compstat.analysis import dashboard_metrics, significant_incidents
from wpd_compstat.analysis.compare import compare_calls
from wpd_compstat.analysis.divisions import PERFORMANCE_NOTE
from wpd_compstat.assignments import overdue_assignments, phase_for
from wpd_compstat.db.seed import get_setting


@dataclass
class ReportTable:
    title: str
    headers: list[str]
    rows: list[list[str]]


@dataclass
class ReportSection:
    title: str
    prose: list[str] = field(default_factory=list)
    tables: list[ReportTable] = field(default_factory=list)


@dataclass
class ReportPacket:
    title: str
    generated_at: str
    period: str
    qualifications: list[str]
    sections: list[ReportSection]


def build_compstat_packet(session, start: date, end: date, commentary: dict | None = None) -> ReportPacket:
    session.require("reports")
    commentary = commentary or {}
    start_text, end_text = start.isoformat(), end.isoformat()
    metrics = dashboard_metrics(session.conn, start_text, end_text)
    significant = significant_incidents(session.conn, start_text, end_text)
    comparisons = compare_calls(session.conn, start, end)
    patterns = session.conn.execute(
        """
        SELECT name, explanation, status FROM patterns
        WHERE date_start = ? AND date_end = ? AND status != 'rejected'
        ORDER BY name
        """,
        (start_text, end_text),
    ).fetchall()
    assignments = session.conn.execute(
        "SELECT action_number, title, status, due_date FROM assignments ORDER BY action_number"
    ).fetchall()
    overdue = overdue_assignments(session.conn, end_text)
    traffic = session.conn.execute(
        """
        SELECT COALESCE(SUM(verified_violations), 0) AS verified,
               COALESCE(SUM(citation_references), 0) AS citations,
               COALESCE(SUM(warnings), 0) AS warnings,
               COALESCE(SUM(stops), 0) AS stops
        FROM traffic_activity
        WHERE occurred_at IS NOT NULL AND substr(occurred_at, 1, 10) >= ? AND substr(occurred_at, 1, 10) <= ?
        """,
        (start_text, end_text),
    ).fetchone()
    goal = int(get_setting(session.conn, "violation_weekly_goal", 200))
    incident_count = session.conn.execute(
        "SELECT COUNT(*) AS n FROM incidents WHERE excluded = 0"
    ).fetchone()["n"]
    qualifications = [
        "Figures include only imported records that the counting rules treat as official.",
        "An incident may appear in more than one category. Category counts are not additive.",
        "Percentages are omitted when the baseline is below the configured minimum.",
        PERFORMANCE_NOTE,
        "No conclusion is added where the record does not document it.",
    ]
    if incident_count == 0:
        qualifications.insert(0, "No call-log incidents have been imported.")
    sections = [
        _section(commentary, "1. Executive summary", _executive(metrics, incident_count)),
        _section(commentary, "2. Previous COMPSTAT action-item review", _assignments(assignments, overdue)),
        _section(commentary, "3. Department-wide activity", _metric_lines(metrics)),
        _section(commentary, "4. Significant incidents", _significant_lines(session, significant)),
        _section(commentary, "5. Crime trends", _comparison_lines(comparisons)),
        _section(commentary, "6. Emerging patterns", _pattern_lines(patterns)),
        _section(commentary, "7. Geographic hotspots", ["Hotspot counts require exact offline coordinates. Open Geographic Intelligence for the current points."]),
        _section(
            commentary,
            "8. Traffic enforcement",
            [
                f"Stops recorded in traffic imports: {traffic['stops']}.",
                f"Verified violations: {traffic['verified']}. Weekly benchmark: {goal}.",
                f"Citation references: {traffic['citations']}. These are not verified violations.",
                f"Warnings: {traffic['warnings']}.",
            ],
        ),
        _section(commentary, "9. Crash analysis", _crash_lines(metrics)),
        _section(commentary, "10. Division and shift activity", [PERFORMANCE_NOTE, "Division tables are available in Division Performance and count an incident once for the division."]),
        _section(commentary, "11. Investigative concerns", ["Investigative concerns are the officially counted significant incidents and accepted patterns. None are inferred beyond those records."]),
        _section(commentary, "12. Resource and staffing considerations", ["Per-officer rates are not shown unless staffing was entered."]),
        _section(commentary, "13. Proposed operational interventions", ["Recommendations stay in draft until an authorized commander approves them. Approval does not start an operation."]),
        _section(commentary, "14. Assignments, owners, and deadlines", _assignment_table(assignments)),
        _section(commentary, "15. Decisions required from command staff", ["Command staff decide which drafts to approve, which commanders are accountable, and how outcomes will be measured."]),
    ]
    packet = ReportPacket(
        title="COMPSTAT briefing",
        generated_at=session.stamp(),
        period=f"{start_text} through {end_text}",
        qualifications=qualifications,
        sections=sections,
    )
    session.conn.execute(
        """
        INSERT INTO report_runs(template_key, generated_at, generated_by, period_start, period_end, qualifications)
        VALUES ('compstat_packet', ?, ?, ?, ?, ?)
        """,
        (session.stamp(), session.user["id"], start_text, end_text, "\n".join(qualifications)),
    )
    session.audit("build_report", entity_type="report", entity_id="compstat_packet")
    return packet


def _section(commentary: dict, title: str, prose) -> ReportSection:
    if isinstance(prose, ReportSection):
        section = prose
        section.title = title
    else:
        section = ReportSection(title=title, prose=list(prose))
    edited = commentary.get(title)
    if edited:
        section.prose = [edited, "Commentary edited by a user."]
    return section


def _executive(metrics, incident_count: int) -> list[str]:
    if incident_count == 0:
        return ["No incidents are in the database for this installation."]
    calls = next(metric for metric in metrics if metric.metric_id == "calls_for_service")
    return [f"Calls for service in the selected period: {calls.value}."]


def _metric_lines(metrics) -> list[str]:
    lines = []
    for metric in metrics:
        if not metric.available:
            lines.append(f"{metric.label}: Not available. {metric.qualification or ''}".strip())
        else:
            lines.append(f"{metric.label}: {metric.value}.")
    return lines


def _significant_lines(session, metric) -> list[str]:
    if metric.value == 0:
        return ["No officially counted significant incidents in this period."]
    lines = [f"Officially counted significant incidents: {metric.value}."]
    include = bool(get_setting(session.conn, "include_narrative_excerpts_in_briefing", False))
    rows = session.conn.execute(
        f"""
        SELECT id, cad_number, event_date, event_time, call_type, disposition, source_page
        FROM incidents
        WHERE id IN ({",".join("?" for _ in metric.incident_ids)})
        ORDER BY event_date, cad_number
        """,
        tuple(metric.incident_ids),
    ).fetchall()
    for row in rows:
        when = row["event_time"] or "time not documented"
        disposition = row["disposition"] or "disposition not documented"
        lines.append(
            f"CAD {row['cad_number']} on {row['event_date']} at {when}. "
            f"Call type: {row['call_type'] or 'not documented'}. Disposition: {disposition}. "
            f"Source page: {row['source_page'] or 'not documented'}."
        )
        if include and session.user and "view_narratives" in _perms(session):
            narrative = session.conn.execute(
                "SELECT body FROM narratives WHERE incident_id = ? ORDER BY sequence LIMIT 1",
                (row["id"],),
            ).fetchone()
            if narrative:
                lines.append("Narrative excerpt: " + " ".join(narrative["body"].split())[:400])
            else:
                lines.append("Narrative excerpt: not documented.")
        else:
            lines.append("Narrative excerpt: withheld unless excerpts are enabled and the role may read narratives.")
    return lines


def _comparison_lines(rows: list[dict]) -> list[str]:
    if not rows:
        return ["No comparison could be calculated."]
    lines = []
    for row in rows:
        if row["baseline"] is None:
            lines.append(f"{row['label']}: not available. {row['reason']}")
        elif not row["comparable"]:
            lines.append(
                f"{row['label']}: current {row['current']}, baseline {row['baseline']}, absolute change {row['absolute_change']}. Percentage not shown. {row['reason']}"
            )
        else:
            lines.append(
                f"{row['label']}: current {row['current']}, baseline {row['baseline']}, absolute change {row['absolute_change']}, percent change {row['percent']}."
            )
    return lines


def _pattern_lines(patterns) -> list[str]:
    if not patterns:
        return ["No open pattern was stored for this exact period."]
    return [f"{row['name']} ({row['status']}): {row['explanation']}" for row in patterns]


def _crash_lines(metrics) -> list[str]:
    accidents = next(metric for metric in metrics if metric.metric_id == "accidents")
    injury = next(metric for metric in metrics if metric.metric_id == "injury_accidents")
    return [
        f"Official accident classifications: {accidents.value}.",
        f"Official injury or fatal accident classifications: {injury.value}.",
        "Unconfirmed starter matches are not included.",
    ]


def _assignments(assignments, overdue) -> list[str]:
    if not assignments:
        return ["No operational assignments are stored."]
    lines = [f"Stored assignments: {len(assignments)}. Overdue unresolved assignments: {len(overdue)}."]
    lines.extend(f"{row['action_number']}: {row['title']} ({row['status']})." for row in assignments)
    return lines


def _assignment_table(assignments) -> ReportSection:
    return ReportSection(
        title="",
        prose=["Each assignment has one status. Completion is not recorded as effective."],
        tables=[
            ReportTable(
                title="Assignments",
                headers=["Action", "Title", "Status", "Due"],
                rows=[
                    [row["action_number"], row["title"], row["status"], row["due_date"] or "not documented"]
                    for row in assignments
                ],
            )
        ],
    )


def _perms(session) -> set[str]:
    from wpd_compstat.security.permissions import ROLE_PERMISSIONS

    return set(ROLE_PERMISSIONS.get(session.user["role"], ()))
