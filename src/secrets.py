from __future__ import annotations

import json
from typing import Any

import boto3

KEY_GOOGLE_SA = "google_service_account"
KEY_WSDOT = "wsdot_access_code"
KEY_ANTHROPIC = "anthropic_api_key"

_cache: dict[str, dict[str, Any]] = {}


def get_secrets(arn: str) -> dict[str, Any]:
    """Fetch and cache the JSON object stored in the single Secrets Manager secret.

    Note: the ``google_service_account`` value is itself a JSON string and
    must be parsed again by the caller.
    """
    if arn in _cache:
        return _cache[arn]
    client = boto3.client("secretsmanager")
    response = client.get_secret_value(SecretId=arn)
    parsed = json.loads(response["SecretString"])
    _cache[arn] = parsed
    return parsed


def reset_cache() -> None:
    _cache.clear()
