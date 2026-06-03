from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .calendar_client import fetch_events
from .config import load_config
from .digest import build_digest
from .models import RedditUnavailableError, RelevanceUnavailableError, WSDOTUnavailableError
from .relevance import match_alerts_to_events
from .renderers.email_renderer import render_email, render_text
from .secrets import KEY_ANTHROPIC, KEY_GOOGLE_SA, KEY_WSDOT, get_secrets
from .senders.ses_sender import send_email

logger = logging.getLogger(__name__)


def lambda_handler(event, context):  # noqa: ARG001 - Lambda contract
    config = load_config()
    logging.basicConfig(level=config.log_level)

    now = datetime.now(ZoneInfo(config.timezone))
    window_end = now + timedelta(days=config.lookahead_days)

    secrets = get_secrets(config.secrets_arn)
    google_sa = json.loads(secrets[KEY_GOOGLE_SA])  # nested JSON: parse again
    wsdot_code = secrets[KEY_WSDOT]
    anthropic_key = secrets[KEY_ANTHROPIC]

    events = fetch_events(
        google_sa,
        config.user_email,
        config.calendar_id,
        now,
        window_end,
        config.timezone,
    )

    traffic_ok = True
    alerts = []
    matches = []
    reddit_posts = []
    try:
        from .wsdot_client import fetch_alerts  # local import: keeps boto warm-path light
        alerts = fetch_alerts(wsdot_code, window_end)
    except WSDOTUnavailableError as exc:
        logger.warning("WSDOT alerts unavailable: %s", exc)
        traffic_ok = False

    try:
        from .reddit_client import fetch_posts
        reddit_posts = fetch_posts(now)
    except RedditUnavailableError as exc:
        # Reddit is best-effort secondary signal; missing it doesn't mark traffic as unavailable.
        logger.warning("Reddit posts unavailable: %s", exc)

    if alerts or reddit_posts:
        try:
            matches = match_alerts_to_events(
                anthropic_key, config.anthropic_model, events, alerts,
                home_location=config.home_location,
                reddit_posts=reddit_posts,
            )
        except RelevanceUnavailableError as exc:
            logger.warning("Relevance matching unavailable: %s", exc)
            traffic_ok = False

    digest = build_digest(events, alerts, matches, traffic_ok, now, reddit_posts=reddit_posts)
    subject, html_body = render_email(digest)
    text_body = render_text(digest)
    message_id = send_email(
        config.user_email,
        config.user_email,
        subject,
        html_body,
        text_body,
    )

    logger.info(
        json.dumps(
            {
                "event_count": len(events),
                "alert_count": len(alerts),
                "reddit_post_count": len(reddit_posts),
                "match_count": len(matches),
                "traffic_ok": traffic_ok,
                "ses_message_id": message_id,
            }
        )
    )
    return {"status": "ok", "message_id": message_id}
