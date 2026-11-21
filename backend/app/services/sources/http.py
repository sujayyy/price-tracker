"""Shared HTTP client with per-domain rate limiting and block detection.

Rate limiting is per marketplace domain, not per item, so tracking many items on one site
does not multiply the request rate. Blocked/CAPTCHA pages are reported, never bypassed.
"""

from __future__ import annotations

import threading
import time
from urllib.parse import urlsplit

import httpx

from app.core.config import get_settings

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-IN,en;q=0.9",
}

_BLOCK_MARKERS = (
    "enter the characters you see below",
    "/errors/validatecaptcha",
    "api-services-support@amazon.com",
    "are you a human",
    "captcha",
)


class BlockedError(RuntimeError):
    pass


class DomainRateLimiter:
    def __init__(self, min_interval_seconds: float):
        self.min_interval = min_interval_seconds
        self._last: dict[str, float] = {}
        self._lock = threading.Lock()

    def wait(self, domain: str) -> None:
        with self._lock:
            now = time.monotonic()
            ready_at = self._last.get(domain, 0.0) + self.min_interval
            delay = max(0.0, ready_at - now)
            self._last[domain] = now + delay
        if delay:
            time.sleep(delay)


_limiter = DomainRateLimiter(get_settings().source_min_interval_seconds)
_client = httpx.Client(headers=_HEADERS, follow_redirects=True, timeout=20.0)


def _registrable_domain(url: str) -> str:
    host = urlsplit(url).hostname or ""
    return ".".join(host.split(".")[-2:])


def get_html(url: str) -> tuple[str, str]:
    """Return (final_url, html). Raises BlockedError or httpx.HTTPError."""
    _limiter.wait(_registrable_domain(url))
    resp = _client.get(url)
    if resp.status_code in (429, 503):
        raise BlockedError(f"HTTP {resp.status_code} (rate-limited or blocked)")
    resp.raise_for_status()
    html = resp.text
    head = html[:20000].lower()
    if any(marker in head for marker in _BLOCK_MARKERS) and "producttitle" not in head:
        raise BlockedError("Blocked page / CAPTCHA served")
    return str(resp.url), html


def resolve_redirect(url: str, short_hosts: set[str], max_hops: int = 5) -> str:
    """Follow a short link (e.g. amzn.in/d/…) to the URL it points at.

    Uses GET without auto-following and reads only the Location header while the URL is still on
    a short-link host: amzn.in answers HEAD with 404, and following all the way would download
    the product page.
    """
    for _ in range(max_hops):
        if (urlsplit(url).hostname or "").lower() not in short_hosts:
            break
        _limiter.wait(_registrable_domain(url))
        resp = _client.get(url, follow_redirects=False)
        location = resp.headers.get("location")
        if not resp.is_redirect or not location:
            break
        url = str(resp.url.join(location))
    return url
