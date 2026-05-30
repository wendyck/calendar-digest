from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from src.digest import build_digest
from src.models import Alert, Event, RelevanceMatch
from src.renderers.email_renderer import (
    TRAFFIC_UNAVAILABLE_BANNER,
    render_email,
    render_text,
)

TZ = ZoneInfo("America/Los_Angeles")


def _ev(eid, day, h, summary="Event", location="123 Main St, Seattle, WA", virtual=False, all_day=False):
    start = datetime(2026, 5, day, h, tzinfo=TZ) if not all_day else datetime(2026, 5, day, 0, tzinfo=TZ)
    end = start.replace(hour=(h + 1) if not all_day else 0, day=day + (1 if all_day else 0))
    return Event(
        id=eid, summary=summary, start=start, end=end,
        location=None if virtual else location,
        all_day=all_day, is_virtual=virtual,
    )


def _alert(aid="a1"):
    return Alert(
        id=aid, headline="h", category="Construction", priority="High",
        roadway="I-405", region="Northwest",
        start_time=datetime(2026, 5, 30, 8, tzinfo=TZ),
        end_time=datetime(2026, 5, 31, 8, tzinfo=TZ),
    )


def _canonical_digest(traffic_ok=True):
    now = datetime(2026, 5, 30, 5, tzinfo=TZ)
    events = [
        _ev("uv", 30, 13, "U Village Things", "2746 NE 45th St, Seattle, WA 98105"),
        _ev("monroe", 31, 10, "Nosework Sniff and Go", "Monroe Bus Barn, 17815 W Main St, Monroe, WA 98272"),
    ]
    # Bump Monroe end to 11:15 for realism, not strictly needed for assertions.
    events[1].end = datetime(2026, 5, 31, 11, 15, tzinfo=TZ)

    alerts = [_alert("alert-monroe")]
    matches = [RelevanceMatch(
        event_id="monroe",
        alert_id="alert-monroe",
        note="Southbound I-405 weekend closure — plan extra time on the way home",
    )]
    return build_digest(events, alerts, matches, traffic_data_available=traffic_ok, now=now)


def test_subject_format():
    digest = _canonical_digest()
    subject, _ = render_email(digest)
    assert subject == "Morning digest — Saturday, May 30"


def test_text_matches_option_b_structure():
    text = render_text(_canonical_digest())
    assert "TODAY — Saturday, May 30" in text
    assert "TOMORROW — Sunday, May 31" in text
    assert "📍 2746 NE 45th St, Seattle, WA 98105" in text
    assert "⚠️" in text
    assert "Southbound I-405 weekend closure" in text


def test_html_matches_option_b_structure():
    _, html = render_email(_canonical_digest())
    assert "TODAY — Saturday, May 30" in html
    assert "TOMORROW — Sunday, May 31" in html
    assert "📍 2746 NE 45th St" in html
    assert "⚠️" in html
    # Both events present
    assert "U Village Things" in html
    assert "Nosework Sniff and Go" in html


def test_traffic_unavailable_banner_and_no_warnings():
    digest = _canonical_digest(traffic_ok=False)
    _, html = render_email(digest)
    text = render_text(digest)
    assert TRAFFIC_UNAVAILABLE_BANNER in html
    assert TRAFFIC_UNAVAILABLE_BANNER in text
    assert "⚠️" not in html
    assert "⚠️" not in text


def test_virtual_event_has_no_location_line():
    now = datetime(2026, 5, 30, 5, tzinfo=TZ)
    events = [_ev("v", 30, 9, "Standup", virtual=True)]
    digest = build_digest(events, [], [], True, now)
    text = render_text(digest)
    assert "📍" not in text


def test_day_with_no_events_omitted():
    # Only one event on day 30, none on day 31 — only "TODAY" header should appear.
    now = datetime(2026, 5, 30, 5, tzinfo=TZ)
    events = [_ev("a", 30, 9, "Solo")]
    digest = build_digest(events, [], [], True, now)
    text = render_text(digest)
    assert "TODAY" in text
    assert "TOMORROW" not in text


def test_multiple_warnings_per_event():
    now = datetime(2026, 5, 30, 5, tzinfo=TZ)
    events = [_ev("e", 30, 9)]
    alerts = [_alert("a1"), _alert("a2")]
    matches = [
        RelevanceMatch(event_id="e", alert_id="a1", note="warning one"),
        RelevanceMatch(event_id="e", alert_id="a2", note="warning two"),
    ]
    digest = build_digest(events, alerts, matches, True, now)
    text = render_text(digest)
    assert text.count("⚠️") == 2
    assert "warning one" in text and "warning two" in text
