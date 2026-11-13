"""Administrator configuration that changes how official counts are produced."""

from __future__ import annotations

import json

from wpd_compstat.db.seed import set_setting
from wpd_compstat.errors import ValidationError
from wpd_compstat.import_engine.profile import validate_profile


def confirm_profile(session, profile_id: str) -> None:
    session.require("configure")
    row = session.conn.execute("SELECT * FROM cad_profiles WHERE id = ?", (profile_id,)).fetchone()
    if row is None:
        raise ValidationError("That CAD profile does not exist.")
    validate_profile(json.loads(row["definition_json"]))
    session.conn.execute(
        """
        UPDATE cad_profiles
        SET confirmation = 'agency_confirmed', confirmed_by = ?, confirmed_at = ?, updated_at = ?
        WHERE id = ?
        """,
        (session.user["id"], session.stamp(), session.stamp(), profile_id),
    )
    set_setting(session.conn, "active_profile_id", profile_id, session.stamp(), session.user["id"])
    session.audit("confirm_profile", entity_type="profile", entity_id=profile_id)


def confirm_source_lists(session, officer_sources: list[str], citizen_sources: list[str]) -> None:
    session.require("configure")
    officer = {item.strip().casefold() for item in officer_sources if item.strip()}
    citizen = {item.strip().casefold() for item in citizen_sources if item.strip()}
    if not officer or not citizen:
        raise ValidationError("Both source lists need at least one value.")
    if officer & citizen:
        raise ValidationError("A call source cannot be both officer-initiated and citizen-generated.")
    set_setting(session.conn, "officer_initiated_sources", sorted(officer), session.stamp(), session.user["id"])
    set_setting(session.conn, "citizen_sources", sorted(citizen), session.stamp(), session.user["id"])
    set_setting(session.conn, "source_lists_confirmed", True, session.stamp(), session.user["id"])
    session.audit("confirm_source_lists")


def confirm_shifts(session, shifts: list[dict]) -> None:
    session.require("configure")
    if not shifts:
        raise ValidationError("Enter at least one shift.")
    for shift in shifts:
        if "name" not in shift or "start" not in shift or "end" not in shift:
            raise ValidationError("Each shift needs a name, start, and end.")
    set_setting(session.conn, "shifts", shifts, session.stamp(), session.user["id"])
    set_setting(session.conn, "shifts_confirmed", True, session.stamp(), session.user["id"])
    session.audit("confirm_shifts")


def confirm_division(session, division_id: int) -> None:
    session.require("configure")
    session.conn.execute(
        "UPDATE divisions SET confirmed = 1 WHERE id = ?",
        (division_id,),
    )
    session.audit("confirm_division", entity_type="division", entity_id=division_id)
