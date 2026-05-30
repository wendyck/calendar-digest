from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from src.digest import build_digest, group_by_day
from src.models import Alert, Event, RelevanceMatch

TZ = ZoneInfo("America/Los_Angeles")


def _event(eid: str, day: int, hour: int):
    start = datetime(2026, 5, day, hour, tzinfo=TZ)
    return Event(
        id=eid,
        summary=f"event {eid}",
        start=start,
        end=start.replace(hour=hour + 1),
        location="loc",
        all_day=False,
        is_virtual=False,
    )


def _alert(aid: str):
    return Alert(
        id=aid,
        headline="h",
        category="Construction",
        priority="High",
        roadway="I-405",
        region="Northwest",
        start_time=datetime(2026, 5, 30, 8, tzinfo=TZ),
        end_time=datetime(2026, 5, 31, 8, tzinfo=TZ),
    )


def test_build_digest_sorts_and_attaches_matches():
    events = [_event("b", 30, 14), _event("a", 30, 9), _event("c", 31, 10)]
    alerts = [_alert("alert-1")]
    matches = [RelevanceMatch(event_id="c", alert_id="alert-1", note="watch I-405")]
    now = datetime(2026, 5, 30, 5, tzinfo=TZ)

    digest = build_digest(events, alerts, matches, traffic_data_available=True, now=now)

    assert [e.id for e in digest.events] == ["a", "b", "c"]
    assert digest.matches_by_event_id["c"][0][1] == "watch I-405"
    assert digest.matches_by_event_id["c"][0][0].id == "alert-1"


def test_group_by_day():
    events = [_event("b", 30, 14), _event("a", 30, 9), _event("c", 31, 10)]
    groups = group_by_day(events)
    assert len(groups) == 2
    assert [e.id for e in groups[0][1]] == ["a", "b"]
    assert [e.id for e in groups[1][1]] == ["c"]


def test_unknown_alert_id_skipped():
    events = [_event("a", 30, 9)]
    matches = [RelevanceMatch(event_id="a", alert_id="missing", note="x")]
    now = datetime(2026, 5, 30, 5, tzinfo=TZ)
    digest = build_digest(events, [], matches, True, now)
    assert digest.matches_by_event_id == {}
