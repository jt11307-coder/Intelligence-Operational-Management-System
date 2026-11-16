"""Dashboard figures in plain words. Categories that wait on rule confirmation are labelled, never shown as 0."""

from __future__ import annotations

import json
from datetime import date, timedelta

from wpd_compstat.analysis.compare import coverage_bounds, effective_period, window_relation
from wpd_compstat.analysis.patterns import _volume_met
from wpd_compstat.classification.call_reasons import CALL_REASONS, official_code
from wpd_compstat.classification.taxonomy import CATEGORY_LABELS
from wpd_compstat.constants import ACCIDENT_CATEGORIES, INJURY_ACCIDENT_CATEGORIES
from wpd_compstat.db.seed import get_setting

COUNTED = "counted"
AWAITING = "awaiting"
AWAITING_TEXT = "Awaiting your rule confirmation"

STRUCTURAL = {
    "arrest_report": ("Arrest reports", "Calls whose CAD record lists an arrest report number."),
    "offense_report": ("Offense reports", "Calls whose CAD record lists an offense report number."),
    "accident_report": ("Accident reports", "Calls whose CAD record lists an accident report number."),
    "citation_reference": ("Calls with a citation number", "A citation number was written on the call. This is not a verified violation."),
    "multiple_units": ("Calls with two or more units", "The CAD record lists two or more officers or units on the call."),
    "follow_up_required": ("Calls marked for follow-up", "The CAD record says Follow Up: yes."),
    "supplemental_report": ("Supplemental reports", "Calls whose CAD record lists a supplemental report number."),
    "verified_traffic_violation": ("Verified traffic violations", "Violations marked verified in an imported traffic export."),
    "warning": ("Traffic warnings", "Warnings recorded in an imported traffic export."),
}

GROUPS = (
    ("accidents", "Accidents (all types)", set(ACCIDENT_CATEGORIES),
     "Calls proposed as any kind of motor-vehicle accident: property damage, injury, hit and run, and similar."),
    ("injury_accidents", "Injury or fatal accidents", set(INJURY_ACCIDENT_CATEGORIES),
     "Calls proposed as a motor-vehicle accident with an injury or a death."),
    ("traffic_stops", "Traffic stops", {"traffic_stop"}, "Calls proposed as a traffic stop."),
)


def _category_label(category: str) -> str:
    if category in STRUCTURAL:
        return STRUCTURAL[category][0]
    return CATEGORY_LABELS.get(category, category.replace("_", " ").capitalize())


def confirmed_categories(conn) -> set[str]:
    """Categories counted from a confirmed source: report fields, a confirmed rule, or a confirmed agency code."""
    found = set(STRUCTURAL)
    for row in conn.execute(
        "SELECT category FROM classification_rules WHERE enabled = 1 AND confirmation != 'starter_unconfirmed'"
    ):
        found.add(row["category"])
    for row in conn.execute("SELECT match_json FROM agency_codes WHERE status = 'confirmed'"):
        try:
            category = json.loads(row["match_json"] or "{}").get("category")
        except (TypeError, ValueError):
            category = None
        if category:
            found.add(category)
    return found


def _count(conn, start: str, end: str, categories: set[str], official: bool) -> int:
    placeholders = ",".join("?" for _ in categories)
    official_sql = "AND c.counts_officially = 1" if official else ""
    # CROSS JOIN keeps incidents (and its date index) as the outer loop; otherwise SQLite walks every row of a large category.
    row = conn.execute(
        f"""
        SELECT COUNT(DISTINCT c.incident_id) AS n
        FROM incidents i CROSS JOIN classifications c ON c.incident_id = i.id
        WHERE i.excluded = 0 AND i.event_date >= ? AND i.event_date <= ?
          AND c.status != 'rejected' AND c.polarity = 'occurred' {official_sql}
          AND c.category IN ({placeholders})
        """,
        (start, end, *sorted(categories)),
    ).fetchone()
    return int(row["n"])


def _calls(conn, start: str, end: str) -> int:
    return int(conn.execute(
        "SELECT COUNT(*) AS n FROM incidents WHERE excluded = 0 AND event_date >= ? AND event_date <= ?",
        (start, end),
    ).fetchone()["n"])


