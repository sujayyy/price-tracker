"""Tests that touch the database run against a separate Postgres database (never SQLite).

Set TEST_DATABASE_URL to override; defaults to the `tracker_test` database created by
infra/postgres-init when the compose Postgres volume is first initialised.
"""

import os
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://tracker:tracker@localhost:5432/tracker_test"
)
os.environ["INTERNAL_RUN_SECRET"] = "test-secret"
os.environ["DEMO_ENDPOINTS_ENABLED"] = "true"
os.environ["SOURCE_MIN_INTERVAL_SECONDS"] = "0"
os.environ["LANGSMITH_TRACING"] = "false"
os.environ["OPS_ALERT_EMAILS"] = "ops@example.com"

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.db import repo  # noqa: E402
from app.db.base import SessionLocal, engine  # noqa: E402
from app.db.models import PriceObservation, Product, TrackedItem  # noqa: E402
from app.services.sources import SOURCES, amazon_in, flipkart  # noqa: E402
from app.services.sources.base import FetchResult  # noqa: E402

BACKEND = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session", autouse=True)
def _migrated():
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    command.upgrade(cfg, "head")


@pytest.fixture
def db():
    with engine.begin() as conn:
        conn.execute(
            text(
                "TRUNCATE our_price_changes, reprice_proposals, alerts_sent, decisions, price_observations, runs, "
                "tracked_items, products, app_settings RESTART IDENTITY CASCADE"
            )
        )
    with SessionLocal() as s:
        yield s


class FakeAmazon(amazon_in.AmazonInSource):
    """Real URL parsing, scripted fetch results."""

    def __init__(self):
        self.next: list[FetchResult] = []
        self.fetches = 0

    def fetch(self, ref):
        self.fetches += 1
        if self.next:
            return self.next.pop(0)
        return FetchResult(ok=True, price_inr=Decimal("1000"), in_stock=True, title="Fake Phone")

    def search(self, query, limit=8):
        return []


@pytest.fixture
def fake_amazon(monkeypatch):
    fake = FakeAmazon()
    monkeypatch.setitem(SOURCES, "amazon_in", fake)
    return fake


def add_listing(
    session, product, *, prices, marketplace="amazon_in", external_id=None, hours_apart=12, last_age_hours=12, **kw
) -> TrackedItem:
    """A competitor listing with a history of ok observations, oldest first; the last is `last_age_hours` old."""
    ext = external_id or f"B0TEST{product.id:04d}"
    listing = TrackedItem(
        product_id=product.id,
        marketplace=marketplace,
        external_id=ext,
        canonical_url=(
            f"https://www.amazon.in/dp/{ext}" if marketplace == "amazon_in" else f"https://www.flipkart.com/x/p/{ext}"
        ),
        title=kw.pop("title", product.title),
        **kw,
    )
    session.add(listing)
    session.flush()
    now = repo.utcnow()
    for i, p in enumerate(prices):
        age = last_age_hours + hours_apart * (len(prices) - 1 - i)
        session.add(
            PriceObservation(
                item_id=listing.id,
                fetched_at=now - timedelta(hours=age),
                price_inr=Decimal(str(p)),
                in_stock=True,
                source="html",
                ok=True,
            )
        )
    session.commit()
    return listing


class FakeFlipkart(flipkart.FlipkartSource):
    """Real URL parsing, scripted fetch results."""

    def __init__(self):
        self.next: list[FetchResult] = []
        self.fetches = 0

    def fetch(self, ref):
        self.fetches += 1
        if self.next:
            return self.next.pop(0)
        return FetchResult(ok=True, price_inr=Decimal("990"), in_stock=True, title="Fake Phone (Flipkart)")

    def search(self, query, limit=8):
        return []


@pytest.fixture
def fake_flipkart(monkeypatch):
    fake = FakeFlipkart()
    monkeypatch.setitem(SOURCES, "flipkart", fake)
    return fake


def make_product(session, *, prices, external_id=None, hours_apart=12, last_age_hours=12, listing_kw=None, **kw):
    """Our product with one Amazon.in listing. Returns (product, listing); with fresh tables both ids are 1."""
    product = Product(title=kw.pop("title", "Test Phone"), notify_email=kw.pop("notify_email", None), **kw)
    session.add(product)
    session.flush()
    listing = add_listing(
        session,
        product,
        prices=prices,
        external_id=external_id,
        hours_apart=hours_apart,
        last_age_hours=last_age_hours,
        **(listing_kw or {}),
    )
    return product, listing
