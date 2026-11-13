"""Classification behavior that must not turn keywords into events."""

from wpd_compstat.classification.codes import scan_codes, validate_match_rules
from wpd_compstat.classification.engine import Classifiable, classify
from wpd_compstat.classification.taxonomy import RULES
from wpd_compstat.errors import ValidationError


def _rules(confirmed: set[str] | None = None) -> list[dict]:
    confirmed = confirmed or set()
    copied = []
    for rule in RULES:
        item = dict(rule)
        item["confirmation"] = "agency_confirmed" if rule["rule_key"] in confirmed else "starter_unconfirmed"
        copied.append(item)
    return copied


def _categories(record: Classifiable, **kwargs):
    return classify(record, _rules(**kwargs))


def test_no_firearm_located_is_not_a_recovery():
    proposals = _categories(
        Classifiable(call_type="CHECK WELLBEING", narratives=["Area checked. No firearm located."]),
        confirmed={"firearm_possession_or_recovery"},
    )
    recoveries = [
        item for item in proposals
        if item.category == "firearm_possession_or_recovery" and item.counts_officially
    ]
    assert recoveries == []


def test_forced_entry_is_not_use_of_force():
    proposals = _categories(
        Classifiable(narratives=["Officers made a forced entry at the front door."]),
        confirmed={"use_of_force"},
    )
    assert not any(item.category == "use_of_force" for item in proposals)


def test_bare_burglary_discussion_does_not_count():
    proposals = _categories(
        Classifiable(narratives=["The briefing discussed burglary trends."]),
        confirmed={"burglary"},
    )
    assert not any(item.category == "burglary" and item.counts_officially for item in proposals)


def test_arrested_for_burglary_counts_only_after_confirmation():
    text = "The suspect was arrested for burglary."
    unconfirmed = _categories(Classifiable(narratives=[text]))
    assert not any(item.category == "burglary" and item.counts_officially for item in unconfirmed)
    confirmed = _categories(Classifiable(narratives=[text]), confirmed={"burglary"})
    assert any(item.category == "burglary" and item.counts_officially and item.polarity == "occurred" for item in confirmed)


def test_historical_and_alleged_events_do_not_count():
    historical = _categories(
        Classifiable(narratives=["Last year he was arrested for burglary."]),
        confirmed={"burglary"},
    )
    alleged = _categories(
        Classifiable(narratives=["The caller alleges an assault occurred."]),
        confirmed={"assault"},
    )
    assert not any(item.counts_officially for item in historical if item.category == "burglary")
    assert not any(item.counts_officially for item in alleged if item.category == "assault")


def test_injury_call_type_contradicted_by_narrative_does_not_count():
    proposals = _categories(
        Classifiable(
            call_type="ACCIDENT WITH INJURY",
            narratives=["Property damage only. No injury reported."],
        ),
        confirmed={"injury_accident", "motor_vehicle_accident"},
    )
    injury = [item for item in proposals if item.category == "injury_accident"]
    assert injury and all(not item.counts_officially for item in injury)


def test_shoplifting_suppresses_larceny_double_count():
    proposals = _categories(
        Classifiable(
            call_type="SHOPLIFTING",
            narratives=["The person shoplifted merchandise during a larceny."],
        ),
        confirmed={"shoplifting", "larceny"},
    )
    assert any(item.category == "shoplifting" and item.counts_officially for item in proposals)
    assert not any(item.category == "larceny" and item.polarity == "occurred" for item in proposals)


def test_repeat_offender_is_never_automatic():
    proposals = _categories(
        Classifiable(narratives=["This is a repeat offender from prior contacts."]),
        confirmed=set(rule["rule_key"] for rule in RULES),
    )
    assert not any(item.category == "repeat_offender_related" for item in proposals)


def test_oji_token_does_not_expand_the_acronym():
    expanded = _categories(Classifiable(narratives=["The officer described an on-the-job injury."]))
    token = _categories(Classifiable(call_type="OJI"))
    assert not any(item.category == "oji" for item in expanded)
    assert any(item.category == "oji" and not item.counts_officially for item in token)


def test_agency_codes_do_not_become_categories():
    mentions = scan_codes(
        "CHECK WELLBEING",
        ["Unit noted 1500G in the remarks. Arrival was 02:00."],
        [{"code": code, "status": "unconfirmed", "match_json": {}} for code in ("1500G", "1500K", "0200", "02", "KCMH")],
    )
    assert {item["code"] for item in mentions} == {"1500G"}
    assert all(item["category"] is None for item in mentions)


def test_short_code_matches_only_the_whole_call_type():
    mentions = scan_codes(
        "02",
        ["See 02 in the narrative and 0200 hours."],
        [{"code": "02", "status": "unconfirmed", "match_json": {}}],
    )
    assert [item["code"] for item in mentions] == ["02"]
    try:
        validate_match_rules("02", {"scan_narrative": True})
        raise AssertionError("Short-code narrative scanning should be refused.")
    except ValidationError:
        pass


def test_citation_flag_is_not_inferred_from_the_word_citation():
    proposals = classify(
        Classifiable(narratives=["The officer issued a citation."], citation_numbers=["C-100"]),
        _rules(),
    )
    assert any(item.category == "citation_reference" and item.counts_officially for item in proposals)
    assert not any(item.category == "verified_traffic_violation" and item.counts_officially for item in proposals)
