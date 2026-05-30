from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Event:
    id: str
    summary: str
    start: datetime
    end: datetime
    location: str | None
    all_day: bool
    is_virtual: bool


@dataclass
class Alert:
    id: str
    headline: str
    category: str
    priority: str
    roadway: str
    region: str
    start_time: datetime
    end_time: datetime | None


@dataclass
class RelevanceMatch:
    event_id: str
    alert_id: str
    note: str


@dataclass
class Digest:
    generated_at: datetime
    events: list[Event]
    matches_by_event_id: dict[str, list[tuple[Alert, str]]] = field(default_factory=dict)
    traffic_data_available: bool = True


class WSDOTUnavailableError(RuntimeError):
    pass


class RelevanceUnavailableError(RuntimeError):
    pass
