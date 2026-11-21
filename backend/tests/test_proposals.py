"""End to end: competitor drop → real LangGraph workflow pauses → ops approves in the API → price applied.

The workflow is the production one (BackendDataProvider over the test database) with a scripted
model and an in-memory checkpointer, so no LLM is called.
"""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import select

from app import ai
from app.ai.checkpoint import _SERDE
from app.ai.testing import ScriptedChatModel, tool_call
from app.db.models import OurPriceChange, RepriceProposal
from app.main import app
from app.services import ai_bridge, runner
from app.services.runner import run_once
from app.services.sources.base import FetchResult
from tests.conftest import make_product


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def mails(monkeypatch):
    sent = []
    monkeypatch.setattr(runner, "send_email", lambda to, subject, html, text: sent.append((to, subject, text)))
    return sent


def use_workflow(monkeypatch, item_id, action="lower_price", price=889.0):
    decision = dict(
        product_id=item_id,
        event="price_drop",
        competitor_price_inr=899,
        our_price_inr=979,
        action=action,
        recommended_price_inr=price,
        market_read="sustained_change",
        urgency="high",
        reasoning="Competitor dropped to ₹899, ₹80 below our ₹979.",
        confidence=0.9,
    )
    model = ScriptedChatModel(
        responses=[
            AIMessage(content="", tool_calls=[tool_call("get_pricing_context", {"product_id": item_id})]),
            AIMessage(content="", tool_calls=[tool_call("RepricingDecision", decision)]),
        ]
    )
    wf = ai.build_repricing_workflow(
        ai_bridge.BackendDataProvider(), model=model, checkpointer=InMemorySaver(serde=_SERDE)
    )
    monkeypatch.setitem(ai_bridge._agents, "repricing", wf)


def drop(db, fake_amazon, monkeypatch, mails, **item_kw):
    item, _ = make_product(
        db, prices=[999, 999, 999], our_price_inr=979, floor_price_inr=850, undercut_by_inr=10, **item_kw
    )
    use_workflow(monkeypatch, item.id)
    fake_amazon.next = [FetchResult(ok=True, price_inr=Decimal("899"), in_stock=True)]
    summary = run_once()
    return item, summary


def test_approve_resumes_the_workflow_and_applies_the_price(client, db, fake_amazon, monkeypatch, mails):
    item, summary = drop(db, fake_amazon, monkeypatch, mails)
    (trigger,) = summary.triggers
    assert trigger["workflow_status"] == "pending_review" and trigger["proposal_status"] == "pending"
    assert mails[0][1].startswith("[Approval needed] Lower to ₹889")
    assert f"/products/{item.id}" in mails[0][2]  # the email links to the dashboard review

    queue = client.get("/api/proposals?status=pending").json()
    assert [p["to_price_inr"] for p in queue] == [889]
    assert queue[0]["decision"]["action"] == "lower_price" and queue[0]["product_title"] == "Test Phone"
    assert queue[0]["marketplace"] == "amazon_in"
    assert client.get(f"/api/products/{item.id}").json()["pending_proposal"]["to_price_inr"] == 889

    r = client.post(f"/api/proposals/{queue[0]['id']}/approve", json={"by": "asha", "note": "match Amazon"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "approved" and r.json()["final_price_inr"] == 889 and r.json()["resolved_by"] == "asha"
    got = client.get(f"/api/products/{item.id}").json()
    assert got["our_price_inr"] == 889 and got["pending_proposal"] is None
    change = db.scalars(select(OurPriceChange)).one()
    assert (change.source, change.actor, change.proposal_id) == ("approved", "asha", queue[0]["id"])

    # A second click is refused instead of applying twice.
    assert client.post(f"/api/proposals/{queue[0]['id']}/approve", json={"by": "asha"}).status_code == 409


def test_override_price_is_checked_against_the_floor(client, db, fake_amazon, monkeypatch, mails):
    item, _ = drop(db, fake_amazon, monkeypatch, mails)
    pid = db.scalars(select(RepriceProposal.id)).one()
    assert client.post(f"/api/proposals/{pid}/approve", json={"by": "a", "price_inr": 800}).status_code == 422
    r = client.post(f"/api/proposals/{pid}/approve", json={"by": "a", "price_inr": 895})
    assert r.status_code == 200 and r.json()["final_price_inr"] == 895


def test_reject_keeps_our_price(client, db, fake_amazon, monkeypatch, mails):
    item, _ = drop(db, fake_amazon, monkeypatch, mails)
    pid = db.scalars(select(RepriceProposal.id)).one()
    r = client.post(f"/api/proposals/{pid}/reject", json={"by": "asha", "note": "flash sale"})
    assert r.status_code == 200 and r.json()["status"] == "rejected" and r.json()["resolution_note"] == "flash sale"
    assert client.get(f"/api/products/{item.id}").json()["our_price_inr"] == 979


def test_manual_price_change_closes_the_open_proposal(client, db, fake_amazon, monkeypatch, mails):
    item, _ = drop(db, fake_amazon, monkeypatch, mails)
    pid = db.scalars(select(RepriceProposal.id)).one()
    client.patch(f"/api/products/{item.id}", json={"our_price_inr": 949})
    assert client.get("/api/proposals?status=pending").json() == []
    assert client.post(f"/api/proposals/{pid}/approve", json={"by": "a"}).status_code == 409


def test_unknown_proposal_is_404(client, db):
    assert client.post("/api/proposals/999/approve", json={"by": "a"}).status_code == 404
