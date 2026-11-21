"""The read-only data interface the agents' tools depend on.

`app.services.ai_bridge` implements this protocol over the database and the source adapters
and hands an instance to the agent and workflow builders. The AI layer therefore never imports
the database or web code (CI enforces this), and the agent can only reach data through these
read methods.

A *product* is ours (our SKU, our price, our limits); a *listing* is one competitor listing of
that product on one marketplace.
"""

from __future__ import annotations

from typing import Protocol

from app.ai.schemas import (
    HistoryStats,
    IntakeCandidate,
    Marketplace,
    ObservationView,
    PricingContext,
    ProductSettings,
)


class DataProvider(Protocol):
    def get_price_history(self, listing_id: int, days: int) -> HistoryStats: ...

    def get_latest_observation(self, listing_id: int) -> ObservationView | None: ...

    def refetch_listing(self, listing_id: int) -> ObservationView:
        """Fetch the listing live once more. Must not persist anything or bypass blocks."""
        ...

    def get_product_settings(self, product_id: int) -> ProductSettings | None: ...

    def get_pricing_context(self, product_id: int) -> PricingContext | None:
        """Our price vs every listing, built with `app.ai.guardrails.build_pricing_context`."""
        ...

    def search_candidate_listings(self, query: str, marketplace: Marketplace) -> list[IntakeCandidate]: ...
