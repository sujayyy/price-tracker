"""Seed the perf database with a realistic, reproducible dataset.

    .venv/bin/python perf/harness/seed.py --products 100 --history 60 --pending 30

Shape (per product): our price, floor (85% of ours), max move 10%, undercut ₹10 on half of them,
one Amazon.in and one Flipkart listing, `history` readings per listing 12 h apart (60 = 30 days),
prices following a seeded random walk.

Decisions and proposals are NOT inserted by hand: a share of products gets a competitor price
drop through the real scheduler cycle (`run_once` with a fake fetch, the real LangGraph workflow
with the deterministic `OptionPickingModel`, a Postgres checkpointer, and a no-op mailer). Some of
the resulting proposals are then approved or rejected through the real approval path; `--pending`
of them stay pending so the approval race tests have something to race on.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from perf.harness import env


def make_dataset(session, n_products: int, history: int, seed: int = 7) -> list[int]:
    """Products + listings + observations. Returns the product ids."""
    from app.db import repo
    from app.db.models import PriceObservation, Product, TrackedItem
    from app.services import pricing

    rng = random.Random(seed)
    now = repo.utcnow()
    ids = []
    for i in range(1, n_products + 1):
        base = rng.uniform(300, 5000)
        amazon = [base]
        for _ in range(history - 1):
            amazon.append(amazon[-1] * (1 + rng.choice([0, 0, 0, 0, rng.uniform(-0.04, 0.04)])))
        flip_ratio = rng.uniform(0.97, 1.05)
        lowest = min(amazon[-1], amazon[-1] * flip_ratio)
        ours = round(lowest * rng.uniform(0.97, 1.08))
        product = Product(
            title=f"Perf product {i:04d} (wireless earbuds, black)",
            our_sku=f"PERF-{i:05d}",
            floor_price_inr=Decimal(str(round(ours * 0.85))),
            max_change_pct=Decimal(10),
            undercut_by_inr=Decimal("10" if i % 2 else "0"),
            check_every_hours=6,
            active=True,
        )
        session.add(product)
        session.flush()
        pricing.set_our_price(
            session,
            product,
            ours,
            source="manual",
            actor="perf-seed",
            note="Initial price",
        )
        for marketplace, ext, url, series in (
            (
                "amazon_in",
                f"B0PERF{i:04d}",
                f"https://www.amazon.in/dp/B0PERF{i:04d}",
                amazon,
            ),
            (
                "flipkart",
                f"PERFFK{i:010d}",
                f"https://www.flipkart.com/perf-{i}/p/itmperf{i:06d}?pid=PERFFK{i:010d}",
                [p * flip_ratio for p in amazon],
            ),
        ):
            listing = TrackedItem(
                product_id=product.id,
                marketplace=marketplace,
                external_id=ext,
                canonical_url=url,
                title=product.title,
            )
            session.add(listing)
            session.flush()
            session.add_all(
                PriceObservation(
                    item_id=listing.id,
                    fetched_at=now - timedelta(hours=12 * (len(series) - 1 - k) + 6),
                    price_inr=Decimal(str(round(p))),
                    in_stock=True,
                    seller="Perf Retail",
                    source="html",
                    ok=True,
                )
                for k, p in enumerate(series)
            )
        ids.append(product.id)
    session.commit()
    return ids


def build_workflow(url: str, model_latency_s: float = 0.0):
    """The production repricing workflow with the deterministic model and a Postgres checkpointer."""
    from app import ai
    from app.services.ai_bridge import BackendDataProvider
    from perf.harness.fake_model import OptionPickingModel

    return ai.build_repricing_workflow(
        BackendDataProvider(),
        model=OptionPickingModel(latency_s=model_latency_s),
        checkpointer=ai.get_checkpointer(url),
    )


def drop_fetcher(session, product_ids: set[int], drop_pct: float):
    """A fake scraper: listings of `product_ids` read `drop_pct` below their last price; the rest are unchanged."""
    from app.db import repo
    from app.db.models import TrackedItem
    from app.services.sources.base import FetchResult

    last = {}
    for listing in session.query(TrackedItem).all():
        obs = repo.latest_observation(session, listing.id, ok_only=True)
        last[listing.id] = (listing.product_id, obs.price_inr if obs else Decimal(1000))

    def fetch(listing) -> FetchResult:
        product_id, price = last[listing.id]
        if product_id in product_ids:
            price = (price * Decimal(str(1 - drop_pct))).quantize(Decimal(1))
        return FetchResult(ok=True, price_inr=price, in_stock=True, seller="Perf Retail", title="perf")

    return fetch


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="tracker_perf")
    ap.add_argument("--products", type=int, default=100)
    ap.add_argument("--history", type=int, default=60, help="readings per listing (12 h apart)")
    ap.add_argument(
        "--drop-share",
        type=float,
        default=0.4,
        help="share of products that get a competitor drop",
    )
    ap.add_argument(
        "--pending",
        type=int,
        default=30,
        help="proposals left pending for the approval race tests",
    )
    args = ap.parse_args()

    url = env.apply(args.db)
    env.ensure_database(args.db)
    env.reset_database()

    from app import ai
    from app.ai.schemas import ReviewAnswer
    from app.db.base import SessionLocal
    from app.db.models import RepriceProposal
    from app.services import proposals
    from app.services.runner import run_once

    t0 = time.perf_counter()
    with SessionLocal() as s:
        ids = make_dataset(s, args.products, args.history)
        rng = random.Random(11)
        dropped = set(rng.sample(ids, max(1, int(len(ids) * args.drop_share))))
        fetch = drop_fetcher(s, dropped, 0.08)
    wf = build_workflow(url)
    summary = run_once(
        force=True,
        fetch=fetch,
        repricer=lambda pid, trig, summ, tag: ai.start_repricing(wf, pid, trig, summ, run_tag=tag),
        mailer=lambda *a: None,
    )

    with SessionLocal() as s:
        pending = [p.id for p in s.query(RepriceProposal).filter_by(status="pending").order_by(RepriceProposal.id)]
    keep = set(pending[: args.pending])
    resolved = {"approved": 0, "rejected": 0}
    for i, pid in enumerate(p for p in pending if p not in keep):
        approve = i % 2 == 0
        proposals.review(
            pid,
            ReviewAnswer(approved=approve, by="perf-seed", note="seeded"),
            resume=lambda tid, ans: ai.resume_repricing(wf, tid, ans),
        )
        resolved["approved" if approve else "rejected"] += 1

    with SessionLocal() as s:
        from sqlalchemy import func, select

        from app.db.models import (
            Decision,
            OurPriceChange,
            PriceObservation,
            Product,
            TrackedItem,
        )

        counts = {
            name: s.scalar(select(func.count()).select_from(model))
            for name, model in [
                ("products", Product),
                ("listings", TrackedItem),
                ("observations", PriceObservation),
                ("decisions", Decision),
                ("proposals", RepriceProposal),
                ("price_changes", OurPriceChange),
            ]
        }
        counts["pending_proposals"] = s.scalar(
            select(func.count()).select_from(RepriceProposal).where(RepriceProposal.status == "pending")
        )
    out = {
        "db": args.db,
        "args": vars(args),
        "seed_seconds": round(time.perf_counter() - t0, 2),
        "run_once": {k: v for k, v in summary.__dict__.items() if k != "triggers"},
        "resolved": resolved,
        "counts": counts,
    }
    (env.RESULTS / f"dataset-{args.db}.json").write_text(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
