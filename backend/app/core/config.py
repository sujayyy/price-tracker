from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated

from dotenv import load_dotenv
from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]
ENV_FILE = REPO_ROOT / "infra" / ".env"

# Export infra/.env into the process environment too: LangSmith and the model provider SDKs
# (GOOGLE_API_KEY etc.) read their settings from os.environ, not from this Settings object.
load_dotenv(ENV_FILE, override=False)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(ENV_FILE, ".env"), extra="ignore")

    database_url: str = "postgresql+psycopg://tracker:tracker@localhost:5432/tracker"

    agent_model: str = "google_genai:gemini-3.6-flash"
    max_agent_invocations_per_day: int = 20
    # Proposals below this confidence are flagged "review carefully"; auto-apply needs the second.
    alert_min_confidence: float = 0.7
    auto_apply_min_confidence: float = 0.85

    # Every competitor alert goes to the operations team (comma-separated), plus an item's notify_email.
    ops_alert_emails: Annotated[list[str], NoDecode] = []
    # Used for the "Review in dashboard" link in alert emails.
    dashboard_url: str = "http://localhost:5173"

    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587  # 587 = STARTTLS, 465 = implicit TLS
    smtp_user: str = ""
    smtp_app_password: str = ""

    internal_run_secret: str = ""
    # POST/DELETE /internal/demo/price: simulate a marketplace price for demos and tests.
    demo_endpoints_enabled: bool = False
    source_min_interval_seconds: float = 5.0
    # Admission control for /api (app/core/admission.py): at most this many requests run at once, so
    # the 40 worker threads and the 15 pooled DB connections can't deadlock under a burst. The rest
    # wait up to api_queue_timeout_seconds, then get 503 + Retry-After.
    api_max_concurrency: int = 10
    api_queue_timeout_seconds: float = 10.0
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:5173"]

    @field_validator("cors_origins", "ops_alert_emails", mode="before")
    @classmethod
    def _split_csv(cls, v):
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()
