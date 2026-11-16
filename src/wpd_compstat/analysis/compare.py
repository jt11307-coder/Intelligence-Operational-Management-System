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


def complete_through(conn) -> dict:
    """The last imported day is treated as partial when its latest known call time is before 23:00."""
    row = conn.execute(
        """
        SELECT event_date AS day, MAX(event_time) AS last_time, COUNT(*) AS n FROM incidents
        WHERE excluded = 0 AND event_date = (SELECT MAX(event_date) FROM incidents WHERE excluded = 0)
        GROUP BY event_date
        """
    ).fetchone()
    if row is None or row["day"] is None:
        return {"last_day": None, "complete_day": None, "last_time": None, "partial_calls": 0}
    last_day = date.fromisoformat(row["day"])
    last_time = row["last_time"]
    if not last_time or last_time >= "23:00":
        return {"last_day": last_day, "complete_day": last_day, "last_time": last_time, "partial_calls": 0}
    return {
        "last_day": last_day,
        "complete_day": last_day - timedelta(days=1),
        "last_time": last_time,
        "partial_calls": int(row["n"]),
    }


def effective_period(conn, start: date, end: date) -> dict:
    """Trim the chosen period to complete imported days so it is not compared against full periods."""
    status = complete_through(conn)
    complete = status["complete_day"]
    trimmed_end = min(end, complete) if complete else end
    note = None
    if complete and end > complete:
        if status["partial_calls"] and status["last_day"] <= end:
            note = (
                f"{status['last_day'].isoformat()} is only partly imported (calls up to {status['last_time'] or 'an unknown time'}), "
                f"so its {status['partial_calls']} call(s) are left out."
            )
        else:
            note = f"Calls are imported only through {complete.isoformat()}."
        note += f" The figures cover {start.isoformat()} through {trimmed_end.isoformat()}."
    days = (trimmed_end - start).days + 1
    return {"start": start, "end": trimmed_end, "days": max(days, 0), "note": note, "requested_end": end}


def _span(first: date, last: date) -> str:
    return f"{first.isoformat()} to {last.isoformat()}"


def comparison_windows(start: date, end: date) -> list[dict]:
    """Every comparison period has the same number of days as the current period."""
    length = (end - start).days + 1
    previous_end = start - timedelta(days=1)
    previous_start = previous_end - timedelta(days=length - 1)
    windows = [
        {
            "key": "previous_equal",
            "label": "Previous period of equal length",
            "description": f"The {length} days just before this period ({_span(previous_start, previous_end)}).",
            "start": previous_start,
            "end": previous_end,
            "periods": 1,
        }
    ]
    if length <= 28:
        shifted_start, shifted_end = start - timedelta(days=28), end - timedelta(days=28)
        windows.append({
            "key": "four_weeks_earlier",
            "label": "Same days four weeks earlier",
            "description": f"The same {length} days moved back 28 days, so the weekdays line up ({_span(shifted_start, shifted_end)}).",
            "start": shifted_start,
            "end": shifted_end,
            "periods": 1,
        })
    average_start = start - timedelta(days=length * 4)
    windows.append({
        "key": "average_previous_4",
        "label": "Average of the 4 previous equal periods",
        "description": f"The average of the four {length}-day periods before this one ({_span(average_start, previous_end)}).",
        "start": average_start,
        "end": previous_end,
        "periods": 4,
    })
    prior_start = add_years(start, -1)
    prior_end = add_years(end, -1)
    if prior_start and prior_end:
        windows.append({
            "key": "prior_year_period",
            "label": "Equivalent prior-year period",
            "description": f"The same dates one year earlier ({_span(prior_start, prior_end)}).",
            "start": prior_start,
            "end": prior_end,
            "periods": 1,
        })
    return windows


def compare_calls(conn, start: date, end: date) -> list[dict]:
    minimum = int(get_setting(conn, "percent_change_min_baseline", 5))
    lo, hi = coverage_bounds(conn)
    period = effective_period(conn, start, end)
    start, end = period["start"], period["end"]
    current = calls_for_service(conn, start.isoformat(), end.isoformat())
    rows = []
    if period["days"] <= 0:
        return rows
    for window in comparison_windows(start, end):
        start_text = window["start"].isoformat()
        end_text = window["end"].isoformat()
        relation = window_relation(lo, hi, start_text, end_text)
        if relation == "outside":
            change = percent_change(current.value, None, minimum)
            change["reason"] = "No calls were imported for that period."
        elif relation == "partial":
            change = percent_change(current.value, None, minimum)
            change["reason"] = "Only part of that period was imported, so it is not compared."
        else:
            baseline = calls_for_service(conn, start_text, end_text).value
            if window["periods"] > 1:
                baseline = round(baseline / window["periods"], 1)
            change = percent_change(current.value, baseline, minimum)
            if change["absolute_change"] is not None:
                change["absolute_change"] = round(change["absolute_change"], 1)
        rows.append(
            {
                "label": window["label"],
                "description": window["description"],
                "start": start_text,
                "end": end_text,
                "days": period["days"],
                "current": current.value,
                **change,
            }
        )
    return rows
