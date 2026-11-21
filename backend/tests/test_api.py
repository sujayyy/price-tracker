from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.ai.schemas import IntakeCandidate, IntakeResolution
from app.db.models import Decision, PriceObservation
from app.main import app
from app.services import ai_bridge
from app.services.sources.base import FetchResult
from tests.conftest import make_product

AMAZON = "https://www.amazon.in/Fake-Phone/dp/B0FAKEFAKE/ref=x"
FLIPKART = "https://www.flipkart.com/fake-phone/p/itmFAKEFAKE12?pid=MOBFAKE"


@pytest.fixture
def client():
    return TestClient(app)


def body(*urls, **kw):
    return {
        "listings": [{"url": u} for u in (urls or (AMAZON,))],
        "pricing": {"our_sku": "SKU-1", "our_price_inr": 1100, "floor_price_inr": 900},
    } | kw


def test_create_product_with_two_platforms(client, db, fake_amazon, fake_flipkart):
    r = client.post("/api/products", json=body(AMAZON, FLIPKART))
    assert r.status_code == 201, r.text
    p = r.json()
    assert p["title"] == "Fake Phone" and p["our_price_inr"] == 1100 and p["floor_price_inr"] == 900
    assert [(x["marketplace"], x["latest"]["price_inr"]) for x in p["listings"]] == [
        ("amazon_in", 1000),
        ("flipkart", 990),
    ]
    assert p["lowest_price_inr"] == 990 and p["lowest_marketplace"] == "flipkart"
    assert [x["is_lowest"] for x in p["listings"]] == [False, True]
    assert p["position"] == "we_are_pricier" and p["gap_inr"] == 110
    assert p["notify_email"] is None and p["pending_proposal"] is None
    audit = client.get(f"/api/products/{p['id']}/our-price-history").json()
    assert [(a["new_price_inr"], a["source"], a["actor"]) for a in audit] == [(1100, "manual", "setup")]
    series = client.get(f"/api/products/{p['id']}/history").json()
    assert [(s["marketplace"], len(s["points"])) for s in series] == [("amazon_in", 1), ("flipkart", 1)]
    assert [x["id"] for x in client.get("/api/products").json()] == [p["id"]]


def test_validation_and_conflicts(client, db, fake_amazon):
    assert client.post("/api/products", json=body() | {"listings": []}).status_code == 422
    assert client.post("/api/products", json=body(AMAZON, AMAZON)).status_code == 422
    assert client.post("/api/products", json=body("https://example.com/x")).status_code == 400
    bad_floor = body() | {"pricing": {"our_price_inr": 900, "floor_price_inr": 950}}
    assert client.post("/api/products", json=bad_floor).status_code == 422
    first = client.post("/api/products", json=body()).json()
    r = client.post("/api/products", json=body())
    assert r.status_code == 409 and r.json()["detail"]["product_id"] == first["id"]


def test_add_pause_and_remove_listings(client, db, fake_amazon, fake_flipkart):
    pid = client.post("/api/products", json=body()).json()["id"]
    r = client.post(f"/api/products/{pid}/listings", json={"url": FLIPKART})
    assert r.status_code == 201 and len(r.json()["listings"]) == 2
    fk = next(x for x in r.json()["listings"] if x["marketplace"] == "flipkart")
    r = client.patch(f"/api/listings/{fk['id']}", json={"active": False})
    assert next(x for x in r.json()["listings"] if x["id"] == fk["id"])["active"] is False
    assert r.json()["lowest_marketplace"] == "amazon_in"  # a paused listing is not compared
    assert client.delete(f"/api/listings/{fk['id']}").status_code == 204
    assert len(client.get(f"/api/products/{pid}").json()["listings"]) == 1
    # A removed listing can be attached again, with its history.
    r = client.post(f"/api/products/{pid}/listings", json={"url": FLIPKART})
    assert r.status_code == 201 and db.scalar(select(func.count()).where(PriceObservation.item_id == fk["id"])) == 2


def test_manual_price_change_is_audited_and_respects_the_floor(client, db, fake_amazon):
    pid = client.post("/api/products", json=body()).json()["id"]
    r = client.patch(f"/api/products/{pid}", json={"our_price_inr": 990, "changed_by": "asha"})
    assert r.status_code == 200 and r.json()["our_price_inr"] == 990 and r.json()["position"] == "we_are_cheaper"
    assert client.patch(f"/api/products/{pid}", json={"our_price_inr": 850}).status_code == 422  # below floor
    assert client.patch(f"/api/products/{pid}", json={"floor_price_inr": 1000}).status_code == 422
    audit = client.get(f"/api/products/{pid}/our-price-history").json()
    assert [(a["old_price_inr"], a["new_price_inr"], a["actor"]) for a in audit][0] == (1100, 990, "asha")


