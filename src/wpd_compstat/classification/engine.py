"""Explainable incident classification.

Official counts require a confirmed rule or a later user acceptance. Negated,
historical, alleged, precautionary, and contradictory readings never count as
an event that occurred.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

AFFIRMATIVE = re.compile(
    r"\b(recovered|seized|arrested for|occurred|victim of|found a|in possession of|"
    r"committed|stole|stolen|shoplifted|robbed|assaulted|vandalized|burglarized|threatened|harassed)\b",
    re.IGNORECASE,
)
NEGATION = re.compile(
    r"\b(no|not|never|without|unable|cannot|can't|didn't|did not|unfounded)\b",
    re.IGNORECASE,
)
HISTORICAL = re.compile(
    r"\b(yesterday|last (?:night|week|month|year)|previously|prior to|historical|earlier this year|in 19\d\d|in 20\d\d)\b",
    re.IGNORECASE,
)
ALLEGATION = re.compile(
    r"\b(alleges|alleged|reports that|stated that|states that|claims|claimed|complainant states)\b",
    re.IGNORECASE,
)
PRECAUTION = re.compile(
    r"\b(checked for|precautionary|area checked|looked for|pat(?:ted)? down|frisk(?:ed)? for)\b",
    re.IGNORECASE,
)


@dataclass
class Proposal:
    category: str
    polarity: str
    confidence: str
    counts_officially: bool
    significant: bool
    evidence: list[dict] = field(default_factory=list)
    rule_key: str | None = None
    status: str = "system"

    def as_dict(self) -> dict:
        return {
            "category": self.category,
            "polarity": self.polarity,
            "confidence": self.confidence,
            "counts_officially": self.counts_officially,
            "significant": self.significant,
            "evidence": self.evidence,
            "rule_key": self.rule_key,
            "status": self.status,
        }


@dataclass
class Classifiable:
    call_type: str | None = None
    call_classification: str | None = None
    disposition: str | None = None
    final_disposition: str | None = None
    narratives: list[str] = field(default_factory=list)
    report_types: list[str] = field(default_factory=list)
    citation_numbers: list[str] = field(default_factory=list)
    citation_verified: bool = False
    citation_warning: bool = False
    officer_slots: int = 0
    follow_up: bool | None = None


def _sentences(text: str) -> list[str]:
    parts = re.split(r"[\n.!?]+", text)
    return [part.strip() for part in parts if part.strip()]


def _excerpt(text: str) -> str:
    compact = " ".join(text.split())
    return compact[:180]


def _phrase_in(text: str | None, phrase: str) -> bool:
    if not text or not phrase:
        return False
    pattern = r"(?<!\w)" + re.escape(phrase.casefold()) + r"(?!\w)"
    return re.search(pattern, text.casefold()) is not None


def _negated(sentence: str, start: int, end: int) -> bool:
    window = sentence[max(0, start - 80) : start]
    if NEGATION.search(window):
        return True
    if re.search(r"\bunfounded\b", sentence, re.IGNORECASE):
        return True
    after = sentence[end : end + 40]
    return re.search(r"^\s+(?:was\s+)?not\b", after, re.IGNORECASE) is not None


def _compile(patterns: list[str]) -> list[re.Pattern[str]]:
    compiled = []
    for pattern in patterns:
        flags = 0 if pattern.startswith(r"\bOJI\b") else re.IGNORECASE
        if pattern == r"\bOJI\b":
            compiled.append(re.compile(pattern))
        else:
            compiled.append(re.compile(pattern, re.IGNORECASE))
    return compiled


def _narrative_polarity(sentence: str, match: re.Match[str], multi_word: bool) -> str:
    if _negated(sentence, match.start(), match.end()):
        return "negated"
    if HISTORICAL.search(sentence):
        return "historical"
    if ALLEGATION.search(sentence):
        return "alleged"
    if AFFIRMATIVE.search(sentence):
        return "occurred"
    if PRECAUTION.search(sentence):
        return "precautionary"
    if multi_word:
        return "occurred"
    return "insufficient"


def _confidence_for(polarity: str, confirmed: bool, structured: bool) -> tuple[str, bool]:
    if polarity in {"negated", "historical", "alleged", "precautionary", "contradictory", "insufficient"}:
        confidence = {
            "negated": "verified_narrative" if confirmed else "probable_review",
            "historical": "verified_narrative" if confirmed else "probable_review",
            "alleged": "probable_review",
            "precautionary": "verified_narrative" if confirmed else "probable_review",
            "contradictory": "contradictory",
            "insufficient": "insufficient",
        }[polarity]
        return confidence, False
    if structured and confirmed:
        return "confirmed_structured", True
    if structured:
        return "probable_review", False
    if confirmed:
        return "verified_narrative", True
    return "probable_review", False


def _structured_veto(rule: dict, narratives: list[str]) -> str | None:
    compiled = _compile(rule.get("contradiction_regex") or [])
    narrative_patterns = _compile(rule.get("narrative_regex") or [])
    for text in narratives:
        for sentence in _sentences(text):
            for pattern in compiled:
                if pattern.search(sentence):
                    return "contradictory"
            for pattern in narrative_patterns:
                match = pattern.search(sentence)
                if match and _negated(sentence, match.start(), match.end()):
                    return "negated"
    return None


def _match_sentence_all(rule: dict, narratives: list[str]) -> str | None:
    required = rule.get("sentence_all") or []
    if not required:
        return None
    compiled = _compile(required)
    for text in narratives:
        for sentence in _sentences(text):
            if all(pattern.search(sentence) for pattern in compiled):
                return sentence
    return None


def classify_rules(record: Classifiable, rules: list[dict]) -> list[Proposal]:
    proposals: list[Proposal] = []
    structured_text = " ".join(
        part for part in (record.call_type, record.call_classification) if part
    )
    for rule in rules:
        if rule.get("enabled", True) is False:
            continue
        confirmed = rule.get("confirmation") == "agency_confirmed"
        significant = rule.get("group") == "significant"
        structured_hit = any(_phrase_in(structured_text, phrase) for phrase in rule.get("call_phrases") or [])
        if structured_hit:
            veto = _structured_veto(rule, record.narratives)
            if veto:
                confidence, counts = _confidence_for(veto if veto != "negated" else "contradictory", confirmed, True)
                polarity = "contradictory" if veto == "negated" else veto
                proposals.append(
                    Proposal(
                        category=rule["category"],
                        polarity=polarity,
                        confidence="contradictory",
                        counts_officially=False,
                        significant=significant,
                        evidence=[{
                            "kind": "structured_call_type_contradicted",
                            "source": "call_type",
                            "text": _excerpt(record.call_type or record.call_classification or ""),
                        }],
                        rule_key=rule["rule_key"],
                    )
                )
            else:
                confidence, counts = _confidence_for("occurred", confirmed, True)
                proposals.append(
                    Proposal(
                        category=rule["category"],
                        polarity="occurred",
                        confidence=confidence,
                        counts_officially=counts,
                        significant=significant and counts,
                        evidence=[{
                            "kind": "structured_call_type",
                            "source": "call_type",
                            "text": _excerpt(record.call_type or record.call_classification or ""),
                        }],
                        rule_key=rule["rule_key"],
                    )
                )
            continue
        sentence_hit = _match_sentence_all(rule, record.narratives)
        patterns = _compile(rule.get("narrative_regex") or [])
        chosen: tuple[str, str, re.Match[str]] | None = None
        if sentence_hit is not None:
            # sentence_all is a multi-condition match. Reuse the first required pattern for span.
            first = _compile(rule.get("sentence_all") or ["$^"])[0]
            match = first.search(sentence_hit)
            if match is not None:
                polarity = _narrative_polarity(sentence_hit, match, True)
                chosen = (sentence_hit, polarity, match)
        if chosen is None:
            for text in record.narratives:
                for sentence in _sentences(text):
                    for pattern in patterns:
                        match = pattern.search(sentence)
                        if not match:
                            continue
                        multi_word = bool(re.search(r"\s", pattern.pattern))
                        polarity = _narrative_polarity(sentence, match, multi_word)
                        chosen = (sentence, polarity, match)
                        break
                    if chosen:
                        break
                if chosen:
                    break
        if chosen is None:
            continue
        sentence, polarity, match = chosen
        if any(pattern.search(sentence) for pattern in _compile(rule.get("contradiction_regex") or [])):
            if polarity == "occurred":
                polarity = "contradictory"
        confidence, counts = _confidence_for(polarity, confirmed, False)
        proposals.append(
            Proposal(
                category=rule["category"],
                polarity=polarity,
                confidence=confidence,
                counts_officially=counts,
                significant=significant and counts and polarity == "occurred",
                evidence=[{
                    "kind": "narrative",
                    "source": "narrative",
                    "text": _excerpt(sentence),
                }],
                rule_key=rule["rule_key"],
            )
        )
    return _suppress(proposals)


def _suppress(proposals: list[Proposal]) -> list[Proposal]:
    occurred = {
        item.category
        for item in proposals
        if item.polarity == "occurred"
    }
    # suppress_if is carried on the proposal only via rule; look up from evidence rule is not enough.
    # The caller passes proposals that include rule_key. Suppression map is attached by category
    # through a function argument stored on the proposal? We keep it in the rule and pass via
    # a side channel: classify_rules closes over rules.
    return proposals


def classify(record: Classifiable, rules: list[dict]) -> list[Proposal]:
    proposals = classify_rules(record, rules)
    suppress_map = {rule["category"]: set(rule.get("suppress_if") or []) for rule in rules}
    blocking = {item.category for item in proposals if item.polarity == "occurred"}
    kept: list[Proposal] = []
    for item in proposals:
        blockers = suppress_map.get(item.category, set())
        if item.polarity == "occurred" and blockers & blocking:
            continue
        kept.append(item)
    kept.extend(structural_proposals(record))
    return _dedupe(kept)


def _dedupe(proposals: list[Proposal]) -> list[Proposal]:
    rank = {
        "confirmed_structured": 5,
        "user_accepted": 5,
        "verified_narrative": 4,
        "probable_review": 3,
        "contradictory": 2,
        "insufficient": 1,
    }
    best: dict[tuple[str, str], Proposal] = {}
    for item in proposals:
        key = (item.category, item.polarity)
        current = best.get(key)
        if current is None or rank.get(item.confidence, 0) > rank.get(current.confidence, 0):
            best[key] = item
    # If a category has a contradictory or negated reading and an occurred reading, drop occurred.
    blocked = {
        item.category
        for item in best.values()
        if item.polarity in {"contradictory", "negated"}
    }
    return [
        item
        for item in best.values()
        if not (item.polarity == "occurred" and item.category in blocked)
    ]


def structural_proposals(record: Classifiable) -> list[Proposal]:
    proposals: list[Proposal] = []
    report_map = {
        "arrest": ("arrest_report", "Arrest report reference", False),
        "offense": ("offense_report", "Offense report reference", False),
        "accident": ("accident_report", "Accident report reference", False),
        "supplemental": ("supplemental_report", "Supplemental report reference", False),
    }
    for ref_type in record.report_types:
        mapped = report_map.get(ref_type)
        if not mapped:
            continue
        category, label, significant = mapped
        proposals.append(
            Proposal(
                category=category,
                polarity="occurred",
                confidence="confirmed_structured",
                counts_officially=True,
                significant=significant,
                evidence=[{"kind": "labeled_report", "source": "report_reference", "text": label}],
                rule_key="structural_report",
            )
        )
    if record.citation_verified:
        proposals.append(
            Proposal(
                category="verified_traffic_violation",
                polarity="occurred",
                confidence="confirmed_structured",
                counts_officially=True,
                significant=False,
                evidence=[{"kind": "labeled_citation", "source": "citation", "text": "verified=yes"}],
                rule_key="structural_citation",
            )
        )
    if record.citation_warning:
        proposals.append(
            Proposal(
                category="warning",
                polarity="occurred",
                confidence="confirmed_structured",
                counts_officially=True,
                significant=False,
                evidence=[{"kind": "labeled_citation", "source": "citation", "text": "warning=yes"}],
                rule_key="structural_citation",
            )
        )
    if record.citation_numbers:
        proposals.append(
            Proposal(
                category="citation_reference",
                polarity="occurred",
                confidence="confirmed_structured",
                counts_officially=True,
                significant=False,
                evidence=[{
                    "kind": "labeled_citation",
                    "source": "citation",
                    "text": "A citation number was recorded. It is not a verified violation.",
                }],
                rule_key="structural_citation",
            )
        )
    if record.follow_up is True:
        proposals.append(
            Proposal(
                category="follow_up_required",
                polarity="occurred",
                confidence="confirmed_structured",
                counts_officially=True,
                significant=False,
                evidence=[{"kind": "labeled_field", "source": "follow_up", "text": "Follow Up: yes"}],
                rule_key="structural_follow_up",
            )
        )
    if record.officer_slots >= 2:
        proposals.append(
            Proposal(
                category="multiple_units",
                polarity="occurred",
                confidence="confirmed_structured",
                counts_officially=True,
                significant=False,
                evidence=[{"kind": "structure", "source": "officers", "text": f"{record.officer_slots} officer or unit slots"}],
                rule_key="structural_units",
            )
        )
    return proposals
