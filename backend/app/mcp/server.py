"""Price Tracker as an MCP server: read-only tools for any MCP client.

Someone on the pricing team can ask an AI assistant or IDE that speaks MCP things like
"what's waiting for approval?", "why did the AI propose ₹X?" or "which listings are failing?"
without opening the dashboard.

Every tool is read-only. Each one reads through the same handler the REST API uses, so the
answers match the dashboard exactly. Nothing here can change a price, approve or reject a
proposal, add a product or start a run; those stay in the dashboard and the API, behind the
human approval step.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ToolAnnotations
from pydantic import Field
from sqlalchemy.orm import Session

from app.api.routes import history, monitoring, products, proposals
from app.db import repo
from app.db.base import SessionLocal
from app.db.models import Product
from app.schemas.product import ProductOut

READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)

INSTRUCTIONS = """\
Read-only access to an e-commerce price tracker. We sell products; for each one we track
competitor listings on Amazon.in and Flipkart. An AI analyst recommends price moves, code
guardrails (floor price, max move) clamp them, and a human approves or rejects them.

Start with list_products to get product ids. Prices are in Indian rupees (INR).
position says where our price sits against the lowest in-stock competitor.
You cannot change anything through these tools: to approve, reject or edit a price,
point the user to the dashboard."""

# Fields of ProductOut that make up the one-line overview in list_products.
SUMMARY_FIELDS = {
    "id",
    "title",
    "our_sku",
    "active",
    "our_price_inr",
    "floor_price_inr",
    "lowest_price_inr",
    "lowest_marketplace",
    "competitor_in_stock",
    "position",
    "gap_inr",
    "gap_pct",
    "pending_proposal",
    "last_checked_at",
}


def _summary(p: ProductOut) -> dict[str, Any]:
    return p.model_dump(mode="json", include=SUMMARY_FIELDS) | {"listings": len(p.listings)}


def build_server(session_factory: Callable[[], Session] = SessionLocal) -> MCPServer:
    """The MCP server. Tests pass their own session factory; the default is the app database."""
    server = MCPServer("price-tracker", instructions=INSTRUCTIONS)

    def product_or_error(session: Session, product_id: int) -> Product:
        product = repo.get_product(session, product_id)
        if product is None:
            raise ToolError(f"No product with id {product_id}. Call list_products to see the product ids.")
        return product

    @server.tool(annotations=READ_ONLY)
    def list_products() -> dict[str, Any]:
        """Every product we track, one entry each: our price and floor, the lowest competitor price
        and which marketplace has it, our position and gap against it, whether a price change is
        waiting for approval, and when it was last checked. Start here to find product ids."""
        with session_factory() as session:
            return {"products": [_summary(p) for p in products.list_products(session)]}

    @server.tool(annotations=READ_ONLY)
    def get_product(product_id: int) -> dict[str, Any]:
        """One product in full: pricing settings (floor, max move %, undercut, auto-apply limits),
        every competitor listing with its latest price, stock and health, our position and gap,
        and any pending proposal."""
        with session_factory() as session:
            return products.get_product(product_or_error(session, product_id), session).model_dump(mode="json")

    @server.tool(annotations=READ_ONLY)
    def get_price_history(
        product_id: int,
        days: Annotated[int, Field(ge=1, le=3650)] = 30,
        max_points: Annotated[int, Field(ge=1, le=500)] = 40,
    ) -> dict[str, Any]:
        """Competitor price history for one product, one series per listing. Each series gives the
        latest, lowest and highest price over the window plus its most recent readings (at most
        max_points, oldest first)."""
        with session_factory() as session:
            series = history.price_history(product_or_error(session, product_id), session, days=days)
        out = []
        for s in series:
            prices = [p.price_inr for p in s.points if p.price_inr is not None]
            out.append(
                {
                    "listing_id": s.listing_id,
                    "marketplace": s.marketplace,
                    "title": s.title,
                    "readings": len(s.points),
                    "latest_price_inr": prices[-1] if prices else None,
                    "lowest_price_inr": min(prices) if prices else None,
                    "highest_price_inr": max(prices) if prices else None,
                    "points": [p.model_dump(mode="json") for p in s.points[-max_points:]],
                }
            )
        return {"product_id": product_id, "days": days, "series": out}

    @server.tool(annotations=READ_ONLY)
    def list_pending_approvals(limit: Annotated[int, Field(ge=1, le=100)] = 20) -> dict[str, Any]:
        """Price changes waiting for a human decision, newest first. Each one has the proposed
        move, the AI's reasoning and confidence, the guardrail checks it passed, and whether the
        market or our price has moved since it was proposed (if so, it may be stale)."""
        with session_factory() as session:
            rows = proposals.list_proposals(session, status_="pending", limit=limit)
            return {"pending": [p.model_dump(mode="json") for p in rows]}

    @server.tool(annotations=READ_ONLY)
    def get_recent_decisions(product_id: int, limit: Annotated[int, Field(ge=1, le=50)] = 5) -> dict[str, Any]:
        """The AI analyst's recent decisions for one product, newest first: what triggered each run,
        the recommended action and price, its reasoning, market read, confidence, any data issues,
        and whether the ops team was emailed. Use this to answer "why did the AI propose that?"."""
        with session_factory() as session:
            rows = history.decisions(product_or_error(session, product_id), session, limit=limit)
            return {"decisions": [d.model_dump(mode="json") for d in rows]}

    @server.tool(annotations=READ_ONLY)
    def get_recent_activity(
        days: Annotated[int, Field(ge=1, le=90)] = 7,
        limit: Annotated[int, Field(ge=1, le=200)] = 50,
    ) -> dict[str, Any]:
        """AI recommendations across all products over the last few days, newest first, with each
        one's action, price, reasoning, confidence and what happened to the resulting proposal."""
        with session_factory() as session:
            rows = history.activity(session, days=days, limit=limit)
            return {"activity": [a.model_dump(mode="json") for a in rows]}

    @server.tool(annotations=READ_ONLY)
    def get_monitoring() -> dict[str, Any]:
        """System health: recent scheduler runs, checks and errors in the last 24 hours, AI runs
        against the daily cap, and each competitor listing's status (ok, failing, paused, not yet
        checked) with its last successful check and next due time."""
        with session_factory() as session:
            return monitoring.monitoring(session).model_dump(mode="json")

    return server
