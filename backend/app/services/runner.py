"""One scheduler cycle: fetch listings → store → gate → per product: repricing workflow → proposal/apply → ops email.

Every competitor listing that is due is fetched and checked against the rules on its own. The
changes are then grouped by product, so a product whose Amazon.in and Flipkart listings both
moved gets ONE decision (priced against the lowest competitor across platforms) and ONE email.
A recommended price change becomes a pending proposal (approved in the dashboard), or is
applied at once when the product allows auto-apply and the move is small.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

import structlog
from sqlalchemy.orm import Session, sessionmaker

from app.ai.schemas import ObservationView, RepricingDecision, RepricingOutcome, TriggerType
from app.core.config import get_settings
from app.db import repo
from app.db.base import SessionLocal
from app.db.models import Product, TrackedItem
from app.services import ai_bridge, pricing
from app.services.gate import GateInput, evaluate_trigger
from app.services.notifier.email import (
    MARKETPLACES,
    EmailNotConfigured,
    format_inr,
    render_ops_alert,
    send_email,
)
from app.services.sources import source_for_marketplace
from app.services.sources.base import FetchResult, ListingRef
from app.services.team import ops_emails

log = structlog.get_logger()

Repricer = Callable[[int, TriggerType, str, str], RepricingOutcome]  # product_id, trigger, summary, run_tag
Mailer = Callable[[str, str, str, str], None]
Fetcher = Callable[[TrackedItem], FetchResult]

# When several listings of one product changed in the same cycle, the decision is about this one first.
TRIGGER_PRIORITY: tuple[TriggerType, ...] = (
    "price_drop",
    "out_of_stock",
    "back_in_stock",
    "price_increase",
    "needs_attention",
)
_PROPOSAL_STATUS = {"pending_review": "pending", "auto_approved": "auto_applied"}


def fetch_live(listing: TrackedItem) -> FetchResult:
    """Production input: scrape the competitor listing."""
    ref = ListingRef(listing.marketplace, listing.external_id, listing.canonical_url)
    return source_for_marketplace(listing.marketplace).fetch(ref)


@dataclass
class ListingChange:
    listing_id: int
    marketplace: str
    trigger: TriggerType
    latest: ObservationView
    previous: ObservationView | None


@dataclass
class RunSummary:
    run_id: int
    items_checked: int = 0  # listings fetched
    agent_invocations: int = 0
    errors: int = 0
    triggers: list[dict] = field(default_factory=list)
    alerts_sent: int = 0


def describe(change: ListingChange) -> str:
    mk = MARKETPLACES.get(change.marketplace, change.marketplace)
    now, prev = change.latest, change.previous
    parts = [f"{mk} listing {change.listing_id}: {change.trigger}, latest price {format_inr(now.price_inr)}"]
    parts.append(f"in_stock={now.in_stock}")
    if prev is not None:
        parts.append(f"previous {format_inr(prev.price_inr)} (in_stock={prev.in_stock})")
    if not now.ok:
        parts.append(f"fetch error: {now.error}")
    return ", ".join(parts)


def changes_summary(changes: list[ListingChange]) -> str:
    return "Competitor changes this cycle: " + "; ".join(describe(c) for c in changes) + "."


def primary_change(changes: list[ListingChange]) -> ListingChange:
    return min(changes, key=lambda c: TRIGGER_PRIORITY.index(c.trigger))


def fallback_outcome(
    product_id: int, trigger: TriggerType, latest: ObservationView, our_price: float | None, reason: str
) -> RepricingOutcome:
    """Used when the LLM is unavailable: the change is still reported, with no price recommendation."""
    decision = RepricingDecision(
        product_id=product_id,
        event=trigger,
        competitor_price_inr=latest.price_inr,
        our_price_inr=our_price,
        action="investigate" if trigger == "needs_attention" else "hold",
        recommended_price_inr=None,
        market_read="unknown",
        urgency="high" if trigger == "needs_attention" else "medium",
        reasoning=f"Rule '{trigger}' fired at {format_inr(latest.price_inr)}; no AI recommendation is available "
        f"({reason}), so review this change manually.",
        confidence=0.0,
        data_issues=[f"llm_unavailable: {reason}"],
    )
    return RepricingOutcome(thread_id="", decision=decision, status="no_change")


def recipients(session: Session, product: Product) -> list[str]:
    """The ops team list (saved in the dashboard, else OPS_ALERT_EMAILS) plus the product's extra recipient."""
    team, _ = ops_emails(session)
    out = [*team, *([product.notify_email] if product.notify_email else [])]
    return list(dict.fromkeys(e.strip() for e in out if e.strip()))


