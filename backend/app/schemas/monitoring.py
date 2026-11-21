from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class RunRow(BaseModel):
    id: int
    started_at: datetime
    finished_at: datetime | None
    items_checked: int
    agent_invocations: int
    errors: int
    notes: str | None


class ListingHealth(BaseModel):
    listing_id: int
    product_id: int
    product_title: str
    marketplace: str
    status: Literal["ok", "failing", "paused", "not_checked"]
    last_checked_at: datetime | None
    next_due_at: datetime | None
    check_every_hours: int
    price_inr: float | None
    in_stock: bool | None
    consecutive_failures: int
    last_error: str | None


class MonitoringOut(BaseModel):
    last_run_at: datetime | None
    runs_24h: int
    errors_24h: int
    ai_runs_today: int
    ai_daily_limit: int
    runs: list[RunRow]
    listings: list[ListingHealth]
