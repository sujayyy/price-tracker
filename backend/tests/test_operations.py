"""Recheck, listing preview, monitoring status, proposal guardrails/freshness, richer activity."""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import ai_bridge, runner
from app.services.sources.base import FetchResult
from tests.conftest import add_listing, make_product
from tests.fakes import Recorder

URL = "https://www.amazon.in/Fake-Phone/dp/B0FAKEFAKE/ref=x"


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def rec(monkeypatch):
    r = Recorder()
    monkeypatch.setattr(ai_bridge, "reprice", r.repricer)
    monkeypatch.setattr(runner, "send_email", r.mailer)
    return r


def test_recheck_with_no_change_confirms_the_data(client, db, fake_amazon, rec):
    product, _ = make_product(db, prices=[1000, 1000], our_price_inr=900)
    fake_amazon.next = [FetchResult(ok=True, price_inr=Decimal("1000"), in_stock=True)]
    out = client.post(f"/api/products/{product.id}/recheck").json()
    assert out["checked"] == 1 and out["changed"] is False and out["proposal_replaced"] is False
    assert rec.calls == [] and out["product"]["last_checked_at"]


def test_recheck_with_a_change_runs_the_pipeline_and_replaces_the_proposal(client, db, fake_amazon, fake_flipkart, rec):
    product, _ = make_product(db, prices=[1000, 1000], our_price_inr=950)
    add_listing(db, product, prices=[990], marketplace="flipkart", external_id="itmTESTFK01")
    fake_amazon.next = [FetchResult(ok=True, price_inr=Decimal("900"), in_stock=True)]
    fake_flipkart.next = [FetchResult(ok=True, price_inr=Decimal("990"), in_stock=True)]
    runner.run_once(repricer=rec.repricer, mailer=rec.mailer, force=True)  # opens a pending proposal
    fake_amazon.next = [FetchResult(ok=True, price_inr=Decimal("880"), in_stock=True)]
    fake_flipkart.next = [FetchResult(ok=True, price_inr=Decimal("990"), in_stock=True)]
    out = client.post(f"/api/products/{product.id}/recheck").json()
    assert out["checked"] == 2 and out["changed"] is True and out["proposal_replaced"] is True


def test_listing_preview_fetches_without_storing(client, db, fake_amazon):
    out = client.post("/api/listings/preview", json={"url": URL}).json()
    assert out["marketplace"] == "amazon_in" and out["external_id"] == "B0FAKEFAKE"
    assert out["price_inr"] == 1000 and out["title"] == "Fake Phone" and out["monitored_by_product_id"] is None
    assert client.get("/api/products").json() == []
    pid = client.post("/api/products", json={"listings": [{"url": URL}]}).json()["id"]
    assert client.post("/api/listings/preview", json={"url": URL}).json()["monitored_by_product_id"] == pid
    assert client.post("/api/listings/preview", json={"url": "https://example.com/x"}).status_code == 400


def test_monitoring_reports_runs_and_listing_health(client, db, fake_amazon, rec):
    product, listing = make_product(db, prices=[1000])
    make_product(db, prices=[500], external_id="B0PAUSED01", active=False, title="Paused")
    fake_amazon.next = [FetchResult(ok=False, error="blocked: captcha")]
    runner.run_once(repricer=rec.repricer, mailer=rec.mailer, force=True)
    out = client.get("/api/monitoring").json()
    assert out["last_run_at"] and out["runs_24h"] == 1 and out["errors_24h"] == 1
    by_id = {x["listing_id"]: x for x in out["listings"]}
    assert by_id[listing.id]["status"] == "failing" and by_id[listing.id]["last_error"] == "blocked: captcha"
    assert by_id[listing.id]["consecutive_failures"] == 1 and by_id[listing.id]["next_due_at"]
    assert [x["status"] for x in out["listings"] if x["product_title"] == "Paused"] == ["paused"]


def test_proposals_carry_guardrails_and_freshness(client, db, fake_amazon, rec):
    product, _ = make_product(db, prices=[1000, 1000], our_price_inr=900, floor_price_inr=700)
    fake_amazon.next = [FetchResult(ok=True, price_inr=Decimal("800"), in_stock=True)]
    runner.run_once(repricer=rec.repricer, mailer=rec.mailer)
    (p,) = client.get("/api/proposals?status=pending").json()
    checks = {g["key"]: g for g in p["guardrails"]}
    assert checks["floor"]["passed"] is True and "₹700" in checks["floor"]["label"]
    assert checks["max_move"]["passed"] is True and checks["direction"]["passed"] is True
    assert p["latest_competitor_price_inr"] == 800 and p["latest_checked_at"]
    assert p["competitor_changed"] is False and p["our_price_changed"] is False
    client.patch(f"/api/products/{product.id}", json={"our_price_inr": 950})  # supersedes it
    assert client.get("/api/proposals?status=pending").json() == []


def test_activity_includes_the_proposal_and_reasoning(client, db, fake_amazon, rec):
    make_product(db, prices=[1000, 1000], our_price_inr=900)
    fake_amazon.next = [FetchResult(ok=True, price_inr=Decimal("800"), in_stock=True)]
    runner.run_once(repricer=rec.repricer, mailer=rec.mailer)
    (a,) = client.get("/api/activity").json()
    assert a["proposal_status"] == "pending" and a["proposal_id"] and a["reasoning"].startswith("The competitor")
    assert a["urgency"] == "high" and a["confidence"] == 0.9
