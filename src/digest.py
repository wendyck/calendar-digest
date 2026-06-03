from __future__ import annotations

from datetime import datetime

from .models import (
    Alert,
    Digest,
    Event,
    RedditPost,
    RelevanceMatch,
    RenderedMatch,
    SOURCE_REDDIT,
)

REDDIT_MARKER = " (r/WSDOT)"


def build_digest(
    events: list[Event],
    alerts: list[Alert],
    matches: list[RelevanceMatch],
    traffic_data_available: bool,
    now: datetime,
    reddit_posts: list[RedditPost] | None = None,
) -> Digest:
    alerts_by_id = {a.id: a for a in alerts}
    posts_by_id = {p.id: p for p in (reddit_posts or [])}

    matches_by_event: dict[str, list[RenderedMatch]] = {}
    for m in matches:
        if m.source_type == SOURCE_REDDIT:
            if m.source_id not in posts_by_id:
                continue
            marker = REDDIT_MARKER
        else:
            if m.source_id not in alerts_by_id:
                continue
            marker = ""
        matches_by_event.setdefault(m.event_id, []).append(
            RenderedMatch(note=m.note, source_marker=marker)
        )

    sorted_events = sorted(events, key=lambda e: e.start)
    return Digest(
        generated_at=now,
        events=sorted_events,
        matches_by_event_id=matches_by_event,
        traffic_data_available=traffic_data_available,
    )


def group_by_day(events: list[Event]) -> list[tuple[datetime, list[Event]]]:
    """Return list of (day-start, events) tuples in chronological order."""
    grouped: dict[str, list[Event]] = {}
    for event in events:
        key = event.start.date().isoformat()
        grouped.setdefault(key, []).append(event)
    out: list[tuple[datetime, list[Event]]] = []
    for key in sorted(grouped):
        day_events = sorted(grouped[key], key=lambda e: e.start)
        out.append((day_events[0].start, day_events))
    return out
