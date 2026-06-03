from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from src.models import Alert, Event, RelevanceMatch, RelevanceUnavailableError, WSDOTUnavailableError


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("SECRETS_ARN", "arn:aws:secretsmanager:us-west-2:111:secret:calendar-digest/keys-AAAA")
    monkeypatch.setenv("USER_EMAIL", "u@example.com")
    monkeypatch.setenv("CALENDAR_ID", "primary")
    monkeypatch.setenv("LOOKAHEAD_DAYS", "7")
    monkeypatch.setenv("TIMEZONE", "America/Los_Angeles")
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    yield


def _event():
    return Event(
        id="e1", summary="Thing",
        start=datetime(2026, 5, 30, 13, tzinfo=timezone.utc),
        end=datetime(2026, 5, 30, 14, tzinfo=timezone.utc),
        location="123 Main St, Seattle, WA",
        all_day=False, is_virtual=False,
    )


def _alert():
    return Alert(
        id="a1", headline="h", category="Construction", priority="High",
        roadway="I-405", region="Northwest",
        start_time=datetime(2026, 5, 30, 8, tzinfo=timezone.utc),
        end_time=datetime(2026, 5, 31, 8, tzinfo=timezone.utc),
    )


def _secrets():
    return {
        "google_service_account": json.dumps({"client_email": "x"}),
        "wsdot_access_code": "code",
        "anthropic_api_key": "sk-ant-x",
    }


def test_handler_happy_path():
    from src import handler

    with patch.object(handler, "get_secrets", return_value=_secrets()), \
         patch.object(handler, "fetch_events", return_value=[_event()]), \
         patch("src.wsdot_client.fetch_alerts", return_value=[_alert()]), \
         patch.object(handler, "match_alerts_to_events",
                      return_value=[RelevanceMatch("e1", "wsdot_alert", "a1", "Watch I-405")]), \
         patch.object(handler, "send_email", return_value="msg-id-123") as send:
        result = handler.lambda_handler({}, None)

    assert result == {"status": "ok", "message_id": "msg-id-123"}
    sent_subject = send.call_args.args[2]
    sent_html = send.call_args.args[3]
    sent_text = send.call_args.args[4]
    assert "Morning digest" in sent_subject
    assert "⚠️" in sent_text
    assert "⚠️" in sent_html


def test_handler_traffic_failure_still_sends():
    from src import handler

    with patch.object(handler, "get_secrets", return_value=_secrets()), \
         patch.object(handler, "fetch_events", return_value=[_event()]), \
         patch("src.wsdot_client.fetch_alerts", side_effect=WSDOTUnavailableError("nope")), \
         patch.object(handler, "send_email", return_value="msg-id-456") as send:
        result = handler.lambda_handler({}, None)

    assert result["status"] == "ok"
    sent_text = send.call_args.args[4]
    assert "Traffic data unavailable today" in sent_text


def test_handler_anthropic_failure_still_sends():
    from src import handler

    with patch.object(handler, "get_secrets", return_value=_secrets()), \
         patch.object(handler, "fetch_events", return_value=[_event()]), \
         patch("src.wsdot_client.fetch_alerts", return_value=[_alert()]), \
         patch.object(handler, "match_alerts_to_events",
                      side_effect=RelevanceUnavailableError("api down")), \
         patch.object(handler, "send_email", return_value="msg-id-789") as send:
        result = handler.lambda_handler({}, None)

    assert result["status"] == "ok"
    sent_text = send.call_args.args[4]
    assert "Traffic data unavailable today" in sent_text
