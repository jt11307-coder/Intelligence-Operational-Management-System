"""Classification behavior that must not turn keywords into events."""

import re

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


def test_overdose_mental_health_and_neighbor_phrases_are_recognized():
    overdose = _categories(Classifiable(call_type="DRUG OVERDOSE"), confirmed={"overdose"})
    negated = _categories(
        Classifiable(call_type="OVERDOSE", narratives=["Not an overdose. The person was awake."]),
        confirmed={"overdose"},
    )
    mental = _categories(Classifiable(call_type="MENTAL HEALTH"), confirmed={"mental_health"})
    neighbor = _categories(Classifiable(call_type="NEIGHBOR DISPUTE"), confirmed={"neighbor_dispute"})
    assert any(item.category == "overdose" and item.counts_officially for item in overdose)
    assert not any(item.category == "overdose" and item.counts_officially for item in negated)
    assert any(item.category == "mental_health" and item.counts_officially for item in mental)
    assert any(item.category == "neighbor_dispute" and item.counts_officially for item in neighbor)


def test_citation_flag_is_not_inferred_from_the_word_citation():
    proposals = classify(
        Classifiable(narratives=["The officer issued a citation."], citation_numbers=["C-100"]),
        _rules(),
    )
    assert any(item.category == "citation_reference" and item.counts_officially for item in proposals)
    assert not any(item.category == "verified_traffic_violation" and item.counts_officially for item in proposals)


SEX_CODE = [{"code": "0200", "status": "confirmed", "match_json": {"category": "sexual_assault", "scan_narrative": True}}]


def _official(proposals, category):
    return [item for item in proposals if item.category == category and item.counts_officially]


def test_sex_assault_call_type_is_sexual_assault_never_assault():
    proposals = _categories(Classifiable(call_type="Sex Assault"), confirmed={"assault", "sexual_assault"})
    assert _official(proposals, "sexual_assault")
    assert not any(item.category == "assault" for item in proposals)


def test_sexually_assaulted_in_a_narrative_is_not_assault():
    proposals = _categories(
        Classifiable(call_type="INFORMATION", narratives=["The victim stated she was sexually assaulted and the suspect assaulted her."]),
        confirmed={"assault", "sexual_assault"},
    )
    assert any(item.category == "sexual_assault" for item in proposals)
    assert not any(item.category == "assault" and item.polarity == "occurred" for item in proposals)


def test_confirmed_0200_code_counts_as_sexual_assault_and_suppresses_assault():
    proposals = classify(
        Classifiable(call_type="ASSAULT/PAST", narratives=["Unit advised this is a 0200."]),
        _rules({"assault", "sexual_assault"}),
        SEX_CODE,
    )
    assert _official(proposals, "sexual_assault")
    assert not _official(proposals, "assault")


def test_0200_as_a_time_is_not_the_code():
    for text in ("Arrived at 0200 and cleared.", "Patrol from 0200-0300.", "Checked the lot 0200 hrs."):
        assert scan_codes("INFORMATION", [text], SEX_CODE) == []


def test_no_injury_update_overrides_an_injury_dispatch_and_records_the_phrase():
    proposals = _categories(
        Classifiable(call_type="MV ACC, WITH INJURIES", narratives=["Both operators checked. No injuries, tow requested."]),
        confirmed={"injury_accident", "property_damage_accident"},
    )
    assert not _official(proposals, "injury_accident")
    damage = _official(proposals, "property_damage_accident")
    assert damage
    evidence = damage[0].evidence[0]
    assert evidence["kind"] == "narrative_override"
    assert evidence["phrase"].lower() == "no injur"
    assert evidence["dispatched_call_type"] == "MV ACC, WITH INJURIES"


def test_no_injury_with_a_hospital_transport_is_left_for_review():
    proposals = _categories(
        Classifiable(
            call_type="MV ACC, WITH INJURIES",
            narratives=["Driver one reported no injuries.", "Driver two transported by rescue."],
        ),
        confirmed={"injury_accident", "property_damage_accident"},
    )
    injury = [item for item in proposals if item.category == "injury_accident"]
    assert injury and not injury[0].counts_officially
    assert injury[0].evidence[1]["reason"] == "mixed_signals"
    assert not _official(proposals, "property_damage_accident")


def test_no_injury_reported_does_not_flip_a_no_injury_dispatch():
    proposals = _categories(
        Classifiable(call_type="MV ACC, NO INJURY", narratives=["No injury reported by either party."]),
        confirmed={"injury_accident", "property_damage_accident"},
    )
    assert _official(proposals, "property_damage_accident")
    assert not _official(proposals, "injury_accident")


def test_not_missing_update_overrides_a_missing_person_dispatch():
    proposals = _categories(
        Classifiable(call_type="MISSING PERSON", narratives=["Subject is not missing, staying with a relative."]),
        confirmed={"missing_person"},
    )
    missing = [item for item in proposals if item.category == "missing_person"]
    assert missing and missing[0].polarity == "contradictory" and not missing[0].counts_officially
    assert missing[0].evidence[1]["phrase"].lower() == "not missing"


def test_located_after_a_missing_report_is_left_for_review():
    proposals = _categories(
        Classifiable(call_type="MISSING PERSON", narratives=["Subject was located at a friend's house."]),
        confirmed={"missing_person"},
    )
    missing = [item for item in proposals if item.category == "missing_person"]
    assert missing and not missing[0].counts_officially
    assert missing[0].evidence[1]["reason"] == "possible_contradiction"


def test_approved_call_types_match_by_exact_name_only():
    def categories(call_type):
        return {item.category for item in classify(Classifiable(call_type=call_type), _rules())}

    assert "directed_traffic_enforcement" in categories("TRAFFIC ENFORCEMENT")
    assert "directed_traffic_enforcement" not in categories("Automated Traffic Enforcement")
    assert {"hit_and_run", "injury_accident"} <= categories("Mv Acc,  Leaving Scene Injuries ")
    assert "mental_health" in categories("psychological problem")
    assert "fraud" in categories("FORGERY")
    assert "disorderly_conduct" not in categories("DISTURB PEACE")


def test_assault_lookbehind_guard_keeps_the_pattern_single_word():
    from wpd_compstat.classification.engine import _multi_word
    from wpd_compstat.classification.taxonomy import RULES

    assault = next(rule for rule in RULES if rule["rule_key"] == "assault")
    assert not _multi_word(re.compile(assault["narrative_regex"][0]))
