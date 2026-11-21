"""Our products and their competitor listings, plus cross-marketplace search for new listings."""

from __future__ import annotations

from decimal import Decimal

import structlog
from fastapi import APIRouter, HTTPException, Query, Response, status

from app.db import repo
from app.deps import ListingDep, ProductDep, SessionDep
from app.schemas.product import (
    CLEARABLE,
    CandidateOut,
    ListingIn,
    ListingPreviewIn,
    ListingPreviewOut,
    ListingUpdate,
    ProductCreate,
    ProductOut,
    ProductUpdate,
    RecheckOut,
    SearchOut,
)
from app.services import ai_bridge
from app.services.pricing import PriceRejected, set_our_price
from app.services.products import ListingAlreadyTracked, attach_listing, create_product, to_out, to_out_many
from app.services.runner import run_once
from app.services.sources import SOURCES, UnsupportedURL, images, source_for_url

log = structlog.get_logger()
router = APIRouter(prefix="/api", tags=["products"])


def _conflict(exc: ListingAlreadyTracked) -> HTTPException:
    return HTTPException(
        status.HTTP_409_CONFLICT, {"message": str(exc), "listing_id": exc.listing_id, "product_id": exc.product_id}
    )


@router.post("/products", status_code=status.HTTP_201_CREATED, response_model=ProductOut)
def create(body: ProductCreate, session: SessionDep):
    """Create our product with one or more competitor listings (each is fetched once)."""
    try:
        product = create_product(session, body)
    except UnsupportedURL as exc:
        session.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except ListingAlreadyTracked as exc:
        session.rollback()
        raise _conflict(exc) from exc
    return to_out(session, product)


@router.get("/products", response_model=list[ProductOut])
def list_products(session: SessionDep):
    products = repo.list_products(session)
    pending = repo.pending_proposals_by_product(session, [p.id for p in products])
    return to_out_many(session, products, pending)


@router.get("/products/{product_id}", response_model=ProductOut)
def get_product(product: ProductDep, session: SessionDep):
    return to_out(session, product)


_DECIMAL_FIELDS = {"min_change_pct", "floor_price_inr", "max_change_pct", "undercut_by_inr", "auto_apply_max_pct"}


@router.patch("/products/{product_id}", response_model=ProductOut)
def update_product(body: ProductUpdate, product: ProductDep, session: SessionDep):
    fields = body.model_fields_set - {"changed_by", "our_price_inr"}
    for field in fields:
        value = getattr(body, field)
        if value is None and field not in CLEARABLE:
            continue
        if field in _DECIMAL_FIELDS and value is not None:
            value = Decimal(str(value))
        setattr(product, field, value)

    new_price = body.our_price_inr if "our_price_inr" in body.model_fields_set else None
    effective = new_price if new_price is not None else product.our_price_inr
    if product.floor_price_inr is not None and effective is not None:
        if product.floor_price_inr > Decimal(str(effective)):
            session.rollback()
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "The floor price must not be above our price")
    if new_price is not None:
        try:
            set_our_price(session, product, new_price, source="manual", actor=body.changed_by)
        except PriceRejected as exc:
            session.rollback()
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    elif "our_price_inr" in body.model_fields_set:
        product.our_price_inr = None  # stop repricing this product; competitors are still watched
    session.commit()
    return to_out(session, product)


