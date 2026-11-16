"""Developing patterns for the dashboard: repeat addresses, volume flags, and day-over-day emerging trends.
Read-only: nothing is stored, and each item is one sentence with a count, without addresses or call details."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, timedelta

from wpd_compstat.analysis.compare import coverage_bounds, effective_period, window_relation
from wpd_compstat.analysis.dashboard import AWAITING_TEXT, _category_label, confirmed_categories, previous_window
from wpd_compstat.analysis.patterns import _call_type_key, _call_type_label, _clusters, _volume_met
from wpd_compstat.constants import REPEAT_LOCATION_WINDOW_DAYS
from wpd_compstat.db.seed import get_setting

TREND_DAYS = 3
HISTORY_DAYS = 28


def _daily(conn, first: date, last: date) -> dict[str, dict]:
    """Per call type and per category: label, kind, and counts by day."""
    series: dict[str, dict] = {}
    for row in conn.execute(
        """
        SELECT call_type, event_date, COUNT(*) AS n FROM incidents
        WHERE excluded = 0 AND event_date >= ? AND event_date <= ?
          AND call_type IS NOT NULL AND TRIM(call_type) != ''
        GROUP BY call_type, event_date
        """,
        (first.isoformat(), last.isoformat()),
    ):
        key = "call|" + _call_type_key(row["call_type"])
        bucket = series.setdefault(key, {"label": _call_type_label(row["call_type"]), "kind": "call type", "days": Counter()})
        bucket["days"][row["event_date"]] += int(row["n"])
    confirmed = confirmed_categories(conn)
    for row in conn.execute(
        """
        SELECT c.category, i.event_date, COUNT(DISTINCT c.incident_id) AS n
        FROM incidents i CROSS JOIN classifications c ON c.incident_id = i.id
        WHERE i.excluded = 0 AND i.event_date >= ? AND i.event_date <= ?
          AND c.status != 'rejected' AND c.polarity = 'occurred'
        GROUP BY c.category, i.event_date
        """,
        (first.isoformat(), last.isoformat()),
    ):
        category = row["category"]
        awaiting = category not in confirmed
        key = "category|" + category
        bucket = series.setdefault(key, {
            "label": _category_label(category),
            "kind": "category" + (f", {AWAITING_TEXT.lower()}" if awaiting else ""),
            "days": Counter(),
        })
        bucket["days"][row["event_date"]] += int(row["n"])
    return series


def day_over_day_trends(conn, end: date, support: int | None = None) -> list[dict]:
    """A call type or category is emerging when it rose on each of the last three complete days and the
    three-day total at least doubled what the prior four weeks predict, by at least the minimum support."""
    support = int(get_setting(conn, "pattern_min_support", 3)) if support is None else support
    last = effective_period(conn, end - timedelta(days=TREND_DAYS - 1), end)["end"]
    first_trend = last - timedelta(days=TREND_DAYS - 1)
    history_start = first_trend - timedelta(days=HISTORY_DAYS)
    lo, hi = coverage_bounds(conn)
    if window_relation(lo, hi, history_start.isoformat(), last.isoformat()) != "full":
        return []
    trend_days = [(first_trend + timedelta(days=offset)).isoformat() for offset in range(TREND_DAYS)]
    found = []
    for key, item in _daily(conn, history_start, last).items():
        counts = [item["days"].get(day, 0) for day in trend_days]
        if not all(later > earlier for earlier, later in zip(counts, counts[1:])):
            continue
        history = sum(n for day, n in item["days"].items() if day < trend_days[0])
        expected = history / HISTORY_DAYS * TREND_DAYS
        total = sum(counts)
        if _volume_met(total, round(expected), support):
            found.append({
                "key": key,
                "kind": "emerging",
                "count": total,
                "sentence": (
                    f"{item['label']} ({item['kind']}) rose three days in a row ({', '.join(str(n) for n in counts)} "
                    f"from {trend_days[0]} to {trend_days[-1]}): {total} in those 3 days, against about "
                    f"{expected:.0f} expected from the 4 weeks before."
                ),
            })
    return sorted(found, key=lambda item: -item["count"])


def volume_flags(conn, start: date, end: date, support: int | None = None) -> list[dict]:
    support = int(get_setting(conn, "pattern_min_support", 3)) if support is None else support
    period = effective_period(conn, start, end)
    if period["days"] <= 0:
        return []
    previous_start, previous_end = previous_window(period["start"], period["end"])
    lo, hi = coverage_bounds(conn)
    if window_relation(lo, hi, previous_start, previous_end) != "full":
        return []
    series = _daily(conn, date.fromisoformat(previous_start), period["end"])
    found = []
    for key, item in series.items():
        current = sum(n for day, n in item["days"].items() if day >= period["start"].isoformat())
        before = sum(n for day, n in item["days"].items() if day <= previous_end)
        if _volume_met(current, before, support):
            found.append({
                "key": key,
                "kind": "volume",
                "count": current,
                "sentence": (
                    f"{item['label']} ({item['kind']}) at least doubled: {current} in these {period['days']} days "
                    f"against {before} in the {period['days']} days before."
                ),
            })
    return sorted(found, key=lambda item: -item["count"])


def repeat_address_flags(conn, start: date, end: date) -> list[dict]:
    """Groups of same-type calls at one address within the repeat window, summarised per call type."""
    period = effective_period(conn, start, end)
    if period["days"] <= 0:
        return []
    minimum = int(get_setting(conn, "repeat_location_min", 3))
    window_days = int(get_setting(conn, "repeat_location_window_days", REPEAT_LOCATION_WINDOW_DAYS))
    window_days = window_days if window_days >= 1 else REPEAT_LOCATION_WINDOW_DAYS
    rows = conn.execute(
        """
        SELECT i.id, i.event_date, i.call_type, l.normalized_address AS address
        FROM incidents i JOIN locations l ON l.id = i.location_id
        WHERE i.excluded = 0 AND i.event_date >= ? AND i.event_date <= ?
          AND l.normalized_address IS NOT NULL AND TRIM(l.normalized_address) != ''
          AND i.call_type IS NOT NULL AND TRIM(i.call_type) != ''
        """,
        (period["start"].isoformat(), period["end"].isoformat()),
    ).fetchall()
    grouped: dict[tuple[str, str], list] = defaultdict(list)
    labels: dict[str, str] = {}
    for row in rows:
        key = _call_type_key(row["call_type"])
        labels.setdefault(key, _call_type_label(row["call_type"]))
        grouped[(row["address"], key)].append((date.fromisoformat(row["event_date"]), int(row["id"]), labels[key]))
    addresses: Counter = Counter()
    calls: Counter = Counter()
    for (_address, key), items in grouped.items():
        clusters = _clusters(items, window_days, minimum)
        if clusters:
            addresses[key] += 1
            calls[key] += sum(len(cluster) for cluster in clusters)
    return [
        {
            "key": "repeat|" + key,
            "kind": "repeat",
            "count": count,
            "sentence": (
                f"{labels[key]}: {count} address{'es' if count != 1 else ''} had {minimum} or more {labels[key]} calls "
                f"within {window_days} days ({calls[key]} calls in all). Run Crime Analysis to see them."
            ),
        }
        for key, count in sorted(addresses.items(), key=lambda kv: (-kv[1], labels[kv[0]]))
    ]


def developing_patterns(conn, start: date, end: date, limit: int = 6) -> dict:
    return {
        "emerging": day_over_day_trends(conn, end)[:limit],
        "volume": volume_flags(conn, start, end)[:limit],
        "repeat": repeat_address_flags(conn, start, end)[:limit],
    }
