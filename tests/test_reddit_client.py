from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from src import reddit_client
from src.models import RedditUnavailableError


class _FakeResponse:
    def __init__(self, content: bytes, status: int = 200):
        self.content = content
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(f"status {self.status_code}")


FIXTURE = Path(__file__).parent / "fixtures" / "reddit_atom.xml"


@patch("src.reddit_client.requests.get")
def test_parses_dedupes_and_filters(get_mock):
    get_mock.return_value = _FakeResponse(FIXTURE.read_bytes())
    now = datetime(2030, 6, 3, tzinfo=timezone.utc)
    posts = reddit_client.fetch_posts(now, lookback_days=10)

    assert len(posts) == 1, [p.title for p in posts]
    post = posts[0]
    assert "Kirkland" in post.title
    assert "fish cross I-405" in post.body
    # HTML entities decoded.
    assert "hasn't" in post.body
    # Crosspost-stub entry (only "submitted by" boilerplate) is dropped.
    assert all("no real body" not in p.title for p in posts)
    # Stale entry outside lookback window is dropped.
    assert all("Way old post" not in p.title for p in posts)


@patch("src.reddit_client.requests.get")
def test_raises_on_http_failure(get_mock):
    import requests
    get_mock.side_effect = requests.ConnectionError("blocked")
    with pytest.raises(RedditUnavailableError):
        reddit_client.fetch_posts(datetime.now(timezone.utc))


@patch("src.reddit_client.requests.get")
def test_user_agent_header_sent(get_mock):
    get_mock.return_value = _FakeResponse(FIXTURE.read_bytes())
    reddit_client.fetch_posts(datetime(2030, 6, 3, tzinfo=timezone.utc))
    headers = get_mock.call_args.kwargs["headers"]
    assert "User-Agent" in headers
    assert "calendar-digest" in headers["User-Agent"]
