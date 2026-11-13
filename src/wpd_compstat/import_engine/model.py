"""Parsed CAD records. Person payloads are omitted from repr so logs stay safe."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ParsedNarrative:
    time_text: str | None
    author: str | None
    body: str
    page: int


@dataclass
class ParsedOfficer:
    badge: str | None
    name: str
    role: str
    unit: str | None = None


@dataclass
class ParsedCitation:
    number: str | None
    verified: bool
    warning: bool


@dataclass
class ParsedReport:
    ref_type: str
    ref_number: str


@dataclass
class ParsedVehicle:
    description: str
    role: str | None
    state: str | None
    plate: str | None


@dataclass
class ParsedPerson:
    role: str
    payload: dict


@dataclass
class ParsedIncident:
    cad_number: str | None
    event_date: str | None
    event_time: str | None = None
    received_time: str | None = None
    dispatch_time: str | None = None
    arrival_time: str | None = None
    clear_time: str | None = None
    call_type: str | None = None
    call_classification: str | None = None
    call_source: str | None = None
    priority: str | None = None
    disposition: str | None = None
    final_disposition: str | None = None
    call_taker: str | None = None
    location: str | None = None
    business: str | None = None
    intersection: str | None = None
    primary_unit: str | None = None
    follow_up: bool | None = None
    source_page: int = 1
    warnings: list[str] = field(default_factory=list)
    narratives: list[ParsedNarrative] = field(default_factory=list)
    officers: list[ParsedOfficer] = field(default_factory=list)
    citations: list[ParsedCitation] = field(default_factory=list)
    reports: list[ParsedReport] = field(default_factory=list)
    vehicles: list[ParsedVehicle] = field(default_factory=list)
    persons: list[ParsedPerson] = field(default_factory=list)
    confidence: float = 0.0

    def __repr__(self) -> str:
        return (
            f"ParsedIncident(cad_number={self.cad_number!r}, event_date={self.event_date!r}, "
            f"narratives={len(self.narratives)}, persons={len(self.persons)})"
        )

    @property
    def low_confidence(self) -> bool:
        return self.confidence < 0.6 or not self.cad_number or not self.event_date


@dataclass
class ParseOutput:
    recognized: bool
    incidents: list[ParsedIncident]
    errors: list[str]
    warnings: list[str]
    declared_start: str | None = None
    declared_end: str | None = None
    tables_ignored: int = 0
