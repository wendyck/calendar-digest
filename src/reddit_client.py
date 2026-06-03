from __future__ import annotations

import html
import os
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

import requests

from .models import RedditPost, RedditUnavailableError

ATOM_URL = "https://www.reddit.com/user/wsdot/submitted/.rss"
ATOM_NS = {"a": "http://www.w3.org/2005/Atom"}

# Atom <content> bodies that are just the standard "submitted by /u/wsdot" boilerplate
# — these crosspost stubs carry no information beyond the title and should be dropped.
_BOILERPLATE_RE = re.compile(r"submitted by", re.IGNORECASE)

DEFAULT_USER_AGENT = "python:calendar-digest:v0.2 (atom feed reader)"


def fetch_posts(now: datetime, lookback_days: int = 10) -> list[RedditPost]:
    """Fetch recent u/wsdot Atom feed entries.

    Reddit's JSON endpoint returns 403 to anonymous traffic, but the Atom feed
    is still served. Entries are deduped by title (u/wsdot crossposts to many
    subreddits) and filtered to the lookback window.
    """
    cutoff = now - timedelta(days=lookback_days)
    user_agent = os.environ.get("REDDIT_USER_AGENT", DEFAULT_USER_AGENT)

    try:
        response = requests.get(
            ATOM_URL,
            params={"limit": 25},
            headers={"User-Agent": user_agent},
            timeout=10,
        )
        response.raise_for_status()
        root = ET.fromstring(response.content)
    except (requests.RequestException, ET.ParseError) as exc:
        raise RedditUnavailableError(str(exc)) from exc

    seen_titles: set[str] = set()
    posts: list[RedditPost] = []
    for entry in root.findall("a:entry", ATOM_NS):
        title = (entry.findtext("a:title", "", ATOM_NS) or "").strip()
        if not title or title in seen_titles:
            continue
        updated = entry.findtext("a:updated", "", ATOM_NS) or ""
        try:
            posted_at = datetime.fromisoformat(updated.replace("Z", "+00:00"))
        except ValueError:
            continue
        if posted_at.tzinfo is None:
            posted_at = posted_at.replace(tzinfo=timezone.utc)
        if posted_at < cutoff:
            continue

        body = _clean_body(entry.findtext("a:content", "", ATOM_NS) or "")
        if not body or _BOILERPLATE_RE.search(body) and len(body) < 80:
            # Pure crosspost stub ("submitted by /u/wsdot to r/foo [link] [comments]")
            # carries no info; skip.
            continue

        entry_id = (entry.findtext("a:id", "", ATOM_NS) or "").strip()
        link_el = entry.find("a:link", ATOM_NS)
        permalink = link_el.get("href", "") if link_el is not None else ""

        seen_titles.add(title)
        posts.append(
            RedditPost(
                id=entry_id or permalink,
                title=title,
                body=body,
                posted_at=posted_at,
                permalink=permalink,
            )
        )
    return posts


def _clean_body(content_html: str) -> str:
    text = re.sub(r"<[^>]+>", " ", content_html)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    # Trim very long bodies — relevance prompt doesn't need the full essay.
    return text[:1200]
