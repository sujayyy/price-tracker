"""Deterministic pricing guardrails: the only place a price is ever computed.

The analyst picks *which* move to make from `PricingContext.options`; it never invents a price.
`enforce` re-checks the model's choice after the fact, and `validate_review` re-checks an
approval against fresh data right before anything is applied. Pure functions: no I/O, no LLM.
"""

from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel

from app.ai.schemas import (
    CompetitorView,
    HistoryStats,
    Marketplace,
    ObservationView,
    Position,
    PriceOption,
    PricingContext,
    PricingRules,
    Proposal,
    RepricingDecision,
    ReviewAnswer,
)

# While every competitor is out of stock we step up by this fraction of the max move.
OOS_RAISE_FRACTION = 0.5
SAME_PRICE_TOLERANCE_INR = 0.5
# Readings this far outside a listing's own history are suspicious, not real moves (the gate uses these too).
ANOMALY_LOW_FACTOR = 0.4
ANOMALY_HIGH_FACTOR = 2.5
MIN_POINTS_FOR_ANOMALY = 3


def inr(value: float | None) -> str:
    return "—" if value is None else f"₹{value:,.0f}" if value == int(value) else f"₹{value:,.2f}"


def _whole(value: float) -> int:
    return math.floor(value + 0.5)


def pct_change(new: float, base: float) -> float:
    return round((new - base) / base * 100, 2) if base else 0.0


def position(
    our: float | None, competitor: float | None, competitor_in_stock: bool | None
) -> tuple[Position, float | None, float | None]:
    """Where we stand against the competitor: (position, gap_inr, gap_pct). Positive gap = we are pricier."""
    if our is None:
        return "our_price_not_set", None, None
    if competitor is None or competitor_in_stock is False:
        return "competitor_unavailable", None, None
    gap = round(our - competitor, 2)
    gap_pct = round(gap / competitor * 100, 2) if competitor else None
    if abs(gap) < SAME_PRICE_TOLERANCE_INR:
        return "same_price", gap, gap_pct
    return ("we_are_pricier" if gap > 0 else "we_are_cheaper"), gap, gap_pct


def _priced(
    action: Literal["lower_price", "raise_price"],
    target: float,
    rules: PricingRules,
    why: str,
    competitor: float | None = None,
):
    """Clamp a target price to the floor and the max move; None if nothing is left of the move."""
    our = rules.our_price_inr
    assert our is not None
    step = rules.max_change_pct / 100
    lo, lo_by = math.ceil(our * (1 - step)), "max_change"
    hi = math.floor(our * (1 + step))
    if rules.floor_price_inr is not None and math.ceil(rules.floor_price_inr) >= lo:
        lo, lo_by = math.ceil(rules.floor_price_inr), "floor"

    price, limited_by = _whole(target), None
    if price < lo:
        price, limited_by = lo, lo_by
    elif price > hi:
        price, limited_by = hi, "max_change"
    if (action == "lower_price" and price >= our) or (action == "raise_price" and price <= our):
        return None

    # A capped move only goes part of the way: say so up front, so nobody reads it as a full undercut.
    note = f"Part of the way toward: {why[0].lower()}{why[1:]}" if limited_by else why
    if limited_by == "floor":
        note += f"; held at our floor {inr(price)} (the full move needs {inr(_whole(target))})"
    elif limited_by == "max_change":
        note += f"; capped at the {rules.max_change_pct:g}% max move (the full move needs {inr(_whole(target))})"
    if action == "lower_price" and competitor is not None and price > competitor:
        note += f". We would still be {inr(price - competitor)} ABOVE the competitor, not below it"
    return PriceOption(
        action=action,
        price_inr=float(price),
        change_pct=pct_change(price, our),
        limited_by=limited_by,
        gap_after_inr=round(price - competitor, 2) if competitor is not None else None,
        note=note,
    )


def trend(latest: float | None, previous: float | None) -> Literal["down", "up", "flat", "unknown"]:
    if latest is None or previous is None:
        return "unknown"
    return "down" if latest < previous else "up" if latest > previous else "flat"


def looks_suspect(price: float | None, stats: HistoryStats | None) -> bool:
    """A price far outside the listing's own history (e.g. ₹499 for a ₹55k phone)."""
    if price is None or stats is None or stats.points_in_window < MIN_POINTS_FOR_ANOMALY:
        return False
    if stats.all_time_low_inr and price < stats.all_time_low_inr * ANOMALY_LOW_FACTOR:
        return True
    return bool(stats.all_time_high_inr and price > stats.all_time_high_inr * ANOMALY_HIGH_FACTOR)


