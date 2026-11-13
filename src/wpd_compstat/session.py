"""Unlocked application session. The data key lives only in memory while unlocked."""

from __future__ import annotations

import json
import logging
import os
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

from wpd_compstat.audit import write_audit
from wpd_compstat.constants import KDF_N, KDF_P, KDF_R, LOCKOUT_MINUTES, MAX_FAILED_ATTEMPTS, MIN_PASSWORD_LENGTH
from wpd_compstat.db.connection import connect
from wpd_compstat.db.migrate import apply_migrations
from wpd_compstat.db.seed import get_setting, seed, set_setting
from wpd_compstat.errors import AppError, AuthError, ValidationError
from wpd_compstat.paths import InstallPaths, require_install_folder_name, use_install_temp
from wpd_compstat.security.crypto import (
    new_dek,
    open_sealed_file,
    seal_file,
    secure_unlink,
    unwrap_dek,
    wrap_dek,
    write_json_atomic,
)
from wpd_compstat.security.permissions import has_permission
from wpd_compstat.security.redact import redact_for_log

BANNED_PASSWORDS = {
    "password1234",
    "password12345",
    "changeme123",
    "wpdcompstat1",
    "administrator1",
}


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class Session:
    def __init__(self, root: Path, clock=None):
        try:
            os.umask(0o077)
        except OSError:
            pass
        self.paths = InstallPaths(require_install_folder_name(Path(root)))
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.dek: bytes | None = None
        self.conn = None
        self.user = None
        self.recovery = False
        self.locked = True
        self.last_activity: datetime | None = None
        self.recovered_working_copy = False
        self.logger = logging.getLogger("wpd_compstat")

    def now(self) -> datetime:
        return _as_utc(self.clock())

    def stamp(self) -> str:
        return self.now().replace(microsecond=0).isoformat()

    def state(self) -> str:
        has_key = self.paths.keystore.exists()
        has_db = self.paths.db_encrypted.exists() or self.paths.db_working.exists()
        if has_key and has_db:
            return "ready"
        if not has_key and not has_db:
            return "new"
        if has_db and not has_key:
            return "incomplete_database"
        return "incomplete_keystore"

    def setup_initial_admin(self, username: str, password: str, recovery_password: str | None = None) -> None:
        if self.state() != "new":
            raise AppError(
                "This installation is not empty. Incomplete installations must be repaired "
                "from an encrypted backup rather than by creating a second key."
            )
        self._validate_new_password(username, password)
        if recovery_password:
            self._validate_new_password(username + "-recovery", recovery_password)
            if recovery_password == password:
                raise ValidationError("The recovery passphrase must be different from the password.")
        self.paths.ensure_folders()
        use_install_temp(self.paths)
        self._configure_log()
        dek = new_dek()
        record = wrap_dek(password, dek, KDF_N, KDF_R, KDF_P)
        record.update({"failed_attempts": 0, "locked_until": None, "active": True})
        keystore = {
            "version": 1,
            "kdf_n": KDF_N,
            "kdf_r": KDF_R,
            "kdf_p": KDF_P,
            "users": {username.casefold(): record},
            "recovery": None,
        }
        if recovery_password:
            keystore["recovery"] = wrap_dek(recovery_password, dek, KDF_N, KDF_R, KDF_P)
        self.dek = dek
        conn = connect(self.paths.db_working)
        try:
            apply_migrations(conn)
            seed(conn, self.stamp())
            conn.execute(
                """
                INSERT INTO users(username, role, active, created_at)
                VALUES (?, 'administrator', 1, ?)
                """,
                (username, self.stamp()),
            )
        finally:
            conn.close()
        self._seal_working_copy()
        write_json_atomic(self.paths.keystore, keystore)
        self._materialize_database()
        self.user = self.conn.execute(
            "SELECT * FROM users WHERE username = ? COLLATE NOCASE",
            (username,),
        ).fetchone()
        self.locked = False
        self.recovery = False
        self.touch()
        self.audit("setup_admin", entity_type="user", entity_id=self.user["id"])

    def unlock(self, username: str, password: str) -> None:
        keystore = self._load_keystore()
        record = keystore["users"].get(username.casefold())
        if record is None or not record.get("active", True):
            raise AuthError("Authentication failed.")
        self._reject_if_locked(record)
        try:
            dek = unwrap_dek(password, record, keystore["kdf_n"], keystore["kdf_r"], keystore["kdf_p"])
        except Exception as exc:
            record["failed_attempts"] = int(record.get("failed_attempts") or 0) + 1
            if record["failed_attempts"] >= MAX_FAILED_ATTEMPTS:
                record["locked_until"] = (self.now() + timedelta(minutes=LOCKOUT_MINUTES)).isoformat()
            self._save_keystore(keystore)
            raise AuthError("Authentication failed.") from exc
        record["failed_attempts"] = 0
        record["locked_until"] = None
        self._save_keystore(keystore)
        self.dek = dek
        use_install_temp(self.paths)
        self._configure_log()
        self._materialize_database()
        user = self.conn.execute(
            "SELECT * FROM users WHERE username = ? COLLATE NOCASE",
            (username,),
        ).fetchone()
        if user is None or not user["active"]:
            self.lock()
            raise AuthError("Authentication failed.")
        self.user = user
        self.locked = False
        self.recovery = False
        self.touch()
        self.audit("unlock")

    def unlock_with_recovery(self, recovery_password: str) -> None:
        keystore = self._load_keystore()
        recovery = keystore.get("recovery")
        if not recovery:
            raise AuthError("No recovery passphrase is configured. Data cannot be recovered from this installation.")
        try:
            dek = unwrap_dek(
                recovery_password, recovery, keystore["kdf_n"], keystore["kdf_r"], keystore["kdf_p"]
            )
        except Exception as exc:
            raise AuthError("Authentication failed.") from exc
        self.dek = dek
        use_install_temp(self.paths)
        self._configure_log()
        self._materialize_database()
        self.user = self.conn.execute(
            "SELECT * FROM users WHERE role = 'administrator' AND active = 1 ORDER BY id LIMIT 1"
        ).fetchone()
        if self.user is None:
            self.lock()
            raise AuthError("Recovery opened the database, but no active administrator account exists.")
        self.locked = False
        self.recovery = True
        self.touch()
        self.audit("recovery_unlock", detail="Restricted recovery session")

    def lock(self) -> None:
        try:
            if self.conn is not None and self.user is not None and not self.recovery:
                self.audit("lock")
        except Exception:
            pass
        self._seal_working_copy()
        self.dek = None
        self.user = None
        self.locked = True
        self.recovery = False
        self.last_activity = None

    def close(self) -> None:
        self.lock()

    def touch(self) -> None:
        self.last_activity = self.now()

    def require(self, permission: str):
        if self.locked or self.user is None or self.conn is None or self.dek is None:
            raise AuthError("The session is locked.")
        if self.timed_out():
            self.lock()
            raise AuthError("The session timed out and locked.")
        if self.recovery and permission not in {"manage_users"}:
            raise AuthError("A recovery session can only reset user credentials.")
        if not has_permission(self.user["role"], permission):
            raise AuthError("This role cannot perform that action.")
        self.touch()
        return self.user

    def timed_out(self) -> bool:
        if self.locked or self.last_activity is None or self.conn is None:
            return False
        minutes = int(get_setting(self.conn, "session_timeout_minutes", 15))
        return self.now() - self.last_activity > timedelta(minutes=minutes)

    def setting(self, key: str, default=None):
        if self.locked or self.conn is None:
            raise AuthError("The session is locked.")
        if self.timed_out():
            self.lock()
            raise AuthError("The session timed out and locked.")
        return get_setting(self.conn, key, default)

    def update_setting(self, key: str, value) -> None:
        self.require("configure")
        set_setting(self.conn, key, value, self.stamp(), self.user["id"])
        self.audit("update_setting", entity_type="setting", entity_id=key)

    def audit(self, action: str, **kwargs) -> None:
        if self.conn is None:
            return
        write_audit(self.conn, occurred_at=self.stamp(), user=self.user, action=action, **kwargs)

    def create_user(self, username: str, password: str, role: str) -> int:
        self.require("manage_users")
        self._validate_new_password(username, password)
        if role not in {
            "administrator",
            "crime_analyst",
            "command_staff",
            "supervisor",
            "read_only",
        }:
            raise ValidationError("Unknown role.")
        existing = self.conn.execute(
            "SELECT id FROM users WHERE username = ? COLLATE NOCASE",
            (username,),
        ).fetchone()
        if existing:
            raise ValidationError("That username already exists.")
        cursor = self.conn.execute(
            """
            INSERT INTO users(username, role, active, created_at, created_by)
            VALUES (?, ?, 1, ?, ?)
            """,
            (username, role, self.stamp(), self.user["id"]),
        )
        keystore = self._load_keystore()
        record = wrap_dek(password, self.dek, keystore["kdf_n"], keystore["kdf_r"], keystore["kdf_p"])
        record.update({"failed_attempts": 0, "locked_until": None, "active": True})
        keystore["users"][username.casefold()] = record
        self._save_keystore(keystore)
        self.audit("create_user", entity_type="user", entity_id=cursor.lastrowid, detail=role)
        return int(cursor.lastrowid)

    def reset_password(self, username: str, new_password: str) -> None:
        self.require("manage_users")
        self._validate_new_password(username, new_password)
        user = self.conn.execute(
            "SELECT * FROM users WHERE username = ? COLLATE NOCASE",
            (username,),
        ).fetchone()
        if user is None:
            raise ValidationError("That user does not exist.")
        keystore = self._load_keystore()
        record = wrap_dek(new_password, self.dek, keystore["kdf_n"], keystore["kdf_r"], keystore["kdf_p"])
        record.update({"failed_attempts": 0, "locked_until": None, "active": True})
        keystore["users"][username.casefold()] = record
        self._save_keystore(keystore)
        self.audit("reset_password", entity_type="user", entity_id=user["id"])

    def deactivate_user(self, username: str) -> None:
        self.require("manage_users")
        if username.casefold() == self.user["username"].casefold() and not self.recovery:
            raise ValidationError("You cannot deactivate the account that is signed in.")
        user = self.conn.execute(
            "SELECT * FROM users WHERE username = ? COLLATE NOCASE",
            (username,),
        ).fetchone()
        if user is None:
            raise ValidationError("That user does not exist.")
        self.conn.execute(
            "UPDATE users SET active = 0, deactivated_at = ? WHERE id = ?",
            (self.stamp(), user["id"]),
        )
        keystore = self._load_keystore()
        record = keystore["users"].get(username.casefold())
        if record:
            record["active"] = False
            self._save_keystore(keystore)
        self.audit("deactivate_user", entity_type="user", entity_id=user["id"])

    def _validate_new_password(self, username: str, password: str) -> None:
        if not username or not username.strip() or any(char.isspace() for char in username):
            raise ValidationError("Usernames cannot contain spaces.")
        if len(password) < MIN_PASSWORD_LENGTH:
            raise ValidationError(f"Passwords must be at least {MIN_PASSWORD_LENGTH} characters.")
        if not any(char.isalpha() for char in password) or not any(char.isdigit() for char in password):
            raise ValidationError("Passwords must include a letter and a number.")
        if password.casefold() == username.casefold() or password.casefold() in BANNED_PASSWORDS:
            raise ValidationError("Choose a different password.")

    def _load_keystore(self) -> dict:
        if not self.paths.keystore.exists():
            raise AppError("The keystore is missing. The database cannot be opened.")
        return json.loads(self.paths.keystore.read_text(encoding="utf-8"))

    def _save_keystore(self, keystore: dict) -> None:
        write_json_atomic(self.paths.keystore, keystore)

    def _reject_if_locked(self, record: dict) -> None:
        locked_until = record.get("locked_until")
        if not locked_until:
            return
        try:
            until = datetime.fromisoformat(locked_until)
        except ValueError:
            return
        if until.tzinfo is None:
            until = until.replace(tzinfo=timezone.utc)
        if self.now() < until:
            raise AuthError("The account is temporarily locked.")

    def _materialize_database(self) -> None:
        working = self.paths.db_working
        encrypted = self.paths.db_encrypted
        self.paths.working.mkdir(parents=True, exist_ok=True)
        recovered = False
        if working.exists():
            header = working.read_bytes()[:16]
            if header.startswith(b"SQLite format 3"):
                recovered = True
            else:
                secure_unlink(working)
        if not working.exists():
            if not encrypted.exists():
                raise AppError("The encrypted database is missing.")
            data = open_sealed_file(encrypted, self.dek)
            if not data.startswith(b"SQLite format 3"):
                raise AppError("The database file could not be opened.")
            working.write_bytes(data)
            try:
                os.chmod(working, 0o600)
            except OSError:
                pass
        self.conn = connect(working)
        apply_migrations(self.conn)
        seed(self.conn, self.stamp())
        self.recovered_working_copy = recovered
        if recovered:
            self.logger.info("Recovered an unsealed working database from an interrupted session.")

    def _seal_working_copy(self) -> None:
        if self.conn is not None:
            try:
                self.conn.close()
            finally:
                self.conn = None
        working = self.paths.db_working
        if working.exists() and self.dek is not None and working.read_bytes()[:16].startswith(b"SQLite format 3"):
            seal_file(self.paths.db_encrypted, self.dek, working.read_bytes())
            secure_unlink(working)
        for suffix in ("-journal", "-wal", "-shm"):
            extra = Path(str(working) + suffix)
            if extra.exists():
                secure_unlink(extra)
        self._wipe_directory(self.paths.temp)
        self._wipe_directory(self.paths.working / "view")

    def _wipe_directory(self, directory: Path) -> None:
        if not directory.exists():
            return
        for child in directory.iterdir():
            if child.is_file():
                secure_unlink(child)
            elif child.is_dir():
                shutil.rmtree(child, ignore_errors=True)

    def _configure_log(self) -> None:
        self.paths.logs.mkdir(parents=True, exist_ok=True)

        class _Redact(logging.Filter):
            def filter(self, record: logging.LogRecord) -> bool:
                record.msg = redact_for_log(record.getMessage(), 300)
                record.args = ()
                return True

        self.logger.setLevel(logging.INFO)
        self.logger.handlers.clear()
        handler = logging.FileHandler(self.paths.logs / "application.log", encoding="utf-8")
        handler.addFilter(_Redact())
        self.logger.addHandler(handler)
        self.logger.propagate = False
