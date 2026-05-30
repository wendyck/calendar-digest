from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
PACIFIC = ZoneInfo("America/Los_Angeles")


@pytest.fixture
def fixed_now() -> datetime:
    # Matches the canonical example digest: Saturday, May 30, 2026 at 5:00 AM PT.
    return datetime(2026, 5, 30, 5, 0, tzinfo=PACIFIC)


@pytest.fixture
def calendar_fixture() -> dict:
    return json.loads((FIXTURES / "calendar_response.json").read_text())


@pytest.fixture
def wsdot_fixture() -> list:
    return json.loads((FIXTURES / "wsdot_alerts.json").read_text())


@pytest.fixture
def claude_match_fixture() -> dict:
    return json.loads((FIXTURES / "claude_match_response.json").read_text())