class ListingSnapshot(BaseModel):
    """What the provider knows about one competitor listing when pricing is computed."""

    listing_id: int
    marketplace: Marketplace
    latest: ObservationView | None
    previous_price: float | None = None
    last_known_price: float | None = None
    stats: HistoryStats | None = None


def _competitor(snap: ListingSnapshot) -> CompetitorView:
    usable = snap.latest is not None and snap.latest.ok
    in_stock = snap.latest.in_stock if usable else None
    price = snap.latest.price_inr if usable and in_stock is not False else None
    return CompetitorView(
        listing_id=snap.listing_id,
        marketplace=snap.marketplace,
        price_inr=price,
        in_stock=in_stock,
        previous_price_inr=snap.previous_price,
        change_pct=pct_change(price, snap.previous_price) if price and snap.previous_price else None,
        trend=trend(price, snap.previous_price),
        suspect=looks_suspect(price, snap.stats),
        is_reference=False,
    )


def build_pricing_context(product_id: int, rules: PricingRules, listings: list[ListingSnapshot]) -> PricingContext:
    """Every move the guardrails allow, priced against the lowest usable in-stock competitor.

    Suspicious readings are ignored as a reference. No raise is offered while ANY competitor is
    cutting (we never raise into a falling market), and we step up only when every competitor
    is out of stock.
    """
    competitors = [_competitor(s) for s in listings]
    usable = [c for c in competitors if c.price_inr is not None and not c.suspect]
    ref = min(usable, key=lambda c: c.price_inr) if usable else None  # type: ignore[arg-type, return-value]
    if ref is not None:
        competitors = [c.model_copy(update={"is_reference": c.listing_id == ref.listing_id}) for c in competitors]
    readings = [c for c in competitors if c.in_stock is not None]
    all_out = bool(readings) and all(c.in_stock is False for c in readings)
    competitor_in_stock = True if ref is not None else (False if all_out else None)
    competitor = ref.price_inr if ref else None
    snap = next((s for s in listings if ref and s.listing_id == ref.listing_id), None)
    if any(c.trend == "down" and not c.suspect for c in competitors):
        direction = "down"
    else:
        direction = ref.trend if ref else "unknown"
    where = f" on {ref.marketplace}" if ref and len(listings) > 1 else ""

    our = rules.our_price_inr
    pos, gap, gap_pct = position(our, competitor, competitor_in_stock)
    options: list[PriceOption] = []
    if our is not None:
        hold_note = "Keep our current price (recommended_price_inr stays null for hold)."
        move = None
        if competitor is not None:
            target = competitor - rules.undercut_by_inr
            how = (
                f"undercut the lowest competitor's {inr(competitor)}{where} by {inr(rules.undercut_by_inr)}"
                if rules.undercut_by_inr
                else f"match the lowest competitor's {inr(competitor)}{where}"
            )
            if target < our:
                move = _priced("lower_price", target, rules, how[0].upper() + how[1:], competitor)
                if move is None:
                    hold_note = (
                        f"Keep our price: the floor {inr(rules.floor_price_inr)} leaves no room to cut "
                        "(recommended_price_inr stays null for hold)."
                    )
            elif target > our and direction == "down":
                hold_note = (
                    "Keep our price: we are still cheaper, and we never raise while a competitor is cutting "
                    "(recommended_price_inr stays null for hold)."
                )
            elif target > our:
                move = _priced("raise_price", target, rules, f"Move up to {how}", competitor)
        elif all_out:
            target = our * (1 + rules.max_change_pct * OOS_RAISE_FRACTION / 100)
            move = _priced("raise_price", target, rules, "Every competitor is out of stock: step up half the max move")
        options.append(
            PriceOption(
                action="hold",
                price_inr=our,
                change_pct=0.0,
                gap_after_inr=round(our - competitor, 2) if competitor is not None else None,
                note=hold_note,
            )
        )
        if move is not None:
            options.append(move)

    last_known = next(
        (s.last_known_price for s in sorted(listings, key=lambda s: s.last_known_price or 1e18) if s.last_known_price),
        None,
    )
    return PricingContext(
        product_id=product_id,
        our_sku=rules.our_sku,
        our_price_inr=our,
        floor_price_inr=rules.floor_price_inr,
        max_change_pct=rules.max_change_pct,
        undercut_by_inr=rules.undercut_by_inr,
        auto_apply=rules.auto_apply,
        auto_apply_max_pct=rules.auto_apply_max_pct,
        competitors=competitors,
        reference_listing_id=ref.listing_id if ref else None,
        reference_marketplace=ref.marketplace if ref else None,
        competitor_price_inr=competitor,
        competitor_in_stock=competitor_in_stock,
        last_known_competitor_price_inr=last_known,
        competitor_previous_price_inr=snap.previous_price if snap else None,
        competitor_trend=direction,
        competitor_change_pct=ref.change_pct if ref else None,
        position=pos,
        gap_inr=gap,
        gap_pct=gap_pct,
        options=options,
    )


