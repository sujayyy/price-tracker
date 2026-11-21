"""ORM models: products (ours) with competitor listings (`tracked_items`), their price readings, AI
decisions, repricing proposals and our price audit log (migrations 0001–0005)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Product(Base):
    """One of OUR products: what we price, with its limits, alert rules and schedule."""

    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint(
            "floor_price_inr IS NULL OR our_price_inr IS NULL OR floor_price_inr <= our_price_inr",
            name="ck_products_floor_le_price",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    title: Mapped[str] = mapped_column(Text)
    our_sku: Mapped[str | None] = mapped_column(Text)
    our_price_inr: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    floor_price_inr: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    max_change_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), server_default=text("10"), default=Decimal("10"))
    undercut_by_inr: Mapped[Decimal] = mapped_column(Numeric(12, 2), server_default=text("0"), default=Decimal("0"))
    auto_apply: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), default=False)
    auto_apply_max_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), server_default=text("3"), default=Decimal("3"))
    # When a competitor reading is worth an alert. NULL min_change_pct = any price change.
    min_change_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    alert_on_stock_change: Mapped[bool] = mapped_column(Boolean, server_default=text("true"), default=True)
    check_every_hours: Mapped[int] = mapped_column(Integer, server_default=text("6"), default=6)
    # Optional extra recipient; alerts always go to OPS_ALERT_EMAILS.
    notify_email: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"), default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TrackedItem(Base):
    """One competitor listing of a product, on one marketplace (table name kept from v1)."""

    __tablename__ = "tracked_items"
    __table_args__ = (
        CheckConstraint("marketplace IN ('amazon_in','flipkart')", name="ck_tracked_items_marketplace"),
        UniqueConstraint("marketplace", "external_id", name="uq_tracked_items_marketplace_external_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    product_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("products.id", ondelete="CASCADE"))
    marketplace: Mapped[str] = mapped_column(Text)
    external_id: Mapped[str] = mapped_column(Text)
    canonical_url: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    variant: Mapped[str | None] = mapped_column(Text)
    # The listing's product photo (thumbnail URL on the marketplace CDN), refreshed on each fetch.
    image_url: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"), default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PriceObservation(Base):
    __tablename__ = "price_observations"
    __table_args__ = (Index("ix_price_obs_item_time", "item_id", text("fetched_at DESC")),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    item_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tracked_items.id", ondelete="CASCADE"))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    price_inr: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    mrp_inr: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    in_stock: Mapped[bool | None] = mapped_column(Boolean)
    seller: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text)
    ok: Mapped[bool] = mapped_column(Boolean)
    error: Mapped[str | None] = mapped_column(Text)


class Decision(Base):
    __tablename__ = "decisions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    product_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("products.id", ondelete="CASCADE"))
    # The listing whose change triggered the decision.
    item_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tracked_items.id", ondelete="CASCADE"))
    trigger_type: Mapped[str] = mapped_column(Text)
    decision: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AlertSent(Base):
    __tablename__ = "alerts_sent"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    item_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("tracked_items.id", ondelete="CASCADE"))
    decision_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("decisions.id"))
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    alert_type: Mapped[str] = mapped_column(Text)


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    items_checked: Mapped[int | None] = mapped_column(Integer)
    agent_invocations: Mapped[int | None] = mapped_column(Integer)
    errors: Mapped[int | None] = mapped_column(Integer)
    notes: Mapped[str | None] = mapped_column(Text)


class RepriceProposal(Base):
    """A recommended change to our price. `thread_id` is the paused LangGraph run that owns it."""

    __tablename__ = "reprice_proposals"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    product_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("products.id", ondelete="CASCADE"))
    # The listing whose change led to the proposal.
    item_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("tracked_items.id", ondelete="CASCADE"))
    decision_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("decisions.id"))
    thread_id: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    action: Mapped[str] = mapped_column(Text)
    competitor_price_inr: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    from_price_inr: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    to_price_inr: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    final_price_inr: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    change_pct: Mapped[Decimal] = mapped_column(Numeric(7, 2))
    limited_by: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_by: Mapped[str | None] = mapped_column(Text)
    resolution_note: Mapped[str | None] = mapped_column(Text)


class OurPriceChange(Base):
    """Audit log: every change to our price, who made it and why."""

    __tablename__ = "our_price_changes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    product_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("products.id", ondelete="CASCADE"))
    old_price_inr: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    new_price_inr: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    source: Mapped[str] = mapped_column(Text)  # manual | approved | auto
    actor: Mapped[str] = mapped_column(Text)
    proposal_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("reprice_proposals.id"))
    note: Mapped[str | None] = mapped_column(Text)


class AppSetting(Base):
    """A dashboard-editable setting that overrides its environment default."""

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[dict | list | str] = mapped_column(JSONB)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_by: Mapped[str | None] = mapped_column(Text)
