from __future__ import annotations

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from google.oauth2 import service_account
from googleapiclient.discovery import build

from .models import Event

SCOPES = ["https://www.googleapis.com/auth/calendar.events.readonly"]

_VIRTUAL_HOSTS = ("meet.google.com", "zoom.us", "teams.microsoft.com", "webex.com")


def fetch_events(
    service_account_info: dict,
    user_email: str,
    calendar_id: str,
    start: datetime,
    end: datetime,
    timezone: str,
) -> list[Event]:
    credentials = service_account.Credentials.from_service_account_info(
        service_account_info, scopes=SCOPES
    ).with_subject(user_email)
    service = build("calendar", "v3", credentials=credentials, cache_discovery=False)

    response = (
        service.events()
        .list(
            calendarId=calendar_id,
            timeMin=start.isoformat(),
            timeMax=end.isoformat(),
            singleEvents=True,
            orderBy="startTime",
            maxResults=250,
        )
        .execute()
    )

    tz = ZoneInfo(timezone)
    return [_parse_event(item, tz) for item in response.get("items", [])]


def _parse_event(item: dict, tz: ZoneInfo) -> Event:
    start_raw = item.get("start", {})
    end_raw = item.get("end", {})
    all_day = "date" in start_raw

    if all_day:
        start_dt = datetime.combine(date.fromisoformat(start_raw["date"]), time.min, tz)
        end_dt = datetime.combine(date.fromisoformat(end_raw["date"]), time.min, tz)
    else:
        start_dt = datetime.fromisoformat(start_raw["dateTime"]).astimezone(tz)
        end_dt = datetime.fromisoformat(end_raw["dateTime"]).astimezone(tz)

    location = item.get("location")
    summary = item.get("summary", "(no title)")
    return Event(
        id=item["id"],
        summary=summary,
        start=start_dt,
        end=end_dt,
        location=location or None,
        all_day=all_day,
        is_virtual=_is_virtual(location, item),
    )


def _is_virtual(location: str | None, item: dict) -> bool:
    if not location:
        # Treat events with a Google Meet hangout link as virtual even when location is blank.
        if item.get("hangoutLink") or item.get("conferenceData"):
            return True
        return True
    low = location.lower()
    if "http://" in low or "https://" in low:
        return True
    return any(host in low for host in _VIRTUAL_HOSTS)
