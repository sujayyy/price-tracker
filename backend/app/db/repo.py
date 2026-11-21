"""Query functions used by services and routes. All database access goes through here."""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from functools import cache
from typing import Any

from sqlalchemy import BigInteger, Select, bindparam, delete, func, literal, select, true, update
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Session, aliased

from app.ai import ListingSnapshot, build_pricing_context
from app.ai.schemas import (
    HistoryStats,
    ListingInfo,
    ObservationView,
    PricePoint,
    PricingContext,
    ProductSettings,
    RepricingDecision,
)
from app.db.models import (
    AlertSent,
    AppSetting,
    Decision,
    OurPriceChange,
    PriceObservation,
    Product,
    RepriceProposal,
    Run,
    TrackedItem,
)
from app.services.sources.base import FetchResult


def _f(v: Decimal | None) -> float | None:
    return float(v) if v is not None else None


def utcnow() -> datetime:
    return datetime.now(UTC)


# --------------------------------------------------------------------------- products (ours)


def list_products(session: Session) -> list[Product]:
    stmt = select(Product).where(Product.deleted_at.is_(None)).order_by(Product.created_at.desc(), Product.id.desc())
    return list(session.scalars(stmt))


def get_product(session: Session, product_id: int) -> Product | None:
    product = session.get(Product, product_id)
    return product if product is not None and product.deleted_at is None else None


def product_settings(session: Session, product: Product, listings: list[TrackedItem] | None = None) -> ProductSettings:
    """`listings` are the product's active listings, if the caller already has them."""
    listings = listings if listings is not None else product_listings(session, product.id)
    return ProductSettings(
        product_id=product.id,
        title=product.title,
        min_change_pct=_f(product.min_change_pct),
        alert_on_stock_change=product.alert_on_stock_change,
        check_every_hours=product.check_every_hours,
        our_sku=product.our_sku,
        our_price_inr=_f(product.our_price_inr),
        floor_price_inr=_f(product.floor_price_inr),
        max_change_pct=float(product.max_change_pct),
        undercut_by_inr=float(product.undercut_by_inr),
        auto_apply=product.auto_apply,
        auto_apply_max_pct=float(product.auto_apply_max_pct),
        listings=[
            ListingInfo(listing_id=listing.id, marketplace=listing.marketplace, title=listing.title)  # type: ignore[arg-type]
            for listing in listings
        ],
    )


def listing_snapshot(session: Session, listing: TrackedItem) -> ListingSnapshot:
    return snapshot_from(listing, listing_reads(session, [listing.id])[listing.id])


def snapshot_from(listing: TrackedItem, reads: ListingReads, days: int = 90) -> ListingSnapshot:
    latest = reads.latest_ok
    priced = reads.priced[:2]
    return ListingSnapshot(
        listing_id=listing.id,
        marketplace=listing.marketplace,  # type: ignore[arg-type]
        latest=to_view(latest) if latest else None,
        previous_price=next((_f(p) for oid, p in priced if latest is None or oid != latest.id), None),
        last_known_price=_f(priced[0][1]) if priced else None,
        stats=stats_from(listing.id, days, reads),
    )


def pricing_context(session: Session, product: Product) -> PricingContext:
    """Our price vs every active listing, with the moves the guardrails allow."""
    return pricing_contexts(session, [product])[product.id]


def pricing_contexts(
    session: Session,
    products: list[Product],
    *,
    listings: dict[int, list[TrackedItem]] | None = None,
    reads: dict[int, ListingReads] | None = None,
) -> dict[int, PricingContext]:
    """`pricing_context` for many products in a fixed number of queries. Pass `listings` (from
    `listings_by_product`, paused included or not) and `reads` if the caller already has them."""
    if listings is None:
        listings = listings_by_product(session, [p.id for p in products])
    active = {p.id: [x for x in listings.get(p.id, []) if x.active] for p in products}
    if reads is None:
        reads = listing_reads(session, [x.id for xs in active.values() for x in xs])
    return {
        p.id: build_pricing_context(
            p.id,
            product_settings(session, p, active[p.id]),
            [snapshot_from(x, reads[x.id]) for x in active[p.id]],
        )
        for p in products
    }


