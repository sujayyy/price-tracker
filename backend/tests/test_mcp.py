"""The MCP server: tools are read-only and return the same data as the REST API."""

import asyncio
from decimal import Decimal

from mcp import Client

from app.db.models import Decision, RepriceProposal
from app.mcp.server import build_server
from tests.conftest import add_listing, make_product

TOOLS = {
    "list_products",
    "get_product",
    "get_price_history",
    "list_pending_approvals",
    "get_recent_decisions",
    "get_recent_activity",
    "get_monitoring",
}


def run(coro_fn):
    async def go():
        async with Client(build_server()) as client:
            return await coro_fn(client)

    return asyncio.run(go())


def call(tool: str, **args):
    return run(lambda client: client.call_tool(tool, args))


def ok(tool: str, **args) -> dict:
    result = call(tool, **args)
    assert not result.is_error, result.content[0].text
    return result.structured_content


def test_every_tool_is_read_only(db):
    tools = run(lambda client: client.list_tools()).tools
    # Adding a tool means updating this set on purpose: anything that writes does not belong here.
    assert {t.name for t in tools} == TOOLS
    for t in tools:
        assert t.annotations.read_only_hint is True, t.name
        assert t.annotations.destructive_hint is False, t.name
        assert t.description, t.name


def test_products_overview_and_detail(db, fake_amazon):
    product, _ = make_product(db, prices=[1100, 1000], our_sku="SKU-1", our_price_inr=Decimal("1050"))
    add_listing(db, product, prices=[990], marketplace="flipkart", external_id="FLIPKART1")

    (row,) = ok("list_products")["products"]
    assert row["id"] == product.id and row["our_sku"] == "SKU-1" and row["listings"] == 2
    assert row["lowest_price_inr"] == 990 and row["lowest_marketplace"] == "flipkart"
    assert "sparkline" not in row  # the overview stays compact

    detail = ok("get_product", product_id=product.id)
    assert detail["our_price_inr"] == 1050 and len(detail["listings"]) == 2


def test_unknown_product_is_a_clear_tool_error(db):
    result = call("get_product", product_id=999)
    assert result.is_error and "list_products" in result.content[0].text
    assert call("get_recent_decisions", product_id=999).is_error


def test_price_history_is_summarised_and_trimmed(db):
    product, listing = make_product(db, prices=[1200, 900, 1000, 1100, 1050])
    (series,) = ok("get_price_history", product_id=product.id, days=30, max_points=2)["series"]
    assert series["listing_id"] == listing.id and series["readings"] == 5
    assert (series["lowest_price_inr"], series["highest_price_inr"], series["latest_price_inr"]) == (900, 1200, 1050)
    assert [p["price_inr"] for p in series["points"]] == [1100, 1050]
    assert call("get_price_history", product_id=product.id, days=0).is_error  # validated arguments


def test_pending_approvals_and_decision_reasoning(db):
    product, listing = make_product(
        db, prices=[1000, 900], our_price_inr=Decimal("1000"), floor_price_inr=Decimal("850")
    )
    decision = Decision(
        product_id=product.id,
        item_id=listing.id,
        trigger_type="price_drop",
        decision={"current_price_inr": 900, "reasoning": "Competitor cut 10%.", "confidence": 0.9},
    )
    db.add(decision)
    db.flush()
    db.add(
        RepriceProposal(
            product_id=product.id,
            item_id=listing.id,
            decision_id=decision.id,
            thread_id="reprice-test",
            status="pending",
            action="lower_price",
            competitor_price_inr=Decimal("900"),
            from_price_inr=Decimal("1000"),
            to_price_inr=Decimal("899"),
            change_pct=Decimal("-10.1"),
            limited_by="max_change",
        )
    )
    db.commit()

    (p,) = ok("list_pending_approvals")["pending"]
    assert p["product_id"] == product.id and p["to_price_inr"] == 899 and p["status"] == "pending"
    assert {g["key"] for g in p["guardrails"]} >= {"floor", "max_move"}
    assert p["decision"]["reasoning"] == "Competitor cut 10%."

    (d,) = ok("get_recent_decisions", product_id=product.id)["decisions"]
    assert d["trigger_type"] == "price_drop" and d["decision"]["reasoning"] == "Competitor cut 10%."

    (a,) = ok("get_recent_activity", days=7)["activity"]
    assert a["product_id"] == product.id and a["proposal_status"] == "pending"


def test_monitoring_reports_listing_health(db):
    make_product(db, prices=[1000])
    health = ok("get_monitoring")
    assert [x["status"] for x in health["listings"]] == ["ok"]
