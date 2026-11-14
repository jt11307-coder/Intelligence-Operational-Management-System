"""Warwick CAD call-log layout. Every name, number, and address here is invented."""

from __future__ import annotations

import json

import pytest

from tests.conftest import write_pdf
from wpd_compstat.admin import confirm_profile
from wpd_compstat.import_engine.call_log import CALL_LOG_PROFILE, count_call_starts, is_call_log, parse_call_log
from wpd_compstat.import_engine.parser import parse_pages
from wpd_compstat.import_engine.pipeline import stage_commit, stage_extract, stage_select, stage_validate


def _header(page: int, title: str = "Selective Search", start: str = "01/05/2026", end: str = "01/06/2026") -> str:
    return (
        " \n"
        "Warwick Police Department \n"
        f"Page: {page:>3}\n"
        f"  {title}  From: {start}  Thru: {end}     0000 - 2359    Printed: 01/07/2026\n"
    )


DAY_ONE = (
    "For Date: 01/05/2026  -  Monday   \n"
    "Call  Number \n Time \n Call  Reason \n Action \n Priority  \n"
    "26-900001       0012 \n"
    "Initiated - TRAFFIC STOP \n"
    "Warning Issued \n"
    "3  \n"
    " \n"
    "        Call Taker:    TCLERK - Civilian Test Clerk\n"
    "       Call Source:    Initiated\n"
    "  Location/Address:    [999 1] EXAMPLE MARKET - 100 SAMPLE AVE\n"
    "                ID:    OALPHA - Officer Test Alpha\n"
    "                                                     Arvd-00:12:00  Clrd-00:20:30\n"
    "                ID:    OBRAVO - Officer Test Bravo\n"
    "                       Disp-00:13:10                 Arvd-00:15:40  Clrd-00:19:00\n"
    "   Location Change:    EXAMPLE PLAZA - 200 SAMPLE AVE [Modified: 01/05/2026\n"
    "0014]\n"
    "           Vehicle:    BLU 2020 MAKE 4D MODEL  Reg: PC RI ZZ0001  VIN: TESTVIN0000000001\n"
    "          Operator:    EXAMPLE, ALEX Q @ 1 FICTION ST - NOWHERE, RI 00000\n"
    "                       SSN: 000000001  DOB: 01/01/1990  Race: U  Sex: U    \n"
    " Refer To Citation:     26-1-CN\n"
    "             Owner:    EXAMPLE, ALEX Q @ 1 FICTION ST - NOWHERE, RI\n"
    "000000001\n"
    "                       Race: U  Sex: U    \n"
    "      Insurance Co:                               \n"
    "         Policy No:                          \n"
    "         Narrative:     01/05/2026 0013 Civilian Test Clerk\n"
    "STOPPED NEAR THE MARKET\n"
    "         Narrative:     01/05/2026 0020 Officer Test Alpha\n"
    "No firearm located. Warning given.\n"
)

DAY_ONE_PAGE_TWO = (
    "26-900002       0105 \n"
    "911 - DISTURBANCE \n"
    "Report Issued \n"
    "2  \n"
    " \n"
    "        Call Taker:    TCLERK - Civilian Test Clerk\n"
    "       Call Source:    911\n"
    "    Call Closed By:    TCLERK - Civilian Test Clerk 01/05/2026 0230\n"
    "  Location/Address:    10 PRETEND RD @ 20 IMAGINARY WAY\n"
    "Calling/Inv. Party:    SAMPLE, PAT @ 3 FICTION ST - NOWHERE, RI 000-000-0000\n"
    "                       SSN: 000000002  DOB: 02/02/1980  Race: U  Sex: U\n"
    "                ID:    OALPHA - Officer Test Alpha\n"
    "                       Disp-01:06:00                 Arvd-01:10:00  Clrd-02:00:00\n"
    "                       OCHARL - Sergeant Test Charlie\n"
    "         Narrative:     01/05/2026 0106 Civilian Test Clerk\n"
    "CALLER REPORTS LOUD ARGUMENT\n"
)

DAY_ONE_PAGE_THREE = (
    "THIS LINE CONTINUES THE NARRATIVE ACROSS THE PAGE BREAK\n"
    "    Location: NOT A FIELD, PART OF THE NARRATIVE\n"
    "       Refer To Incident:     26-10-OF\n"
    "         Refer To Arrest:     26-11-AR\n"
    "            Arrest:    SAMPLE, PAT       \n"
    "           Address:    3 FICTION ST   NOWHERE, RI\n"
    "               Age:    46       SSN: 000000002    \n"
    "           Charges:    TEST CHARGE ONE\n"
    "                       TEST CHARGE TWO\n"
    "26-900003       2350 \n"
    "Phone - DISTURB PEACE \n"
    "Merge: 26-900002 By: TCLERK 3\n"
    "        Call Taker:    TCLERK - Civilian Test Clerk\n"
    "       Call Source:    Telephone\n"
    "  Location/Address:    10 PRETEND RD\n"
    "For Date: 01/06/2026  -  Tuesday   \n"
    "Call  Number \n Time \n Call  Reason \n Action \n Priority  \n"
    "26-900004       0001 \n"
    "Walk-In - INFORMATION \n"
    "Services Rendered 3  \n"
    " \n"
    "        Call Taker:    TCLERK - Civilian Test Clerk\n"
    "       Call Source:    Walk-In\n"
    "       Vicinity of:    ROUTE 0 EAST HWY\n"
    "         Narrative:     01/06/2026 0002 Civilian Test Clerk\n"
    "10-49 4516\n"
    "REF CODE 1500G MENTIONED\n"
)


