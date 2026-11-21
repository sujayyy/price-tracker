"""POST/DELETE /internal/demo/price: a simulated competitor price goes through the normal pipeline.

The repricer and the mailer are recorded (no LLM calls, no email); the rules, storage, proposals
and audit trail are the real ones.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.api.routes import internal
from app.core.config import Settings, get_settings
from app.db.models import PriceObservation
from app.main import app
from app.services import ai_bridge, runner
from tests.conftest import add_listing, make_product
from tests.fakes import Recorder

AUTH = {"X-Internal-Secret": "test-secret"}


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def rec(monkeypatch):
    r = Recorder()
    monkeypatch.setattr(ai_bridge, "reprice", r.repricer)
    monkeypatch.setattr(runner, "send_email", r.mailer)
    return r


def simulate(client, listing_id, price=None, **kw):
    return client.post("/internal/demo/price", headers=AUTH, json={"listing_id": listing_id, "price_inr": price} | kw)


def test_requires_secret_and_can_be_disabled(client, db, monkeypatch):
    product, item = make_product(db, prices=[799])
    assert client.post("/internal/demo/price", json={"listing_id": item.id, "price_inr": 700}).status_code == 401
    monkeypatch.setattr(internal, "get_settings", lambda: Settings(demo_endpoints_enabled=False))
    assert simulate(client, item.id, 700).status_code == 404


def test_competitor_drop_runs_through_the_normal_pipeline(client, db, rec, fake_amazon):
    product, item = make_product(db, prices=[1000], our_price_inr=900, floor_price_inr=700)

    r = simulate(client, item.id, 800)
    assert r.status_code == 200
    out = r.json()
    assert out["simulated_price_inr"] == 800 and out["previous_price_inr"] == 1000
    assert out["our_price_before_inr"] == 900 and out["our_price_after_inr"] == 900 and out["floor_price_inr"] == 700
    obs = out["observation"]
    assert obs["price_inr"] == 800 and obs["ok"] is True and obs["source"] == "demo" and obs["fetched_at"]
    (trigger,) = out["run"]["triggers"]
    assert trigger["trigger"] == "price_drop" and trigger["proposal_status"] == "pending" and trigger["emailed"]
    assert out["decision"]["action"] == "lower_price"
    assert rec.calls[0][1] == "price_drop" and len(rec.mails) == 1
    assert fake_amazon.fetches == 0  # only the scraper's output was simulated

    (series,) = client.get(f"/api/products/{product.id}/history").json()
    assert [p["price_inr"] for p in series["points"]][-2:] == [1000, 800]
    assert client.get(f"/api/products/{product.id}/decisions").json()[0]["alerted"] is True
    assert out["lowest_price_inr"] == 800 and out["marketplace"] == "amazon_in" and out["product_id"] == product.id


def test_increase_and_unchanged_price(client, db, rec):
    product, item = make_product(db, prices=[1000], our_price_inr=900)
    assert simulate(client, item.id, 1000).json()["run"]["triggers"] == []  # no change: no AI, no email
    rec.decision = {"action": "hold", "recommended_price_inr": None}
    (trigger,) = simulate(client, item.id, 1100).json()["run"]["triggers"]
    assert trigger["trigger"] == "price_increase" and trigger["proposal_id"] is None


def test_min_change_pct_filters_small_moves(client, db, rec):
    product, item = make_product(db, prices=[1000], min_change_pct=5)
    assert simulate(client, item.id, 980).json()["run"]["triggers"] == []
    assert simulate(client, item.id, 900).json()["run"]["triggers"][0]["trigger"] == "price_drop"


def test_stock_changes(client, db, rec):
    product, item = make_product(db, prices=[799])
    rec.decision = {"action": "hold", "recommended_price_inr": None}
    out = simulate(client, item.id, in_stock=False).json()
    assert out["observation"]["in_stock"] is False and out["run"]["triggers"][0]["trigger"] == "out_of_stock"
    assert simulate(client, item.id, 799).json()["run"]["triggers"][0]["trigger"] == "back_in_stock"


def test_auto_apply_shows_the_new_price(client, db, monkeypatch):
    r = Recorder(status="auto_approved", recommended_price_inr=880)
    monkeypatch.setattr(ai_bridge, "reprice", r.repricer)
    monkeypatch.setattr(runner, "send_email", r.mailer)
    product, item = make_product(db, prices=[1000], our_price_inr=900, auto_apply=True)
    out = simulate(client, item.id, 880).json()
    assert out["our_price_after_inr"] == 880 and out["run"]["triggers"][0]["proposal_status"] == "auto_applied"


def test_validation(client, db, rec):
    product, item = make_product(db, prices=[799])
    assert simulate(client, item.id, 0).status_code == 422
    assert simulate(client, item.id, -5).status_code == 422
    assert simulate(client, item.id).status_code == 422  # in stock needs a price
    assert simulate(client, 999_999, 700).status_code == 404
    client.patch(f"/api/products/{product.id}", json={"active": False})
    assert simulate(client, item.id, 700).status_code == 409


def test_clear_removes_only_simulated_readings(client, db, rec):
    product, item = make_product(db, prices=[799, 799])
    simulate(client, item.id, 900)
    r = client.delete(f"/internal/demo/price?product_id={product.id}", headers=AUTH)
    assert r.status_code == 200 and r.json()["deleted_observations"] == 1
    sources = db.scalars(select(PriceObservation.source).where(PriceObservation.item_id == item.id)).all()
    assert sources == ["html", "html"]


def test_simulating_one_platform_prices_against_the_lowest(client, db, rec):
    product, amazon = make_product(db, prices=[1000], our_price_inr=950)
    flipkart = add_listing(db, product, prices=[980], marketplace="flipkart", external_id="itmTESTFK01")
    out = simulate(client, flipkart.id, 900).json()
    assert (
        out["marketplace"] == "flipkart" and out["lowest_price_inr"] == 900 and out["lowest_marketplace"] == "flipkart"
    )
    assert out["run"]["triggers"][0]["listing_id"] == flipkart.id
    assert simulate(client, amazon.id, 870).json()["lowest_marketplace"] == "amazon_in"


def test_health_reports_demo_mode_and_cors_allows_the_secret_header(client):
    health = client.get("/health").json()
    assert health["status"] == "ok" and health["demo_endpoints"] is True
    assert health["ai"]["daily_limit"] == get_settings().max_agent_invocations_per_day
    assert health["ai"]["runs_today"] >= 0
    r = client.options(
        "/internal/demo/price",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,x-internal-secret",
        },
    )
    assert r.status_code == 200 and "x-internal-secret" in r.headers["access-control-allow-headers"].lower()
