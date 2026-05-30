from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from src import wsdot_client
from src.models import WSDOTUnavailableError


class _FakeResponse:
    def __init__(self, data, status=200):
        self._data = data
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(f"status {self.status_code}")

    def json(self):
        return self._data


@patch("src.wsdot_client.requests.get")
def test_filters_expired_and_far_future(get_mock, wsdot_fixture):
    get_mock.return_value = _FakeResponse(wsdot_fixture)
    lookahead = datetime(2026, 6, 6, tzinfo=timezone.utc)
    alerts = wsdot_client.fetch_alerts("code", lookahead)

    ids = [a.id for a in alerts]
    assert "12345" in ids
    assert "99999" not in ids  # expired
    assert "88888" not in ids  # too far in future


@patch("src.wsdot_client.requests.get")
def test_handles_empty(get_mock):
    get_mock.return_value = _FakeResponse([])
    lookahead = datetime(2026, 6, 6, tzinfo=timezone.utc)
    assert wsdot_client.fetch_alerts("code", lookahead) == []


@patch("src.wsdot_client.requests.get")
def test_raises_on_http_failure(get_mock):
    import requests
    get_mock.side_effect = requests.ConnectionError("boom")
    with pytest.raises(WSDOTUnavailableError):
        wsdot_client.fetch_alerts("code", datetime(2026, 6, 6, tzinfo=timezone.utc))


def test_parse_net_date_roundtrip():
    parsed = wsdot_client._parse_net_date("/Date(1780099200000-0700)/")
    assert parsed.tzinfo is not None
    assert parsed.year == 2026
    assert parsed.month == 5
