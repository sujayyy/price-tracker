from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.ai.schemas import RepricingDecision


class DecisionOut(BaseModel):
    id: int
    product_id: int
    listing_id: int
    marketplace: str | None
    trigger_type: str
    created_at: datetime
    alerted: bool
    decision: RepricingDecision


class RunTrigger(BaseModel):
    product_id: int
    listing_id: int = Field(description="The listing whose change the decision is mainly about")
    trigger: str
    listings_changed: list[int]
    decision_id: int
    action: str
    recommended_price_inr: float | None
    workflow_status: str
    proposal_id: int | None
    proposal_status: str | None
    emailed: bool
    reason: str = Field(description="ok | email_not_configured | email_failed | no_recipients")


class RunOut(BaseModel):
    run_id: int
    items_checked: int = Field(description="Competitor listings fetched")
    agent_invocations: int
    errors: int
    alerts_sent: int
    triggers: list[RunTrigger]


class ActivityOut(BaseModel):
    """One AI decision in the cross-product activity feed."""

    id: int
    product_id: int
    product_title: str
    our_sku: str | None
    listing_id: int
    marketplace: str | None
    trigger_type: str
    created_at: datetime
    alerted: bool
    action: str
    recommended_price_inr: float | None
    competitor_price_inr: float | None
    our_price_inr: float | None
    reasoning: str = ""
    urgency: str | None = None
    market_read: str | None = None
    confidence: float | None = None
    proposal_id: int | None = None
    proposal_status: str | None = None
    resolved_by: str | None = None
