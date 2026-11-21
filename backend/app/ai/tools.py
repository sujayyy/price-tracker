"""Read-only tools for the two agents.

Tools are built by factories bound to a `DataProvider`, so the same agent code runs against
the real backend, the eval harness, or a test double. Tools return JSON strings; nothing here
writes to the database or sends anything.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from langchain.tools import ToolRuntime, tool
from langchain_core.tools import BaseTool

from app.ai.provider import DataProvider
from app.ai.schemas import Marketplace


@dataclass(frozen=True)
class AnalystContext:
    """Per-run context. Tools refuse to read any product or listing other than the ones being analysed."""

    product_id: int
    listing_ids: tuple[int, ...]


def _error(msg: str) -> str:
    return json.dumps({"error": msg})


def _wrong_product(requested: int, runtime: ToolRuntime[AnalystContext]) -> str | None:
    ctx = runtime.context
    if ctx is not None and requested != ctx.product_id:
        return _error(f"This run may only read product {ctx.product_id}; product {requested} was requested.")
    return None


def _wrong_listing(requested: int, runtime: ToolRuntime[AnalystContext]) -> str | None:
    ctx = runtime.context
    if ctx is not None and requested not in ctx.listing_ids:
        return _error(f"Listing {requested} does not belong to this product; use one of {list(ctx.listing_ids)}.")
    return None


def make_analyst_tools(provider: DataProvider) -> list[BaseTool]:
    @tool
    def get_pricing_context(product_id: int, runtime: ToolRuntime[AnalystContext]) -> str:
        """Our price vs every competitor listing (Amazon.in, Flipkart…): each listing's latest
        price, stock and change, which one is the lowest (the reference we price against), our
        position and gap, our floor and max move, and the list of allowed price moves (options),
        each already priced and clamped by the guardrails. Choose your action from these options."""
        if err := _wrong_product(product_id, runtime):
            return err
        ctx = provider.get_pricing_context(product_id)
        return ctx.model_dump_json() if ctx else _error("Unknown product.")

    @tool
    def get_price_history(listing_id: int, runtime: ToolRuntime[AnalystContext], days: int = 90) -> str:
        """Summary statistics of one competitor listing's stored price history (min/median/max,
        30-day median, all-time low/high) plus up to 10 recent readings. All statistics exclude
        the most recent observation so the current price can be compared against them."""
        if err := _wrong_listing(listing_id, runtime):
            return err
        days = max(1, min(int(days), 3650))
        return provider.get_price_history(listing_id, days).model_dump_json()

    @tool
    def get_latest_observation(listing_id: int, runtime: ToolRuntime[AnalystContext]) -> str:
        """The most recent stored price reading for one competitor listing."""
        if err := _wrong_listing(listing_id, runtime):
            return err
        obs = provider.get_latest_observation(listing_id)
        return obs.model_dump_json() if obs else _error("No observations stored for this listing.")

    @tool
    def refetch_listing(listing_id: int, runtime: ToolRuntime[AnalystContext]) -> str:
        """Fetch one competitor listing live one more time to confirm a suspicious reading.
        Allowed at most once per run; use only when a reading looks anomalous."""
        if err := _wrong_listing(listing_id, runtime):
            return err
        try:
            return provider.refetch_listing(listing_id).model_dump_json()
        except Exception as exc:  # the agent should record this as a data issue, not crash
            return _error(f"Refetch failed: {type(exc).__name__}: {exc}")

    @tool
    def get_product_settings(product_id: int, runtime: ToolRuntime[AnalystContext]) -> str:
        """The ops team's settings for our product: SKU, our price, floor price, max move %,
        undercut amount, auto-apply limits, alert thresholds, and its competitor listings."""
        if err := _wrong_product(product_id, runtime):
            return err
        settings = provider.get_product_settings(product_id)
        return settings.model_dump_json() if settings else _error("Unknown product.")

    return [get_pricing_context, get_price_history, get_latest_observation, refetch_listing, get_product_settings]


def make_intake_tools(provider: DataProvider) -> list[BaseTool]:
    @tool(response_format="content_and_artifact")
    def search_candidate_listings(query: str, marketplace: Marketplace) -> tuple[str, list[dict]]:
        """Search one marketplace ('amazon_in' or 'flipkart') for listings matching the query.
        Returns candidate listings with marketplace, external_id, title, price_inr and url."""
        try:
            results = provider.search_candidate_listings(query, marketplace)
        except Exception as exc:
            return _error(f"Search failed: {type(exc).__name__}: {exc}"), []
        payload = [c.model_dump(mode="json") for c in results]
        # The artifact lets `resolve_query` verify that the agent only returns real results.
        return json.dumps(payload), payload

    return [search_candidate_listings]
