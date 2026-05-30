from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    secrets_arn: str
    user_email: str
    calendar_id: str
    lookahead_days: int
    timezone: str
    anthropic_model: str
    log_level: str


def load_config() -> Config:
    return Config(
        secrets_arn=_required("SECRETS_ARN"),
        user_email=_required("USER_EMAIL"),
        calendar_id=os.environ.get("CALENDAR_ID", "primary"),
        lookahead_days=int(os.environ.get("LOOKAHEAD_DAYS", "7")),
        timezone=os.environ.get("TIMEZONE", "America/Los_Angeles"),
        anthropic_model=os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6"),
        log_level=os.environ.get("LOG_LEVEL", "INFO"),
    )


def _required(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value
