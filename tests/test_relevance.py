from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from src import relevance
from src.relevance import _build_system_prompt, _filter_offroute_sr18_alerts
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


def test_system_prompt_uses_home_location_when_provided():
    prompt = _build_system_prompt("West Seattle, WA 98116")
    assert "West Seattle, WA 98116" in prompt
    assert "overnight-only" in prompt
    assert "SR 18" in prompt


def _sr18_alert():
    return Alert(
        id="sr18", headline="SR 18 closed under I-90 interchange",
        category="Construction", priority="High",
        roadway="SR 18", region="Northwest",
        start_time=datetime(2026, 6, 5, tzinfo=timezone.utc),
        end_time=datetime(2026, 6, 8, tzinfo=timezone.utc),
    )


def _i5_alert():
    return Alert(
        id="i5", headline="NB I-5 closure", category="Construction", priority="High",
        roadway="I-5", region="Northwest",
        start_time=datetime(2026, 6, 5, tzinfo=timezone.utc),
        end_time=datetime(2026, 6, 8, tzinfo=timezone.utc),
    )


def _event_at(location: str):
    return Event(
        id="e1", summary="x",
        start=datetime(2026, 6, 7, 13, tzinfo=timezone.utc),
        end=datetime(2026, 6, 7, 16, tzinfo=timezone.utc),
        location=location, all_day=False, is_virtual=False,
    )


def test_sr18_dropped_when_no_event_in_sr18_corridor():
    events = [_event_at("Green River College, Auburn, WA 98092")]
    alerts = [_sr18_alert(), _i5_alert()]
    kept = _filter_offroute_sr18_alerts(alerts, events)
    assert [a.id for a in kept] == ["i5"]


def test_sr18_kept_when_event_is_in_snoqualmie():
    events = [_event_at("Snoqualmie Falls, Snoqualmie, WA")]
    alerts = [_sr18_alert(), _i5_alert()]
    kept = _filter_offroute_sr18_alerts(alerts, events)
    assert {a.id for a in kept} == {"sr18", "i5"}


def test_sr18_kept_when_event_is_in_federal_way():
    events = [_event_at("Federal Way, WA 98003")]
    alerts = [_sr18_alert()]
    assert _filter_offroute_sr18_alerts(alerts, events) == alerts


def test_system_prompt_falls_back_when_blank():
    prompt = _build_system_prompt("")
    assert "Seattle area" in prompt


def test_parses_tool_use_response():
    fake_block = SimpleNamespace(
        type="tool_use",
        name="record_relevant_alerts",
        input={"matches": [{"event_id": "e1", "source_type": "wsdot_alert", "source_id": "a1", "note": "Watch I-405"}]},
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
    assert matches[0].source_id == "a1"
    assert matches[0].source_type == "wsdot_alert"
    assert "I-405" in matches[0].note

    call_kwargs = client.messages.create.call_args.kwargs
    assert call_kwargs["tool_choice"]["name"] == "record_relevant_alerts"
    assert call_kwargs["tools"][0]["name"] == "record_relevant_alerts"
