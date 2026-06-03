from __future__ import annotations

import json
import re
from typing import Any

import anthropic

from .models import (
    Alert,
    Event,
    RedditPost,
    RelevanceMatch,
    RelevanceUnavailableError,
    SOURCE_REDDIT,
    SOURCE_WSDOT,
)

TOOL: dict[str, Any] = {
    "name": "record_relevant_alerts",
    "description": (
        "Record which traffic signals (WSDOT highway alerts and/or u/wsdot Reddit "
        "posts) are relevant to which calendar events."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "matches": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "event_id": {"type": "string"},
                        "source_type": {
                            "type": "string",
                            "enum": [SOURCE_WSDOT, SOURCE_REDDIT],
                            "description": (
                                "Which source this match came from: 'wsdot_alert' for "
                                "the structured WSDOT highway alerts feed, or "
                                "'reddit_post' for a u/wsdot Reddit post."
                            ),
                        },
                        "source_id": {
                            "type": "string",
                            "description": "ID of the matching alert or Reddit post.",
                        },
                        "note": {
                            "type": "string",
                            "description": (
                                "Short note for the digest, e.g. 'Southbound I-405 "
                                "closure on return'. Max 80 chars."
                            ),
                        },
                    },
                    "required": ["event_id", "source_type", "source_id", "note"],
                },
            }
        },
        "required": ["matches"],
    },
}

_BASE_PROMPT = """You match Washington State traffic signals to a user's calendar events to help
them anticipate disruptions.

You receive TWO kinds of traffic signals:
1. Structured WSDOT highway alerts (source_type = "wsdot_alert"): authoritative,
   with roadway, category, priority, and an active time window.
2. u/wsdot Reddit posts (source_type = "reddit_post"): supplementary, written by
   the WSDOT social team. Useful for advance heads-ups about planned closures
   that may not yet be in the alerts feed, or for added context on an ongoing
   event. Reddit post bodies can be conversational; extract the operational
   facts (which roadway, which dates/times, which direction) and ignore filler.

{origin_block}
Typical Seattle-area corridors:
- South: I-5 / WA-99
- North-south east of Lake Washington: I-405
- East across Lake Washington: I-90, WA-520
- South to Auburn/Kent/Puyallup: WA-167
- SR 18 runs east of Auburn between I-5 (Federal Way) and I-90 (Snoqualmie)
  and is NOT on the route to WA-167-corridor destinations. Only flag SR 18
  alerts when the event itself is on or east of SR 18 (e.g., Snoqualmie,
  Tiger Mountain, Issaquah-area east side).

For each event with a physical address, decide whether any of the provided
highway alerts are likely to affect their drive to or from that location.

Rules:
- Identify the plausible route first. Only match alerts whose roadway lies
  on that route. An alert on a parallel or adjacent highway is NOT a match,
  even if it's near the destination city.
- Only match alerts whose active window overlaps the plausible travel
  window for the event (departure up to 2 hours before, return up to 3
  hours after).
- If an alert is overnight-only (e.g., active 10 PM–5 AM) and the event is
  daytime, do not match.
- If an alert applies only on weekdays (Mon–Fri) and the event is on a
  weekend, do not match. Same in reverse.
- If multiple signals describe the same underlying incident (e.g., a
  WSDOT alert AND a Reddit post about the same closure, or a closure
  plus its detour congestion), pick ONE that best captures the
  user-facing impact rather than listing all of them. When a WSDOT alert
  and a Reddit post both cover the same event, prefer the WSDOT alert.
- For each match, write a brief, useful note (max 80 chars) describing the
  impact, e.g. "Southbound I-405 closure on return".
- Prefer no match over a speculative one. False positives are worse than
  false negatives here.
- An event may match zero, one, or multiple alerts.
"""