# --------------------------------------------------------------------------- competitor listings


def get_listing(session: Session, listing_id: int) -> TrackedItem | None:
    listing = session.get(TrackedItem, listing_id)
    return listing if listing is not None and listing.deleted_at is None else None


def get_listing_by_external_id(session: Session, marketplace: str, external_id: str) -> TrackedItem | None:
    stmt = select(TrackedItem).where(TrackedItem.marketplace == marketplace, TrackedItem.external_id == external_id)
    return session.scalars(stmt).first()


def product_listings(session: Session, product_id: int, *, include_paused: bool = False) -> list[TrackedItem]:
    return listings_by_product(session, [product_id], include_paused=include_paused)[product_id]


def listings_by_product(
    session: Session, product_ids: list[int], *, include_paused: bool = False
) -> dict[int, list[TrackedItem]]:
    """Each product's listings (oldest first) in one query."""
    out: dict[int, list[TrackedItem]] = {pid: [] for pid in product_ids}
    if not out:
        return out
    stmt = select(TrackedItem).where(TrackedItem.product_id.in_(list(out)), TrackedItem.deleted_at.is_(None))
    if not include_paused:
        stmt = stmt.where(TrackedItem.active.is_(True))
    for listing in session.scalars(stmt.order_by(TrackedItem.id)):
        out[listing.product_id].append(listing)
    return out


def _monitored():
    """Listings the scheduler may fetch: listing and product both active and not deleted."""
    return (
        select(TrackedItem)
        .join(Product, Product.id == TrackedItem.product_id)
        .where(
            TrackedItem.active.is_(True),
            TrackedItem.deleted_at.is_(None),
            Product.active.is_(True),
            Product.deleted_at.is_(None),
        )
    )


def due_listings(session: Session, now: datetime | None = None) -> list[TrackedItem]:
    """Monitored listings whose last fetch is older than their product's check interval."""
    now = now or utcnow()
    last_fetch = (
        select(PriceObservation.item_id, func.max(PriceObservation.fetched_at).label("last"))
        .group_by(PriceObservation.item_id)
        .subquery()
    )
    stmt = (
        _monitored()
        .outerjoin(last_fetch, last_fetch.c.item_id == TrackedItem.id)
        .where(
            (last_fetch.c.last.is_(None))
            # 5 min of slack so an hourly scheduler doesn't skip a listing fetched at :00:03.
            | (
                last_fetch.c.last
                <= literal(now + timedelta(minutes=5)) - func.make_interval(0, 0, 0, 0, Product.check_every_hours)
            ),
        )
        .order_by(TrackedItem.product_id, TrackedItem.id)
    )
    return list(session.scalars(stmt))


def active_listings(session: Session) -> list[TrackedItem]:
    return list(session.scalars(_monitored().order_by(TrackedItem.product_id, TrackedItem.id)))


# --------------------------------------------------------------------------- observations


def add_observation(session: Session, item_id: int, result: FetchResult) -> PriceObservation:
    obs = PriceObservation(
        item_id=item_id,
        price_inr=result.price_inr,
        mrp_inr=result.mrp_inr,
        in_stock=result.in_stock,
        seller=result.seller,
        source=result.source,
        ok=result.ok,
        error=result.error,
    )
    session.add(obs)
    # Keep the listing's photo current (simulated and failed readings carry none).
    if result.ok and result.image_url:
        listing = session.get(TrackedItem, item_id)
        if listing is not None and listing.image_url != result.image_url:
            listing.image_url = result.image_url
    session.flush()
    session.refresh(obs)
    return obs


def delete_observations_by_source(session: Session, listing_ids: list[int], source: str) -> int:
    """Delete listings' observations from one source (e.g. simulated 'demo' readings). Returns the count."""
    stmt = delete(PriceObservation).where(PriceObservation.item_id.in_(listing_ids), PriceObservation.source == source)
    return session.execute(stmt).rowcount


