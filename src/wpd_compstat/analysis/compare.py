"""Period comparisons. Small baselines do not produce a percentage."""

from __future__ import annotations

from datetime import date, timedelta

from wpd_compstat.analysis import calls_for_service
from wpd_compstat.db.seed import get_setting


def percent_change(current: int | None, baseline: int | None, min_baseline: int = 5) -> dict:
    if current is None or baseline is None:
        return {
            "comparable": False,
            "percent": None,
            "absolute_change": None,
            "current": current,
            "baseline": baseline,
            "reason": "One side of the comparison is not available.",
        }
    absolute = current - baseline
    if baseline <= 0 or baseline < min_baseline:
        return {
            "comparable": False,
            "percent": None,
            "absolute_change": absolute,
            "current": current,
            "baseline": baseline,
            "reason": "Baseline is too small for a percentage comparison.",
        }
    return {
        "comparable": True,
        "percent": round((current - baseline) / baseline * 100, 1),
        "absolute_change": absolute,
        "current": current,
        "baseline": baseline,
        "reason": None,
    }


def coverage_bounds(conn) -> tuple[str | None, str | None]:
    row = conn.execute(
        """
        SELECT MIN(event_date) AS lo, MAX(event_date) AS hi
        FROM incidents
        WHERE excluded = 0 AND event_date IS NOT NULL
        """
    ).fetchone()
    return row["lo"], row["hi"]


def window_relation(lo: str | None, hi: str | None, start: str, end: str) -> str:
    if not lo or not hi:
        return "outside"
    if end < lo or start > hi:
        return "outside"
    if start >= lo and end <= hi:
        return "full"
    return "partial"


def add_years(value: date, years: int) -> date | None:
    try:
        return value.replace(year=value.year + years)
    except ValueError:
        return None


def comparison_windows(start: date, end: date) -> list[dict]:
    length = (end - start).days + 1
    previous_end = start - timedelta(days=1)
    previous_start = previous_end - timedelta(days=length - 1)
    windows = [
        {"key": "previous_equal", "label": "Previous period of equal length", "start": previous_start, "end": previous_end},
        {"key": "previous_14", "label": "Previous 14 days", "start": end - timedelta(days=27), "end": end - timedelta(days=14)},
        {"key": "previous_28", "label": "Previous 28 days", "start": end - timedelta(days=55), "end": end - timedelta(days=28)},
    ]
    month_start = date(end.year, end.month, 1)
    prior_month_end = month_start - timedelta(days=1)
    prior_month_start = date(prior_month_end.year, prior_month_end.month, 1)
    windows.append({"key": "previous_month", "label": "Previous month", "start": prior_month_start, "end": prior_month_end})
    quarter = (end.month - 1) // 3
    quarter_start = date(end.year, quarter * 3 + 1, 1)
    prior_quarter_end = quarter_start - timedelta(days=1)
    prior_quarter = (prior_quarter_end.month - 1) // 3
    prior_quarter_start = date(prior_quarter_end.year, prior_quarter * 3 + 1, 1)
    windows.append(
        {"key": "previous_quarter", "label": "Previous quarter", "start": prior_quarter_start, "end": prior_quarter_end}
    )
    ytd_start = date(end.year, 1, 1)
    prior_ytd_start = add_years(ytd_start, -1)
    prior_ytd_end = add_years(end, -1)
    if prior_ytd_start and prior_ytd_end:
        windows.append({"key": "prior_ytd", "label": "Year to date, prior year", "start": prior_ytd_start, "end": prior_ytd_end})
    prior_start = add_years(start, -1)
    prior_end = add_years(end, -1)
    if prior_start and prior_end:
        windows.append(
            {"key": "prior_year_period", "label": "Equivalent prior-year period", "start": prior_start, "end": prior_end}
        )
    current_14 = {"key": "current_14", "label": "Latest 14 days", "start": end - timedelta(days=13), "end": end}
    windows.insert(1, current_14)
    return windows


def compare_calls(conn, start: date, end: date) -> list[dict]:
    minimum = int(get_setting(conn, "percent_change_min_baseline", 5))
    lo, hi = coverage_bounds(conn)
    current = calls_for_service(conn, start.isoformat(), end.isoformat())
    rows = []
    for window in comparison_windows(start, end):
        if window["key"] == "current_14":
            continue
        start_text = window["start"].isoformat()
        end_text = window["end"].isoformat()
        relation = window_relation(lo, hi, start_text, end_text)
        if relation == "outside":
            change = percent_change(current.value, None, minimum)
            change["reason"] = "Prior-period data is not in the imported coverage."
        else:
            baseline = calls_for_service(conn, start_text, end_text)
            change = percent_change(current.value, baseline.value, minimum)
            if relation == "partial" and change["reason"] is None:
                change["reason"] = "Imported coverage only partly overlaps this comparison period."
            elif relation == "partial":
                change["reason"] = (change["reason"] or "") + " Imported coverage only partly overlaps this comparison period."
        rows.append(
            {
                "label": window["label"],
                "start": start_text,
                "end": end_text,
                "current": current.value,
                **change,
            }
        )
    return rows
