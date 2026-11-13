"""Idempotent reference data. No incidents are seeded."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime, timezone

from wpd_compstat.classification.taxonomy import RULES
from wpd_compstat.constants import AGENCY_CODES, DEFAULT_SESSION_MINUTES, PERCENT_MIN_BASELINE
from wpd_compstat.import_engine.profile import GENERIC_PROFILE, profile_json

DIVISIONS = (
    ("Uniform Division", "division"),
    ("First Shift", "shift"),
    ("Second Shift", "shift"),
    ("Third Shift", "shift"),
    ("Traffic Unit", "unit"),
    ("Community Police", "unit"),
    ("Detectives", "unit"),
)

DIVISION_NOTE = (
    "Listed from the COMPSTAT specification. An administrator must confirm the name, "
    "command, and effective dates before the unit is treated as official."
)


def default_settings() -> dict:
    return {
        "session_timeout_minutes": DEFAULT_SESSION_MINUTES,
        "backup_retention": 15,
        "backup_interval_minutes": 0,
        "violation_weekly_goal": 200,
        "percent_change_min_baseline": PERCENT_MIN_BASELINE,
        "repeat_location_min": 3,
        "pattern_min_support": 3,
        "source_lists_confirmed": False,
        "officer_initiated_sources": ["OFFICER INITIATED", "OI", "SELF-INITIATED"],
        "citizen_sources": ["911", "E911", "PHONE", "WALK-IN", "CITIZEN"],
        "shifts": [
            {"name": "First Shift", "start": "07:00", "end": "15:00"},
            {"name": "Second Shift", "start": "15:00", "end": "23:00"},
            {"name": "Third Shift", "start": "23:00", "end": "07:00"},
        ],
        "shifts_confirmed": False,
        "cleared_dispositions": [],
        "cleared_dispositions_confirmed": False,
        "active_profile_id": None,
        "include_narrative_excerpts_in_briefing": False,
        "agency_name": "Warwick Police Department",
        "retention_days": None,
        "next_action_seq": 1,
    }


def seed(conn, now: str | None = None) -> None:
    stamp = now or datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    for key, value in default_settings().items():
        conn.execute(
            """
            INSERT INTO app_settings(key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO NOTHING
            """,
            (key, json.dumps(value), stamp),
        )
    for name, unit_type in DIVISIONS:
        conn.execute(
            """
            INSERT INTO divisions(name, unit_type, active, confirmed, notes)
            VALUES (?, ?, 1, 0, ?)
            ON CONFLICT(name) DO NOTHING
            """,
            (name, unit_type, DIVISION_NOTE),
        )
    for code in AGENCY_CODES:
        conn.execute(
            """
            INSERT INTO agency_codes(code, label, definition, status, notes)
            VALUES (?, NULL, NULL, 'unconfirmed', ?)
            ON CONFLICT(code) DO NOTHING
            """,
            (
                code,
                "Official definition has not been entered. The application does not assign a meaning to this code.",
            ),
        )
    for rule in RULES:
        conn.execute(
            """
            INSERT INTO classification_rules(
                rule_key, category, definition_json, enabled, confirmation, updated_at
            ) VALUES (?, ?, ?, 1, 'starter_unconfirmed', ?)
            ON CONFLICT(rule_key) DO NOTHING
            """,
            (rule["rule_key"], rule["category"], json.dumps(rule), stamp),
        )
    conn.execute(
        """
        INSERT INTO cad_profiles(id, name, confirmation, definition_json, updated_at)
        VALUES (?, ?, 'unconfirmed', ?, ?)
        ON CONFLICT(id) DO NOTHING
        """,
        (GENERIC_PROFILE["id"], GENERIC_PROFILE["name"], profile_json(GENERIC_PROFILE), stamp),
    )


def get_setting(conn, key: str, default=None):
    row = conn.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
    if row is None:
        return default
    return json.loads(row["value"])


def set_setting(conn, key: str, value, now: str, user_id: int | None) -> None:
    conn.execute(
        """
        INSERT INTO app_settings(key, value, updated_at, updated_by)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET
            value = excluded.value,
            updated_at = excluded.updated_at,
            updated_by = excluded.updated_by
        """,
        (key, json.dumps(value), now, user_id),
    )
