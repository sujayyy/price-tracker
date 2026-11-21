"""The `PriceSource` interface every marketplace adapter implements.

Swapping HTML scraping for an official affiliate API later means writing a new class with
the same four methods; neither the runner nor the agent changes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Protocol

from app.ai.schemas import IntakeCandidate


class UnsupportedURL(ValueError):
    pass


@dataclass(frozen=True)
class ListingRef:
    marketplace: str
    external_id: str
    canonical_url: str


@dataclass
class FetchResult:
    ok: bool
    price_inr: Decimal | None = None
    mrp_inr: Decimal | None = None
    in_stock: bool | None = None
    seller: str | None = None
    title: str | None = None
    image_url: str | None = None  # the product photo, at thumbnail size (display only)
    error: str | None = None
    source: str = "html"  # 'html' | 'affiliate_api' | 'third_party_api'


class PriceSource(Protocol):
    marketplace: str

    def matches(self, url: str) -> bool: ...

    def parse_url(self, url: str) -> ListingRef:
        """Raise UnsupportedURL if the URL is not a product page of this marketplace."""
        ...

    def fetch(self, ref: ListingRef) -> FetchResult:
        """Fetch one listing. Never raises for network/parse problems: returns ok=False."""
        ...

    def search(self, query: str, limit: int = 8) -> list[IntakeCandidate]: ...


_PRICE_RE = re.compile(r"[\d,]+(?:\.\d{1,2})?")


def parse_inr(text: str | None) -> Decimal | None:
    """'₹1,23,999.00' → Decimal('123999.00'). Returns None when no number is present."""
    if not text:
        return None
    m = _PRICE_RE.search(text.replace("₹", " ").replace("Rs.", " "))
    if not m:
        return None
    try:
        value = Decimal(m.group(0).replace(",", ""))
    except InvalidOperation:
        return None
    return value if value > 0 else None


_AMAZON_SIZE_RE = re.compile(r"\._[A-Z0-9_,]+_\.(jpe?g|png|webp)$", re.I)
_FLIPKART_SIZE_RE = re.compile(r"/image/\d+/\d+/")


def thumb_url(url: str | None, px: int = 400) -> str | None:
    """A marketplace product image at thumbnail size. Both CDNs size images from the URL itself
    (Amazon: `._SL400_.jpg`, Flipkart: `/image/400/400/`). Anything that isn't an https image
    (lazy-load placeholders, data: URIs) is dropped."""
    if not url:
        return None
    url = url.strip()
    if url.startswith("//"):
        url = f"https:{url}"
    if not url.startswith("https://") or len(url) > 1000:
        return None
    if "media-amazon.com/images/I/" in url:
        return _AMAZON_SIZE_RE.sub(lambda m: f"._SL{px}_.{m.group(1)}", url)
    if "flixcart.com/image/" in url:
        return _FLIPKART_SIZE_RE.sub(f"/image/{px}/{px}/", url, count=1)
    return url


def clean_text(text: str | None, limit: int = 500) -> str | None:
    if text is None:
        return None
    text = " ".join(text.split())
    return text[:limit] or None
