"""Per-product history: competitor readings per listing, AI decisions, our price log, proposals."""

from fastapi import APIRouter, Query

from app.ai.schemas import RepricingDecision
from app.db import repo
from app.db.models import Product, RepriceProposal, TrackedItem
from app.deps import ProductDep, SessionDep
from app.schemas.decision import ActivityOut, DecisionOut
from app.schemas.product import HistoryPoint, HistorySeries, OurPriceChangeOut

router = APIRouter(prefix="/api/products", tags=["history"])
activity_router = APIRouter(prefix="/api", tags=["history"])


@activity_router.get("/activity", response_model=list[ActivityOut])
def activity(
    session: SessionDep,
    days: int = Query(default=14, ge=1, le=365),
    limit: int = Query(default=200, ge=1, le=1000),
):
    """Recent AI decisions across every product: the overview's movement chart and activity feed."""
    rows = repo.recent_decisions(session, days=days, limit=limit)
    alerted = repo.alerted_decision_ids(session, [r.id for r in rows])
    products = {p.id: p for p in session.query(Product).filter(Product.id.in_({r.product_id for r in rows}))}
    listings = {x.id: x for x in session.query(TrackedItem).filter(TrackedItem.id.in_({r.item_id for r in rows}))}
    props = {
        p.decision_id: p
        for p in session.query(RepriceProposal).filter(RepriceProposal.decision_id.in_({r.id for r in rows}))
    }
    out = []
    for r in rows:
        d = read_decision(r.product_id, r.decision)
        listing = listings.get(r.item_id)
        pr = props.get(r.id)
        out.append(
            ActivityOut(
                id=r.id,
                product_id=r.product_id,
                product_title=products[r.product_id].title,
                our_sku=products[r.product_id].our_sku,
                listing_id=r.item_id,
                marketplace=listing.marketplace if listing else None,
                trigger_type=r.trigger_type,
                created_at=r.created_at,
                alerted=r.id in alerted,
                action=d.action,
                recommended_price_inr=d.recommended_price_inr,
                competitor_price_inr=d.competitor_price_inr,
                our_price_inr=d.our_price_inr,
                reasoning=d.reasoning,
                urgency=d.urgency,
                market_read=d.market_read,
                confidence=d.confidence,
                proposal_id=pr.id if pr else None,
                proposal_status=pr.status if pr else None,
                resolved_by=pr.resolved_by if pr else None,
            )
        )
    return out


def read_decision(product_id: int, raw: dict) -> RepricingDecision:
    """Decisions stored before the ops-repricing change (consumer deal alerts) are shown as history."""
    if "action" in raw:
        return RepricingDecision.model_validate(raw | {"product_id": raw.get("product_id", product_id)})
    return RepricingDecision(
        product_id=product_id,
        event="none",
        competitor_price_inr=raw.get("current_price_inr"),
        our_price_inr=None,
        action="hold",
        recommended_price_inr=None,
        market_read="unknown",
        urgency="low",
        reasoning=raw.get("reasoning", ""),
        confidence=raw.get("confidence", 0),
        data_issues=[*raw.get("data_issues", []), "legacy: recorded by the earlier consumer deal-alert version"],
    )


@router.get("/{product_id}/history", response_model=list[HistorySeries])
def price_history(product: ProductDep, session: SessionDep, days: int = Query(default=90, ge=1, le=3650)):
    """Competitor price points, one series per listing."""
    return [
        HistorySeries(
            listing_id=listing.id,
            marketplace=listing.marketplace,
            title=listing.title,
            points=[
                HistoryPoint(
                    fetched_at=o.fetched_at,
                    price_inr=float(o.price_inr) if o.price_inr is not None else None,
                    mrp_inr=float(o.mrp_inr) if o.mrp_inr is not None else None,
                    in_stock=o.in_stock,
                )
                for o in repo.history_points(session, listing.id, days)
            ],
        )
        for listing in repo.product_listings(session, product.id, include_paused=True)
    ]


@router.get("/{product_id}/decisions", response_model=list[DecisionOut])
def decisions(product: ProductDep, session: SessionDep, limit: int = Query(default=50, ge=1, le=500)):
    rows = repo.decisions_for_product(session, product.id, limit)
    alerted = repo.alerted_decision_ids(session, [r.id for r in rows])
    return [
        DecisionOut(
            id=r.id,
            product_id=r.product_id,
            listing_id=r.item_id,
            marketplace=(listing.marketplace if (listing := session.get(TrackedItem, r.item_id)) else None),
            trigger_type=r.trigger_type,
            created_at=r.created_at,
            alerted=r.id in alerted,
            decision=read_decision(r.product_id, r.decision),
        )
        for r in rows
    ]


@router.get("/{product_id}/our-price-history", response_model=list[OurPriceChangeOut])
def our_price_history(product: ProductDep, session: SessionDep):
    """Audit log of our price for this product, newest first."""
    return repo.price_changes_for_product(session, product.id)
