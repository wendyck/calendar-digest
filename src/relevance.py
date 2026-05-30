from __future__ import annotations

import json
from typing import Any

import anthropic

from .models import Alert, Event, RelevanceMatch, RelevanceUnavailableError

TOOL: dict[str, Any] = {
    "name": "record_relevant_alerts",
    "description": "Record which highway alerts are relevant to which calendar events.",
    "input_schema": {
        "type": "object",
        "properties": {
            "matches": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "event_id": {"type": "string"},
                        "alert_id": {"type": "string"},
                        "note": {
                            "type": "string",
                            "description": (
                                "Short note for the digest, e.g. 'Southbound I-405 "
                                "closure on return'. Max 80 chars."
                            ),
                        },
                    },
                    "required": ["event_id", "alert_id", "note"],
                },
            }
        },
        "required": ["matches"],
    },
}

SYSTEM_PROMPT = """You match Washington State highway alerts to a user's calendar events to help
them anticipate traffic disruptions.

The user lives in the Seattle area. For each event with a physical address,
decide whether any of the provided highway alerts are likely to affect their
drive to or from that location.

Rules:
- Only match alerts whose active window overlaps the plausible travel window
  for the event (assume departure up to 2 hours before, return up to 3 hours
  after).
- Only match alerts on roads that are plausibly on the route between the
  Seattle area and the event location.
- For each match, write a brief, useful note (max 80 chars) describing the
  impact, e.g. "Southbound I-405 closure on return" or "Construction on
  I-5 N near destination".
- Prefer no match over a speculative one. False positives are worse than
  false negatives here.
- An event may match zero, one, or multiple alerts.
"""


def match_alerts_to_events(
    api_key: str,
    model: str,
    events: list[Event],
    alerts: list[Alert],
) -> list[RelevanceMatch]:
    physical = [e for e in events if not e.is_virtual and e.location]
    if not physical or not alerts:
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
        },
        indent=2,
    )

    try:
        client = anthropic.Anthropic(api_key=api_key, timeout=30.0)
        response = client.messages.create(
            model=model,
            max_tokens=2048,
            system=SYSTEM_PROMPT,
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
                    alert_id=m["alert_id"],
                    note=m["note"],
                )
                for m in raw_matches
            ]
    raise RelevanceUnavailableError("Claude response did not include the expected tool use")
