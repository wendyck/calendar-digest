from __future__ import annotations

from ..models import Digest


def render_slack(digest: Digest) -> dict:
    """Renders the digest as a Slack Block Kit payload. Not implemented in v1."""
    raise NotImplementedError("Slack rendering planned for v2.")
