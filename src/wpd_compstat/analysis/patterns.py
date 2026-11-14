"""Rule-based patterns. A volume change is not described as a common offender."""

from __future__ import annotations

import json
from datetime import date, timedelta

from wpd_compstat.analysis import category_metric
from wpd_compstat.analysis.compare import coverage_bounds, window_relation
from wpd_compstat.classification.taxonomy import CATEGORY_LABELS
from wpd_compstat.constants import REPEAT_LOCATION_WINDOW_DAYS
from wpd_compstat.db.connection import transaction
from wpd_compstat.db.seed import get_setting

LIMITATION = (
    "This is a volume or repeat-location rule. It does not establish a common offender, "
    "a criminal conspiracy, or a cause."
)
CALL_TYPE_LIMITATION = (
    "This counts imported calls that share the uploaded call-type text. "
    "It is not an official crime classification. " + LIMITATION
)


def detect_patterns(session, start: str, end: str) -> dict:
    session.require("analyze")
    notes = []
    official = session.conn.execute(
        """
        SELECT COUNT(*) AS n FROM classifications
        WHERE counts_officially = 1 AND status != 'rejected' AND polarity = 'occurred'
        """
    ).fetchone()["n"]
    if official == 0:
        notes.append(
            "No officially counted classifications are available. "
            "Category patterns were not created from unconfirmed suggestions. "
            "Uploaded call types are still compared."
        )
    support = int(get_setting(session.conn, "pattern_min_support", 3))
    window_days = _window_days(session)
    minimum = int(get_setting(session.conn, "repeat_location_min", 3))
    notes.append(
        f"Volume flags use every classifier category and every uploaded call type. "
        f"A flag requires the count to at least double and to rise by at least {support}."
    )
    notes.append(
        f"Repeat flags require at least {minimum} calls of the same call type at one address "
        f"within {window_days} calendar days."
    )
    created = []
    with transaction(session.conn):
        created.extend(_repeat_locations(session, start, end))
        created.extend(_category_increases(session, start, end))
        created.extend(_displacement(session, start, end, notes))
    if not session.conn.execute("SELECT COUNT(*) AS n FROM zone_neighbors").fetchone()["n"]:
        notes.append("Displacement was not evaluated because neighboring areas are not configured.")
    session.audit("detect_patterns", detail=f"created_or_updated={len(created)}")
    return {"patterns": created, "notes": notes}


