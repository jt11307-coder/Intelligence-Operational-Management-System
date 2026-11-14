"""Schema migrations. Each file runs once inside a transaction."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from wpd_compstat.db.connection import fetchall

MIGRATION_DIR = Path(__file__).resolve().parent
MIGRATION_FILES = (
    (1, "001_initial.sql"),
    (2, "002_report_runs.sql"),
    (3, "003_incident_child_indexes.sql"),
)


def applied_versions(conn: sqlite3.Connection) -> set[int]:
    try:
        rows = fetchall(conn, "SELECT version FROM schema_migrations")
    except sqlite3.OperationalError:
        return set()
    return {int(row["version"]) for row in rows}


def apply_migrations(conn: sqlite3.Connection, *, only_through: int | None = None) -> list[int]:
    done = applied_versions(conn)
    applied_now: list[int] = []
    for version, name in MIGRATION_FILES:
        if only_through is not None and version > only_through:
            break
        if version in done:
            continue
        script = (MIGRATION_DIR / name).read_text(encoding="utf-8")
        # The SQL file contains its own BEGIN/COMMIT. executescript cannot sit
        # inside another explicit transaction because it commits first.
        conn.executescript(script)
        applied_now.append(version)
        done.add(version)
    return applied_now


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
