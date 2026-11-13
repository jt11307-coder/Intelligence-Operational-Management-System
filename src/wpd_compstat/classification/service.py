"""Store and correct classifications without dropping the original system reading."""

from __future__ import annotations

import json

from wpd_compstat.classification.codes import scan_codes, validate_match_rules
from wpd_compstat.classification.engine import Classifiable, classify
from wpd_compstat.classification.taxonomy import CATEGORY_LABELS
from wpd_compstat.db.connection import transaction
from wpd_compstat.errors import ValidationError


def load_rules(conn) -> list[dict]:
    rows = conn.execute("SELECT * FROM classification_rules WHERE enabled = 1").fetchall()
    rules = []
    for row in rows:
        rule = json.loads(row["definition_json"])
        rule["confirmation"] = row["confirmation"]
        rule["enabled"] = bool(row["enabled"])
        rules.append(rule)
    return rules


def load_codes(conn) -> list[dict]:
    rows = conn.execute("SELECT * FROM agency_codes").fetchall()
    codes = []
    for row in rows:
        codes.append(
            {
                "code": row["code"],
                "status": row["status"],
                "definition": row["definition"],
                "match_json": json.loads(row["match_json"]) if row["match_json"] else {},
            }
        )
    return codes


def classifiable_from_incident(conn, incident_id: int) -> Classifiable:
    incident = conn.execute("SELECT * FROM incidents WHERE id = ?", (incident_id,)).fetchone()
    narratives = [
        row["body"]
        for row in conn.execute(
            "SELECT body FROM narratives WHERE incident_id = ? ORDER BY sequence",
            (incident_id,),
        )
    ]
    reports = [
        row["ref_type"]
        for row in conn.execute("SELECT ref_type FROM report_references WHERE incident_id = ?", (incident_id,))
    ]
    citations = conn.execute("SELECT * FROM citations WHERE incident_id = ?", (incident_id,)).fetchall()
    officers = conn.execute(
        """
        SELECT COUNT(*) AS n FROM incident_officers
        WHERE incident_id = ? AND COALESCE(role, '') != 'primary_unit'
        """,
        (incident_id,),
    ).fetchone()["n"]
    return Classifiable(
        call_type=incident["call_type"],
        call_classification=incident["call_classification"],
        disposition=incident["disposition"],
        final_disposition=incident["final_disposition"],
        narratives=narratives,
        report_types=reports,
        citation_numbers=[row["citation_number"] for row in citations if row["citation_number"]],
        citation_verified=any(row["verified_violation"] for row in citations),
        citation_warning=any(row["warning"] for row in citations),
        officer_slots=officers,
        follow_up=None if incident["follow_up"] is None else bool(incident["follow_up"]),
    )


def store_system_classifications(conn, incident_id: int, record: Classifiable, rules, codes, stamp: str) -> None:
    proposals = classify(record, rules)
    for proposal in proposals:
        _insert_proposal(conn, incident_id, proposal, stamp)
    for mention in scan_codes(record.call_type, record.narratives, codes):
        conn.execute(
            """
            INSERT INTO code_mentions(incident_id, code, evidence, status)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(incident_id, code) DO NOTHING
            """,
            (incident_id, mention["code"], mention["evidence"], mention["status"]),
        )
        category = mention.get("category")
        if mention["status"] == "definition_confirmed" and category in CATEGORY_LABELS:
            conn.execute(
                """
                INSERT INTO classifications(
                    incident_id, category, polarity, confidence, counts_officially,
                    significant, evidence_json, rule_key, status, created_at
                ) VALUES (?, ?, 'occurred', 'confirmed_structured', 1, 0, ?, ?, 'system', ?)
                """,
                (
                    incident_id,
                    category,
                    json.dumps([{"kind": "agency_code", "source": mention["code"], "text": mention["evidence"]}]),
                    f"code:{mention['code']}",
                    stamp,
                ),
            )


