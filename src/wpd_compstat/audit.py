"""Audit rows. Details are redacted and kept short."""

from __future__ import annotations

from wpd_compstat.security.redact import redact_for_log


def write_audit(
    conn,
    *,
    occurred_at: str,
    user,
    action: str,
    result: str = "ok",
    entity_type: str | None = None,
    entity_id: object = None,
    detail: object = None,
) -> None:
    username = None
    user_id = None
    if user is not None:
        username = user["username"]
        user_id = user["id"]
    conn.execute(
        """
        INSERT INTO audit_log(
            occurred_at, user_id, username, action, entity_type, entity_id, detail, result
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            occurred_at,
            user_id,
            username,
            action,
            entity_type,
            None if entity_id is None else str(entity_id),
            None if detail is None else redact_for_log(detail),
            result,
        ),
    )
