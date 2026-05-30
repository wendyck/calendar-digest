from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

import requests

from .models import Alert, WSDOTUnavailableError

ENDPOINT = (
    "https://wsdot.wa.gov/Traffic/api/HighwayAlerts/HighwayAlertsREST.svc/"
    "GetAlertsAsJson"
)

_NET_DATE_RE = re.compile(r"/Date\((-?\d+)([+-]\d{4})?\)/")


def fetch_alerts(access_code: str, lookahead_end: datetime) -> list[Alert]:
    try:
        response = requests.get(
            ENDPOINT, params={"AccessCode": access_code}, timeout=10
        )
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise WSDOTUnavailableError(str(exc)) from exc

    now = datetime.now(timezone.utc)
    alerts: list[Alert] = []
    for item in data:
        end_time = _parse_net_date(item.get("EndTime"))
        if end_time is not None and end_time < now:
            continue
        start_time = _parse_net_date(item.get("StartTime"))
        if start_time is None:
            continue
        if start_time > lookahead_end:
            continue
        location = item.get("StartRoadwayLocation") or {}
        alerts.append(
            Alert(
                id=str(item.get("AlertID")),
                headline=item.get("HeadlineDescription") or "",
                category=item.get("EventCategory") or "",
                priority=item.get("Priority") or "",
                roadway=location.get("RoadName") or "",
                region=item.get("Region") or "",
                start_time=start_time,
                end_time=end_time,
            )
        )
    return alerts


def _parse_net_date(value: str | None) -> datetime | None:
    """Parse Microsoft .NET ``/Date(ms-offset)/`` into a tz-aware datetime.

    The offset (when present) only describes the *display* timezone; the
    millisecond value is always UTC milliseconds since the epoch. We return
    everything in UTC and let callers convert as needed.
    """
    if not value:
        return None
    match = _NET_DATE_RE.match(value)
    if not match:
        return None
    ms = int(match.group(1))
    return datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(milliseconds=ms)
