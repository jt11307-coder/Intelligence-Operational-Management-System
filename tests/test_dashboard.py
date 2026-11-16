"""Dashboard figures: complete days only, equal-length comparisons, labelled unconfirmed categories, patterns."""

from datetime import date, timedelta

from wpd_compstat.analysis.compare import compare_calls, comparison_windows, effective_period
from wpd_compstat.analysis.dashboard import AWAITING, COUNTED, compstat_table, tiles, top_call_types
from wpd_compstat.analysis.trends import day_over_day_trends, repeat_address_flags, volume_flags

_counter = iter(range(1, 10**6))


def _incident(session, day: date, call_type: str = "LARCENY", time: str = "12:00", address: str | None = None) -> int:
    number = next(_counter)
    location_id = None
    if address:
        location_id = int(session.conn.execute(
            "INSERT INTO locations(raw_address, normalized_address) VALUES (?, ?)", (address, address.upper())
        ).lastrowid)
    return int(session.conn.execute(
        """
        INSERT INTO incidents(
            cad_number, event_date, event_time, call_type, location_id, match_key,
            created_at, updated_at, extraction_confidence, review_status
        ) VALUES (?, ?, ?, ?, ?, ?, '2026-11-01T00:00:00+00:00', '2026-11-01T00:00:00+00:00', 1, 'unreviewed')
        """,
        (f"SYN-{number}", day.isoformat(), time, call_type, location_id, f"SYN-{number}|{day}"),
    ).lastrowid)


def _classify(session, incident_id: int, category: str, official: bool) -> None:
    session.conn.execute(
        """
        INSERT INTO classifications(
            incident_id, category, polarity, confidence, counts_officially, significant, evidence_json, status, created_at
        ) VALUES (?, ?, 'occurred', ?, ?, 0, '{}', 'system', '2026-11-01T00:00:00+00:00')
        """,
        (incident_id, category, "confirmed_structured" if official else "probable_review", 1 if official else 0),
    )


def _days(first: date, last: date):
    day = first
    while day <= last:
        yield day
        day += timedelta(days=1)


def test_partial_last_day_is_left_out_and_comparisons_have_equal_length(session):
    for day in _days(date(2026, 8, 1), date(2026, 11, 15)):
        _incident(session, day, time="23:30")
    _incident(session, date(2026, 11, 16), time="00:41")
    period = effective_period(session.conn, date(2026, 11, 3), date(2026, 11, 16))
    assert period["end"] == date(2026, 11, 15) and period["days"] == 13
    assert "2026-11-16 is only partly imported" in period["note"]
    rows = compare_calls(session.conn, date(2026, 11, 3), date(2026, 11, 16))
    assert {row["current"] for row in rows} == {13}
    by_label = {row["label"]: row for row in rows}
    assert by_label["Previous period of equal length"]["baseline"] == 13
    assert by_label["Same days four weeks earlier"]["baseline"] == 13
    assert by_label["Average of the 4 previous equal periods"]["baseline"] == 13
    assert by_label["Equivalent prior-year period"]["baseline"] is None
    assert all(row["description"] for row in rows)
    for window in comparison_windows(date(2026, 11, 3), date(2026, 11, 15)):
        span = (window["end"] - window["start"]).days + 1
        assert span == 13 * window["periods"]


def test_unconfirmed_categories_are_labelled_not_zero_and_empty_tiles_are_hidden(session):
    for day in _days(date(2026, 10, 1), date(2026, 11, 15)):
        incident = _incident(session, day, "MV ACC, NO INJURY", time="23:30")
        _classify(session, incident, "property_damage_accident", official=False)
        _classify(session, incident, "arrest_report", official=True)
    result = tiles(session.conn, date(2026, 11, 2), date(2026, 11, 15))
    by_key = {tile["key"]: tile for tile in result["tiles"]}
    assert by_key["accidents"]["status"] == AWAITING and by_key["accidents"]["value"] == 14
    assert by_key["accidents"]["counted"] == 0 and by_key["accidents"]["previous"] == 14
    assert by_key["arrest_report"]["status"] == COUNTED and by_key["arrest_report"]["value"] == 14
    assert by_key["calls_for_service"]["value"] == 14 and by_key["calls_for_service"]["previous"] == 14
    assert all(tile["description"] for tile in result["tiles"])
    assert not {"priority_incidents", "officer_initiated", "citizen_generated", "verified_traffic_violation", "warning"} & set(by_key)


def test_compstat_table_flags_unusual_weeks_and_top_call_types_use_imc_names(session):
    for day in _days(date(2026, 9, 1), date(2026, 11, 15)):
        _incident(session, day, "LARCENY", time="23:30")
    for day in _days(date(2026, 11, 9), date(2026, 11, 15)):
        for _ in range(3):
            _incident(session, day, "LARCENY", time="23:30")
    table = compstat_table(session.conn, date(2026, 11, 15))
    calls = table["rows"][0]
    assert calls["label"] == "Calls for service"
    assert (calls["this_week"], calls["last_week"], calls["four_week_average"]) == (28, 7, 7.0)
    assert calls["change"] == 21 and calls["flag"] == "UP"
    assert calls["ytd"] == 76 + 21
    types = top_call_types(session.conn, date(2026, 11, 9), date(2026, 11, 15))
    assert types[0]["code"] == "LAR" and types[0]["name"] == "Larceny" and types[0]["on_imc_list"]
    assert (types[0]["count"], types[0]["previous"], types[0]["change"]) == (28, 7, 21)


def test_developing_patterns_find_emerging_volume_and_repeat_flags_without_addresses(session):
    for day in _days(date(2026, 10, 1), date(2026, 11, 15)):
        _incident(session, day, "DIRECTED PATROL", time="23:30")
    for count, day in zip((2, 4, 7), _days(date(2026, 11, 13), date(2026, 11, 15))):
        for _ in range(count):
            _incident(session, day, "FRAUD", time="10:00", address="12 Example St")
    emerging = day_over_day_trends(session.conn, date(2026, 11, 15))
    assert [item["key"] for item in emerging] == ["call|fraud"]
    assert emerging[0]["count"] == 13 and "rose three days in a row (2, 4, 7" in emerging[0]["sentence"]
    volume = volume_flags(session.conn, date(2026, 11, 9), date(2026, 11, 15))
    assert [item["key"] for item in volume] == ["call|fraud"]
    repeats = repeat_address_flags(session.conn, date(2026, 11, 9), date(2026, 11, 15))
    assert repeats[0]["key"] == "repeat|fraud" and repeats[0]["count"] == 1
    assert all("EXAMPLE" not in item["sentence"].upper() for item in emerging + volume + repeats)