class _Daily:
    """Per-day counts for one date span, loaded once, so each window is a sum instead of a query."""

    def __init__(self, conn, first: date, last: date):
        self.calls: dict[str, int] = {}
        self.categories: dict[str, dict[str, list[int]]] = {}
        span = (first.isoformat(), last.isoformat())
        for row in conn.execute(
            "SELECT event_date AS day, COUNT(*) AS n FROM incidents WHERE excluded = 0 AND event_date >= ? AND event_date <= ? GROUP BY event_date",
            span,
        ):
            self.calls[row["day"]] = int(row["n"])
        for row in conn.execute(
            """
            SELECT c.category, i.event_date AS day, COUNT(DISTINCT c.incident_id) AS n,
                   COUNT(DISTINCT CASE WHEN c.counts_officially = 1 THEN c.incident_id END) AS official
            FROM incidents i CROSS JOIN classifications c ON c.incident_id = i.id
            WHERE i.excluded = 0 AND i.event_date >= ? AND i.event_date <= ?
              AND c.status != 'rejected' AND c.polarity = 'occurred'
            GROUP BY c.category, i.event_date
            """,
            span,
        ):
            self.categories.setdefault(row["category"], {})[row["day"]] = [int(row["n"]), int(row["official"])]

    def call_count(self, first: date, last: date) -> int:
        a, b = first.isoformat(), last.isoformat()
        return sum(n for day, n in self.calls.items() if a <= day <= b)

    def category_count(self, category: str, first: date, last: date, official: bool) -> int:
        a, b = first.isoformat(), last.isoformat()
        index = 1 if official else 0
        return sum(pair[index] for day, pair in self.categories.get(category, {}).items() if a <= day <= b)

    def totals(self, first: date, last: date) -> dict[str, int]:
        a, b = first.isoformat(), last.isoformat()
        return {
            category: sum(pair[0] for day, pair in days.items() if a <= day <= b)
            for category, days in self.categories.items()
        }


def _ever(conn, category: str) -> bool:
    return conn.execute("SELECT 1 FROM classifications WHERE category = ? LIMIT 1", (category,)).fetchone() is not None


def figure(conn, start: str, end: str, categories: set[str], confirmed: set[str]) -> dict:
    """Counted figure when every category is confirmed; otherwise the proposed count, marked as awaiting."""
    if categories <= confirmed:
        return {"status": COUNTED, "value": _count(conn, start, end, categories, official=True)}
    return {
        "status": AWAITING,
        "value": _count(conn, start, end, categories, official=False),
        "counted": _count(conn, start, end, categories, official=True),
    }


def previous_window(start: date, end: date) -> tuple[str, str]:
    length = (end - start).days + 1
    previous_end = start - timedelta(days=1)
    return (previous_end - timedelta(days=length - 1)).isoformat(), previous_end.isoformat()


def tiles(conn, start: date, end: date) -> dict:
    period = effective_period(conn, start, end)
    if period["days"] <= 0:
        return {"period": period, "tiles": []}
    first, last = period["start"].isoformat(), period["end"].isoformat()
    previous = previous_window(period["start"], period["end"])
    lo, hi = coverage_bounds(conn)
    has_previous = window_relation(lo, hi, *previous) == "full"
    confirmed = confirmed_categories(conn)
    days = period["days"]
    previous_start, previous_end = date.fromisoformat(previous[0]), date.fromisoformat(previous[1])
    daily = _Daily(conn, previous_start, period["end"])

    def single(category: str) -> tuple[int, int | None]:
        value = daily.category_count(category, period["start"], period["end"], True)
        before = daily.category_count(category, previous_start, previous_end, True) if has_previous else None
        return value, before

    found = [{
        "key": "calls_for_service",
        "label": "Calls for service",
        "description": f"Every CAD call dated in these {days} complete days.",
        "status": COUNTED,
        "value": daily.call_count(period["start"], period["end"]),
        "previous": daily.call_count(previous_start, previous_end) if has_previous else None,
    }]
    for category in ("arrest_report", "offense_report", "accident_report", "multiple_units", "citation_reference",
                     "follow_up_required", "verified_traffic_violation", "warning"):
        if not _ever(conn, category):
            continue
        label, description = STRUCTURAL[category]
        value, before = single(category)
        found.append({
            "key": category, "label": label, "description": description, "status": COUNTED,
            "value": value, "previous": before,
        })
    code_rows = conn.execute("SELECT code, label, match_json FROM agency_codes WHERE status = 'confirmed' ORDER BY code").fetchall()
    for row in code_rows:
        category = json.loads(row["match_json"] or "{}").get("category")
        if not category:
            continue
        value, before = single(category)
        found.append({
            "key": f"code_{row['code']}",
            "label": f"{_category_label(category)} (code {row['code']})",
            "description": f"Calls counted for {_category_label(category).lower()} through your confirmed code {row['code']} or an accepted review.",
            "status": COUNTED,
            "value": value,
            "previous": before,
        })
    for key, label, categories, description in GROUPS:
        item = figure(conn, first, last, categories, confirmed)
        before = figure(conn, *previous, categories, confirmed) if has_previous else None
        found.append({
            "key": key, "label": label, "description": description, **item,
            "previous": before["value"] if before else None,
        })
    return {"period": period, "tiles": found}


