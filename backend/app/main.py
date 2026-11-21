# Create the FastAPI application, configure it, connect the API routes,
# handle startup/shutdown, and expose a health endpoint.


from contextlib import asynccontextmanager
from datetime import UTC, datetime

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import history, internal, monitoring, products, proposals, settings
from app.core.admission import AdmissionLimit
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db import repo
from app.db.base import SessionLocal
from app.services import ai_bridge

configure_logging()
log = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        ai_bridge.setup_checkpointer()  # idempotent: creates LangGraph's checkpoint tables
    except Exception as exc:
        log.warning("checkpointer_setup_failed", error=str(exc))
    yield
    ai_bridge.shutdown()


app = FastAPI(title="AI Price Tracker · Ops", version="0.1.0", lifespan=lifespan)
# Added first so it sits inside CORS: a 503 from it still carries the CORS headers the dashboard needs.
app.add_middleware(
    AdmissionLimit,
    limit=get_settings().api_max_concurrency,
    max_wait_s=get_settings().api_queue_timeout_seconds,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    # X-Internal-Secret lets the dashboard's demo panel call /internal/demo/*; the secret is still required.
    allow_headers=["Content-Type", "X-Internal-Secret"],
)
app.include_router(products.router)
app.include_router(history.router)
app.include_router(history.activity_router)
app.include_router(proposals.router)
app.include_router(settings.router)
app.include_router(monitoring.router)
app.include_router(internal.router)


@app.get("/health", tags=["meta"])
def health():
    settings = get_settings()
    out = {"status": "ok", "demo_endpoints": settings.demo_endpoints_enabled}
    try:  # AI budget, so the dashboard can say why a change got no AI recommendation
        now = datetime.now(UTC)
        with SessionLocal() as s:
            used = repo.agent_invocations_since(s, now.replace(hour=0, minute=0, second=0, microsecond=0))
        out["ai"] = {"runs_today": used, "daily_limit": settings.max_agent_invocations_per_day}
    except Exception as exc:  # health must answer even if the database is down
        log.warning("health_ai_budget_failed", error=str(exc))
    return out
