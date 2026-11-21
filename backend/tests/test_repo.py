"""repo.history_stats against real Postgres rows."""

from decimal import Decimal

from app.db import repo
from app.services.sources.base import FetchResult
from tests.conftest import make_product


def test_history_stats_precompute_the_deal_comparison(db):
    _, item = make_product(db, prices=[1999, 1999, 2299, 2299, 1999, 1999])
    stats = repo.history_stats(db, item.id)
    assert stats.all_time_low_inr == 1999 and stats.latest_price_inr == 1999
    assert stats.latest_vs_all_time_low == "equals_low"
    assert stats.prior_readings_at_latest_price == 3

    _, new_low = make_product(db, prices=[1049, 1029, 1049, 1019], external_id="B0NEWLOW00")
    stats = repo.history_stats(db, new_low.id)
    assert stats.latest_vs_all_time_low == "new_low"
    assert stats.prior_readings_at_latest_price == 0


def test_a_reading_keeps_the_listing_photo_current(db):
    _, item = make_product(db, prices=[999])
    url = "https://m.media-amazon.com/images/I/61X._SL400_.jpg"
    repo.add_observation(db, item.id, FetchResult(ok=True, price_inr=Decimal("989"), in_stock=True, image_url=url))
    db.refresh(item)
    assert item.image_url == url
    # A reading without a photo (a failed fetch, a simulated demo price) never clears it.
    repo.add_observation(db, item.id, FetchResult(ok=False, error="blocked: 503"))
    repo.add_observation(db, item.id, FetchResult(ok=True, price_inr=Decimal("979"), in_stock=True, source="demo"))
    db.refresh(item)
    assert item.image_url == url


def test_batched_reads_match_reading_each_listing_alone(db):
    """The list endpoints read many listings at once; nothing may leak between listings."""
    _, a = make_product(db, prices=[1999, 1899, 1999, 2099], title="A")
    _, b = make_product(db, prices=[499, 459, 459], external_id="B0BATCHB00", title="B")
    _, c = make_product(db, prices=[799], external_id="B0BATCHC00", title="C")
    repo.add_observation(db, b.id, FetchResult(ok=False, error="blocked: 503"))  # newest reading of b failed
    db.commit()
    ids = [a.id, b.id, c.id]

    together = repo.listing_reads(db, ids)
    for i in ids:
        alone = repo.listing_reads(db, [i])[i]
        assert repo.stats_from(i, 90, together[i]).model_dump(exclude={"note"}) == repo.stats_from(
            i, 90, alone
        ).model_dump(exclude={"note"})
        assert repo.series_from(together[i]) == repo.series_from(alone)
        assert [o.id for o in together[i].recent] == [o.id for o in alone.recent]
    assert together[b.id].recent[0].ok is False and together[b.id].latest_ok.price_inr == Decimal("459")


def test_failure_streak_reads_past_the_recent_window(db):
    _, item = make_product(db, prices=[999])
    for _ in range(repo.RECENT_READINGS + 5):
        repo.add_observation(db, item.id, FetchResult(ok=False, error="blocked: captcha"))
    db.commit()
    reads = repo.listing_reads(db, [item.id])[item.id]
    assert repo.failure_streak(db, item.id, reads) == repo.consecutive_failures(db, item.id) == 25
