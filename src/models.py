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
class RedditPost:
    id: str
    title: str
    body: str
    posted_at: datetime
    permalink: str


SOURCE_WSDOT = "wsdot_alert"
SOURCE_REDDIT = "reddit_post"


@dataclass
class RelevanceMatch:
    event_id: str
    source_type: str       # SOURCE_WSDOT or SOURCE_REDDIT
    source_id: str         # alert.id or post.id
    note: str


@dataclass
class RenderedMatch:
    """What the email renderer needs: the note text plus an optional source marker."""
    note: str
    source_marker: str = ""   # e.g. " (r/WSDOT)" — empty for default WSDOT-API alerts


@dataclass
class Digest:
    generated_at: datetime
    events: list[Event]
    matches_by_event_id: dict[str, list[RenderedMatch]] = field(default_factory=dict)
    traffic_data_available: bool = True


class WSDOTUnavailableError(RuntimeError):
    pass


class RedditUnavailableError(RuntimeError):
    pass


class RelevanceUnavailableError(RuntimeError):
    pass
