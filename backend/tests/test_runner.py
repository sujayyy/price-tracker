"""runner.run_once with a recorded repricer — no LLM calls are made in these tests."""

from datetime import timedelta
from decimal import Decimal

from sqlalchemy import func, select

from app.core.config import get_settings
from app.db import repo
from app.db.models import AlertSent, Decision, OurPriceChange, RepriceProposal, Run
from app.services.runner import run_once
from app.services.sources.base import FetchResult
from tests.conftest import add_listing, make_product
from tests.fakes import Recorder


def run(rec, **kw):
    return run_once(repricer=rec.repricer, mailer=rec.mailer, **kw)


def reading(price, in_stock=True):
    return FetchResult(ok=True, price_inr=Decimal(str(price)) if price else None, in_stock=in_stock)


def test_no_change_means_no_agent_call_and_no_email(db, fake_amazon):
    make_product(db, prices=[1000, 990, 1000])
    fake_amazon.next = [reading(1000)]
    rec = Recorder()
    s = run(rec)
    assert s.items_checked == 1 and rec.calls == [] and rec.mails == []
    assert db.scalars(select(Run)).one().finished_at is not None


def test_competitor_drop_opens_a_proposal_and_emails_ops(db, fake_amazon):
    product, listing = make_product(db, prices=[1000, 1000, 1000], our_price_inr=900, notify_email="owner@example.com")
    fake_amazon.next = [reading(800)]
    rec = Recorder()
    s = run(rec)
    assert [c[1] for c in rec.calls] == ["price_drop"] and s.alerts_sent == 1
    assert "Amazon.in listing" in rec.calls[0][2]
    to, subject = rec.mails[0]
    assert to == "ops@example.com, owner@example.com"
    assert subject.startswith("[Approval needed] Lower to ₹810") and "dropped to ₹800" in subject
    p = db.scalars(select(RepriceProposal)).one()
    assert p.status == "pending" and p.product_id == product.id and p.item_id == listing.id
    assert s.triggers[0]["proposal_id"] == p.id and s.triggers[0]["emailed"] is True
    dec = db.scalars(select(Decision)).one()
    assert dec.product_id == product.id and dec.item_id == listing.id
    assert db.scalars(select(AlertSent)).one().decision_id == dec.id
    db.refresh(product)
    assert product.our_price_inr == 900  # nothing is applied until someone approves


def test_two_platforms_moving_together_give_one_decision_and_one_email(db, fake_amazon, fake_flipkart):
    product, amazon = make_product(db, prices=[1000, 1000], our_price_inr=950)
    flipkart = add_listing(db, product, prices=[990, 990], marketplace="flipkart", external_id="itmTESTFK01")
    fake_amazon.next = [reading(900)]
    fake_flipkart.next = [reading(880)]
    rec = Recorder()
    s = run(rec)
    assert s.items_checked == 2 and len(rec.calls) == 1 and len(rec.mails) == 1
    summary = rec.calls[0][2]
    assert "Amazon.in listing" in summary and "Flipkart listing" in summary
    (t,) = s.triggers
    assert sorted(t["listings_changed"]) == sorted([amazon.id, flipkart.id])
    assert db.scalar(select(func.count()).select_from(RepriceProposal)) == 1


def test_price_increase_is_also_reported(db, fake_amazon):
    make_product(db, prices=[1000, 1000], our_price_inr=900)
    fake_amazon.next = [reading(1100)]
    rec = Recorder(action="hold", recommended_price_inr=None)
    s = run(rec)
    assert rec.calls[0][1] == "price_increase" and rec.mails[0][1].startswith("[FYI] Hold at ₹900")
    assert s.triggers[0]["proposal_id"] is None


def test_auto_apply_changes_our_price_with_an_audit_row(db, fake_amazon):
    product, _ = make_product(db, prices=[1000, 1000], our_price_inr=900, auto_apply=True)
    fake_amazon.next = [reading(880)]
    run(Recorder(status="auto_approved", recommended_price_inr=880))
    db.refresh(product)
    assert product.our_price_inr == 880
    change = db.scalars(select(OurPriceChange)).one()
    assert change.source == "auto" and float(change.old_price_inr) == 900 and change.product_id == product.id
    assert db.scalars(select(RepriceProposal)).one().status == "auto_applied"


def test_a_newer_change_supersedes_the_open_proposal(db, fake_amazon):
    make_product(db, prices=[1000, 1000], our_price_inr=900)
    fake_amazon.next = [reading(800)]
    rec = Recorder()
    run(rec)
    fake_amazon.next = [reading(850)]
    run(rec, force=True)
    statuses = db.scalars(select(RepriceProposal.status).order_by(RepriceProposal.id)).all()
    assert statuses == ["superseded", "pending"]


def test_daily_cap_falls_back_without_llm_but_still_reports(db, fake_amazon, monkeypatch):
    monkeypatch.setattr(get_settings(), "max_agent_invocations_per_day", 0)
    make_product(db, prices=[1000, 1000], our_price_inr=900)
    fake_amazon.next = [reading(800)]
    rec = Recorder()
    s = run(rec)
    assert rec.calls == [] and s.alerts_sent == 1
    dec = db.scalars(select(Decision)).one().decision
    assert dec["data_issues"] == ["llm_unavailable: daily agent cap reached"] and dec["action"] == "hold"


def test_agent_failure_falls_back(db, fake_amazon):
    make_product(db, prices=[1000, 1000])
    fake_amazon.next = [reading(800)]
    rec = Recorder()
    rec.fail = True
    s = run(rec)
    assert s.errors == 1 and s.alerts_sent == 1
    assert "no AI recommendation is available" in db.scalars(select(Decision)).one().decision["reasoning"]


def test_no_recipients_is_reported(db, fake_amazon, monkeypatch):
    monkeypatch.setattr(get_settings(), "ops_alert_emails", [])
    make_product(db, prices=[1000, 1000])
    fake_amazon.next = [reading(800)]
    rec = Recorder()
    s = run(rec)
    assert rec.mails == [] and s.triggers[0]["reason"] == "no_recipients"


def test_not_due_paused_and_deleted_are_skipped(db, fake_amazon):
    make_product(db, prices=[1000], last_age_hours=1, external_id="B0RECENT01")  # not due (6h interval)
    make_product(db, prices=[1000], external_id="B0PAUSED01", active=False)
    make_product(db, prices=[1000], external_id="B0DELETED1", active=False, deleted_at=repo.utcnow())
    paused_listing_product, _ = make_product(db, prices=[1000], external_id="B0LSTPAUSE", listing_kw={"active": False})
    due, _ = make_product(db, prices=[1000], external_id="B0DUEDUE01")
    rec = Recorder()
    s = run(rec)
    assert s.items_checked == 1 and fake_amazon.fetches == 1
    assert db.scalar(select(func.count()).where(Decision.product_id == due.id)) == 0
    # force=True ignores the interval but still never touches paused/deleted products or listings.
    s = run(rec, force=True)
    assert s.items_checked == 2


def test_fetch_failure_streak_triggers_once(db, fake_amazon):
    make_product(db, prices=[1000, 1000])
    rec = Recorder(event="needs_attention", action="investigate", recommended_price_inr=None)
    for _ in range(4):
        fake_amazon.next = [FetchResult(ok=False, error="blocked: captcha")]
        run(rec, force=True, now=repo.utcnow() + timedelta(hours=1))
    assert [c[1] for c in rec.calls] == ["needs_attention"]
    assert rec.mails[0][1].startswith("[Check needed]")
