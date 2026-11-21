import hmac

from fastapi import Header, HTTPException, status

from app.core.config import get_settings


def require_internal_secret(x_internal_secret: str | None = Header(default=None)) -> None:
    expected = get_settings().internal_run_secret
    if not expected:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "INTERNAL_RUN_SECRET is not configured")
    if not x_internal_secret or not hmac.compare_digest(x_internal_secret, expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid internal secret")
