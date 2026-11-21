"""The ops team's alert recipients: saved from the dashboard, else OPS_ALERT_EMAILS from the environment."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db import repo

OPS_EMAILS_KEY = "ops_alert_emails"


def ops_emails(session: Session) -> tuple[list[str], str]:
    """(emails, source): source is "dashboard" when saved in the app, else "environment"."""
    row = repo.get_setting(session, OPS_EMAILS_KEY)
    if row is not None and isinstance(row.value, list):
        return [str(e) for e in row.value], "dashboard"
    return list(get_settings().ops_alert_emails), "environment"