def to_view(obs: PriceObservation) -> ObservationView:
    return ObservationView(
        listing_id=obs.item_id,
        fetched_at=obs.fetched_at,
        price_inr=_f(obs.price_inr),
        mrp_inr=_f(obs.mrp_inr),
        in_stock=obs.in_stock,
        seller=obs.seller,
        source=obs.source,
        ok=obs.ok,
        error=obs.error,
    )


def latest_observation(session: Session, item_id: int, *, ok_only: bool = False) -> PriceObservation | None:
    stmt = select(PriceObservation).where(PriceObservation.item_id == item_id)
    if ok_only:
        stmt = stmt.where(PriceObservation.ok.is_(True))
    return session.scalars(
        stmt.order_by(PriceObservation.fetched_at.desc(), PriceObservation.id.desc()).limit(1)
    ).first()


def latest_observations(session: Session, item_id: int, n: int) -> list[PriceObservation]:
    stmt = (
        select(PriceObservation)
        .where(PriceObservation.item_id == item_id)
        .order_by(PriceObservation.fetched_at.desc(), PriceObservation.id.desc())
        .limit(n)
    )
    return list(session.scalars(stmt))


def previous_ok_observation(session: Session, item_id: int, before: PriceObservation) -> PriceObservation | None:
    stmt = (
        select(PriceObservation)
        .where(
            PriceObservation.item_id == item_id,
            PriceObservation.ok.is_(True),
            PriceObservation.id != before.id,
            PriceObservation.fetched_at <= before.fetched_at,
        )
        .order_by(PriceObservation.fetched_at.desc(), PriceObservation.id.desc())
        .limit(1)
    )
    return session.scalars(stmt).first()


def consecutive_failures(session: Session, item_id: int, limit: int = 50) -> int:
    count = 0
    for obs in latest_observations(session, item_id, limit):
        if obs.ok:
            break
        count += 1
    return count


def history_points(session: Session, item_id: int, days: int) -> list[PriceObservation]:
    stmt = (
        select(PriceObservation)
        .where(
            PriceObservation.item_id == item_id,
            PriceObservation.ok.is_(True),
            PriceObservation.fetched_at >= utcnow() - timedelta(days=days),
        )
        .order_by(PriceObservation.fetched_at.asc())
    )
    return list(session.scalars(stmt))


def history_stats(session: Session, item_id: int, days: int = 90) -> HistoryStats:
    """Stats over successful readings, excluding the most recent one (see HistoryStats)."""
    return stats_from(item_id, days, listing_reads(session, [item_id], days=days, series=False)[item_id])


def stats_from(item_id: int, days: int, reads: ListingReads) -> HistoryStats:
    latest = reads.latest_ok
    window = [float(p) for p, t in reads.prior if t >= reads.now - timedelta(days=days)]
    last30 = [float(p) for p, t in reads.prior if t >= reads.now - timedelta(days=30)]
    recent = [o for o in reads.recent[:RECENT_READINGS] if o.ok][:10]
    atl, ath = reads.low_high
    latest_price = _f(latest.price_inr) if latest else None
    return HistoryStats(
        listing_id=item_id,
        window_days=days,
        points_in_window=len(window),
        min_inr=min(window) if window else None,
        median_inr=statistics.median(window) if window else None,
        max_inr=max(window) if window else None,
        median_30d_inr=statistics.median(last30) if last30 else None,
        all_time_low_inr=_f(atl),
        all_time_high_inr=_f(ath),
        latest_price_inr=latest_price,
        prior_readings_at_latest_price=window.count(latest_price) if latest_price is not None else None,
        recent_points=[
            PricePoint(fetched_at=o.fetched_at, price_inr=_f(o.price_inr), in_stock=o.in_stock) for o in recent
        ],
    )


