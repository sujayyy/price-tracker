"""Creating products, attaching competitor listings, and presenting them."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy.orm import Session

from app.ai.schemas import PricingContext
from app.db import repo
from app.db.models import Product, RepriceProposal, TrackedItem
from app.schemas.product import (
    AlertRulesIn,
    ListingOut,
    ObservationOut,
    PricingIn,
    ProductCreate,
    ProductOut,
    ProposalBrief,
)
from app.services import pricing
from app.services.sources import source_for_url


class ListingAlreadyTracked(Exception):
    def __init__(self, listing_id: int, product_id: int):
        super().__init__(f"This listing is already monitored (product {product_id})")
        self.listing_id = listing_id
        self.product_id = product_id


def _dec(v: float | None) -> Decimal | None:
    return Decimal(str(v)) if v is not None else None


def _num(v: Decimal | None) -> float | None:
    return float(v) if v is not None else None


def attach_listing(session: Session, product: Product, url: str, title: str | None = None) -> TrackedItem:
    """Parse the URL, fetch once for the title and first reading, and attach it to the product.

    Raises UnsupportedURL or ListingAlreadyTracked. A listing that was removed (or whose
    product was deleted) is revived under this product with its history intact.
    """
    source = source_for_url(url)
    ref = source.parse_url(url)
    existing = repo.get_listing_by_external_id(session, ref.marketplace, ref.external_id)
    if existing is not None and existing.deleted_at is None:
        owner = session.get(Product, existing.product_id)
        if owner is not None and owner.deleted_at is None:
            raise ListingAlreadyTracked(existing.id, existing.product_id)

    result = source.fetch(ref)
    listing = existing or TrackedItem(marketplace=ref.marketplace, external_id=ref.external_id)
    listing.product_id = product.id
    listing.canonical_url = ref.canonical_url
    listing.title = title or result.title or f"{ref.marketplace} {ref.external_id}"
    listing.active = True
    listing.deleted_at = None
    session.add(listing)
    session.flush()
    repo.add_observation(session, listing.id, result)
    return listing


def apply_settings(product: Product, rules: AlertRulesIn, settings: PricingIn) -> None:
    product.min_change_pct = _dec(rules.min_change_pct)
    product.alert_on_stock_change = rules.alert_on_stock_change
    product.check_every_hours = rules.check_every_hours
    product.our_sku = settings.our_sku
    product.floor_price_inr = _dec(settings.floor_price_inr)
    product.max_change_pct = Decimal(str(settings.max_change_pct))
    product.undercut_by_inr = Decimal(str(settings.undercut_by_inr))
    product.auto_apply = settings.auto_apply
    product.auto_apply_max_pct = Decimal(str(settings.auto_apply_max_pct))


def create_product(session: Session, body: ProductCreate) -> Product:
    """Create our product and attach every competitor listing (all or nothing)."""
    for listing in body.listings:  # fail fast on a bad URL, before any fetch
        source_for_url(listing.url.strip())
    product = Product(title=body.title or "New product", notify_email=body.notify_email, active=True)
    apply_settings(product, body.rules, body.pricing)
    session.add(product)
    session.flush()
    listings = [attach_listing(session, product, x.url.strip(), x.title) for x in body.listings]
    if not body.title:
        product.title = listings[0].title
    if body.pricing.our_price_inr is not None:
        pricing.set_our_price(
            session, product, body.pricing.our_price_inr, source="manual", actor="setup", note="Initial price"
        )
    session.commit()
    return product


def brief(p: RepriceProposal | None) -> ProposalBrief | None:
    if p is None:
        return None
    return ProposalBrief(
        id=p.id,
        action=p.action,
        from_price_inr=float(p.from_price_inr),
        to_price_inr=float(p.to_price_inr),
        change_pct=float(p.change_pct),
        created_at=p.created_at,
    )


def product_image_url(listings) -> str | None:
    """One photo for our product: an active listing's, Amazon's first (usually the cleanest shot)."""
    ordered = sorted(listings, key=lambda x: (not x.active, x.marketplace != "amazon_in", x.id))
    return next((x.image_url for x in ordered if x.image_url), None)


def listing_out(
    listing: TrackedItem, reads: repo.ListingReads, is_lowest: bool = False, suspect: bool = False
) -> ListingOut:
    recent = reads.recent[:10]
    latest_ok = next((o for o in recent if o.ok), None)
    prev_ok = next((o for o in recent if o.ok and o is not latest_ok and o.price_inr is not None), None)
    return ListingOut(
        id=listing.id,
        marketplace=listing.marketplace,
        external_id=listing.external_id,
        canonical_url=listing.canonical_url,
        title=listing.title,
        active=listing.active,
        image_url=listing.image_url,
        latest=ObservationOut.model_validate(latest_ok) if latest_ok else None,
        previous_price_inr=float(prev_ok.price_inr) if prev_ok else None,
        last_checked_at=recent[0].fetched_at if recent else None,
        is_lowest=is_lowest,
        suspect=suspect,
    )


def to_out(session: Session, product: Product, pending: RepriceProposal | None | bool = False) -> ProductOut:
    """`pending` may be passed in; by default it is looked up."""
    if pending is False:
        pending = repo.pending_proposals_by_product(session, [product.id]).get(product.id)
    return to_out_many(session, [product], {product.id: pending} if pending else {})[0]


def to_out_many(session: Session, products: list[Product], pending: dict[int, RepriceProposal]) -> list[ProductOut]:
    """Many products in a fixed number of queries (see repo.listing_reads)."""
    listings = repo.listings_by_product(session, [p.id for p in products], include_paused=True)
    reads = repo.listing_reads(session, [x.id for xs in listings.values() for x in xs])
    contexts = repo.pricing_contexts(session, products, listings=listings, reads=reads)
    return [_product_out(p, contexts[p.id], listings[p.id], reads, pending.get(p.id)) for p in products]


def _product_out(
    product: Product,
    ctx: PricingContext,
    product_listings: list[TrackedItem],
    reads: dict[int, repo.ListingReads],
    pending: RepriceProposal | None,
) -> ProductOut:
    flags = {c.listing_id: c for c in ctx.competitors}
    listings = [
        listing_out(
            listing,
            reads[listing.id],
            is_lowest=flags[listing.id].is_reference if listing.id in flags else False,
            suspect=flags[listing.id].suspect if listing.id in flags else False,
        )
        for listing in product_listings
    ]
    checked = [x.last_checked_at for x in listings if x.last_checked_at]
    spark_listing = ctx.reference_listing_id or next((x.id for x in listings if x.active), None)
    return ProductOut(
        id=product.id,
        title=product.title,
        our_sku=product.our_sku,
        our_price_inr=_num(product.our_price_inr),
        floor_price_inr=_num(product.floor_price_inr),
        max_change_pct=float(product.max_change_pct),
        undercut_by_inr=float(product.undercut_by_inr),
        auto_apply=product.auto_apply,
        auto_apply_max_pct=float(product.auto_apply_max_pct),
        min_change_pct=_num(product.min_change_pct),
        alert_on_stock_change=product.alert_on_stock_change,
        check_every_hours=product.check_every_hours,
        notify_email=product.notify_email,
        active=product.active,
        created_at=product.created_at,
        image_url=product_image_url(listings),
        listings=listings,
        lowest_price_inr=ctx.competitor_price_inr,
        lowest_marketplace=ctx.reference_marketplace,
        lowest_listing_id=ctx.reference_listing_id,
        competitor_in_stock=ctx.competitor_in_stock,
        position=ctx.position,
        gap_inr=ctx.gap_inr,
        gap_pct=ctx.gap_pct,
        pending_proposal=brief(pending),
        last_checked_at=max(checked) if checked else None,
        sparkline=repo.series_from(reads[spark_listing]) if spark_listing in reads else [],
    )