@router.delete("/products/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_product(product: ProductDep, session: SessionDep):
    """Soft delete: stops monitoring, keeps history, decisions and our price log."""
    product.active = False
    product.deleted_at = repo.utcnow()
    repo.supersede_pending(session, product.id, "Product was deleted")
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/products/{product_id}/listings", status_code=status.HTTP_201_CREATED, response_model=ProductOut)
def add_listing(body: ListingIn, product: ProductDep, session: SessionDep):
    """Add another competitor listing (e.g. the same product on Flipkart) to our product."""
    try:
        attach_listing(session, product, body.url.strip(), body.title)
    except UnsupportedURL as exc:
        session.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except ListingAlreadyTracked as exc:
        session.rollback()
        raise _conflict(exc) from exc
    session.commit()
    return to_out(session, product)


@router.patch("/listings/{listing_id}", response_model=ProductOut)
def update_listing(body: ListingUpdate, listing: ListingDep, session: SessionDep):
    """Pause or resume monitoring one competitor listing."""
    listing.active = body.active
    session.commit()
    return to_out(session, repo.get_product(session, listing.product_id))


@router.delete("/listings/{listing_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_listing(listing: ListingDep, session: SessionDep):
    """Stop comparing against this listing (its price history is kept)."""
    listing.active = False
    listing.deleted_at = repo.utcnow()
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _with_images(candidates) -> list[CandidateOut]:
    """Re-attach the photos the marketplace searches just saw (the agent's schema has none)."""
    return [CandidateOut(**c.model_dump(), image_url=images.lookup(c.marketplace, c.external_id)) for c in candidates]


@router.get("/search", response_model=SearchOut)
def search(q: str = Query(min_length=3, max_length=300)):
    """Find the same product on every marketplace, for adding competitor listings.

    The intake agent searches Amazon.in and Flipkart and scores each result against the query
    (only real search results are returned). Without a model, plain marketplace search is used.
    """
    try:
        res = ai_bridge.resolve_intake(q)
        seen: set[tuple[str, str]] = set()
        ranked = []
        for c in [*([res.chosen] if res.chosen else []), *res.candidates]:
            if (c.marketplace, c.external_id) not in seen:
                seen.add((c.marketplace, c.external_id))
                ranked.append(c)
        return SearchOut(query=q, candidates=_with_images(ranked), reasoning=res.reasoning, ai_used=True)
    except Exception as exc:
        log.warning("intake_unavailable", error=str(exc))

    candidates, errors = [], {}
    for name, source in SOURCES.items():
        try:
            candidates.extend(source.search(q, limit=5))
        except Exception as exc:  # a blocked marketplace must not hide the other one
            errors[name] = f"{type(exc).__name__}: {exc}"[:200]
    return SearchOut(
        query=q,
        candidates=_with_images(candidates),
        reasoning="AI matching is unavailable, so these are plain marketplace search results; check each one.",
        ai_used=False,
        errors=errors,
    )


@router.post("/products/{product_id}/recheck", response_model=RecheckOut)
def recheck(product: ProductDep, session: SessionDep):
    """Check this product's competitor listings now, through the normal pipeline.

    If a competitor moved, the usual rules, recommendation, proposal and ops email follow (and an
    open proposal is replaced). If nothing moved, the latest data is simply confirmed.
    """
    before = repo.pending_proposals_by_product(session, [product.id]).get(product.id)
    summary = run_once(product_id=product.id)
    session.expire_all()
    after = repo.pending_proposals_by_product(session, [product.id]).get(product.id)
    return RecheckOut(
        checked=summary.items_checked,
        errors=summary.errors,
        changed=bool(summary.triggers),
        proposal_replaced=before is not None and (after is None or after.id != before.id),
        checked_at=repo.utcnow(),
        product=to_out(session, repo.get_product(session, product.id)),
    )


@router.post("/listings/preview", response_model=ListingPreviewOut)
def preview_listing(body: ListingPreviewIn, session: SessionDep):
    """Fetch what a listing URL points to (title, price, stock) without storing anything."""
    try:
        source = source_for_url(body.url.strip())
        ref = source.parse_url(body.url.strip())
    except UnsupportedURL as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    existing = repo.get_listing_by_external_id(session, ref.marketplace, ref.external_id)
    owner = repo.get_product(session, existing.product_id) if existing and existing.deleted_at is None else None
    result = source.fetch(ref)
    return ListingPreviewOut(
        marketplace=ref.marketplace,
        external_id=ref.external_id,
        canonical_url=ref.canonical_url,
        title=result.title,
        price_inr=float(result.price_inr) if result.price_inr is not None else None,
        in_stock=result.in_stock,
        image_url=result.image_url,
        ok=result.ok,
        error=result.error,
        monitored_by_product_id=owner.id if owner else None,
    )
