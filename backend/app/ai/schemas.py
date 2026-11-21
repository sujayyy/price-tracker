"""Structured types for the AI layer.

The agents' outputs (`RepricingDecision`, `IntakeResolution`) are validated Pydantic models,
never free text. The remaining models describe what tools return to the agent (produced by the
backend through the `DataProvider` protocol in `app.ai.provider`) and what the repricing
workflow hands back to the backend.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, Field, HttpUrl, computed_field

Marketplace = Literal["amazon_in", "flipkart"]
# What the rules gate saw happen to the competitor's listing.
TriggerType = Literal["price_drop", "price_increase", "out_of_stock", "back_in_stock", "needs_attention"]
EventType = Literal["price_drop", "price_increase", "out_of_stock", "back_in_stock", "needs_attention", "none"]
PriceAction = Literal["lower_price", "raise_price", "hold", "investigate"]
MarketRead = Literal["sustained_change", "flash_sale", "data_glitch", "stock_change", "minor_fluctuation", "unknown"]


def _http_url(value: str) -> str:
    return str(HttpUrl(value))


# Validated like HttpUrl but kept as a plain str: LangGraph's checkpoint serializer can't store Url objects.
HttpUrlStr = Annotated[str, AfterValidator(_http_url)]


# --------------------------------------------------------------------------- agent outputs


class RepricingDecision(BaseModel):
    """The analyst's recommendation for one product after a competitor event. Code enforces it; a human approves it."""

    product_id: int
    event: EventType
    competitor_price_inr: float | None = Field(description="The lowest in-stock competitor price (the reference).")
    our_price_inr: float | None
    action: PriceAction
    recommended_price_inr: float | None = Field(
        description="The price_inr of the chosen option from get_pricing_context. null for hold and investigate."
    )
    market_read: MarketRead = Field(description="What the competitor's move most likely is.")
    urgency: Literal["high", "medium", "low"]
    reasoning: str = Field(max_length=600, description="At most 3 sentences, citing a number.")
    confidence: float = Field(ge=0, le=1)
    data_issues: list[str] = []


class IntakeCandidate(BaseModel):
    marketplace: Marketplace
    external_id: str
    title: str
    price_inr: float | None
    url: HttpUrlStr
    match_score: float = Field(ge=0, le=1)


class IntakeResolution(BaseModel):
    resolved: bool
    needs_confirmation: bool
    chosen: IntakeCandidate | None = None
    candidates: list[IntakeCandidate] = []
    reasoning: str


# --------------------------------------------------------------------------- tool payloads


class ObservationView(BaseModel):
    """One stored (or freshly re-fetched) competitor price reading."""

    listing_id: int
    fetched_at: datetime
    price_inr: float | None
    mrp_inr: float | None
    in_stock: bool | None
    seller: str | None
    source: str
    ok: bool
    error: str | None = None


class PricePoint(BaseModel):
    fetched_at: datetime
    price_inr: float | None
    in_stock: bool | None


class HistoryStats(BaseModel):
    """Summary of an item's price history — deliberately not raw rows.

    Every statistic EXCLUDES the most recent observation, so the latest price can be
    compared against what came before it. `None` means there was no prior data.
    """

    listing_id: int
    window_days: int
    points_in_window: int
    min_inr: float | None
    median_inr: float | None
    max_inr: float | None
    median_30d_inr: float | None
    all_time_low_inr: float | None
    all_time_high_inr: float | None
    latest_price_inr: float | None
    prior_readings_at_latest_price: int | None = Field(
        default=None,
        description="How many earlier readings in the window had exactly the latest price. "
        "Two or more means the latest price is a level the item has sat at before.",
    )
    recent_points: list[PricePoint] = Field(
        default_factory=list, description="Up to 10 most recent readings, newest first."
    )
    note: str = "All statistics exclude the most recent observation."

    @computed_field
    @property
    def latest_vs_all_time_low(self) -> Literal["new_low", "equals_low", "above_low", "unknown"]:
        """Precomputed so the model never has to compare the two numbers itself."""
        if self.latest_price_inr is None or self.all_time_low_inr is None:
            return "unknown"
        if self.latest_price_inr < self.all_time_low_inr:
            return "new_low"
        if self.latest_price_inr == self.all_time_low_inr:
            return "equals_low"
        return "above_low"


class AlertRules(BaseModel):
    """When a competitor reading is worth an ops alert. `min_change_pct=None` means any price change."""

    min_change_pct: float | None = None
    alert_on_stock_change: bool = True
    check_every_hours: int = 6


