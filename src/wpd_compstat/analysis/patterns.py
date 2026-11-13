"""Rule-based patterns. A volume change is not described as a common offender."""

from __future__ import annotations

import json

from wpd_compstat.analysis import category_metric
from wpd_compstat.analysis.compare import coverage_bounds, window_relation
from wpd_compstat.db.connection import transaction
from wpd_compstat.db.seed import get_setting

PATTERN_CATEGORIES = (
    "shoplifting",
    "theft_from_vehicle",
    "burglary",
    "vandalism",
    "domestic_incident",
    "disorderly_conduct",
    "suspicious_activity",
)
LIMITATION = (
    "This is a volume or repeat-location rule. It does not establish a common offender, "
    "a criminal conspiracy, or a cause."
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
        notes.append("No officially counted classifications are available. Category patterns were not created from unconfirmed suggestions.")
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


def _repeat_locations(session, start: str, end: str) -> list[int]:
    minimum = int(get_setting(session.conn, "repeat_location_min", 3))
    rows = session.conn.execute(
        """
        SELECT l.normalized_address AS address, COUNT(DISTINCT i.id) AS n
        FROM incidents i
        JOIN locations l ON l.id = i.location_id
        WHERE i.excluded = 0 AND i.event_date >= ? AND i.event_date <= ?
          AND l.normalized_address IS NOT NULL AND TRIM(l.normalized_address) != ''
        GROUP BY l.normalized_address
        HAVING n >= ?
        """,
        (start, end, minimum),
    ).fetchall()
    ids = []
    for row in rows:
        incidents = [
            item["id"]
            for item in session.conn.execute(
                """
                SELECT i.id FROM incidents i
                JOIN locations l ON l.id = i.location_id
                WHERE i.excluded = 0 AND l.normalized_address = ?
                  AND i.event_date >= ? AND i.event_date <= ?
                """,
                (row["address"], start, end),
            )
        ]
        ids.append(
            _upsert(
                session,
                pattern_key=f"repeat|{row['address']}|{start}|{end}",
                name=f"Repeat calls at {row['address']}",
                pattern_type="repeat_location",
                trigger=f"At least {minimum} calls at the same normalized address in the selected period.",
                baseline={"count": int(row["n"]), "minimum": minimum},
                start=start,
                end=end,
                area=row["address"],
                explanation=(
                    f"{int(row['n'])} calls for service were recorded at this address from {start} through {end}. "
                    + LIMITATION
                ),
                incident_ids=incidents,
                confidence="rule_based",
            )
        )
    return ids


def _category_increases(session, start: str, end: str) -> list[int]:
    from datetime import date, timedelta

    support = int(get_setting(session.conn, "pattern_min_support", 3))
    start_date = date.fromisoformat(start)
    end_date = date.fromisoformat(end)
    length = (end_date - start_date).days + 1
    baseline_end = start_date - timedelta(days=1)
    baseline_start = baseline_end - timedelta(days=length - 1)
    lo, hi = coverage_bounds(session.conn)
    if window_relation(lo, hi, baseline_start.isoformat(), baseline_end.isoformat()) == "outside":
        return []
    ids = []
    for category in PATTERN_CATEGORIES:
        current = category_metric(session.conn, start, end, category, category, category)
        baseline = category_metric(
            session.conn,
            baseline_start.isoformat(),
            baseline_end.isoformat(),
            category,
            category,
            category,
        )
        if current.value >= max(support, baseline.value * 2) and current.value - baseline.value >= support:
            ids.append(
                _upsert(
                    session,
                    pattern_key=f"increase|{category}|{start}|{end}",
                    name=f"Volume increase: {category.replace('_', ' ')}",
                    pattern_type="category_increase",
                    trigger="Count at least doubled versus the previous equal-length period and met the minimum support.",
                    baseline={"current": current.value, "previous": baseline.value, "minimum": support},
                    start=start,
                    end=end,
                    area=None,
                    explanation=(
                        f"Official {category.replace('_', ' ')} incidents were {current.value} in this period and "
                        f"{baseline.value} in the previous equal-length period. {LIMITATION}"
                    ),
                    incident_ids=current.incident_ids,
                    confidence="moderate_rule",
                )
            )
    return ids


def _displacement(session, start: str, end: str, notes: list[str]) -> list[int]:
    if not session.conn.execute("SELECT COUNT(*) AS n FROM zone_neighbors").fetchone()["n"]:
        return []
    return []


def _upsert(session, **kwargs) -> int:
    existing = session.conn.execute(
        "SELECT id FROM patterns WHERE pattern_key = ?",
        (kwargs["pattern_key"],),
    ).fetchone()
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
                LIMITATION,
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
                LIMITATION,
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
