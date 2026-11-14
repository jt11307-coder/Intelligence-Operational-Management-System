"""Dashboard and search counts must not probe classifications once per incident; a year of calls made that take over an hour."""

from __future__ import annotations

from wpd_compstat.analysis import dashboard_metrics
from wpd_compstat.search import search_incidents


def _correlated_plans(conn, run) -> list[str]:
    statements: list[str] = []
    conn.set_trace_callback(statements.append)
    try:
        run()
    finally:
        conn.set_trace_callback(None)
    found = []
    for sql in statements:
        if "classifications" not in sql or not sql.lstrip().upper().startswith("SELECT"):
            continue
        plan = " ".join(row[3] for row in conn.execute("EXPLAIN QUERY PLAN " + sql))
        if "CORRELATED" in plan:
            found.append(plan)
    return found


def test_dashboard_category_counts_are_not_correlated_per_incident(session):
    assert _correlated_plans(session.conn, lambda: dashboard_metrics(session.conn, "2026-01-01", "2026-12-31")) == []


def test_category_search_is_not_correlated_per_incident(session):
    assert _correlated_plans(session.conn, lambda: search_incidents(session, {"category": "arrest_report"})) == []