def _pages() -> list[tuple[int, str]]:
    return [
        (1, _header(1) + DAY_ONE),
        (2, _header(2) + DAY_ONE_PAGE_TWO),
        (3, _header(3) + DAY_ONE_PAGE_THREE),
    ]


def _by_cad(output) -> dict:
    return {incident.cad_number: incident for incident in output.incidents}


def test_call_log_layout_is_recognized_and_counted():
    pages = _pages()
    assert is_call_log(pages)
    output = parse_call_log(pages, CALL_LOG_PROFILE)
    assert output.recognized
    assert output.errors == []
    assert len(output.incidents) == count_call_starts(pages) == 4
    assert (output.declared_start, output.declared_end) == ("2026-01-05", "2026-01-06")
    assert parse_pages(pages, CALL_LOG_PROFILE).incidents[0].cad_number == "26-900001"


def test_header_fields_officers_and_times():
    stop = _by_cad(parse_call_log(_pages(), CALL_LOG_PROFILE))["26-900001"]
    assert stop.event_date == "2026-01-05"
    assert stop.event_time == "00:12:00"
    assert stop.call_type == "TRAFFIC STOP"
    assert stop.disposition == "Warning Issued"
    assert stop.priority == "3"
    assert stop.call_source == "Initiated"
    assert stop.business == "EXAMPLE MARKET"
    assert stop.location == "100 SAMPLE AVE"
    assert [(item.name, item.role) for item in stop.officers] == [
        ("OALPHA - Officer Test Alpha", "primary"),
        ("OBRAVO - Officer Test Bravo", "assisting"),
    ]
    assert stop.dispatch_time == "00:13:10"
    assert stop.arrival_time == "00:12:00"
    assert stop.clear_time == "00:19:00"
    assert [item.number for item in stop.citations] == ["26-1-CN"]
    assert not stop.citations[0].verified and not stop.citations[0].warning
    assert stop.vehicles[0].state == "RI"
    assert stop.vehicles[0].plate == "ZZ0001 VIN TESTVIN0000000001"
    assert not stop.low_confidence


def test_wrapped_location_change_and_narratives_are_kept_whole():
    stop = _by_cad(parse_call_log(_pages(), CALL_LOG_PROFILE))["26-900001"]
    bodies = [item.body for item in stop.narratives]
    assert bodies[0] == "Location Change: EXAMPLE PLAZA - 200 SAMPLE AVE [Modified: 01/05/2026 0014]"
    assert stop.narratives[0].time_text == "01/05/2026 0014"
    assert bodies[1:] == ["STOPPED NEAR THE MARKET", "No firearm located. Warning given."]
    assert stop.narratives[2].author == "Officer Test Alpha"
    assert stop.narratives[2].time_text == "01/05/2026 0020"


def test_person_details_stay_in_person_payloads_and_out_of_narratives():
    output = parse_call_log(_pages(), CALL_LOG_PROFILE)
    stop = _by_cad(output)["26-900001"]
    operator, owner = stop.persons
    assert operator.role == "operator" and operator.payload["ssn"] == "000000001"
    assert owner.role == "owner" and owner.payload["continued"] == "000000001"
    for incident in output.incidents:
        for narrative in incident.narratives:
            assert "000000001" not in narrative.body and "000000002" not in narrative.body
            assert "FICTION ST" not in narrative.body


def test_multi_page_call_with_arrest_block_and_column_zero_label():
    disturbance = _by_cad(parse_call_log(_pages(), CALL_LOG_PROFILE))["26-900002"]
    assert disturbance.source_page == 2
    assert disturbance.intersection == "10 PRETEND RD @ 20 IMAGINARY WAY"
    assert disturbance.clear_time == "02:30:00"
    assert [item.name for item in disturbance.officers] == [
        "OALPHA - Officer Test Alpha",
        "OCHARL - Sergeant Test Charlie",
    ]
    narrative = disturbance.narratives[0]
    assert narrative.body.splitlines() == [
        "CALLER REPORTS LOUD ARGUMENT",
        "THIS LINE CONTINUES THE NARRATIVE ACROSS THE PAGE BREAK",
        "    Location: NOT A FIELD, PART OF THE NARRATIVE",
    ]
    assert [(item.ref_type, item.ref_number) for item in disturbance.reports] == [
        ("offense", "26-10-OF"),
        ("arrest", "26-11-AR"),
    ]
    roles = [person.role for person in disturbance.persons]
    assert roles == ["calling_involved_party", "arrestee"]
    arrestee = disturbance.persons[1].payload
    assert arrestee["age"] == "46"
    assert arrestee["charges"] == "TEST CHARGE ONE; TEST CHARGE TWO"