def reevaluate_classifications(session) -> int:
    session.require("classify")
    rules = load_rules(session.conn)
    codes = load_codes(session.conn)
    changed = 0
    incident_ids = [
        row["id"] for row in session.conn.execute("SELECT id FROM incidents WHERE excluded = 0")
    ]
    with transaction(session.conn):
        for incident_id in incident_ids:
            manual = {
                row["category"]
                for row in session.conn.execute(
                    """
                    SELECT category FROM classifications
                    WHERE incident_id = ? AND status != 'system'
                    """,
                    (incident_id,),
                )
            }
            session.conn.execute(
                "DELETE FROM classifications WHERE incident_id = ? AND status = 'system'",
                (incident_id,),
            )
            session.conn.execute("DELETE FROM code_mentions WHERE incident_id = ?", (incident_id,))
            before = session.conn.execute(
                "SELECT COUNT(*) AS n FROM classifications WHERE incident_id = ?",
                (incident_id,),
            ).fetchone()["n"]
            record = classifiable_from_incident(session.conn, incident_id)
            proposals = [
                proposal
                for proposal in classify(record, rules)
                if proposal.category not in manual
            ]
            for proposal in proposals:
                _insert_proposal(session.conn, incident_id, proposal, session.stamp())
            for mention in scan_codes(record.call_type, record.narratives, codes):
                session.conn.execute(
                    """
                    INSERT INTO code_mentions(incident_id, code, evidence, status)
                    VALUES (?, ?, ?, ?)
                    """,
                    (incident_id, mention["code"], mention["evidence"], mention["status"]),
                )
            after = session.conn.execute(
                "SELECT COUNT(*) AS n FROM classifications WHERE incident_id = ?",
                (incident_id,),
            ).fetchone()["n"]
            if after != before:
                changed += 1
        session.audit("reevaluate_classifications", detail=f"incidents={len(incident_ids)}")
    return changed


def accept_classification(session, classification_id: int, reason: str) -> None:
    session.require("classify")
    if not reason or not reason.strip():
        raise ValidationError("A reason is required.")
    row = session.conn.execute(
        "SELECT * FROM classifications WHERE id = ?",
        (classification_id,),
    ).fetchone()
    if row is None:
        raise ValidationError("That classification does not exist.")
    if row["polarity"] != "occurred":
        raise ValidationError(
            "Only an occurred reading can be accepted into official counts. "
            "A negated, historical, alleged, precautionary, or contradictory reading stays non-counting."
        )
    with transaction(session.conn):
        session.conn.execute(
            """
            INSERT INTO classification_history(
                classification_id, old_status, new_status, old_category, new_category,
                changed_by, changed_at, reason
            ) VALUES (?, ?, 'accepted', ?, ?, ?, ?, ?)
            """,
            (
                row["id"],
                row["status"],
                row["category"],
                row["category"],
                session.user["id"],
                session.stamp(),
                reason.strip(),
            ),
        )
        session.conn.execute(
            """
            UPDATE classifications
            SET status = 'accepted', counts_officially = 1, confidence = 'user_accepted',
                significant = CASE WHEN significant = 1 OR rule_key IN (
                    SELECT rule_key FROM classification_rules WHERE category = classifications.category
                ) THEN significant ELSE significant END,
                reviewed_by = ?, reviewed_at = ?
            WHERE id = ?
            """,
            (session.user["id"], session.stamp(), row["id"]),
        )
        session.audit("accept_classification", entity_type="classification", entity_id=row["id"])


def reject_classification(session, classification_id: int, reason: str) -> None:
    session.require("classify")
    if not reason or not reason.strip():
        raise ValidationError("A reason is required.")
    row = session.conn.execute(
        "SELECT * FROM classifications WHERE id = ?",
        (classification_id,),
    ).fetchone()
    if row is None:
        raise ValidationError("That classification does not exist.")
    with transaction(session.conn):
        session.conn.execute(
            """
            INSERT INTO classification_history(
                classification_id, old_status, new_status, old_category, new_category,
                changed_by, changed_at, reason
            ) VALUES (?, ?, 'rejected', ?, ?, ?, ?, ?)
            """,
            (
                row["id"],
                row["status"],
                row["category"],
                row["category"],
                session.user["id"],
                session.stamp(),
                reason.strip(),
            ),
        )
        session.conn.execute(
            """
            UPDATE classifications
            SET status = 'rejected', counts_officially = 0, reviewed_by = ?, reviewed_at = ?
            WHERE id = ?
            """,
            (session.user["id"], session.stamp(), row["id"]),
        )
        session.audit("reject_classification", entity_type="classification", entity_id=row["id"])


