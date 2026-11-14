"""Volume flags cover every category and call type. Repeats use a short same-type window."""

from wpd_compstat.analysis.patterns import detect_patterns, trend_categories
from wpd_compstat.classification.taxonomy import CATEGORY_LABELS
from wpd_compstat.constants import REPEAT_LOCATION_WINDOW_DAYS


def _incident(session, cad: str, day: str, call_type: str, address: str | None = None) -> int:
    location_id = None
    if address:
        cursor = session.conn.execute(
            "INSERT INTO locations(raw_address, normalized_address) VALUES (?, ?)",
            (address, address.upper()),
        )
        location_id = int(cursor.lastrowid)
    cursor = session.conn.execute(
        """
        INSERT INTO incidents(
            cad_number, event_date, call_type, location_id, match_key,
            created_at, updated_at, extraction_confidence, review_status
        ) VALUES (?, ?, ?, ?, ?, '2026-11-01T00:00:00+00:00', '2026-11-01T00:00:00+00:00', 1, 'unreviewed')
        """,
        (cad, day, call_type, location_id, f"{cad}|{day}"),
    )
    return int(cursor.lastrowid)


def _official(session, incident_id: int, category: str) -> None:
    session.conn.execute(
        """
        INSERT INTO classifications(
            incident_id, category, polarity, confidence, counts_officially, significant,
            evidence_json, status, created_at
        ) VALUES (?, ?, 'occurred', 'user_accepted', 1, 0, '{}', 'accepted', '2026-11-01T00:00:00+00:00')
        """,
        (incident_id, category),
    )


def _patterns(session):
    return session.conn.execute("SELECT pattern_type, name, date_start, date_end, explanation FROM patterns").fetchall()


def test_trend_categories_include_every_classifier_category(session):
    covered = set(trend_categories(session.conn))
    assert set(CATEGORY_LABELS) <= covered
    for category in (
        "overdose",
        "mental_health",
        "neighbor_dispute",
        "drug_offense",
        "assault",
        "robbery",
        "motor_vehicle_theft",
        "firearm_related_call",
        "injury_accident",
        "shoplifting",
    ):
        assert category in covered


def test_volume_flag_fires_for_a_category_outside_the_old_seven(session):
    _incident(session, "ANCHOR", "2026-11-01", "OTHER")
    for index, day in enumerate(("2026-11-01", "2026-11-02", "2026-11-03"), start=1):
        _official(session, _incident(session, f"BASE-{index}", day, "ROBBERY"), "robbery")
    for index, day in enumerate(
        ("2026-11-08", "2026-11-09", "2026-11-10", "2026-11-11", "2026-11-12", "2026-11-13"),
        start=1,
    ):
        _official(session, _incident(session, f"NOW-{index}", day, "ROBBERY"), "robbery")
    for index, day in enumerate(("2026-11-01", "2026-11-02", "2026-11-03", "2026-11-04"), start=1):
        _official(session, _incident(session, f"A-BASE-{index}", day, "ASSAULT"), "assault")
    for index, day in enumerate(
        ("2026-11-08", "2026-11-09", "2026-11-10", "2026-11-11", "2026-11-12", "2026-11-13"),
        start=1,
    ):
        _official(session, _incident(session, f"A-NOW-{index}", day, "ASSAULT"), "assault")

    detect_patterns(session, "2026-11-08", "2026-11-14")
    names = {row["name"] for row in _patterns(session) if row["pattern_type"] == "category_increase"}
    assert "Volume increase: Robbery" in names
    assert "Volume increase: Assault" not in names


def test_uploaded_call_type_flags_without_a_classification(session):
    _incident(session, "ANCHOR", "2026-11-01", "OTHER")
    for index, day in enumerate(("2026-11-08", "2026-11-09", "2026-11-10"), start=1):
        _incident(session, f"MH-{index}", day, "Mental Health" if index == 1 else "MENTAL HEALTH")
    detect_patterns(session, "2026-11-08", "2026-11-14")
    rows = [row for row in _patterns(session) if row["pattern_type"] == "call_type_increase"]
    assert len(rows) == 1
    assert rows[0]["name"] == "Volume increase: call type Mental Health"
    assert "not an official crime classification" in rows[0]["explanation"]


def test_same_call_type_repeats_inside_seven_days(session):
    address = "10 Main St"
    for index, day in enumerate(("2026-11-02", "2026-11-03", "2026-11-04"), start=1):
        _incident(session, f"REP-{index}", day, "MENTAL HEALTH", address)
    detect_patterns(session, "2026-11-01", "2026-11-14")
    rows = [row for row in _patterns(session) if row["pattern_type"] == "repeat_same_type"]
    assert len(rows) == 1
    assert rows[0]["date_start"] == "2026-11-02"
    assert rows[0]["date_end"] == "2026-11-04"
    assert "MENTAL HEALTH" in rows[0]["name"]
    assert str(REPEAT_LOCATION_WINDOW_DAYS) in rows[0]["explanation"]


def test_mixed_call_types_at_one_address_do_not_make_a_repeat(session):
    address = "20 Main St"
    for index, (day, call_type) in enumerate(
        (
            ("2026-11-02", "MENTAL HEALTH"),
            ("2026-11-03", "NEIGHBOR DISPUTE"),
            ("2026-11-04", "BURGLARY"),
        ),
        start=1,
    ):
        _incident(session, f"MIX-{index}", day, call_type, address)
    detect_patterns(session, "2026-11-01", "2026-11-14")
    assert [row for row in _patterns(session) if row["pattern_type"] == "repeat_same_type"] == []


def test_same_call_type_spread_past_the_window_does_not_flag(session):
    address = "30 Main St"
    for index, day in enumerate(("2026-11-01", "2026-11-06", "2026-11-12"), start=1):
        _incident(session, f"WIDE-{index}", day, "NEIGHBOR DISPUTE", address)
    detect_patterns(session, "2026-11-01", "2026-11-14")
    assert [row for row in _patterns(session) if row["pattern_type"] == "repeat_same_type"] == []