# --------------------------------------------------------------------------- per-listing reads, batched
#
# Lists (products, proposals, monitoring) show each listing's latest reading, history stats and
# sparkline. Read one listing at a time that was ~9 round trips per listing (1,800 for
# /api/products with 100 products); `listing_reads` gets all of it in at most five queries, however
# many listings there are. The single-listing helpers above call it too, so the numbers come from one
# code path; for a single listing the queries are the plain indexed ones (see perf/REPORT.md).

RECENT_READINGS = 20  # newest readings kept per listing (any outcome)
SERIES_READINGS = 24  # newest priced readings kept per listing (sparkline, previous price)
_NEWEST = (PriceObservation.fetched_at.desc(), PriceObservation.id.desc())


@dataclass
class ListingReads:
    now: datetime
    recent: list[PriceObservation] = field(default_factory=list)  # newest first, any outcome
    latest_ok: PriceObservation | None = None
    priced: list[tuple[int, Decimal]] = field(default_factory=list)  # newest first: (id, price), ok + priced
    low_high: tuple[Decimal | None, Decimal | None] = (None, None)  # all-time, latest ok reading excluded
    prior: list[tuple[Decimal, datetime]] = field(default_factory=list)  # (price, at) in the stats window, ditto


_FILTERS = {
    "any": (),
    "ok": (PriceObservation.ok.is_(True),),
    "priced": (PriceObservation.ok.is_(True), PriceObservation.price_inr.is_not(None)),
}


@cache
def _newest(n: int, which: str, many: bool) -> Select:
    """Each listing's newest `n` readings (filter `which`), newest first per listing.

    One listing (the scheduler and the AI tools ask for one at a time) is a plain indexed
    `ORDER BY … LIMIT n` on :item_id. Several are `unnest(:item_ids)` with a LATERAL `… LIMIT n` per
    id, so each listing still walks the (item_id, fetched_at) index instead of sorting every reading.
    Built once per shape: building the aliased ORM query costs more than running it.
    """
    where = _FILTERS[which]
    if not many:
        stmt = select(PriceObservation).where(PriceObservation.item_id == bindparam("item_id"), *where)
        return _columns(PriceObservation, stmt.order_by(*_NEWEST).limit(n), which)
    listing = func.unnest(bindparam("item_ids", type_=ARRAY(BigInteger))).table_valued("item_id").render_derived()
    top = (
        select(PriceObservation)
        .where(PriceObservation.item_id == listing.c.item_id, *where)
        .order_by(*_NEWEST)
        .limit(n)
        .lateral()
    )
    row = aliased(PriceObservation, top)
    stmt = select(row).select_from(listing).join(top, true())
    return _columns(row, stmt.order_by(row.item_id, row.fetched_at.desc(), row.id.desc()), which)


def _columns(row: Any, stmt: Select, which: str) -> Select:
    """Priced readings only feed sparklines and previous prices: (item_id, id, price) rows, not objects."""
    return stmt.with_only_columns(row.item_id, row.id, row.price_inr) if which == "priced" else stmt


def listing_reads(
    session: Session, item_ids: list[int], *, days: int = 90, series: bool = True
) -> dict[int, ListingReads]:
    """`series=False` skips the priced readings (sparkline, previous price) when only stats are needed."""
    now = utcnow()
    reads = {i: ListingReads(now=now) for i in dict.fromkeys(item_ids)}
    if not reads:
        return reads
    ids = list(reads)
    ok = PriceObservation.ok.is_(True)
    priced = _FILTERS["priced"]
    many = len(ids) > 1
    params = {"item_ids": ids} if many else {"item_id": ids[0]}

    for obs in session.scalars(_newest(RECENT_READINGS, "any", many), params):
        reads[obs.item_id].recent.append(obs)
    for obs in session.scalars(_newest(1, "ok", many), params):
        reads[obs.item_id].latest_ok = obs
    if series:
        for item_id, oid, price in session.execute(_newest(SERIES_READINGS, "priced", many), params):
            reads[item_id].priced.append((oid, price))

    # Ids are unique across listings, so excluding every listing's latest ok reading at once
    # excludes exactly each listing's own.
    latest_ids = [r.latest_ok.id for r in reads.values() if r.latest_ok]
    not_latest = (
        PriceObservation.id != latest_ids[0] if len(latest_ids) == 1 else PriceObservation.id.not_in(latest_ids)
    )
    of_ids = PriceObservation.item_id == ids[0] if len(ids) == 1 else PriceObservation.item_id.in_(ids)
    rows = session.execute(
        select(PriceObservation.item_id, func.min(PriceObservation.price_inr), func.max(PriceObservation.price_inr))
        .where(of_ids, ok, not_latest)
        .group_by(PriceObservation.item_id)
    )
    for item_id, low, high in rows:
        reads[item_id].low_high = (low, high)
    rows = session.execute(
        select(PriceObservation.item_id, PriceObservation.price_inr, PriceObservation.fetched_at).where(
            of_ids, *priced, not_latest, PriceObservation.fetched_at >= now - timedelta(days=max(days, 30))
        )
    )
    for item_id, price, at in rows:
        reads[item_id].prior.append((price, at))
    return reads