# SR 18 is a frequent false positive: the model sometimes flags it for any
# event near Auburn because SR 18 *does* serve some Auburn destinations, but
# in practice the user's calendar destinations are on the WA-167 or I-5/I-90
# corridors where SR 18 is irrelevant. This pre-filter drops SR 18 alerts
# unless at least one event location is in the narrow corridor SR 18 actually
# serves (south end at I-5 in Federal Way → Auburn east side / Maple Valley →
# Tiger Mountain → north end at I-90 in Snoqualmie).
_SR18_ROADWAY_RE = re.compile(r"\b(?:SR|WA)[-\s]?18\b", re.IGNORECASE)
_SR18_CORRIDOR_TOWNS = (
    "snoqualmie",
    "north bend",
    "issaquah",
    "tiger mountain",
    "maple valley",
    "federal way",
)


def _alert_is_sr18(alert: Alert) -> bool:
    return bool(_SR18_ROADWAY_RE.search(alert.roadway or ""))


def _filter_offroute_sr18_alerts(
    alerts: list[Alert], events: list[Event]
) -> list[Alert]:
    """Drop SR 18 alerts when no event location is in the SR 18 corridor.

    Lives here (not in wsdot_client) because the decision requires knowing
    the events as well as the alerts.
    """
    has_sr18_event = any(
        e.location and any(town in e.location.lower() for town in _SR18_CORRIDOR_TOWNS)
        for e in events
        if not e.is_virtual
    )
    if has_sr18_event:
        return alerts
    return [a for a in alerts if not _alert_is_sr18(a)]


def _build_system_prompt(home_location: str) -> str:
    if home_location.strip():
        origin = f"The user departs from {home_location.strip()}."
    else:
        origin = "The user lives in the Seattle area."
    return _BASE_PROMPT.format(origin_block=origin)


def match_alerts_to_events(
    api_key: str,
    model: str,
    events: list[Event],
    alerts: list[Alert],
    home_location: str = "",
    reddit_posts: list[RedditPost] | None = None,
) -> list[RelevanceMatch]:
    physical = [e for e in events if not e.is_virtual and e.location]
    reddit_posts = reddit_posts or []
    alerts = _filter_offroute_sr18_alerts(alerts, physical)
    if not physical or (not alerts and not reddit_posts):
        return []

    user_message = json.dumps(
        {
            "events": [
                {
                    "id": e.id,
                    "summary": e.summary,
                    "location": e.location,
                    "start": e.start.isoformat(),
                    "end": e.end.isoformat(),
                }
                for e in physical
            ],
            "alerts": [
                {
                    "id": a.id,
                    "headline": a.headline,
                    "roadway": a.roadway,
                    "category": a.category,
                    "priority": a.priority,
                    "start_time": a.start_time.isoformat(),
                    "end_time": a.end_time.isoformat() if a.end_time else None,
                }
                for a in alerts
            ],
            "reddit_posts": [
                {
                    "id": p.id,
                    "title": p.title,
                    "body": p.body,
                    "posted_at": p.posted_at.isoformat(),
                }
                for p in reddit_posts
            ],
        },
        indent=2,
    )

    try:
        client = anthropic.Anthropic(api_key=api_key, timeout=30.0)
        response = client.messages.create(
            model=model,
            max_tokens=2048,
            system=_build_system_prompt(home_location),
            tools=[TOOL],
            tool_choice={"type": "tool", "name": "record_relevant_alerts"},
            messages=[{"role": "user", "content": user_message}],
        )
    except Exception as exc:  # noqa: BLE001 - external SDK, surface all failures uniformly
        raise RelevanceUnavailableError(str(exc)) from exc

    for block in response.content:
        if getattr(block, "type", None) == "tool_use" and block.name == "record_relevant_alerts":
            raw_matches = block.input.get("matches", [])
            return [
                RelevanceMatch(
                    event_id=m["event_id"],
                    source_type=m.get("source_type", SOURCE_WSDOT),
                    source_id=m.get("source_id") or m.get("alert_id", ""),
                    note=m["note"],
                )
                for m in raw_matches
            ]
    raise RelevanceUnavailableError("Claude response did not include the expected tool use")
