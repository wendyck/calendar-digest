from __future__ import annotations

from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from src import calendar_client


@patch("src.calendar_client.build")
@patch("src.calendar_client.service_account.Credentials")
def test_fetch_events_parses_mix_of_event_types(creds_mock, build_mock, calendar_fixture):
    creds_mock.from_service_account_info.return_value.with_subject.return_value = MagicMock()
    service = build_mock.return_value
    service.events.return_value.list.return_value.execute.return_value = calendar_fixture

    from datetime import datetime

    events = calendar_client.fetch_events(
        service_account_info={"client_email": "x"},
        user_email="u@example.com",
        calendar_id="primary",
        start=datetime(2026, 5, 30, tzinfo=ZoneInfo("America/Los_Angeles")),
        end=datetime(2026, 6, 6, tzinfo=ZoneInfo("America/Los_Angeles")),
        timezone="America/Los_Angeles",
    )

    assert len(events) == 6
    by_id = {e.id: e for e in events}

    monroe = by_id["evt-monroe"]
    assert monroe.is_virtual is False
    assert monroe.location.startswith("Monroe Bus Barn")
    assert monroe.all_day is False

    virtual = by_id["evt-virtual"]
    assert virtual.is_virtual is True
    assert virtual.location is None

    allday = by_id["evt-allday"]
    assert allday.all_day is True
    assert allday.start.tzinfo is not None


@patch("src.calendar_client.build")
@patch("src.calendar_client.service_account.Credentials")
def test_zoom_location_is_virtual(creds_mock, build_mock):
    creds_mock.from_service_account_info.return_value.with_subject.return_value = MagicMock()
    service = build_mock.return_value
    service.events.return_value.list.return_value.execute.return_value = {
        "items": [
            {
                "id": "z1",
                "summary": "Zoom call",
                "start": {"dateTime": "2026-05-30T09:00:00-07:00"},
                "end": {"dateTime": "2026-05-30T10:00:00-07:00"},
                "location": "https://zoom.us/j/123",
            }
        ]
    }
    from datetime import datetime

    events = calendar_client.fetch_events(
        {}, "u@example.com", "primary",
        datetime(2026, 5, 30, tzinfo=ZoneInfo("America/Los_Angeles")),
        datetime(2026, 6, 6, tzinfo=ZoneInfo("America/Los_Angeles")),
        "America/Los_Angeles",
    )
    assert events[0].is_virtual is True
