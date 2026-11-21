"""Deterministic trigger rules. The repricing workflow runs only when this returns a trigger.

Every rule fires on a *transition* between two readings, never on a state: a competitor sitting
at ₹799 fires `price_drop` once, when it moves there, not on every scheduled check. Rules run
per listing; the runner then makes one decision per product for all of its listings' changes.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.ai import looks_suspect
from app.ai.schemas import AlertRules, HistoryStats, ObservationView, TriggerType

# A fetch-failure streak triggers the agent once, when it reaches this length.
FAILURE_STREAK_TRIGGER = 3


@dataclass(frozen=True)
class GateInput:
    rules: AlertRules
    latest: ObservationView
    previous_ok: ObservationView | None
    stats: HistoryStats
    consecutive_failures: int = 0


def pct_change(price: float, reference: float) -> float:
    return (price - reference) / reference * 100 if reference > 0 else 0.0


def looks_anomalous(latest: ObservationView, stats: HistoryStats) -> bool:
    """Same test the pricing guardrails use to ignore a listing as a reference."""
    if latest.price_inr is None:
        return bool(latest.in_stock)  # "in stock" with no price is a bad parse
    return looks_suspect(latest.price_inr, stats)


def evaluate_trigger(g: GateInput) -> TriggerType | None:
    latest, prev, rules = g.latest, g.previous_ok, g.rules

    if not latest.ok:
        return "needs_attention" if g.consecutive_failures == FAILURE_STREAK_TRIGGER else None
    if looks_anomalous(latest, g.stats):
        return "needs_attention"
    if prev is None:
        return None  # first reading: nothing to compare against

    was_in, now_in = prev.in_stock is not False, latest.in_stock is not False
    if was_in and not now_in:
        return "out_of_stock" if rules.alert_on_stock_change else None
    if not was_in and now_in:
        return "back_in_stock" if rules.alert_on_stock_change else None

    price, prev_price = latest.price_inr, prev.price_inr
    if not now_in or price is None or prev_price is None or price == prev_price:
        return None
    change = pct_change(price, prev_price)
    if rules.min_change_pct is not None and abs(change) < rules.min_change_pct:
        return None
    return "price_drop" if change < 0 else "price_increase"