def test_patch_and_soft_delete_keep_history(client, db, fake_amazon):
    pid = client.post("/api/products", json=body()).json()["id"]
    r = client.patch(f"/api/products/{pid}", json={"active": False, "min_change_pct": 2.5, "our_sku": None})
    assert r.status_code == 200
    assert r.json()["active"] is False and r.json()["min_change_pct"] == 2.5 and r.json()["our_sku"] is None
    listing_id = r.json()["listings"][0]["id"]
    assert client.delete(f"/api/products/{pid}").status_code == 204
    assert client.get(f"/api/products/{pid}").status_code == 404
    assert client.get("/api/products").json() == []
    # The listing can be monitored again under a new product, keeping its readings.
    fake_amazon.next = [FetchResult(ok=True, price_inr=Decimal("990"), in_stock=True, title="Fake Phone")]
    r = client.post("/api/products", json=body())
    assert r.status_code == 201 and r.json()["listings"][0]["id"] == listing_id
    assert r.json()["listings"][0]["previous_price_inr"] == 1000


def _cand(ext, score, marketplace="amazon_in"):
    url = f"https://www.amazon.in/dp/{ext}" if marketplace == "amazon_in" else f"https://www.flipkart.com/x/p/{ext}"
    return IntakeCandidate(
        marketplace=marketplace, external_id=ext, title=f"Phone {ext}", price_inr=1000, url=url, match_score=score
    )


def test_search_returns_matches_from_both_marketplaces(client, db, monkeypatch):
    res = IntakeResolution(
        resolved=True,
        needs_confirmation=False,
        chosen=_cand("B0AAAAAAAA", 0.95),
        candidates=[_cand("B0AAAAAAAA", 0.95), _cand("itmBBBBBBBBBB", 0.9, "flipkart")],
        reasoning="Same model on both.",
    )
    monkeypatch.setattr(ai_bridge, "resolve_intake", lambda q: res)
    out = client.get("/api/search?q=fake phone").json()
    assert out["ai_used"] is True
    assert [(c["marketplace"], c["external_id"]) for c in out["candidates"]] == [
        ("amazon_in", "B0AAAAAAAA"),
        ("flipkart", "itmBBBBBBBBBB"),
    ]


def test_search_falls_back_to_plain_marketplace_search(client, db, monkeypatch, fake_amazon, fake_flipkart):
    def boom(q):
        raise RuntimeError("no api key")

    def blocked(query, limit=8):
        raise RuntimeError("blocked: js challenge")

    monkeypatch.setattr(ai_bridge, "resolve_intake", boom)
    monkeypatch.setattr(fake_amazon, "search", lambda q, limit=8: [_cand("B0AAAAAAAA", 0)])
    monkeypatch.setattr(fake_flipkart, "search", blocked)
    out = client.get("/api/search?q=fake phone").json()
    assert out["ai_used"] is False and [c["external_id"] for c in out["candidates"]] == ["B0AAAAAAAA"]
    assert "blocked" in out["errors"]["flipkart"]
    assert client.get("/api/search?q=ab").status_code == 422


def test_legacy_consumer_decisions_are_still_listed(client, db):
    product, listing = make_product(db, prices=[799])
    legacy = {
        "item_id": product.id, "current_price_inr": 700, "availability": "in_stock", "should_alert": True,
        "alert_type": "target_hit", "deal_quality": "excellent", "compared_to": "target",
        "reasoning": "₹700 is below the ₹800 target.", "confidence": 0.95, "data_issues": [],
    }  # fmt: skip
    db.add(Decision(product_id=product.id, item_id=listing.id, trigger_type="target_hit", decision=legacy))
    db.commit()
    (d,) = client.get(f"/api/products/{product.id}/decisions").json()
    assert d["decision"]["action"] == "hold" and d["decision"]["reasoning"] == "₹700 is below the ₹800 target."
    assert d["decision"]["data_issues"][-1].startswith("legacy") and d["marketplace"] == "amazon_in"


def test_internal_run_requires_secret(client, db, fake_amazon):
    assert client.post("/internal/run-once").status_code == 401
    assert client.post("/internal/run-once", headers={"X-Internal-Secret": "wrong"}).status_code == 401
    r = client.post("/internal/run-once", headers={"X-Internal-Secret": "test-secret"})
    assert r.status_code == 200 and r.json()["agent_invocations"] == 0


def test_activity_feed_and_sparkline(client, db, fake_amazon, monkeypatch):
    from app.services import runner
    from tests.fakes import Recorder

    pid = client.post("/api/products", json=body()).json()["id"]
    fake_amazon.next = [FetchResult(ok=True, price_inr=Decimal("900"), in_stock=True)]
    rec = Recorder()
    runner.run_once(repricer=rec.repricer, mailer=rec.mailer, force=True)
    (a,) = client.get("/api/activity").json()
    assert a["product_id"] == pid and a["product_title"] == "Fake Phone" and a["trigger_type"] == "price_drop"
    assert a["marketplace"] == "amazon_in" and a["action"] == "lower_price" and a["alerted"] is True
    assert client.get(f"/api/products/{pid}").json()["sparkline"] == [1000, 900]
