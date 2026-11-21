"""The backend's only doorway into the AI layer (`app.ai`).

Implements `app.ai.DataProvider` over the database and source adapters, and builds the repricing
workflow and the intake agent lazily (so the API still starts, and add-by-URL still works,
without a model key).
"""

from __future__ import annotations

import threading

from app import ai
from app.ai.schemas import (
    HistoryStats,
    IntakeCandidate,
    IntakeResolution,
    Marketplace,
    ObservationView,
    PricingContext,
    ProductSettings,
    RepricingOutcome,
    ReviewAnswer,
    TriggerType,
)
from app.core.config import get_settings
from app.db import repo
from app.db.base import SessionLocal
from app.services.sources import source_for_marketplace
from app.services.sources.base import ListingRef


class BackendDataProvider:
    """Read-only. Each call opens its own short session."""

    def get_price_history(self, listing_id: int, days: int) -> HistoryStats:
        with SessionLocal() as s:
            return repo.history_stats(s, listing_id, days)

    def get_latest_observation(self, listing_id: int) -> ObservationView | None:
        with SessionLocal() as s:
            obs = repo.latest_observation(s, listing_id)
            return repo.to_view(obs) if obs else None

    def refetch_listing(self, listing_id: int) -> ObservationView:
        with SessionLocal() as s:
            listing = repo.get_listing(s, listing_id)
            if listing is None:
                raise LookupError(f"Unknown listing {listing_id}")
            ref = ListingRef(listing.marketplace, listing.external_id, listing.canonical_url)
        result = source_for_marketplace(ref.marketplace).fetch(ref)
        # Returned to the agent only; the scheduler's next cycle records the stored reading.
        return ObservationView(
            listing_id=listing_id,
            fetched_at=repo.utcnow(),
            price_inr=float(result.price_inr) if result.price_inr is not None else None,
            mrp_inr=float(result.mrp_inr) if result.mrp_inr is not None else None,
            in_stock=result.in_stock,
            seller=result.seller,
            source=result.source,
            ok=result.ok,
            error=result.error,
        )

    def get_product_settings(self, product_id: int) -> ProductSettings | None:
        with SessionLocal() as s:
            product = repo.get_product(s, product_id)
            return repo.product_settings(s, product) if product else None

    def get_pricing_context(self, product_id: int) -> PricingContext | None:
        with SessionLocal() as s:
            product = repo.get_product(s, product_id)
            return repo.pricing_context(s, product) if product else None

    def search_candidate_listings(self, query: str, marketplace: Marketplace) -> list[IntakeCandidate]:
        return source_for_marketplace(marketplace).search(query)


_lock = threading.Lock()
_agents: dict[str, object] = {}


def _agent(kind: str):
    with _lock:
        if kind not in _agents:
            settings = get_settings()
            checkpointer = ai.get_checkpointer(settings.database_url)
            if kind == "repricing":
                _agents[kind] = ai.build_repricing_workflow(
                    BackendDataProvider(),
                    model=settings.agent_model,
                    checkpointer=checkpointer,
                    low_confidence=settings.alert_min_confidence,
                    auto_min_confidence=settings.auto_apply_min_confidence,
                )
            else:
                _agents[kind] = ai.build_intake_agent(
                    BackendDataProvider(), model=settings.agent_model, checkpointer=checkpointer
                )
        return _agents[kind]


def reprice(product_id: int, trigger_type: TriggerType, latest_summary: str, run_tag: str) -> RepricingOutcome:
    """Run the repricing workflow for one product until it finishes or pauses for a human review."""
    return ai.start_repricing(_agent("repricing"), product_id, trigger_type, latest_summary, run_tag=run_tag)


def resume_reprice(thread_id: str, answer: ReviewAnswer) -> RepricingOutcome:
    """Resume a paused repricing run with the reviewer's answer (works across processes)."""
    return ai.resume_repricing(_agent("repricing"), thread_id, answer)


def resolve_intake(query: str) -> IntakeResolution:
    return ai.resolve_query(_agent("intake"), query)


def setup_checkpointer() -> None:
    ai.setup_checkpointer(get_settings().database_url)


def shutdown() -> None:
    ai.close_checkpointers()
