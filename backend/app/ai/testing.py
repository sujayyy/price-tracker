"""Test doubles: a scripted chat model and an in-memory DataProvider.

They let the real `create_agent` graph (tools, middleware, structured output) run in tests
and evals without any LLM call or database.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from app.ai.guardrails import ListingSnapshot, build_pricing_context
from app.ai.schemas import (
    HistoryStats,
    IntakeCandidate,
    ListingInfo,
    Marketplace,
    ObservationView,
    PricePoint,
    PricingContext,
    ProductSettings,
)


class ScriptedChatModel(BaseChatModel):
    """Returns the given AIMessages in order, one per model call. Records the prompts."""

    responses: list[AIMessage]
    calls: list[list[BaseMessage]] = []

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools: Any, **kwargs: Any) -> ScriptedChatModel:
        return self

    def _generate(self, messages: list[BaseMessage], stop=None, run_manager=None, **kwargs):
        self.calls.append(list(messages))
        idx = len(self.calls) - 1
        if idx >= len(self.responses):
            raise AssertionError(f"ScriptedChatModel ran out of responses at call {idx + 1}")
        return ChatResult(generations=[ChatGeneration(message=self.responses[idx])])


def tool_call(name: str, args: dict, call_id: str | None = None) -> dict:
    return {"name": name, "args": args, "id": call_id or f"call_{name}_{abs(hash(str(args))) % 10**8}"}


@dataclass
class InMemoryProvider:
    """A DataProvider over fixed price series: products, each with one or more listings."""

    settings: dict[int, ProductSettings] = field(default_factory=dict)
    observations: dict[int, list[ObservationView]] = field(default_factory=dict)
    refetch_results: dict[int, ObservationView] = field(default_factory=dict)
    search_results: dict[Marketplace, list[IntakeCandidate]] = field(default_factory=dict)
    refetch_calls: int = 0

    def add_series(
        self,
        settings: ProductSettings,
        prices: list[float | None],
        *,
        listing_id: int | None = None,
        marketplace: Marketplace = "amazon_in",
        in_stock: list[bool] | None = None,
        mrp: float | None = None,
        every_hours: int = 12,
        seller: str = "Example Retail",
    ) -> int:
        """Add one listing's readings (oldest → newest) to a product. Returns the listing id.

        The first listing of a product defaults to the product's id, so single-listing tests
        can use one number for both.
        """
        base = self.settings.get(settings.product_id) or settings
        if listing_id is None:
            listing_id = settings.product_id if not base.listings else 1000 + len(self.observations)
        info = ListingInfo(listing_id=listing_id, marketplace=marketplace, title=settings.title)
        self.settings[settings.product_id] = settings.model_copy(update={"listings": [*base.listings, info]})
        now = datetime.now(UTC)
        n = len(prices)
        stock = in_stock or [p is not None for p in prices]
        self.observations[listing_id] = [
            ObservationView(
                listing_id=listing_id,
                fetched_at=now - timedelta(hours=every_hours * (n - 1 - i)),
                price_inr=p,
                mrp_inr=mrp,
                in_stock=stock[i],
                seller=seller,
                source="html",
                ok=True,
            )
            for i, p in enumerate(prices)
        ]
        return listing_id

    def get_price_history(self, listing_id: int, days: int) -> HistoryStats:
        return summarize(listing_id, days, self.observations.get(listing_id, []))

    def get_latest_observation(self, listing_id: int) -> ObservationView | None:
        obs = self.observations.get(listing_id, [])
        return obs[-1] if obs else None

    def refetch_listing(self, listing_id: int) -> ObservationView:
        self.refetch_calls += 1
        return self.refetch_results.get(listing_id) or self.observations[listing_id][-1]

    def get_product_settings(self, product_id: int) -> ProductSettings | None:
        return self.settings.get(product_id)

    def get_pricing_context(self, product_id: int) -> PricingContext | None:
        settings = self.settings.get(product_id)
        if settings is None:
            return None
        snaps = []
        for info in settings.listings:
            obs = [o for o in self.observations.get(info.listing_id, []) if o.ok]
            priced = [o.price_inr for o in obs if o.price_inr is not None]
            before = [o.price_inr for o in obs[:-1] if o.price_inr is not None]
            snaps.append(
                ListingSnapshot(
                    listing_id=info.listing_id,
                    marketplace=info.marketplace,
                    latest=obs[-1] if obs else None,
                    previous_price=before[-1] if before else None,
                    last_known_price=priced[-1] if priced else None,
                    stats=summarize(info.listing_id, 90, obs),
                )
            )
        return build_pricing_context(product_id, settings, snaps)

    def search_candidate_listings(self, query: str, marketplace: Marketplace) -> list[IntakeCandidate]:
        return self.search_results.get(marketplace, [])


def summarize(listing_id: int, days: int, obs: list[ObservationView]) -> HistoryStats:
    """Reference implementation of HistoryStats over an ordered (oldest→newest) list."""
    ok = [o for o in obs if o.ok]
    latest = ok[-1] if ok else None
    prior = ok[:-1]
    now = datetime.now(UTC)

    def prices(since: datetime | None) -> list[float]:
        return [o.price_inr for o in prior if o.price_inr is not None and (since is None or o.fetched_at >= since)]

    window = prices(now - timedelta(days=days))
    last30 = prices(now - timedelta(days=30))
    all_prices = prices(None)
    latest_price = latest.price_inr if latest else None
    return HistoryStats(
        listing_id=listing_id,
        window_days=days,
        points_in_window=len(window),
        min_inr=min(window) if window else None,
        median_inr=statistics.median(window) if window else None,
        max_inr=max(window) if window else None,
        median_30d_inr=statistics.median(last30) if last30 else None,
        all_time_low_inr=min(all_prices) if all_prices else None,
        all_time_high_inr=max(all_prices) if all_prices else None,
        latest_price_inr=latest_price,
        prior_readings_at_latest_price=window.count(latest_price) if latest_price is not None else None,
        recent_points=[
            PricePoint(fetched_at=o.fetched_at, price_inr=o.price_inr, in_stock=o.in_stock) for o in reversed(ok[-10:])
        ],
    )
