from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from src import relevance
from src.models import Alert, Event


def _event(eid: str, virtual: bool = False, location: str | None = "somewhere"):
    return Event(
        id=eid,
        summary="x",
        start=datetime(2026, 5, 30, 10, tzinfo=timezone.utc),
        end=datetime(2026, 5, 30, 11, tzinfo=timezone.utc),
        location=location,
        all_day=False,
        is_virtual=virtual,
    )


def _alert(aid: str):
    return Alert(
        id=aid,
        headline="h",
        category="Construction",
        priority="High",
        roadway="I-405",
        region="Northwest",
        start_time=datetime(2026, 5, 30, 8, tzinfo=timezone.utc),
        end_time=datetime(2026, 5, 31, 8, tzinfo=timezone.utc),
    )


def test_no_call_when_no_physical_events():
    with patch("src.relevance.anthropic.Anthropic") as client_cls:
        result = relevance.match_alerts_to_events(
            "key", "claude-x", [_event("e1", virtual=True)], [_alert("a1")]
        )
        assert result == []
        client_cls.assert_not_called()


def test_no_call_when_no_alerts():
    with patch("src.relevance.anthropic.Anthropic") as client_cls:
        result = relevance.match_alerts_to_events("key", "claude-x", [_event("e1")], [])
        assert result == []
        client_cls.assert_not_called()


def test_parses_tool_use_response():
    fake_block = SimpleNamespace(
        type="tool_use",
        name="record_relevant_alerts",
        input={"matches": [{"event_id": "e1", "alert_id": "a1", "note": "Watch I-405"}]},
    )
    fake_response = SimpleNamespace(content=[fake_block])

    client = MagicMock()
    client.messages.create.return_value = fake_response

    with patch("src.relevance.anthropic.Anthropic", return_value=client):
        matches = relevance.match_alerts_to_events(
            "key", "claude-x", [_event("e1")], [_alert("a1")]
        )

    assert len(matches) == 1
    assert matches[0].event_id == "e1"
    assert matches[0].alert_id == "a1"
    assert "I-405" in matches[0].note

    call_kwargs = client.messages.create.call_args.kwargs
    assert call_kwargs["tool_choice"]["name"] == "record_relevant_alerts"
    assert call_kwargs["tools"][0]["name"] == "record_relevant_alerts"
