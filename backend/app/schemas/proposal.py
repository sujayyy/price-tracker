from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.ai.schemas import RepricingDecision


class GuardrailCheck(BaseModel):
    """One pricing rule this proposal was checked against (computed by the backend, not the UI)."""

    key: str
    label: str
    passed: bool | None = Field(description="None = rule not configured for this product")
    detail: str | None = None


class ProposalOut(BaseModel):
    id: int
    product_id: int
    product_title: str
    product_image_url: str | None = None
    our_sku: str | None
    listing_id: int | None = Field(description="The competitor listing whose change led to the proposal")
    marketplace: str | None
    status: str
    action: str
    competitor_price_inr: float | None
    from_price_inr: float
    to_price_inr: float
    final_price_inr: float | None
    change_pct: float
    limited_by: str | None
    floor_price_inr: float | None
    created_at: datetime
    resolved_at: datetime | None
    resolved_by: str | None
    resolution_note: str | None
    decision: RepricingDecision | None
    guardrails: list[GuardrailCheck] = []
    latest_competitor_price_inr: float | None = Field(default=None, description="Lowest competitor price right now")
    latest_checked_at: datetime | None = Field(default=None, description="When competitor data was last fetched")
    competitor_changed: bool = Field(
        default=False, description="The lowest competitor price differs from the proposal's"
    )
    our_price_changed: bool = Field(
        default=False, description="Our price changed since the proposal (approval would be stale)"
    )


class ApproveIn(BaseModel):
    by: str = Field(min_length=1, max_length=100, description="Who approved (shown in the audit log)")
    price_inr: float | None = Field(default=None, gt=0, le=10_000_000, description="Override the proposed price")
    note: str | None = Field(default=None, max_length=500)


class RejectIn(BaseModel):
    by: str = Field(min_length=1, max_length=100)
    note: str | None = Field(default=None, max_length=500)
