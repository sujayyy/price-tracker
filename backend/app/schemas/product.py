from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

from app.ai.schemas import IntakeCandidate, Position


class AlertRulesIn(BaseModel):
    """When a competitor change is worth an ops alert. `min_change_pct=null` = any price change."""

    min_change_pct: float | None = Field(default=None, gt=0, le=95)
    alert_on_stock_change: bool = True
    check_every_hours: int = Field(default=6, ge=1, le=168)


class PricingIn(BaseModel):
    """Our side of the product. Leave `our_price_inr` empty to only watch competitors."""

    our_sku: str | None = Field(default=None, max_length=100)
    our_price_inr: float | None = Field(default=None, gt=0, le=10_000_000)
    floor_price_inr: float | None = Field(default=None, gt=0, le=10_000_000)
    max_change_pct: float = Field(default=10, gt=0, le=50)
    undercut_by_inr: float = Field(default=0, ge=0, le=100_000)
    auto_apply: bool = False
    auto_apply_max_pct: float = Field(default=3, gt=0, le=50)

    @model_validator(mode="after")
    def _floor_below_price(self):
        if self.floor_price_inr is not None and self.our_price_inr is not None:
            if self.floor_price_inr > self.our_price_inr:
                raise ValueError("floor_price_inr must not be above our_price_inr")
        return self


class ListingIn(BaseModel):
    """A competitor listing URL (Amazon.in or Flipkart, including amzn.in short links)."""

    url: str = Field(min_length=8, max_length=2000)
    title: str | None = Field(default=None, max_length=500)


class ProductCreate(BaseModel):
    title: str | None = Field(default=None, max_length=500, description="Defaults to the first listing's title")
    listings: list[ListingIn] = Field(min_length=1, max_length=10)
    rules: AlertRulesIn = AlertRulesIn()
    pricing: PricingIn = PricingIn()
    notify_email: EmailStr | None = None

    @model_validator(mode="after")
    def _distinct_urls(self):
        urls = [x.url.strip() for x in self.listings]
        if len(set(urls)) != len(urls):
            raise ValueError("The same listing URL was given twice")
        return self


# Fields a PATCH may set to null.
CLEARABLE = {"min_change_pct", "our_sku", "our_price_inr", "floor_price_inr", "notify_email"}


class ProductUpdate(BaseModel):
    """PATCH body. Changing `our_price_inr` is recorded in the price audit log (source 'manual')."""

    title: str | None = Field(default=None, min_length=1, max_length=500)
    min_change_pct: float | None = Field(default=None, gt=0, le=95)
    alert_on_stock_change: bool | None = None
    check_every_hours: int | None = Field(default=None, ge=1, le=168)
    notify_email: EmailStr | None = None
    active: bool | None = None
    our_sku: str | None = Field(default=None, max_length=100)
    our_price_inr: float | None = Field(default=None, gt=0, le=10_000_000)
    floor_price_inr: float | None = Field(default=None, gt=0, le=10_000_000)
    max_change_pct: float | None = Field(default=None, gt=0, le=50)
    undercut_by_inr: float | None = Field(default=None, ge=0, le=100_000)
    auto_apply: bool | None = None
    auto_apply_max_pct: float | None = Field(default=None, gt=0, le=50)
    changed_by: str = Field(default="dashboard", min_length=1, max_length=100)


class ListingUpdate(BaseModel):
    active: bool


class ObservationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    fetched_at: datetime
    price_inr: float | None
    mrp_inr: float | None
    in_stock: bool | None
    seller: str | None
    ok: bool
    error: str | None


class ListingOut(BaseModel):
    id: int
    marketplace: str
    external_id: str
    canonical_url: str
    title: str
    active: bool
    image_url: str | None = None
    latest: ObservationOut | None = None
    previous_price_inr: float | None = None
    last_checked_at: datetime | None = None
    is_lowest: bool = False
    suspect: bool = False


class ProposalBrief(BaseModel):
    id: int
    action: str
    from_price_inr: float
    to_price_inr: float
    change_pct: float
    created_at: datetime


class ProductOut(BaseModel):
    id: int
    title: str
    our_sku: str | None
    our_price_inr: float | None
    floor_price_inr: float | None
    max_change_pct: float
    undercut_by_inr: float
    auto_apply: bool
    auto_apply_max_pct: float
    min_change_pct: float | None
    alert_on_stock_change: bool
    check_every_hours: int
    notify_email: str | None
    active: bool
    created_at: datetime
    image_url: str | None = Field(default=None, description="One product photo, taken from a competitor listing")
    listings: list[ListingOut]
    lowest_price_inr: float | None = Field(description="Lowest usable in-stock competitor price across listings")
    lowest_marketplace: str | None = None
    lowest_listing_id: int | None = None
    competitor_in_stock: bool | None = None
    position: Position
    gap_inr: float | None = None
    gap_pct: float | None = None
    pending_proposal: ProposalBrief | None = None
    last_checked_at: datetime | None = None
    sparkline: list[float] = Field(
        default_factory=list, description="Recent prices of the lowest listing, oldest first (for sparklines)"
    )


class HistoryPoint(BaseModel):
    fetched_at: datetime
    price_inr: float | None
    mrp_inr: float | None
    in_stock: bool | None


class HistorySeries(BaseModel):
    listing_id: int
    marketplace: str
    title: str
    points: list[HistoryPoint]


class OurPriceChangeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    old_price_inr: float | None
    new_price_inr: float
    changed_at: datetime
    source: str
    actor: str
    proposal_id: int | None
    note: str | None


class CandidateOut(IntakeCandidate):
    """A search candidate as the dashboard sees it: the agent's candidate plus its photo."""

    image_url: str | None = None


class SearchOut(BaseModel):
    """Candidate competitor listings for one of our products, across marketplaces."""

    query: str
    candidates: list[CandidateOut]
    reasoning: str
    ai_used: bool
    errors: dict[str, str] = {}


class RecheckOut(BaseModel):
    """Result of checking one product's competitor listings right now (the normal pipeline)."""

    checked: int = Field(description="Listings fetched")
    errors: int
    changed: bool = Field(description="A rule fired: a competitor moved since the last reading")
    proposal_replaced: bool = Field(description="The pending proposal was superseded by a newer decision")
    checked_at: datetime
    product: ProductOut


class ListingPreviewIn(BaseModel):
    url: str = Field(min_length=8, max_length=2000)


class ListingPreviewOut(BaseModel):
    """What a listing URL points to, fetched live and not stored."""

    marketplace: str
    external_id: str
    canonical_url: str
    title: str | None
    price_inr: float | None
    in_stock: bool | None
    image_url: str | None = None
    ok: bool
    error: str | None = None
    monitored_by_product_id: int | None = Field(default=None, description="Already monitored under this product")
