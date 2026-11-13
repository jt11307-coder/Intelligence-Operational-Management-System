"""SQLite connection helpers. Journal mode DELETE avoids leftover WAL files."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.isolation_level = None
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = DELETE")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def fetchall(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
    return list(conn.execute(sql, params).fetchall())


def fetchone(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> sqlite3.Row | None:
    return conn.execute(sql, params).fetchone()