class PricingRules(BaseModel):
    """Our side of the listing: our price and the limits any price change must respect."""

    our_sku: str | None = None
    our_price_inr: float | None = None
    floor_price_inr: float | None = Field(default=None, description="Never sell below this (cost + minimum margin).")
    max_change_pct: float = Field(default=10, description="Largest single price move, up or down.")
    undercut_by_inr: float = Field(default=0, description="Price this much below the competitor; 0 = match.")
    auto_apply: bool = False
    auto_apply_max_pct: float = Field(default=3, description="Auto-apply only moves at most this large.")


class ListingInfo(BaseModel):
    listing_id: int
    marketplace: Marketplace
    title: str


class ProductSettings(AlertRules, PricingRules):
    """Our product and the competitor listings it is compared against."""

    product_id: int
    title: str
    listings: list[ListingInfo] = []


class PriceOption(BaseModel):
    """One allowed move, already priced and clamped by the guardrails."""

    action: Literal["lower_price", "raise_price", "hold"]
    price_inr: float
    change_pct: float = Field(description="Change vs our current price, in percent (negative = cheaper).")
    limited_by: Literal["floor", "max_change"] | None = None
    gap_after_inr: float | None = Field(
        default=None,
        description="Our price minus the lowest competitor's after this move. Positive = we would still be ABOVE them.",
    )
    note: str


Position = Literal["we_are_cheaper", "we_are_pricier", "same_price", "competitor_unavailable", "our_price_not_set"]
Trend = Literal["down", "up", "flat", "unknown"]


class CompetitorView(BaseModel):
    """One competitor listing's latest state, as the pricing context sees it."""

    listing_id: int
    marketplace: Marketplace
    price_inr: float | None
    in_stock: bool | None
    previous_price_inr: float | None
    change_pct: float | None = Field(description="Latest vs previous price, in percent (negative = cheaper).")
    trend: Trend
    suspect: bool = Field(description="The latest price is far outside this listing's history; ignored for pricing.")
    is_reference: bool = Field(description="True for the lowest usable in-stock price, the one we price against.")


class PricingContext(BaseModel):
    """Our price vs the lowest competitor across every platform, plus every move the guardrails
    allow. Precomputed so the model chooses between options instead of doing arithmetic."""

    product_id: int
    our_sku: str | None
    our_price_inr: float | None
    floor_price_inr: float | None
    max_change_pct: float
    undercut_by_inr: float
    auto_apply: bool
    auto_apply_max_pct: float
    competitors: list[CompetitorView] = Field(description="Every monitored listing, on every platform.")
    reference_listing_id: int | None = None
    reference_marketplace: Marketplace | None = None
    competitor_price_inr: float | None = Field(description="Lowest usable in-stock competitor price; null if none.")
    competitor_in_stock: bool | None = Field(description="True if any competitor is in stock, False if all are out.")
    last_known_competitor_price_inr: float | None
    competitor_previous_price_inr: float | None = Field(
        default=None, description="The reference listing's priced reading before its latest one."
    )
    competitor_trend: Trend = Field(
        default="unknown", description="'down' if ANY competitor just cut its price, else the reference's direction."
    )
    competitor_change_pct: float | None = Field(
        default=None, description="The reference listing's latest vs previous price, in percent."
    )
    position: Position
    gap_inr: float | None = Field(description="Our price minus the competitor's (positive = we are pricier).")
    gap_pct: float | None = Field(description="gap_inr as a percent of the competitor's price.")
    options: list[PriceOption]
    note: str = (
        "Choose action from options. recommended_price_inr must equal that option's price_inr. "
        "investigate is always allowed and never changes the price."
    )


# --------------------------------------------------------------------------- workflow payloads


class Proposal(BaseModel):
    """A price change waiting for (or past) approval."""

    action: Literal["lower_price", "raise_price"]
    from_price_inr: float
    to_price_inr: float
    change_pct: float
    competitor_price_inr: float | None
    limited_by: Literal["floor", "max_change"] | None = None


class ReviewAnswer(BaseModel):
    """What the ops reviewer sent back. `price_inr` overrides the proposed price."""

    approved: bool
    by: str = Field(min_length=1, max_length=100)
    price_inr: float | None = Field(default=None, gt=0)
    note: str | None = Field(default=None, max_length=500)


WorkflowStatus = Literal["no_change", "pending_review", "auto_approved", "approved", "rejected", "stale", "invalid"]


class RepricingOutcome(BaseModel):
    """Where one repricing workflow run ended up. The backend acts on this; the workflow never writes."""

    thread_id: str
    decision: RepricingDecision
    status: WorkflowStatus
    proposal: Proposal | None = None
    final_price_inr: float | None = None
    reason: str | None = None