def compstat_table(conn, end: date, limit: int = 25) -> dict:
    """Weekly COMPSTAT view ending on the last complete day: this week, last week, 4-week average, change, year to date."""
    period = effective_period(conn, end - timedelta(days=6), end)
    week_end = period["end"]
    week_start = week_end - timedelta(days=6)
    last_start, last_end = week_start - timedelta(days=7), week_start - timedelta(days=1)
    avg_start = week_start - timedelta(days=28)
    ytd_start = date(week_end.year, 1, 1)
    support = int(get_setting(conn, "pattern_min_support", 3))
    lo, hi = coverage_bounds(conn)
    has_average = window_relation(lo, hi, avg_start.isoformat(), last_end.isoformat()) == "full"
    confirmed = confirmed_categories(conn)
    daily = _Daily(conn, min(avg_start, ytd_start), week_end)
    rows = []

    def build(label: str, counter, status: str) -> dict:
        this_week = counter(week_start, week_end)
        last_week = counter(last_start, last_end)
        average = round(counter(avg_start, last_end) / 4, 1) if has_average else None
        flag = ""
        if average is not None:
            if _volume_met(this_week, round(average), support):
                flag = "UP"
            elif _volume_met(round(average), this_week, support):
                flag = "DOWN"
        return {
            "label": label,
            "status": status,
            "this_week": this_week,
            "last_week": last_week,
            "four_week_average": average,
            "change": this_week - last_week,
            "ytd": counter(ytd_start, week_end),
            "flag": flag,
        }

    rows.append(build("Calls for service", daily.call_count, COUNTED))
    totals = daily.totals(ytd_start, week_end)
    categories = sorted((category for category, n in totals.items() if n), key=lambda category: (-totals[category], category))
    for category in categories[:limit]:
        counted = category in confirmed
        rows.append(build(
            _category_label(category),
            lambda a, b, item=category, official=counted: daily.category_count(item, a, b, official),
            COUNTED if counted else AWAITING,
        ))
    return {
        "week": (week_start, week_end),
        "last_week": (last_start, last_end),
        "average_weeks": (avg_start, last_end),
        "ytd_start": ytd_start,
        "rows": rows,
        "support": support,
    }


def _official_names() -> dict[str, str]:
    return {code: description for code, description in CALL_REASONS}


def top_call_types(conn, start: date, end: date, limit: int = 15) -> list[dict]:
    period = effective_period(conn, start, end)
    if period["days"] <= 0:
        return []
    previous = previous_window(period["start"], period["end"])
    lo, hi = coverage_bounds(conn)
    has_previous = window_relation(lo, hi, *previous) == "full"
    names = _official_names()

    def grouped(first: str, last: str) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for row in conn.execute(
            """
            SELECT call_type, COUNT(*) AS n FROM incidents
            WHERE excluded = 0 AND event_date >= ? AND event_date <= ?
              AND call_type IS NOT NULL AND TRIM(call_type) != ''
            GROUP BY call_type
            """,
            (first, last),
        ):
            code = official_code(row["call_type"])
            key = code or " ".join(row["call_type"].split()).casefold()
            bucket = out.setdefault(key, {
                "code": code,
                "name": names.get(code) if code else " ".join(row["call_type"].split()),
                "count": 0,
            })
            bucket["count"] += int(row["n"])
        return out

    current = grouped(period["start"].isoformat(), period["end"].isoformat())
    before = grouped(*previous) if has_previous else {}
    rows = []
    for key, item in sorted(current.items(), key=lambda kv: (-kv[1]["count"], kv[1]["name"]))[:limit]:
        previous_count = before.get(key, {}).get("count", 0) if has_previous else None
        rows.append({
            **item,
            "on_imc_list": item["code"] is not None,
            "previous": previous_count,
            "change": None if previous_count is None else item["count"] - previous_count,
        })
    return rows