def run_once(
    *,
    force: bool = False,
    session_factory: sessionmaker[Session] = SessionLocal,
    repricer: Repricer | None = None,
    mailer: Mailer | None = None,
    now: datetime | None = None,
    listing_id: int | None = None,
    product_id: int | None = None,
    fetch: Fetcher = fetch_live,
) -> RunSummary:
    """`listing_id` / `product_id` limit the cycle to one listing or one product's active listings (a manual
    recheck); `fetch` replaces the scraper (demo/test input only)."""
    repricer = repricer or ai_bridge.reprice
    mailer = mailer or send_email
    now = now or datetime.now(UTC)
    settings = get_settings()
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    with session_factory() as s:
        run = repo.start_run(s)
        s.commit()
        if listing_id is not None:
            listings = [x] if (x := repo.get_listing(s, listing_id)) is not None else []
        elif product_id is not None:
            listings = repo.product_listings(s, product_id)
        else:
            listings = repo.active_listings(s) if force else repo.due_listings(s, now)
        used_today = repo.agent_invocations_since(s, day_start)

    summary = RunSummary(run_id=run.id)
    notes: list[str] = []
    changed: dict[int, list[ListingChange]] = {}
    for listing in listings:
        try:
            change = _check_listing(listing, summary, notes, session_factory, fetch)
            if change is not None:
                changed.setdefault(listing.product_id, []).append(change)
        except Exception as exc:  # one bad listing must not stop the cycle
            summary.errors += 1
            notes.append(f"listing {listing.id}: {type(exc).__name__}: {exc}")
            log.exception("listing_failed", listing_id=listing.id)

    for product_id, changes in changed.items():
        try:
            _decide_product(
                product_id,
                changes,
                summary,
                notes,
                session_factory,
                repricer,
                mailer,
                now,
                budget_left=settings.max_agent_invocations_per_day - used_today - summary.agent_invocations,
            )
        except Exception as exc:
            summary.errors += 1
            notes.append(f"product {product_id}: {type(exc).__name__}: {exc}")
            log.exception("product_failed", product_id=product_id)

    with session_factory() as s:
        repo.finish_run(
            s,
            run,
            items_checked=summary.items_checked,
            agent_invocations=summary.agent_invocations,
            errors=summary.errors,
            notes="\n".join(notes)[:4000] or None,
        )
        s.commit()
    log.info("run_finished", **{k: v for k, v in summary.__dict__.items() if k != "triggers"})
    return summary


def _check_listing(
    listing: TrackedItem, summary: RunSummary, notes: list[str], session_factory, fetch: Fetcher
) -> ListingChange | None:
    result = fetch(listing)
    with session_factory() as s:
        obs = repo.add_observation(s, listing.id, result)
        s.commit()
        summary.items_checked += 1
        if not result.ok:
            summary.errors += 1
            notes.append(f"listing {listing.id}: fetch failed: {result.error}")
        product = s.get(Product, listing.product_id)
        prev = repo.previous_ok_observation(s, listing.id, obs)
        latest_v, prev_v = repo.to_view(obs), (repo.to_view(prev) if prev else None)
        gate = GateInput(
            rules=repo.product_settings(s, product),
            latest=latest_v,
            previous_ok=prev_v,
            stats=repo.history_stats(s, listing.id),
            consecutive_failures=repo.consecutive_failures(s, listing.id),
        )
    trigger = evaluate_trigger(gate)
    log.info("gate_evaluated", listing_id=listing.id, ok=result.ok, price=latest_v.price_inr, trigger=trigger)
    if trigger is None:
        return None  # nothing notable: no LLM call, no email
    return ListingChange(listing.id, listing.marketplace, trigger, latest_v, prev_v)


