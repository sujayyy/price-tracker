"""The isolated performance environment.

Every perf script imports this module FIRST. It points the backend at its own Postgres database
(`tracker_perf` by default, never the dev `tracker` or the pytest `tracker_test` database) and
switches off everything that could reach the outside world:

- no email: SMTP credentials and recipients are blanked, so `send_email` raises EmailNotConfigured;
- no model calls: provider API keys are replaced with a dummy (a real call would fail with 401);
- no LangSmith traces;
- no demo endpoints;
- no marketplace traffic: perf scripts inject fake fetchers, and the k6 scripts only call
  read-only endpoints plus the approval endpoint (see perf/k6/lib.js).

`allow_real_model=True` (only `ai_latency.py --real`) keeps the real provider key from infra/.env.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
# PERF_BACKEND points at another copy of backend/ (e.g. the code before an optimization) so the
# same scripts can measure both versions.
BACKEND = Path(os.environ.get("PERF_BACKEND", ROOT / "backend")).resolve()
RESULTS = ROOT / "perf" / "results"
PG = os.environ.get("PERF_PG", "postgresql+psycopg://tracker:tracker@localhost:5432")
FORBIDDEN_DBS = {"tracker", "tracker_test"}

_applied: str | None = None


def apply(db: str | None = None, *, allow_real_model: bool = False) -> str:
    """Set the environment for `db` and make the backend importable. Call before importing `app`."""
    global _applied
    db = db or os.environ.get("PERF_DB", "tracker_perf")
    if db in FORBIDDEN_DBS:
        raise SystemExit(f"Refusing to run performance tests against the {db!r} database.")
    if "app" in sys.modules and _applied != db:
        raise RuntimeError("perf.harness.env.apply() must run before the backend (`app`) is imported")
    url = f"{PG}/{db}"
    safe = {
        "DATABASE_URL": url,
        "DEMO_ENDPOINTS_ENABLED": "false",
        "SMTP_USER": "",
        "SMTP_APP_PASSWORD": "",
        "OPS_ALERT_EMAILS": "",
        "LANGSMITH_TRACING": "false",
        "LANGCHAIN_TRACING_V2": "false",
        "INTERNAL_RUN_SECRET": "perf-secret",
        "SOURCE_MIN_INTERVAL_SECONDS": "0",
        "MAX_AGENT_INVOCATIONS_PER_DAY": "1000000",
    }
    if not allow_real_model:
        safe |= {k: "perf-disabled" for k in ("ANTHROPIC_API_KEY", "GOOGLE_API_KEY", "OPENAI_API_KEY")}
    os.environ.update(safe)
    if str(BACKEND) not in sys.path:
        sys.path.insert(0, str(BACKEND))
    RESULTS.mkdir(parents=True, exist_ok=True)
    _applied = db
    return url


def ensure_database(db: str) -> None:
    """Create the perf database if needed, then migrate it and create LangGraph's checkpoint tables."""
    import psycopg

    with psycopg.connect(f"{PG.replace('+psycopg', '')}/postgres", autocommit=True) as conn:
        if not conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (db,)).fetchone():
            conn.execute(f'CREATE DATABASE "{db}" OWNER tracker')
    from alembic import command
    from alembic.config import Config

    from app.ai.checkpoint import setup_checkpointer

    url = f"{PG}/{db}"
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    cfg.attributes["database_url"] = url
    command.upgrade(cfg, "head")
    setup_checkpointer(url)


def reset_database() -> None:
    """Empty every app table and LangGraph's checkpoints (the schema stays)."""
    from sqlalchemy import text

    from app.db.base import engine

    with engine.begin() as conn:
        conn.execute(
            text(
                "TRUNCATE our_price_changes, reprice_proposals, alerts_sent, decisions, price_observations, runs, "
                "tracked_items, products, app_settings, checkpoints, checkpoint_blobs, checkpoint_writes "
                "RESTART IDENTITY CASCADE"
            )
        )
