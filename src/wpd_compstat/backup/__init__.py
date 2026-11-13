"""Encrypted backups of the working database. Copies stay encrypted."""

from __future__ import annotations

import hashlib
from pathlib import Path

from wpd_compstat.constants import SAME_DRIVE_BACKUP_WARNING
from wpd_compstat.db.connection import connect
from wpd_compstat.db.migrate import apply_migrations
from wpd_compstat.db.seed import get_setting
from wpd_compstat.errors import AppError
from wpd_compstat.security.crypto import open_sealed_file, seal_file, secure_unlink


def create_backup(session, reason: str, kind: str, *, permission: str = "backup") -> dict:
    session.require(permission)
    stamp = session.stamp().replace(":", "").replace("+", "")
    relative = f"Backups/{stamp}-{kind}.db.enc"
    destination = session.paths.root / relative
    plain = session.paths.temp / f"{stamp}.db"
    plain.parent.mkdir(parents=True, exist_ok=True)
    copy = connect(plain)
    try:
        session.conn.backup(copy)
    finally:
        copy.close()
    data = plain.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    seal_file(destination, session.dek, data)
    secure_unlink(plain)
    opened = open_sealed_file(destination, session.dek)
    if hashlib.sha256(opened).hexdigest() != digest or not opened.startswith(b"SQLite format 3"):
        secure_unlink(destination)
        raise AppError("The backup could not be verified. No database change was committed.")
    verify_path = session.paths.temp / f"{stamp}-verify.db"
    verify_path.write_bytes(opened)
    verified = connect(verify_path)
    try:
        result = verified.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        verified.close()
        secure_unlink(verify_path)
    if result != "ok":
        secure_unlink(destination)
        raise AppError("The backup failed its integrity check. No database change was committed.")
    cursor = session.conn.execute(
        """
        INSERT INTO backups(
            relative_path, created_at, created_by, reason, plaintext_sha256,
            byte_size, verified, verified_at, kind
        ) VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)
        """,
        (
            relative,
            session.stamp(),
            session.user["id"],
            reason,
            digest,
            destination.stat().st_size,
            session.stamp(),
            kind,
        ),
    )
    _enforce_retention(session)
    session.audit("backup", entity_type="backup", entity_id=cursor.lastrowid, detail=kind)
    return {
        "id": int(cursor.lastrowid),
        "relative_path": relative,
        "sha256": digest,
        "warning": SAME_DRIVE_BACKUP_WARNING,
    }


def restore_backup(session, backup_id: int) -> dict:
    session.require("restore")
    row = session.conn.execute("SELECT * FROM backups WHERE id = ?", (backup_id,)).fetchone()
    if row is None:
        raise AppError("That backup does not exist.")
    source = session.paths.root / row["relative_path"]
    opened = open_sealed_file(source, session.dek)
    if hashlib.sha256(opened).hexdigest() != row["plaintext_sha256"]:
        raise AppError("The backup no longer matches its recorded checksum and was not restored.")
    create_backup(session, "Before restore", "pre_restore")
    session.conn.close()
    session.conn = None
    session.paths.db_working.write_bytes(opened)
    session.conn = connect(session.paths.db_working)
    apply_migrations(session.conn)
    check = session.conn.execute("PRAGMA integrity_check").fetchone()[0]
    if check != "ok":
        raise AppError("The restored database failed its integrity check.")
    session.audit("restore", entity_type="backup", entity_id=backup_id)
    return {"restored": backup_id, "warning": SAME_DRIVE_BACKUP_WARNING}


def export_encrypted_copy(session, backup_id: int, destination_dir: Path) -> Path:
    session.require("backup")
    row = session.conn.execute("SELECT * FROM backups WHERE id = ?", (backup_id,)).fetchone()
    if row is None:
        raise AppError("That backup does not exist.")
    source = session.paths.root / row["relative_path"]
    payload = source.read_bytes()
    if payload.startswith(b"SQLite format 3"):
        raise AppError("Refusing to copy a plaintext database.")
    destination_dir.mkdir(parents=True, exist_ok=True)
    target = destination_dir / source.name
    target.write_bytes(payload)
    session.audit("export_backup_copy", entity_type="backup", entity_id=backup_id)
    return target


def list_backups(session) -> list[dict]:
    session.require("backup")
    rows = session.conn.execute("SELECT * FROM backups ORDER BY id DESC").fetchall()
    return [dict(row) for row in rows]


def _enforce_retention(session) -> None:
    keep = int(get_setting(session.conn, "backup_retention", 15) or 15)
    rows = session.conn.execute("SELECT id, relative_path FROM backups ORDER BY id DESC").fetchall()
    for row in rows[keep:]:
        path = session.paths.root / row["relative_path"]
        if path.exists():
            secure_unlink(path)
        session.conn.execute("DELETE FROM backups WHERE id = ?", (row["id"],))
