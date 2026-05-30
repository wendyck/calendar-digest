"""Placeholder for a future user-OAuth fallback flow.

v1 uses a Google Workspace service account with domain-wide delegation, so
this script is intentionally a stub. Kept around so that if/when we add an
OAuth-based auth path (for non-Workspace users or as a fallback), it has a
predictable home.
"""

if __name__ == "__main__":
    raise SystemExit(
        "Not implemented in v1. Calendar access uses a service account; "
        "see README setup runbook."
    )
