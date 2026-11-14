"""Official counts. Category totals count incidents, not classification rows or narratives."""

from __future__ import annotations

from dataclasses import dataclass

from wpd_compstat.constants import ACCIDENT_CATEGORIES, INJURY_ACCIDENT_CATEGORIES
from wpd_compstat.db.seed import get_setting


@dataclass
class MetricResult:
    metric_id: str
    label: str
    available: bool
    value: int | None
    incident_ids: list[int]
    qualification: str | None = None


def calls_for_service(conn, start: str | None, end: str | None) -> MetricResult:
    ids = _ids(conn, "1=1", (), start, end)
    return MetricResult("calls_for_service", "Total calls for service", True, len(ids), ids)


def source_metric(conn, start, end, metric_id: str, label: str, setting_key: str) -> MetricResult:
    if not get_setting(conn, "source_lists_confirmed", False):
        return MetricResult(
            metric_id,
            label,
            False,
            None,
            [],
            "Call-source lists have not been confirmed by an administrator.",
        )
    officer = {item.casefold() for item in get_setting(conn, "officer_initiated_sources", [])}
    citizen = {item.casefold() for item in get_setting(conn, "citizen_sources", [])}
    if officer & citizen:
        return MetricResult(
            metric_id,
            label,
            False,
            None,
            [],
            "The officer-initiated and citizen source lists overlap, so neither count is shown.",
        )
    wanted = officer if setting_key == "officer_initiated_sources" else citizen
    if not wanted:
        return MetricResult(metric_id, label, False, None, [], "The confirmed source list is empty.")
    placeholders = ",".join("?" for _ in wanted)
    ids = _ids(
        conn,
        f"LOWER(call_source) IN ({placeholders})",
        tuple(sorted(wanted)),
        start,
        end,
    )
    return MetricResult(metric_id, label, True, len(ids), ids)


def category_metric(conn, start, end, metric_id: str, label: str, categories: set[str] | str) -> MetricResult:
    if isinstance(categories, str):
        categories = {categories}
    placeholders = ",".join("?" for _ in categories)
    sql = f"""
        incidents.id IN (
            SELECT c.incident_id FROM classifications c
            WHERE c.counts_officially = 1
              AND c.status != 'rejected'
              AND c.polarity = 'occurred'
              AND c.category IN ({placeholders})
        )
    """
    ids = _ids(conn, sql, tuple(sorted(categories)), start, end)
    return MetricResult(metric_id, label, True, len(ids), ids)


def significant_incidents(conn, start, end) -> MetricResult:
    sql = """
        incidents.id IN (
            SELECT c.incident_id FROM classifications c
            WHERE c.counts_officially = 1
              AND c.status != 'rejected'
              AND c.polarity = 'occurred'
              AND c.significant = 1
        )
    """
    ids = _ids(conn, sql, (), start, end)
    return MetricResult("significant_incidents", "Significant incidents", True, len(ids), ids)


def follow_up_metric(conn, start, end) -> MetricResult:
    return category_metric(conn, start, end, "follow_up", "Calls requiring follow-up", "follow_up_required")


def accidents(conn, start, end) -> MetricResult:
    return category_metric(conn, start, end, "accidents", "Total accidents", set(ACCIDENT_CATEGORIES))


def injury_accidents(conn, start, end) -> MetricResult:
    return category_metric(
        conn, start, end, "injury_accidents", "Injury accidents", set(INJURY_ACCIDENT_CATEGORIES)
    )


def arrest_reports(conn, start, end) -> MetricResult:
    return category_metric(conn, start, end, "arrest_reports", "Arrest reports", "arrest_report")


def offense_reports(conn, start, end) -> MetricResult:
    return category_metric(conn, start, end, "offense_reports", "Offense reports", "offense_report")


def verified_violations(conn, start, end) -> MetricResult:
    return category_metric(
        conn, start, end, "verified_violations", "Verified violations", "verified_traffic_violation"
    )


def warnings(conn, start, end) -> MetricResult:
    return category_metric(conn, start, end, "warnings", "Warnings", "warning")


def traffic_stops(conn, start, end) -> MetricResult:
    return category_metric(conn, start, end, "traffic_stops", "Traffic stops", "traffic_stop")


def multiple_units(conn, start, end) -> MetricResult:
    return category_metric(conn, start, end, "multiple_units", "Calls involving multiple units", "multiple_units")


def priority_incidents(conn, start, end) -> MetricResult:
    ids = _ids(conn, "priority IS NOT NULL AND TRIM(priority) != ''", (), start, end)
    return MetricResult(
        "priority_incidents",
        "Incidents with a priority value",
        True,
        len(ids),
        ids,
        "Priority is shown only when the CAD record contained one. It is not inferred.",
    )


def dashboard_metrics(conn, start, end) -> list[MetricResult]:
    return [
        calls_for_service(conn, start, end),
        source_metric(conn, start, end, "officer_initiated", "Officer-initiated activity", "officer_initiated_sources"),
        source_metric(conn, start, end, "citizen_generated", "Citizen-generated calls", "citizen_sources"),
        accidents(conn, start, end),
        injury_accidents(conn, start, end),
        traffic_stops(conn, start, end),
        verified_violations(conn, start, end),
        warnings(conn, start, end),
        arrest_reports(conn, start, end),
        offense_reports(conn, start, end),
        significant_incidents(conn, start, end),
        follow_up_metric(conn, start, end),
        multiple_units(conn, start, end),
        priority_incidents(conn, start, end),
    ]


def metric_by_id(conn, metric_id: str, start, end) -> MetricResult:
    for metric in dashboard_metrics(conn, start, end):
        if metric.metric_id == metric_id:
            return metric
    found = category_metric(conn, start, end, metric_id, metric_id, metric_id)
    return found


def _ids(conn, extra_sql: str, params: tuple, start, end) -> list[int]:
    clauses = ["excluded = 0", f"({extra_sql})"]
    values = list(params)
    if start:
        clauses.append("event_date >= ?")
        values.append(start)
    if end:
        clauses.append("event_date <= ?")
        values.append(end)
    rows = conn.execute(
        f"SELECT id FROM incidents WHERE {' AND '.join(clauses)} ORDER BY event_date, cad_number, id",
        tuple(values),
    ).fetchall()
    return [int(row["id"]) for row in rows]
