"""Official IMC call-reason codes are stored and looked up by call-type name."""

from wpd_compstat.classification.call_reasons import CALL_REASONS, official_code


def test_list_has_222_unique_codes_and_names():
    assert len(CALL_REASONS) == 222
    assert len({code for code, _name in CALL_REASONS}) == 222
    assert len({name.casefold() for _code, name in CALL_REASONS}) == 222


def test_lookup_ignores_case_spacing_and_known_keying_slips_only():
    assert official_code("ROBBERY IN PROGRESS") == "ROBP"
    assert official_code(" mv acc,  no injury in prog") == "NIAP"
    assert official_code("SUSPICIOUS ACTIVITY IN PROGRES") == "SUSP"
    assert official_code("FOLLOW-UP INVESTIGATIONQ") == "FU"
    assert official_code("CVSCHECK CONDITION") is None
    assert official_code("ROBBERY NOW") is None


def test_codes_are_seeded_and_shown_on_the_incident(session):
    conn = session.conn
    assert conn.execute("SELECT COUNT(*) AS n FROM call_reasons").fetchone()["n"] == 222
    cursor = conn.execute(
        "INSERT INTO incidents(cad_number, event_date, call_type, match_key, created_at, updated_at) VALUES ('26-1', '2026-01-05', 'Sex Assault', 'k', 'now', 'now')"
    )
    from wpd_compstat.search import incident_detail

    assert incident_detail(session, cursor.lastrowid)["call_reason_code"] == "SEX"
