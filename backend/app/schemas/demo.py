from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, model_validator

from app.ai.schemas import RepricingDecision
from app.schemas.decision import RunOut


class DemoPriceIn(BaseModel):
    """A simulated competitor reading for one listing. Omit `price_inr` only for an out-of-stock reading."""

    listing_id: int = Field(gt=0)
    price_inr: float | None = Field(default=None, gt=0, le=10_000_000)
    in_stock: bool = True

    @model_validator(mode="after")
    def _price_when_in_stock(self):
        if self.in_stock and self.price_inr is None:
            raise ValueError("price_inr is required when in_stock is true")
        return self


class DemoObservationOut(BaseModel):
    id: int
    fetched_at: datetime
    price_inr: float | None
    mrp_inr: float | None
    in_stock: bool | None
    ok: bool
    source: str


class DemoPriceOut(BaseModel):
    listing_id: int
    product_id: int
    marketplace: str
    simulated_price_inr: float | None
    previous_price_inr: float | None = Field(description="Competitor price right before the simulated reading")
    our_price_before_inr: float | None
    our_price_after_inr: float | None = Field(description="Differs from 'before' only if the change was auto-applied")
    floor_price_inr: float | None
    lowest_price_inr: float | None = Field(description="Lowest competitor price across listings after the reading")
    lowest_marketplace: str | None = None
    observation: DemoObservationOut
    run: RunOut = Field(description="The normal pipeline run for this item: rules, workflow, proposal, email")
    decision: RepricingDecision | None = Field(default=None, description="The AI recommendation, if a rule fired")


class DemoClearOut(BaseModel):
    product_id: int
    deleted_observations: int
