"""Approval races: many reviewers clicking at the same instant.

`proposals.review` locks the proposal row (SELECT … FOR UPDATE) before it resumes the paused
workflow, so concurrent clicks queue on the lock and only the first one finds the proposal still
pending. These tests release N threads from a barrier at once and check the outcome in the
database: one decision, one price change, the rest refused (the API maps that to 409).

The resumer is wrapped with a short sleep so the race window is wide: without the lock, every
thread would read "pending" before the first one commits. The last-but-one test proves that by
removing the lock and watching the price get applied more than once.
"""

import threading
import time
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.ai.schemas import RepricingDecision, RepricingOutcome, ReviewAnswer
from app.db import repo
from app.db.models import OurPriceChange, Product, RepriceProposal
from app.services import ai_bridge, proposals
from app.services.runner import run_once
from app.services.sources.base import FetchResult
from tests.conftest import make_product
from tests.test_proposals import use_workflow

N = 10
RACE_WINDOW_S = 0.2


def race(n, call):
    """Run `call(i)` on n threads released together; returns (results, errors, wall seconds)."""
    barrier = threading.Barrier(n)
    results, errors = [None] * n, [None] * n

    def worker(i):
        barrier.wait()
        try:
            results[i] = call(i)
        except Exception as exc:  # noqa: BLE001 - the test inspects what each click got
            errors[i] = exc

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    t0 = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    return results, errors, time.perf_counter() - t0


def slow(resume):
    calls = []

    def wrapped(thread_id, answer):
        calls.append(thread_id)
        time.sleep(RACE_WINDOW_S)
        return resume(thread_id, answer)

    return wrapped, calls


def pending_from_real_workflow(db, fake_amazon, monkeypatch):
    """Competitor drop → the production workflow pauses for review (scripted model, no LLM)."""
    monkeypatch.setattr("app.services.runner.send_email", lambda *a, **k: None)
    product, listing = make_product(
        db, prices=[999, 999, 999], our_price_inr=979, floor_price_inr=850, undercut_by_inr=10
    )
    use_workflow(monkeypatch, listing.id)
    fake_amazon.next = [FetchResult(ok=True, price_inr=Decimal("899"), in_stock=True)]
    run_once()
    proposal = db.scalars(select(RepriceProposal)).one()
    assert proposal.status == "pending"
    db.rollback()  # don't hold a snapshot open while the threads race
    return product.id, proposal.id


def price_changes(db, product_id):
    db.rollback()
    return db.scalar(select(func.count()).select_from(OurPriceChange).where(OurPriceChange.product_id == product_id))


def test_concurrent_approvals_apply_the_price_once(db, fake_amazon, monkeypatch):
    product_id, pid = pending_from_real_workflow(db, fake_amazon, monkeypatch)
    resume, calls = slow(ai_bridge.resume_reprice)

    results, errors, _ = race(
        N, lambda i: proposals.review(pid, ReviewAnswer(approved=True, by=f"r{i}"), resume=resume)
    )

    winners = [r for r in results if r is not None]
    assert len(winners) == 1 and winners[0].status == "approved"
    assert sum(isinstance(e, proposals.ProposalClosed) for e in errors) == N - 1
    assert len(calls) == 1  # the paused workflow was resumed exactly once
    assert price_changes(db, product_id) == 1
    assert db.get(Product, product_id).our_price_inr == Decimal("889.00")
    assert db.get(RepriceProposal, pid).resolved_by == winners[0].resolved_by


def test_approve_and_reject_racing_have_one_winner(db, fake_amazon, monkeypatch):
    product_id, pid = pending_from_real_workflow(db, fake_amazon, monkeypatch)
    resume, calls = slow(ai_bridge.resume_reprice)

    results, errors, _ = race(
        N, lambda i: proposals.review(pid, ReviewAnswer(approved=i % 2 == 0, by=f"r{i}"), resume=resume)
    )

    (winner,) = [r for r in results if r is not None]
    assert sum(isinstance(e, proposals.ProposalClosed) for e in errors) == N - 1 and len(calls) == 1
    final = db.get(RepriceProposal, pid)
    db.refresh(final)
    if winner.status == "approved":
        assert price_changes(db, product_id) == 1 and db.get(Product, product_id).our_price_inr == Decimal("889.00")
    else:
        assert winner.status == "rejected"
        assert price_changes(db, product_id) == 0 and db.get(Product, product_id).our_price_inr == Decimal("979.00")
    assert final.status == winner.status


# --------------------------------------------------------------------------- stub workflow

DECISION = RepricingDecision(
    product_id=1,
    event="price_drop",
    competitor_price_inr=899,
    our_price_inr=979,
    action="lower_price",
    recommended_price_inr=889,
    market_read="sustained_change",
    urgency="high",
    reasoning="Competitor dropped to ₹899.",
    confidence=0.9,
)


def approve_stub(thread_id, answer):
    status = "approved" if answer.approved else "rejected"
    return RepricingOutcome(thread_id=thread_id, decision=DECISION, status=status, final_price_inr=889.0)


def stub_proposals(db, n):
    ids = []
    for i in range(n):
        product, listing = make_product(
            db, prices=[999], our_price_inr=979, floor_price_inr=850, external_id=f"B0RACE{i:04d}", title=f"P{i}"
        )
        p = repo.add_proposal(
            db,
            product_id=product.id,
            item_id=listing.id,
            thread_id=f"stub-{i}",
            status="pending",
            action="lower_price",
            competitor_price_inr=Decimal("899"),
            from_price_inr=Decimal("979"),
            to_price_inr=Decimal("889"),
            change_pct=Decimal("-9.19"),
        )
        ids.append((product.id, p.id))
    db.commit()
    return ids


def test_without_the_row_lock_the_race_double_applies(db, monkeypatch):
    """Counterfactual: proves the race above is real and the lock is what stops it."""
    ((product_id, pid),) = stub_proposals(db, 1)
    unlocked = repo.get_proposal
    monkeypatch.setattr(repo, "get_proposal", lambda s, i, for_update=False: unlocked(s, i, for_update=False))
    resume, calls = slow(approve_stub)

    race(N, lambda i: proposals.review(pid, ReviewAnswer(approved=True, by=f"r{i}"), resume=resume))

    assert len(calls) > 1 and price_changes(db, product_id) > 1  # double-applied without the lock


@pytest.mark.parametrize("n", [5])
def test_reviews_of_different_proposals_do_not_wait_on_each_other(db, n):
    """The lock is per proposal row: approving different proposals runs in parallel."""
    pairs = stub_proposals(db, n)
    resume, calls = slow(approve_stub)

    results, errors, wall = race(
        n, lambda i: proposals.review(pairs[i][1], ReviewAnswer(approved=True, by="r"), resume=resume)
    )

    assert errors == [None] * n and len(calls) == n
    assert all(r.status == "approved" for r in results)
    assert wall < RACE_WINDOW_S * n * 0.6  # serialised would take ≥ n × the resume time
    assert all(price_changes(db, product_id) == 1 for product_id, _ in pairs)
