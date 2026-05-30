"""Run the Lambda handler locally for smoke testing.

Expects env vars (or a .env file) for SECRETS_ARN, USER_EMAIL, plus AWS
credentials with access to the secret and to SES in us-west-2.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.handler import lambda_handler  # noqa: E402


if __name__ == "__main__":
    result = lambda_handler({}, None)
    print(json.dumps(result, indent=2))
