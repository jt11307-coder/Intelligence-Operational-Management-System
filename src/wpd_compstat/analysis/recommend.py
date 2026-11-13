"""Explainable recommendations. Nothing here starts an operation."""

from __future__ import annotations

from wpd_compstat.db.connection import transaction
from wpd_compstat.errors import ValidationError

PERSON_FREE = (
    "This recommendation is about places, times, and incident types. "
    "It is not a person-specific enforcement instruction and it does not authorize action."
)


def draft_recommendations(session) -> int:
    session.require("analyze")
    rows = session.conn.execute(
        """
        SELECT p.* FROM patterns p
        WHERE p.status IN ('open', 'accepted', 'monitoring')
          AND NOT EXISTS (
              SELECT 1 FROM recommendations r WHERE r.pattern_id = p.id
          )
        """
    ).fetchall()
    created = 0
    with transaction(session.conn):
        for pattern in rows:
            incidents = session.conn.execute(
                """
                SELECT i.cad_number FROM pattern_incidents pi
                JOIN incidents i ON i.id = pi.incident_id
                WHERE pi.pattern_id = ?
                ORDER BY i.cad_number
                """,
                (pattern["id"],),
            ).fetchall()
            numbers = ", ".join(row["cad_number"] for row in incidents) or "none recorded"
            session.conn.execute(
                """
                INSERT INTO recommendations(
                    pattern_id, title, identified, evidence, why, resources, measurement,
                    limitations, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'draft', ?)
                """,
                (
                    pattern["id"],
                    f"Review: {pattern['name']}",
                    pattern["explanation"],
                    f"Supporting CAD numbers: {numbers}. Trigger: {pattern['trigger_rule']}.",
                    "The documented rule was met. A commander can decide whether any response is appropriate. "
                    + PERSON_FREE,
                    "Analyst review and command judgment. No resource is assigned by this draft.",
                    "Compare the same measure over a later period of similar length. Completing a task is not the same as an effective outcome.",
                    pattern["limitations"],
                    session.stamp(),
                ),
            )
            created += 1
        session.audit("draft_recommendations", detail=f"created={created}")
    return created


def review_recommendation(session, recommendation_id: int, decision: str) -> None:
    session.require("assignments_approve")
    if decision not in {"approved", "rejected"}:
        raise ValidationError("A recommendation can be approved or rejected. Approval does not create an assignment.")
    row = session.conn.execute(
        "SELECT id, status FROM recommendations WHERE id = ?",
        (recommendation_id,),
    ).fetchone()
    if row is None:
        raise ValidationError("That recommendation does not exist.")
    session.conn.execute(
        """
        UPDATE recommendations
        SET status = ?, reviewed_by = ?, reviewed_at = ?
        WHERE id = ?
        """,
        (decision, session.user["id"], session.stamp(), recommendation_id),
    )
    session.audit("review_recommendation", entity_type="recommendation", entity_id=recommendation_id, detail=decision)