Route = Literal["no_change", "needs_review", "auto_apply"]


class GuardrailResult(BaseModel):
    decision: RepricingDecision
    route: Route
    proposal: Proposal | None = None


def enforce(
    decision: RepricingDecision,
    ctx: PricingContext,
    *,
    low_confidence: float = 0.7,
    auto_min_confidence: float = 0.85,
) -> GuardrailResult:
    """Hold the model to the allowed options and decide whether a human must approve."""
    notes: list[str] = []
    update: dict = {"our_price_inr": ctx.our_price_inr}
    route: Route = "no_change"
    proposal = None
    option = next((o for o in ctx.options if o.action == decision.action), None)

    if decision.action in ("hold", "investigate"):
        update["recommended_price_inr"] = None
    elif option is None:
        notes.append(f"guardrail: '{decision.action}' is not an allowed move here; holding instead")
        update |= {"action": "hold", "recommended_price_inr": None}
    elif decision.event == "needs_attention" or decision.market_read == "data_glitch":
        notes.append("guardrail: no price change on suspect data; investigate first")
        update |= {"action": "investigate", "recommended_price_inr": None}
    else:
        if decision.recommended_price_inr != option.price_inr:
            notes.append(
                f"guardrail: recommended {inr(decision.recommended_price_inr)} replaced by the allowed "
                f"{inr(option.price_inr)}"
            )
        update["recommended_price_inr"] = option.price_inr
        if option.limited_by == "floor":
            notes.append(f"guardrail: stopped at the floor {inr(option.price_inr)}")
        if decision.confidence < low_confidence:
            notes.append(f"low confidence ({decision.confidence:.0%}): review carefully")
        proposal = Proposal(
            action=option.action,  # type: ignore[arg-type]
            from_price_inr=ctx.our_price_inr,  # type: ignore[arg-type]
            to_price_inr=option.price_inr,
            change_pct=option.change_pct,
            competitor_price_inr=ctx.competitor_price_inr,
            limited_by=option.limited_by,
        )
        auto = (
            ctx.auto_apply
            and decision.confidence >= auto_min_confidence
            and abs(option.change_pct) <= ctx.auto_apply_max_pct
            and option.limited_by != "floor"
            and decision.market_read != "flash_sale"
        )
        route = "auto_apply" if auto else "needs_review"

    update["data_issues"] = [*decision.data_issues, *notes]
    return GuardrailResult(decision=decision.model_copy(update=update), route=route, proposal=proposal)


class ReviewResult(BaseModel):
    status: Literal["approved", "rejected", "stale", "invalid"]
    final_price_inr: float | None = None
    reason: str


def validate_review(proposal: Proposal, ctx: PricingContext, answer: ReviewAnswer) -> ReviewResult:
    """Re-check an approval against *current* data: the world may have moved since the proposal."""
    if not answer.approved:
        return ReviewResult(status="rejected", reason=f"Rejected by {answer.by}")
    if ctx.our_price_inr != proposal.from_price_inr:
        return ReviewResult(
            status="stale",
            reason=f"Our price changed from {inr(proposal.from_price_inr)} to {inr(ctx.our_price_inr)} since this "
            "was proposed",
        )
    price = round(answer.price_inr if answer.price_inr is not None else proposal.to_price_inr, 2)
    if ctx.floor_price_inr is not None and price < ctx.floor_price_inr:
        return ReviewResult(status="invalid", reason=f"{inr(price)} is below the floor {inr(ctx.floor_price_inr)}")
    if price == ctx.our_price_inr:
        return ReviewResult(status="invalid", reason=f"{inr(price)} is already our price")
    return ReviewResult(status="approved", final_price_inr=price, reason=f"Approved by {answer.by}")