def _decide_product(
    product_id: int,
    changes: list[ListingChange],
    summary: RunSummary,
    notes: list[str],
    session_factory,
    repricer: Repricer,
    mailer: Mailer,
    now: datetime,
    budget_left: int,
) -> None:
    main = primary_change(changes)
    trigger = main.trigger
    with session_factory() as s:
        product = s.get(Product, product_id)
        our_price = float(product.our_price_inr) if product.our_price_inr is not None else None

    if budget_left <= 0:
        outcome = fallback_outcome(product_id, trigger, main.latest, our_price, "daily agent cap reached")
    else:
        summary.agent_invocations += 1
        try:
            outcome = repricer(product_id, trigger, changes_summary(changes), f"run{summary.run_id}")
        except Exception as exc:
            summary.errors += 1
            notes.append(f"product {product_id}: agent failed: {type(exc).__name__}: {exc}")
            log.warning("agent_failed", product_id=product_id, error=str(exc))
            outcome = fallback_outcome(
                product_id, trigger, main.latest, our_price, f"agent error: {type(exc).__name__}"
            )

    decision, proposal = outcome.decision, outcome.proposal
    with session_factory() as s:
        product = s.get(Product, product_id)
        row = repo.add_decision(s, product_id, main.listing_id, trigger, decision)
        # Any new competitor change makes an older open proposal obsolete.
        repo.supersede_pending(s, product_id, "A newer competitor change replaced this proposal")
        proposal_row = None
        if proposal is not None:
            status = _PROPOSAL_STATUS.get(outcome.status, "failed")
            proposal_row = repo.add_proposal(
                s,
                product_id=product_id,
                item_id=main.listing_id,
                decision_id=row.id,
                thread_id=outcome.thread_id,
                status=status,
                action=proposal.action,
                competitor_price_inr=proposal.competitor_price_inr,
                from_price_inr=proposal.from_price_inr,
                to_price_inr=proposal.to_price_inr,
                change_pct=proposal.change_pct,
                limited_by=proposal.limited_by,
                resolved_at=None if status == "pending" else now,
                resolved_by=None if status == "pending" else "auto-apply",
                resolution_note=outcome.reason if status == "failed" else None,
            )
            if status == "auto_applied" and outcome.final_price_inr is not None:
                pricing.set_our_price(
                    s,
                    product,
                    outcome.final_price_inr,
                    source="auto",
                    actor="auto-apply",
                    proposal_id=proposal_row.id,
                    note=f"Within the {float(product.auto_apply_max_pct):g}% auto-apply limit",
                )
                proposal_row.final_price_inr = outcome.final_price_inr
        s.commit()

        entry = {
            "product_id": product_id,
            "listing_id": main.listing_id,
            "trigger": trigger,
            "listings_changed": [c.listing_id for c in changes],
            "decision_id": row.id,
            "action": decision.action,
            "recommended_price_inr": decision.recommended_price_inr,
            "workflow_status": outcome.status,
            "proposal_id": proposal_row.id if proposal_row else None,
            "proposal_status": proposal_row.status if proposal_row else None,
            "emailed": False,
            "reason": "ok",
        }
        summary.triggers.append(entry)

        to = recipients(s, product)
        if not to:
            entry["reason"] = "no_recipients"
            notes.append(f"product {product_id}: alert not sent: no OPS_ALERT_EMAILS and no notify_email")
            return
        ctx = repo.pricing_context(s, product)
        subject, html, text = render_ops_alert(
            title=product.title,
            sku=product.our_sku,
            marketplace=main.marketplace,
            review_url=f"{get_settings().dashboard_url.rstrip('/')}/products/{product_id}",
            trigger=trigger,
            decision=decision,
            status=outcome.status,
            proposal=proposal,
            competitor_prev=main.previous.price_inr if main.previous else None,
            competitor_now=main.latest.price_inr,
            competitor_in_stock=main.latest.in_stock,
            floor=float(product.floor_price_inr) if product.floor_price_inr is not None else None,
            competitors=ctx.competitors,
            listing_urls={x.id: x.canonical_url for x in repo.product_listings(s, product_id)},
        )
        try:
            mailer(", ".join(to), subject, html, text)
        except EmailNotConfigured as exc:
            notes.append(f"product {product_id}: alert not sent: {exc}")
            entry["reason"] = "email_not_configured"
            return
        except Exception as exc:  # an SMTP failure must not lose the stored decision
            summary.errors += 1
            notes.append(f"product {product_id}: alert not sent: {type(exc).__name__}: {exc}")
            entry["reason"] = "email_failed"
            return
        repo.add_alert(s, main.listing_id, row.id, trigger)
        s.commit()
        entry["emailed"] = True
        summary.alerts_sent += 1
