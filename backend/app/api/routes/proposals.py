"""The ops approval queue: list proposed price changes, approve or reject them."""

from __future__ import annotations

import structlog
from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from app import ai
from app.ai.schemas import ReviewAnswer
from app.api.routes.history import read_decision
from app.db import repo
from app.db.models import Decision, Product, RepriceProposal, TrackedItem
from app.deps import ProductDep, SessionDep
from app.schemas.proposal import ApproveIn, GuardrailCheck, ProposalOut, RejectIn
from app.services import proposals
from app.services.pricing import PriceRejected
from app.services.products import product_image_url

log = structlog.get_logger()
router = APIRouter(prefix="/api", tags=["proposals"])


def num(v) -> float | None:
    return float(v) if v is not None else None


def inr(v: float) -> str:
    return f"₹{v:,.0f}" if v == int(v) else f"₹{v:,.2f}"


def guardrail_checks(p: RepriceProposal, product: Product) -> list[GuardrailCheck]:
    """The pricing rules the proposed price was held to, restated from the stored proposal."""
    price = float(p.final_price_inr if p.final_price_inr is not None else p.to_price_inr)
    change = abs(float(p.change_pct))
    floor = num(product.floor_price_inr)
    checks = [
        GuardrailCheck(
            key="floor",
            label=f"At or above our floor ({inr(floor)})" if floor is not None else "No floor price set",
            passed=(price >= floor) if floor is not None else None,
            detail="Stopped at the floor: the full move would go below it" if p.limited_by == "floor" else None,
        ),
        GuardrailCheck(
            key="max_move",
            label=f"Within the max move ({float(product.max_change_pct):g}%)",
            passed=change <= float(product.max_change_pct) + 1e-6,
            detail="Capped at the max move: the full move is larger" if p.limited_by == "max_change" else None,
        ),
    ]
    if p.action == "raise_price":
        checks.append(
            GuardrailCheck(
                key="direction",
                label="No competitor is cutting its price",
                passed=True,
                detail="Raises are only offered when no platform is moving down",
            )
        )
    elif p.competitor_price_inr is not None:
        checks.append(
            GuardrailCheck(
                key="direction",
                label="Lowest competitor is below our price",
                passed=float(p.competitor_price_inr) < float(p.from_price_inr),
            )
        )
    return checks


def _out(session, p: RepriceProposal, *, fresh: bool = True) -> ProposalOut:
    return _outs(session, [p], fresh=fresh)[0]


def _outs(session, ps: list[RepriceProposal], *, fresh: bool = True) -> list[ProposalOut]:
    """Proposals with their product, listing and decision and, for pending ones, how the market has
    moved since, in a fixed number of queries however many there are (see repo.listing_reads)."""
    if not ps:
        return []
    products = {x.id: x for x in session.scalars(select(Product).where(Product.id.in_({p.product_id for p in ps})))}
    item_ids = {p.item_id for p in ps if p.item_id}
    sources = {x.id: x for x in session.scalars(select(TrackedItem).where(TrackedItem.id.in_(item_ids)))}
    decisions = {
        x.id: x
        for x in session.scalars(select(Decision).where(Decision.id.in_({p.decision_id for p in ps if p.decision_id})))
    }
    listings = repo.listings_by_product(session, list(products), include_paused=True)
    live = [products[i] for i in dict.fromkeys(p.product_id for p in ps if fresh and p.status == "pending")]
    reads = repo.listing_reads(session, [x.id for product in live for x in listings[product.id] if x.active])
    contexts = repo.pricing_contexts(session, live, listings=listings, reads=reads)
    out = []
    for p in ps:
        product = products[p.product_id]
        freshness = {}
        if p.product_id in contexts and p.status == "pending":
            ctx = contexts[p.product_id]
            checked = [
                reads[x.id].recent[0].fetched_at for x in listings[product.id] if x.active and reads[x.id].recent
            ]
            freshness = dict(
                latest_competitor_price_inr=ctx.competitor_price_inr,
                latest_checked_at=max(checked) if checked else None,
                competitor_changed=ctx.competitor_price_inr != num(p.competitor_price_inr),
                our_price_changed=num(product.our_price_inr) != float(p.from_price_inr),
            )
        listing = sources.get(p.item_id) if p.item_id else None
        decision = decisions.get(p.decision_id) if p.decision_id else None
        out.append(
            ProposalOut(
                id=p.id,
                product_id=p.product_id,
                product_title=product.title,
                product_image_url=product_image_url(listings[product.id]),
                our_sku=product.our_sku,
                listing_id=p.item_id,
                marketplace=listing.marketplace if listing else None,
                status=p.status,
                action=p.action,
                competitor_price_inr=num(p.competitor_price_inr),
                from_price_inr=float(p.from_price_inr),
                to_price_inr=float(p.to_price_inr),
                final_price_inr=num(p.final_price_inr),
                change_pct=float(p.change_pct),
                limited_by=p.limited_by,
                floor_price_inr=num(product.floor_price_inr),
                created_at=p.created_at,
                resolved_at=p.resolved_at,
                resolved_by=p.resolved_by,
                resolution_note=p.resolution_note,
                decision=read_decision(p.product_id, decision.decision) if decision else None,
                guardrails=guardrail_checks(p, product),
                **freshness,
            )
        )
    return out


@router.get("/proposals", response_model=list[ProposalOut])
def list_proposals(
    session: SessionDep,
    status_: str | None = Query(default=None, alias="status", description="e.g. pending"),
    limit: int = Query(default=100, ge=1, le=500),
):
    return _outs(session, repo.list_proposals(session, status=status_, limit=limit))


@router.get("/products/{product_id}/proposals", response_model=list[ProposalOut])
def product_proposals(product: ProductDep, session: SessionDep, limit: int = Query(default=50, ge=1, le=500)):
    return _outs(session, repo.list_proposals(session, product_id=product.id, limit=limit))


def _review(proposal_id: int, answer: ReviewAnswer, session) -> ProposalOut:
    try:
        p = proposals.review(proposal_id, answer)
    except proposals.ProposalNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except proposals.ProposalClosed as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except PriceRejected as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    except ai.NotAwaitingReview as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except Exception as exc:
        log.warning("review_failed", proposal_id=proposal_id, error=str(exc))
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, f"Could not resume the approval workflow: {type(exc).__name__}"
        ) from exc
    return _out(session, session.get(RepriceProposal, p.id))  # re-read: review() used its own session


@router.post("/proposals/{proposal_id}/approve", response_model=ProposalOut)
def approve(proposal_id: int, body: ApproveIn, session: SessionDep):
    """Resume the paused workflow with an approval. The price is re-checked against fresh data first."""
    return _review(
        proposal_id, ReviewAnswer(approved=True, by=body.by, price_inr=body.price_inr, note=body.note), session
    )


@router.post("/proposals/{proposal_id}/reject", response_model=ProposalOut)
def reject(proposal_id: int, body: RejectIn, session: SessionDep):
    return _review(proposal_id, ReviewAnswer(approved=False, by=body.by, note=body.note), session)
