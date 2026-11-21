"""Team settings: the ops team's alert emails can be changed from the dashboard."""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import runner
from app.services.notifier import email
from app.services.sources.base import FetchResult
from tests.conftest import make_product
from tests.fakes import Recorder


@pytest.fixture
def client():
    return TestClient(app)


def test_defaults_to_the_environment_then_saved_list_wins(client, db):
    out = client.get("/api/settings/team").json()
    assert out["ops_alert_emails"] == ["ops@example.com"] and out["source"] == "environment"

    r = client.put(
        "/api/settings/team",
        json={
            "ops_alert_emails": ["Pricing@Example.com", "lead@example.com", "pricing@example.com"],
            "updated_by": "asha",
        },
    )
    assert r.status_code == 200
    assert r.json()["ops_alert_emails"] == ["pricing@example.com", "lead@example.com"]  # normalised + deduped
    assert r.json()["source"] == "dashboard" and r.json()["updated_by"] == "asha"

    assert client.delete("/api/settings/team").json()["source"] == "environment"


def test_validation(client, db):
    assert client.put("/api/settings/team", json={"ops_alert_emails": []}).status_code == 422
    assert client.put("/api/settings/team", json={"ops_alert_emails": ["not-an-email"]}).status_code == 422


def test_alerts_go_to_the_saved_list(client, db, fake_amazon):
    client.put("/api/settings/team", json={"ops_alert_emails": ["pricing@example.com"]})
    make_product(db, prices=[1000, 1000], our_price_inr=900, notify_email="owner@example.com")
    fake_amazon.next = [FetchResult(ok=True, price_inr=Decimal("800"), in_stock=True)]
    rec = Recorder()
    runner.run_once(repricer=rec.repricer, mailer=rec.mailer)
    assert rec.mails[0][0] == "pricing@example.com, owner@example.com"


def test_test_email(client, db, monkeypatch):
    sent = []
    monkeypatch.setattr(email, "send_email", lambda to, subject, html, text: sent.append((to, subject)))
    r = client.post("/api/settings/team/test-email", json={"sent_by": "asha"})
    assert r.status_code == 200 and r.json()["sent_to"] == ["ops@example.com"]
    assert sent[0][0] == "ops@example.com" and "Test alert" in sent[0][1]

    def not_configured(*a):
        raise email.EmailNotConfigured("SMTP_USER / SMTP_APP_PASSWORD are not set")

    monkeypatch.setattr(email, "send_email", not_configured)
    assert client.post("/api/settings/team/test-email", json={}).status_code == 503


def test_cors_allows_put_from_the_dashboard(client):
    r = client.options(
        "/api/settings/team",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "PUT",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert r.status_code == 200 and "PUT" in r.headers["access-control-allow-methods"]
