"""Monitoring: is the scheduler running, and is every competitor listing being read successfully?"""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter
from sqlalchemy import select

from app.core.config import get_settings
from app.db import repo
from app.db.models import Product, Run, TrackedItem
from app.deps import SessionDep
from app.schemas.monitoring import ListingHealth, MonitoringOut, RunRow

router = APIRouter(prefix="/api", tags=["monitoring"])


@router.get("/monitoring", response_model=MonitoringOut)
def monitoring(session: SessionDep):
    now = repo.utcnow()
    runs = repo.recent_runs(session, 20)
    day_ago = now - timedelta(hours=24)
    last_day = list(session.scalars(select(Run).where(Run.started_at >= day_ago)))
    rows = session.execute(
        select(TrackedItem, Product)
        .join(Product, Product.id == TrackedItem.product_id)
        .where(TrackedItem.deleted_at.is_(None), Product.deleted_at.is_(None))
        .order_by(Product.title, TrackedItem.id)
    ).all()
    reads = repo.listing_reads(session, [listing.id for listing, _ in rows])
    listings = []
    for listing, product in rows:
        r = reads[listing.id]
        latest = r.recent[0] if r.recent else None
        latest_ok = r.latest_ok
        failures = repo.failure_streak(session, listing.id, r)
        active = listing.active and product.active
        status = "paused" if not active else "not_checked" if latest is None else "failing" if failures else "ok"
        listings.append(
            ListingHealth(
                listing_id=listing.id,
                product_id=product.id,
                product_title=product.title,
                marketplace=listing.marketplace,
                status=status,
                last_checked_at=latest.fetched_at if latest else None,
                next_due_at=(latest.fetched_at + timedelta(hours=product.check_every_hours))
                if latest and active
                else None,
                check_every_hours=product.check_every_hours,
                price_inr=float(latest_ok.price_inr) if latest_ok and latest_ok.price_inr is not None else None,
                in_stock=latest_ok.in_stock if latest_ok else None,
                consecutive_failures=failures,
                last_error=latest.error if latest and not latest.ok else None,
            )
        )
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return MonitoringOut(
        last_run_at=runs[0].started_at if runs else None,
        runs_24h=len(last_day),
        errors_24h=sum(r.errors or 0 for r in last_day),
        ai_runs_today=repo.agent_invocations_since(session, day_start),
        ai_daily_limit=get_settings().max_agent_invocations_per_day,
        runs=[
            RunRow(
                id=r.id,
                started_at=r.started_at,
                finished_at=r.finished_at,
                items_checked=r.items_checked or 0,
                agent_invocations=r.agent_invocations or 0,
                errors=r.errors or 0,
                notes=r.notes,
            )
            for r in runs
        ],
        listings=listings,
    )