def add_manual_classification(session, incident_id: int, category: str, reason: str) -> int:
    session.require("classify")
    if category not in CATEGORY_LABELS:
        raise ValidationError("Unknown category.")
    if not reason or not reason.strip():
        raise ValidationError("A reason is required.")
    incident = session.conn.execute("SELECT id FROM incidents WHERE id = ?", (incident_id,)).fetchone()
    if incident is None:
        raise ValidationError("That incident does not exist.")
    significant = 1 if _is_significant(category) else 0
    with transaction(session.conn):
        cursor = session.conn.execute(
            """
            INSERT INTO classifications(
                incident_id, category, polarity, confidence, counts_officially, significant,
                evidence_json, rule_key, status, created_at, reviewed_by, reviewed_at
            ) VALUES (?, ?, 'occurred', 'user_accepted', 1, ?, ?, 'manual', 'corrected', ?, ?, ?)
            """,
            (
                incident_id,
                category,
                significant,
                json.dumps([{"kind": "user", "source": "manual", "text": "Entered by an authorized user."}]),
                session.stamp(),
                session.user["id"],
                session.stamp(),
            ),
        )
        session.conn.execute(
            """
            INSERT INTO classification_history(
                classification_id, old_status, new_status, old_category, new_category,
                changed_by, changed_at, reason
            ) VALUES (?, NULL, 'corrected', NULL, ?, ?, ?, ?)
            """,
            (cursor.lastrowid, category, session.user["id"], session.stamp(), reason.strip()),
        )
        session.audit("manual_classification", entity_type="incident", entity_id=incident_id, detail=category)
    return int(cursor.lastrowid)


def confirm_rule(session, rule_key: str) -> None:
    session.require("configure")
    row = session.conn.execute(
        "SELECT id FROM classification_rules WHERE rule_key = ?",
        (rule_key,),
    ).fetchone()
    if row is None:
        raise ValidationError("Unknown classification rule.")
    session.conn.execute(
        """
        UPDATE classification_rules
        SET confirmation = 'agency_confirmed', confirmed_by = ?, confirmed_at = ?, updated_at = ?
        WHERE rule_key = ?
        """,
        (session.user["id"], session.stamp(), session.stamp(), rule_key),
    )
    session.audit("confirm_rule", entity_type="rule", entity_id=rule_key)


def confirm_code(session, code: str, definition: str, match_json: dict | None = None) -> None:
    session.require("configure")
    if not definition or not definition.strip():
        raise ValidationError("Enter the official definition. The application will not invent one.")
    match_json = validate_match_rules(code, match_json)
    if match_json and match_json.get("category") and match_json["category"] not in CATEGORY_LABELS:
        raise ValidationError("That category key is not defined.")
    session.conn.execute(
        """
        UPDATE agency_codes
        SET definition = ?, status = 'confirmed', match_json = ?, confirmed_by = ?, confirmed_at = ?
        WHERE code = ?
        """,
        (
            definition.strip(),
            None if not match_json else json.dumps(match_json),
            session.user["id"],
            session.stamp(),
            code,
        ),
    )
    if session.conn.execute("SELECT changes()").fetchone()[0] == 0:
        raise ValidationError("Unknown agency code.")
    session.audit("confirm_code", entity_type="agency_code", entity_id=code)


def _insert_proposal(conn, incident_id: int, proposal, stamp: str) -> None:
    conn.execute(
        """
        INSERT INTO classifications(
            incident_id, category, polarity, confidence, counts_officially, significant,
            evidence_json, rule_key, status, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'system', ?)
        """,
        (
            incident_id,
            proposal.category,
            proposal.polarity,
            proposal.confidence,
            1 if proposal.counts_officially else 0,
            1 if proposal.significant else 0,
            json.dumps(proposal.evidence),
            proposal.rule_key,
            stamp,
        ),
    )


def _is_significant(category: str) -> bool:
    significant = {
        "firearm_related_call",
        "firearm_possession_or_recovery",
        "knife_related_call",
        "officer_injury",
        "oji",
        "officer_assault",
        "in_custody_injury",
        "prisoner_transport",
        "vehicle_pursuit",
        "foot_pursuit",
        "use_of_force",
        "warrant_service",
        "arrest_on_warrant",
        "missing_person",
        "missing_juvenile",
        "found_person",
        "dog_bite",
        "animal_attack",
        "city_vehicle_damage",
        "city_property_damage",
        "traffic_camera_damage",
        "critical_incident",
        "mutual_aid",
        "major_disturbance",
        "public_safety_threat",
    }
    return category in significant
