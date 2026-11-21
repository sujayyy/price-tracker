"""Demo/test input: simulate the competitor's price for one item, then run the normal pipeline.

Only the scraper's output is simulated. The runner stores the reading, applies the rules, runs
the repricing workflow, opens a proposal and emails the ops team exactly as for a real fetch.
Simulated readings are tagged source='demo' so they are visibly not real and can be removed.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy.orm import Session, sessionmaker

from app.ai.schemas import RepricingDecision
from app.db import repo
from app.db.base import SessionLocal
from app.db.models import Decision
from app.schemas.decision import RunOut
from app.schemas.demo import DemoObservationOut, DemoPriceOut
from app.services.runner import Mailer, Repricer, run_once
from app.services.sources.base import FetchResult

DEMO_SOURCE = "demo"


def _num(value: Decimal | None) -> float | None:
    return float(value) if value is not None else None


class ItemNotFound(LookupError):
    pass


class ItemPaused(RuntimeError):
    pass


def simulate_price(
    listing_id: int,
    price_inr: float | None,
    in_stock: bool = True,
    *,
    session_factory: sessionmaker[Session] = SessionLocal,
    repricer: Repricer | None = None,
    mailer: Mailer | None = None,
) -> DemoPriceOut:
    with session_factory() as s:
        listing = repo.get_listing(s, listing_id)
        product = repo.get_product(s, listing.product_id) if listing else None
        if listing is None or product is None:
            raise ItemNotFound(f"Listing {listing_id} not found")
        if not (listing.active and product.active):
            raise ItemPaused(f"Listing {listing_id} or its product is paused; resume it first (the scheduler skips it)")
        last = repo.latest_observation(s, listing_id, ok_only=True)
        our_before, floor = _num(product.our_price_inr), _num(product.floor_price_inr)
        product_id, marketplace = product.id, listing.marketplace

    # What the scraper would have returned; MRP and seller carry over from the last real reading.
    simulated = FetchResult(
        ok=True,
        price_inr=Decimal(str(price_inr)) if price_inr is not None else None,
        mrp_inr=last.mrp_inr if last else None,
        in_stock=in_stock,
        seller=last.seller if last else None,
        source=DEMO_SOURCE,
    )
    summary = run_once(
        listing_id=listing_id,
        fetch=lambda _listing: simulated,
        session_factory=session_factory,
        repricer=repricer,
        mailer=mailer,
    )
    if summary.items_checked != 1:
        raise RuntimeError(f"The simulated reading was not stored (run {summary.run_id}); see that run's notes")

    with session_factory() as s:
        obs = repo.latest_observation(s, listing_id)
        prev = repo.previous_ok_observation(s, listing_id, obs)  # the same "previous" the rules just used
        decision = None
        if summary.triggers:
            row = s.get(Decision, summary.triggers[0]["decision_id"])
            decision = RepricingDecision.model_validate(row.decision)
        product = repo.get_product(s, product_id)
        ctx = repo.pricing_context(s, product)
        return DemoPriceOut(
            listing_id=listing_id,
            product_id=product_id,
            marketplace=marketplace,
            simulated_price_inr=price_inr,
            previous_price_inr=_num(prev.price_inr) if prev else None,
            our_price_before_inr=our_before,
            our_price_after_inr=_num(product.our_price_inr),
            floor_price_inr=floor,
            lowest_price_inr=ctx.competitor_price_inr,
            lowest_marketplace=ctx.reference_marketplace,
            observation=DemoObservationOut(
                id=obs.id,
                fetched_at=obs.fetched_at,
                price_inr=_num(obs.price_inr),
                mrp_inr=_num(obs.mrp_inr),
                in_stock=obs.in_stock,
                ok=obs.ok,
                source=obs.source,
            ),
            run=RunOut(
                run_id=summary.run_id,
                items_checked=summary.items_checked,
                agent_invocations=summary.agent_invocations,
                errors=summary.errors,
                alerts_sent=summary.alerts_sent,
                triggers=summary.triggers,
            ),
            decision=decision,
        )


def clear_simulated_prices(product_id: int, *, session_factory: sessionmaker[Session] = SessionLocal) -> int:
    """Remove the simulated readings of every listing of a product. Real readings, decisions,
    proposals and our price log are kept."""
    with session_factory() as s:
        if repo.get_product(s, product_id) is None:
            raise ItemNotFound(f"Product {product_id} not found")
        ids = [x.id for x in repo.product_listings(s, product_id, include_paused=True)]
        deleted = repo.delete_observations_by_source(s, ids, DEMO_SOURCE) if ids else 0
        s.commit()
        return deleted
