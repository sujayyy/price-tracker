from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator


class TeamSettingsOut(BaseModel):
    ops_alert_emails: list[str] = Field(description="Where every competitor alert is sent")
    source: Literal["dashboard", "environment"] = Field(description="Saved in the app, or OPS_ALERT_EMAILS from .env")
    updated_at: datetime | None = None
    updated_by: str | None = None
    email_configured: bool = Field(description="Gmail SMTP credentials are set, so alerts can actually be sent")
    sender: str | None = Field(default=None, description="The address alerts are sent from")


class TeamSettingsIn(BaseModel):
    ops_alert_emails: list[EmailStr] = Field(min_length=1, max_length=20)
    updated_by: str = Field(default="dashboard", min_length=1, max_length=100)

    @field_validator("ops_alert_emails")
    @classmethod
    def _dedupe(cls, v: list[str]) -> list[str]:
        return list(dict.fromkeys(str(e).strip().lower() for e in v))


class TestEmailIn(BaseModel):
    sent_by: str = Field(default="dashboard", min_length=1, max_length=100)


class TestEmailOut(BaseModel):
    sent_to: list[str]
