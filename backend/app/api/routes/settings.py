"""Team settings the ops team can change from the dashboard (no restart, no .env edit)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.core.config import get_settings
from app.db import repo
from app.deps import SessionDep
from app.schemas.settings import TeamSettingsIn, TeamSettingsOut, TestEmailIn, TestEmailOut
from app.services.notifier import email
from app.services.team import OPS_EMAILS_KEY, ops_emails

router = APIRouter(prefix="/api/settings", tags=["settings"])


def _out(session) -> TeamSettingsOut:
    emails, source = ops_emails(session)
    row = repo.get_setting(session, OPS_EMAILS_KEY)
    s = get_settings()
    return TeamSettingsOut(
        ops_alert_emails=emails,
        source=source,
        updated_at=row.updated_at if row else None,
        updated_by=row.updated_by if row else None,
        email_configured=bool(s.smtp_user and s.smtp_app_password),
        sender=s.smtp_user or None,
    )


@router.get("/team", response_model=TeamSettingsOut)
def get_team(session: SessionDep):
    return _out(session)


@router.put("/team", response_model=TeamSettingsOut)
def save_team(body: TeamSettingsIn, session: SessionDep):
    """Save the ops team's alert emails. Overrides OPS_ALERT_EMAILS from the environment."""
    repo.put_setting(session, OPS_EMAILS_KEY, body.ops_alert_emails, body.updated_by)
    session.commit()
    return _out(session)


@router.delete("/team", response_model=TeamSettingsOut)
def reset_team(session: SessionDep):
    """Forget the saved list and use OPS_ALERT_EMAILS from the environment again."""
    repo.delete_setting(session, OPS_EMAILS_KEY)
    session.commit()
    return _out(session)


@router.post("/team/test-email", response_model=TestEmailOut)
def send_test_email(body: TestEmailIn, session: SessionDep):
    """Send a short test message to the current ops team list."""
    to, _ = ops_emails(session)
    if not to:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Add at least one ops team email first")
    text = (
        f"This is a test from Price Tracker, sent by {body.sent_by}.\n\n"
        "Competitor price alerts and approval requests will arrive at this address.\n"
    )
    html = (
        "<p style='font-family:-apple-system,Segoe UI,sans-serif;font-size:14px;color:#13171e'>"
        f"This is a test from <b>Price Tracker</b>, sent by {body.sent_by}.<br><br>"
        "Competitor price alerts and approval requests will arrive at this address.</p>"
    )
    try:
        email.send_email(", ".join(to), "[Price Tracker] Test alert: your ops team inbox is connected", html, text)
    except email.EmailNotConfigured as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"Email isn't configured: {exc}") from exc
    except Exception as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, f"The mail server refused the message: {type(exc).__name__}"
        ) from exc
    return TestEmailOut(sent_to=to)
