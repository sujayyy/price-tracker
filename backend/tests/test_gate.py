from datetime import UTC, datetime

from app.ai.schemas import AlertRules, HistoryStats, ObservationView
from app.services.gate import FAILURE_STREAK_TRIGGER, GateInput, evaluate_trigger

NOW = datetime(2026, 9, 1, tzinfo=UTC)


def obs(price, in_stock=True, ok=True, error=None):
    return ObservationView(
        listing_id=1,
        fetched_at=NOW,
        price_inr=price,
        mrp_inr=None,
        in_stock=in_stock,
        seller=None,
        source="html",
        ok=ok,
        error=error,
    )


def stats(median30=1000.0, atl=900.0, ath=1100.0, points=10):
    return HistoryStats(
        listing_id=1,
        window_days=90,
        points_in_window=points,
        min_inr=atl,
        median_inr=median30,
        max_inr=ath,
        median_30d_inr=median30,
        all_time_low_inr=atl,
        all_time_high_inr=ath,
        latest_price_inr=None,
    )


def gate(latest, prev=None, rules=None, st=None, failures=0):
    return evaluate_trigger(
        GateInput(
            rules=rules or AlertRules(),
            latest=latest,
            previous_ok=prev,
            stats=st or stats(),
            consecutive_failures=failures,
        )
    )


def test_no_change_or_first_reading_no_trigger():
    assert gate(obs(1000), prev=obs(1000)) is None
    assert gate(obs(1000)) is None


def test_any_price_move_fires_in_either_direction():
    assert gate(obs(999), prev=obs(1000)) == "price_drop"
    assert gate(obs(1001), prev=obs(1000)) == "price_increase"


def test_min_change_pct_filters_small_moves():
    rules = AlertRules(min_change_pct=2)
    assert gate(obs(990), prev=obs(1000), rules=rules) is None  # 1%
    assert gate(obs(970), prev=obs(1000), rules=rules) == "price_drop"
    assert gate(obs(1030), prev=obs(1000), rules=rules) == "price_increase"


def test_stock_changes():
    assert gate(obs(None, in_stock=False), prev=obs(1000)) == "out_of_stock"
    assert gate(obs(1000), prev=obs(None, in_stock=False)) == "back_in_stock"
    off = AlertRules(alert_on_stock_change=False)
    assert gate(obs(None, in_stock=False), prev=obs(1000), rules=off) is None
    assert gate(obs(1000), prev=obs(None, in_stock=False), rules=off) is None


def test_still_out_of_stock_is_quiet():
    assert gate(obs(None, in_stock=False), prev=obs(None, in_stock=False)) is None


def test_anomalous_price_needs_attention():
    assert gate(obs(100), prev=obs(1000)) == "needs_attention"  # < 40% of all-time low
    assert gate(obs(5000), prev=obs(1000)) == "needs_attention"
    # Not enough history to call anything anomalous.
    assert gate(obs(100), prev=obs(1000), st=stats(points=1)) == "price_drop"


def test_in_stock_without_price_is_anomalous():
    assert gate(obs(None, in_stock=True), prev=obs(1000)) == "needs_attention"


def test_fetch_failure_streak_fires_once():
    failed = obs(None, in_stock=None, ok=False, error="blocked")
    assert gate(failed, failures=1) is None
    assert gate(failed, failures=FAILURE_STREAK_TRIGGER) == "needs_attention"
    assert gate(failed, failures=FAILURE_STREAK_TRIGGER + 1) is None