def test_merged_call_keeps_reference_without_inventing_a_disposition():
    merged = _by_cad(parse_call_log(_pages(), CALL_LOG_PROFILE))["26-900003"]
    assert merged.disposition is None
    assert merged.priority == "3"
    assert [(item.ref_type, item.ref_number) for item in merged.reports] == [("merged_with", "26-900002")]


def test_new_day_and_narrative_text_that_looks_like_a_call_number():
    output = parse_call_log(_pages(), CALL_LOG_PROFILE)
    walk_in = _by_cad(output)["26-900004"]
    assert walk_in.event_date == "2026-01-06"
    assert walk_in.location == "ROUTE 0 EAST HWY"
    assert walk_in.narratives[0].body == "10-49 4516\nREF CODE 1500G MENTIONED"
    assert len(output.incidents) == 4


def test_other_documents_are_not_guessed():
    output = parse_call_log([(1, "Warwick Police Department\nSome other report\n26-1  0001\nA - B\n")], CALL_LOG_PROFILE)
    assert not output.recognized and output.incidents == []
    assert parse_call_log([], CALL_LOG_PROFILE).recognized is False


def test_dispatch_log_title_is_the_same_layout():
    pages = [(1, _header(1, title="Dispatch Log") + DAY_ONE)]
    output = parse_call_log(pages, CALL_LOG_PROFILE)
    assert output.recognized and len(output.incidents) == 1


def _write(path, pages):
    write_pdf(path, [text for _number, text in pages])


def test_profile_is_seeded_unconfirmed_and_imports_nothing_until_confirmed(session, tmp_path):
    row = session.conn.execute("SELECT confirmation FROM cad_profiles WHERE id = ?", (CALL_LOG_PROFILE["id"],)).fetchone()
    assert row["confirmation"] == "unconfirmed"
    path = tmp_path / "synthetic-call-log.pdf"
    _write(path, _pages())
    batch = stage_select(session, [path])
    stage_extract(session, batch)
    stage_validate(session, batch)
    assert stage_commit(session, batch)["new_incidents"] == 0


@pytest.fixture
def call_log_session(session):
    confirm_profile(session, CALL_LOG_PROFILE["id"])
    return session


def _import(session, path):
    batch = stage_select(session, [path])
    stage_extract(session, batch)
    stage_validate(session, batch)
    return stage_commit(session, batch)


def test_pipeline_reconciles_and_dedupes_overlapping_call_logs(call_log_session, tmp_path):
    first = tmp_path / "first.pdf"
    _write(first, _pages())
    summary = _import(call_log_session, first)
    assert summary["new_incidents"] == 4
    assert summary["files"][0]["call_lines"] == summary["files"][0]["extracted"] == 4
    conn = call_log_session.conn
    persons = conn.execute("SELECT payload_enc FROM sensitive_persons").fetchall()
    assert persons and all("000000001" not in row["payload_enc"] for row in persons)
    assert conn.execute("SELECT COUNT(*) AS n FROM narratives WHERE body LIKE '%000000001%'").fetchone()["n"] == 0
    overlap = tmp_path / "overlap.pdf"
    later = DAY_ONE + "         Narrative:     01/05/2026 0300 Officer Test Alpha\nSUPPLEMENT ADDED LATER\n"
    _write(overlap, [(1, _header(1, start="01/05/2026", end="01/05/2026") + later)])
    second = _import(call_log_session, overlap)
    assert second["new_incidents"] == 0
    assert second["existing_updated"] == 1
    assert second["final_incident_count"] == 4
    again = _import(call_log_session, first)
    assert again["new_incidents"] == 0 and again["duplicates_skipped"] == 4
    files = json.loads(
        conn.execute("SELECT summary_json FROM import_batches ORDER BY id DESC LIMIT 1").fetchone()["summary_json"]
    )["files"]
    assert files[0]["duplicates_skipped"] == 4


def test_long_import_stages_count_as_session_activity(call_log_session, tmp_path, monkeypatch):
    from datetime import timedelta

    from wpd_compstat.import_engine import pipeline

    clock = [call_log_session.now()]
    monkeypatch.setattr(call_log_session, "now", lambda: clock[0])
    real_parse = pipeline.parse_pages

    def slow_parse(pages, profile):
        clock[0] += timedelta(minutes=10)
        return real_parse(pages, profile)

    monkeypatch.setattr(pipeline, "parse_pages", slow_parse)
    first, second = tmp_path / "first.pdf", tmp_path / "second.pdf"
    _write(first, _pages())
    _write(second, [(1, _header(1, start="01/05/2026", end="01/05/2026") + DAY_ONE)])
    batch = stage_select(call_log_session, [first, second])
    stage_extract(call_log_session, batch)
    stage_validate(call_log_session, batch)
    assert stage_commit(call_log_session, batch)["new_incidents"] == 4