def failure_streak(session: Session, item_id: int, reads: ListingReads) -> int:
    """`consecutive_failures` from already-read readings; reads further only if all were failures."""
    streak = next((i for i, o in enumerate(reads.recent) if o.ok), None)
    if streak is not None:
        return streak
    if len(reads.recent) < RECENT_READINGS:
        return len(reads.recent)
    return consecutive_failures(session, item_id)


def series_from(reads: ListingReads, n: int = SERIES_READINGS) -> list[float]:
    """`price_series` from already-read readings."""
    return [float(p) for _, p in reversed(reads.priced[:n])]


# --------------------------------------------------------------------------- decisions & alerts


def add_decision(
    session: Session, product_id: int, listing_id: int, trigger_type: str, decision: RepricingDecision
) -> Decision:
    row = Decision(
        product_id=product_id,
        item_id=listing_id,
        trigger_type=trigger_type,
        decision=decision.model_dump(mode="json"),
    )
    session.add(row)
    session.flush()
    return row


def decisions_for_product(session: Session, product_id: int, limit: int = 50) -> list[Decision]:
    stmt = (
        select(Decision)
        .where(Decision.product_id == product_id)
        .order_by(Decision.created_at.desc(), Decision.id.desc())
        .limit(limit)
    )
    return list(session.scalars(stmt))


def recent_decisions(session: Session, *, days: int = 14, limit: int = 200) -> list[Decision]:
    """Decisions across all monitored products, newest first (the activity feed)."""
    stmt = (
        select(Decision)
        .join(Product, Product.id == Decision.product_id)
        .where(Product.deleted_at.is_(None), Decision.created_at >= utcnow() - timedelta(days=days))
        .order_by(Decision.created_at.desc(), Decision.id.desc())
        .limit(limit)
    )
    return list(session.scalars(stmt))


def price_series(session: Session, listing_id: int, n: int = 24) -> list[float]:
    """The listing's last `n` priced readings, oldest first (for sparklines)."""
    stmt = (
        select(PriceObservation.price_inr)
        .where(
            PriceObservation.item_id == listing_id,
            PriceObservation.ok.is_(True),
            PriceObservation.price_inr.is_not(None),
        )
        .order_by(PriceObservation.fetched_at.desc(), PriceObservation.id.desc())
        .limit(n)
    )
    return [float(p) for p in reversed(session.scalars(stmt).all())]


def alerted_decision_ids(session: Session, decision_ids: list[int]) -> set[int]:
    if not decision_ids:
        return set()
    stmt = select(AlertSent.decision_id).where(AlertSent.decision_id.in_(decision_ids))
    return {d for d in session.scalars(stmt) if d is not None}


def add_alert(session: Session, item_id: int, decision_id: int | None, alert_type: str) -> AlertSent:
    row = AlertSent(item_id=item_id, decision_id=decision_id, alert_type=alert_type)
    session.add(row)
    session.flush()
    return row


# --------------------------------------------------------------------------- proposals & our price