def review_pattern(session, pattern_id: int, decision: str, note: str | None) -> None:
    session.require("analyze")
    if decision not in {"accept", "reject", "annotate", "monitor"}:
        from wpd_compstat.errors import ValidationError

        raise ValidationError("Unknown pattern decision.")
    status = {"accept": "accepted", "reject": "rejected", "annotate": "open", "monitor": "monitoring"}[decision]
    with transaction(session.conn):
        session.conn.execute("UPDATE patterns SET status = ? WHERE id = ?", (status, pattern_id))
        session.conn.execute(
            """
            INSERT INTO pattern_reviews(pattern_id, user_id, decision, note, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (pattern_id, session.user["id"], decision, note, session.stamp()),
        )
        session.audit("review_pattern", entity_type="pattern", entity_id=pattern_id, detail=decision)


def trend_categories(conn) -> list[str]:
    """Every category the classifier knows, plus any category already stored."""
    found = set(CATEGORY_LABELS)
    rows = conn.execute(
        """
        SELECT DISTINCT category FROM classifications
        WHERE category IS NOT NULL AND TRIM(category) != ''
        """
    ).fetchall()
    found.update(row["category"] for row in rows)
    return sorted(found)


def _repeat_locations(session, start: str, end: str) -> list[int]:
    minimum = int(get_setting(session.conn, "repeat_location_min", 3))
    window_days = _window_days(session)
    rows = session.conn.execute(
        """
        SELECT i.id, i.event_date, i.call_type, l.normalized_address AS address
        FROM incidents i
        JOIN locations l ON l.id = i.location_id
        WHERE i.excluded = 0 AND i.event_date >= ? AND i.event_date <= ?
          AND l.normalized_address IS NOT NULL AND TRIM(l.normalized_address) != ''
          AND i.call_type IS NOT NULL AND TRIM(i.call_type) != ''
        ORDER BY i.event_date, i.id
        """,
        (start, end),
    ).fetchall()
    grouped: dict[tuple[str, str], list[tuple[date, int, str]]] = {}
    for row in rows:
        call_key = _call_type_key(row["call_type"])
        if not call_key:
            continue
        grouped.setdefault((row["address"], call_key), []).append(
            (date.fromisoformat(row["event_date"]), int(row["id"]), _call_type_label(row["call_type"]))
        )
    ids = []
    for (address, call_key), items in grouped.items():
        for cluster in _clusters(items, window_days, minimum):
            first, last = cluster[0][0], cluster[-1][0]
            label = cluster[0][2]
            incident_ids = [item[1] for item in cluster]
            ids.append(
                _upsert(
                    session,
                    pattern_key=f"repeat|{address}|{call_key}|{first.isoformat()}|{last.isoformat()}",
                    name=f"Repeat {label} calls at {address}",
                    pattern_type="repeat_same_type",
                    trigger=(
                        f"At least {minimum} calls of the same call type at the same normalized address "
                        f"within {window_days} calendar days."
                    ),
                    baseline={
                        "count": len(cluster),
                        "minimum": minimum,
                        "window_days": window_days,
                        "call_type": label,
                    },
                    start=first.isoformat(),
                    end=last.isoformat(),
                    area=address,
                    explanation=(
                        f"{len(cluster)} {label} calls were recorded at this address from "
                        f"{first.isoformat()} through {last.isoformat()}, inside a {window_days}-day window. "
                        + LIMITATION
                    ),
                    incident_ids=incident_ids,
                    confidence="rule_based",
                    limitation=LIMITATION,
                )
            )
    return ids


def _category_increases(session, start: str, end: str) -> list[int]:
    support = int(get_setting(session.conn, "pattern_min_support", 3))
    start_date = date.fromisoformat(start)
    end_date = date.fromisoformat(end)
    length = (end_date - start_date).days + 1
    baseline_end = start_date - timedelta(days=1)
    baseline_start = baseline_end - timedelta(days=length - 1)
    lo, hi = coverage_bounds(session.conn)
    baseline_start_text = baseline_start.isoformat()
    baseline_end_text = baseline_end.isoformat()
    if window_relation(lo, hi, baseline_start_text, baseline_end_text) == "outside":
        return []
    ids = []
    trigger = "Count at least doubled versus the previous equal-length period and met the minimum support."
    for category in trend_categories(session.conn):
        label = CATEGORY_LABELS.get(category, category.replace("_", " "))
        current = category_metric(session.conn, start, end, category, category, category)
        baseline = category_metric(
            session.conn,
            baseline_start_text,
            baseline_end_text,
            category,
            category,
            category,
        )
        if _volume_met(current.value, baseline.value, support):
            ids.append(
                _upsert(
                    session,
                    pattern_key=f"increase|{category}|{start}|{end}",
                    name=f"Volume increase: {label}",
                    pattern_type="category_increase",
                    trigger=trigger,
                    baseline={"current": current.value, "previous": baseline.value, "minimum": support},
                    start=start,
                    end=end,
                    area=None,
                    explanation=(
                        f"Official {label} incidents were {current.value} in this period and "
                        f"{baseline.value} in the previous equal-length period. {LIMITATION}"
                    ),
                    incident_ids=current.incident_ids,
                    confidence="moderate_rule",
                    limitation=LIMITATION,
                )
            )
    current_types = _call_type_counts(session.conn, start, end)
    baseline_types = _call_type_counts(session.conn, baseline_start_text, baseline_end_text)
    for call_key in sorted(set(current_types) | set(baseline_types)):
        current = current_types.get(call_key, {"label": call_key, "ids": []})
        baseline = baseline_types.get(call_key, {"label": call_key, "ids": []})
        if _volume_met(len(current["ids"]), len(baseline["ids"]), support):
            label = current["label"] if current["ids"] else baseline["label"]
            ids.append(
                _upsert(
                    session,
                    pattern_key=f"increase|call|{call_key}|{start}|{end}",
                    name=f"Volume increase: call type {label}",
                    pattern_type="call_type_increase",
                    trigger=trigger,
                    baseline={"current": len(current["ids"]), "previous": len(baseline["ids"]), "minimum": support},
                    start=start,
                    end=end,
                    area=None,
                    explanation=(
                        f"Uploaded call type {label} was {len(current['ids'])} in this period and "
                        f"{len(baseline['ids'])} in the previous equal-length period. {CALL_TYPE_LIMITATION}"
                    ),
                    incident_ids=current["ids"],
                    confidence="moderate_rule",
                    limitation=CALL_TYPE_LIMITATION,
                )
            )
    return ids


def _volume_met(current: int, baseline: int, support: int) -> bool:
    return current >= max(support, baseline * 2) and current - baseline >= support


def _window_days(session) -> int:
    window_days = int(get_setting(session.conn, "repeat_location_window_days", REPEAT_LOCATION_WINDOW_DAYS))
    return window_days if window_days >= 1 else REPEAT_LOCATION_WINDOW_DAYS


def _call_type_key(value: str) -> str:
    return " ".join(value.split()).casefold()


def _call_type_label(value: str) -> str:
    return " ".join(value.split())


def _call_type_counts(conn, start: str, end: str) -> dict[str, dict]:
    rows = conn.execute(
        """
        SELECT id, call_type FROM incidents
        WHERE excluded = 0 AND event_date >= ? AND event_date <= ?
          AND call_type IS NOT NULL AND TRIM(call_type) != ''
        ORDER BY event_date, id
        """,
        (start, end),
    ).fetchall()
    grouped: dict[str, dict] = {}
    for row in rows:
        key = _call_type_key(row["call_type"])
        if not key:
            continue
        bucket = grouped.setdefault(key, {"label": _call_type_label(row["call_type"]), "ids": []})
        bucket["ids"].append(int(row["id"]))
    return grouped


def _clusters(items: list[tuple[date, int, str]], window_days: int, minimum: int) -> list[list[tuple[date, int, str]]]:
    ordered = sorted(items, key=lambda item: (item[0], item[1]))
    found = []
    left = 0
    right = 0
    count = len(ordered)
    while left < count:
        while right + 1 < count and (ordered[right + 1][0] - ordered[left][0]).days <= window_days - 1:
            right += 1
        if right - left + 1 >= minimum:
            found.append(ordered[left : right + 1])
            left = right + 1
            right = max(right, left)
        else:
            left += 1
            if right < left:
                right = left
    return found


def _displacement(session, start: str, end: str, notes: list[str]) -> list[int]:
    if not session.conn.execute("SELECT COUNT(*) AS n FROM zone_neighbors").fetchone()["n"]:
        return []
    return []


def _upsert(session, **kwargs) -> int:
    existing = session.conn.execute(
        "SELECT id FROM patterns WHERE pattern_key = ?",
        (kwargs["pattern_key"],),
    ).fetchone()
    limitation = kwargs.get("limitation", LIMITATION)
    if existing:
        pattern_id = int(existing["id"])
        session.conn.execute(
            """
            UPDATE patterns
            SET explanation = ?, baseline_json = ?, confidence = ?, limitations = ?, trigger_rule = ?
            WHERE id = ? AND status NOT IN ('rejected')
            """,
            (
                kwargs["explanation"],
                json.dumps(kwargs["baseline"]),
                kwargs["confidence"],
                limitation,
                kwargs["trigger"],
                pattern_id,
            ),
        )
    else:
        cursor = session.conn.execute(
            """
            INSERT INTO patterns(
                pattern_key, name, pattern_type, status, confidence, limitations, trigger_rule,
                baseline_json, date_start, date_end, area_label, explanation, created_at
            ) VALUES (?, ?, ?, 'open', ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                kwargs["pattern_key"],
                kwargs["name"],
                kwargs["pattern_type"],
                kwargs["confidence"],
                limitation,
                kwargs["trigger"],
                json.dumps(kwargs["baseline"]),
                kwargs["start"],
                kwargs["end"],
                kwargs["area"],
                kwargs["explanation"],
                session.stamp(),
            ),
        )
        pattern_id = int(cursor.lastrowid)
    session.conn.execute("DELETE FROM pattern_incidents WHERE pattern_id = ?", (pattern_id,))
    for incident_id in kwargs["incident_ids"]:
        session.conn.execute(
            "INSERT INTO pattern_incidents(pattern_id, incident_id) VALUES (?, ?)",
            (pattern_id, incident_id),
        )
    return pattern_id