def add_proposal(session: Session, **fields) -> RepriceProposal:
    row = RepriceProposal(**fields)
    session.add(row)
    session.flush()
    return row


def get_proposal(session: Session, proposal_id: int, *, for_update: bool = False) -> RepriceProposal | None:
    stmt = select(RepriceProposal).where(RepriceProposal.id == proposal_id)
    return session.scalars(stmt.with_for_update() if for_update else stmt).first()


def list_proposals(
    session: Session, *, status: str | None = None, product_id: int | None = None, limit: int = 100
) -> list[RepriceProposal]:
    stmt = select(RepriceProposal).join(Product, Product.id == RepriceProposal.product_id)
    stmt = stmt.where(Product.deleted_at.is_(None))
    if status:
        stmt = stmt.where(RepriceProposal.status == status)
    if product_id is not None:
        stmt = stmt.where(RepriceProposal.product_id == product_id)
    return list(
        session.scalars(stmt.order_by(RepriceProposal.created_at.desc(), RepriceProposal.id.desc()).limit(limit))
    )


def pending_proposals_by_product(session: Session, product_ids: list[int]) -> dict[int, RepriceProposal]:
    """The newest pending proposal per product."""
    if not product_ids:
        return {}
    stmt = (
        select(RepriceProposal)
        .where(RepriceProposal.product_id.in_(product_ids), RepriceProposal.status == "pending")
        .order_by(RepriceProposal.created_at.asc(), RepriceProposal.id.asc())
    )
    return {p.product_id: p for p in session.scalars(stmt)}


def supersede_pending(session: Session, product_id: int, reason: str) -> int:
    """Close a product's open proposals: newer data (or a manual change) made them obsolete."""
    stmt = (
        update(RepriceProposal)
        .where(RepriceProposal.product_id == product_id, RepriceProposal.status == "pending")
        .values(status="superseded", resolved_at=utcnow(), resolved_by="system", resolution_note=reason)
    )
    return session.execute(stmt).rowcount


def add_price_change(session: Session, **fields) -> OurPriceChange:
    row = OurPriceChange(**fields)
    session.add(row)
    session.flush()
    return row


def price_changes_for_product(session: Session, product_id: int, limit: int = 200) -> list[OurPriceChange]:
    stmt = (
        select(OurPriceChange)
        .where(OurPriceChange.product_id == product_id)
        .order_by(OurPriceChange.changed_at.desc(), OurPriceChange.id.desc())
        .limit(limit)
    )
    return list(session.scalars(stmt))


# --------------------------------------------------------------------------- app settings


def get_setting(session: Session, key: str) -> AppSetting | None:
    return session.get(AppSetting, key)


def put_setting(session: Session, key: str, value, updated_by: str | None) -> AppSetting:
    row = session.get(AppSetting, key) or AppSetting(key=key)
    row.value = value
    row.updated_by = updated_by
    row.updated_at = utcnow()
    session.add(row)
    session.flush()
    return row


def delete_setting(session: Session, key: str) -> None:
    session.execute(delete(AppSetting).where(AppSetting.key == key))


# --------------------------------------------------------------------------- runs


def start_run(session: Session) -> Run:
    run = Run(items_checked=0, agent_invocations=0, errors=0)
    session.add(run)
    session.flush()
    return run


def finish_run(
    session: Session, run: Run, *, items_checked: int, agent_invocations: int, errors: int, notes: str | None
) -> None:
    session.execute(
        update(Run)
        .where(Run.id == run.id)
        .values(
            finished_at=utcnow(),
            items_checked=items_checked,
            agent_invocations=agent_invocations,
            errors=errors,
            notes=notes,
        )
    )


def agent_invocations_since(session: Session, since: datetime) -> int:
    return int(
        session.scalar(select(func.coalesce(func.sum(Run.agent_invocations), 0)).where(Run.started_at >= since)) or 0
    )


def recent_runs(session: Session, limit: int = 20) -> list[Run]:
    return list(session.scalars(select(Run).order_by(Run.started_at.desc()).limit(limit)))
