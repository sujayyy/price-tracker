"""Amazon.in adapter (HTML). Selectors are best-effort; Amazon changes markup often."""

from __future__ import annotations

import re
from urllib.parse import quote_plus, urlsplit

from bs4 import BeautifulSoup

from app.ai.schemas import IntakeCandidate
from app.services.sources import http, images
from app.services.sources.base import FetchResult, ListingRef, UnsupportedURL, clean_text, parse_inr, thumb_url

_HOSTS = {"amazon.in", "www.amazon.in", "m.amazon.in"}
_SHORT_HOSTS = {"amzn.in", "amzn.to", "a.co"}
_ASIN_RE = re.compile(r"/(?:dp|gp/product|gp/aw/d|exec/obidos/asin|o/ASIN)/([A-Z0-9]{10})(?:[/?]|$)")

_PRICE_SELECTORS = (
    "#corePriceDisplay_desktop_feature_div .priceToPay .a-offscreen",
    "#corePriceDisplay_desktop_feature_div .a-price .a-offscreen",
    "#corePrice_feature_div .a-price .a-offscreen",
    "#corePrice_desktop .a-price .a-offscreen",
    "#apex_desktop .a-price .a-offscreen",
    "#priceblock_dealprice",
    "#priceblock_ourprice",
    "#tp_price_block_total_price_ww .a-offscreen",
)
_MRP_SELECTORS = (
    "#corePriceDisplay_desktop_feature_div .basisPrice .a-offscreen",
    ".basisPrice .a-offscreen",
    "#corePrice_desktop .a-text-price .a-offscreen",
    "span.a-price.a-text-price[data-a-strike='true'] .a-offscreen",
)
_SELLER_SELECTORS = (
    "#sellerProfileTriggerId",
    "#merchantInfoFeature_feature_div .offer-display-feature-text-message",
    "#merchant-info a",
)


def _first_text(soup: BeautifulSoup, selectors: tuple[str, ...]) -> str | None:
    for sel in selectors:
        el = soup.select_one(sel)
        if el and el.get_text(strip=True):
            return el.get_text(" ", strip=True)
    return None


class AmazonInSource:
    marketplace = "amazon_in"

    def matches(self, url: str) -> bool:
        host = (urlsplit(url).hostname or "").lower()
        return host in _HOSTS or host in _SHORT_HOSTS

    def parse_url(self, url: str) -> ListingRef:
        host = (urlsplit(url).hostname or "").lower()
        short_link = host in _SHORT_HOSTS
        if short_link:
            url = http.resolve_redirect(url, _SHORT_HOSTS)
            host = (urlsplit(url).hostname or "").lower()
        if host not in _HOSTS:
            if short_link:
                raise UnsupportedURL("The short link did not lead to an amazon.in product page")
            raise UnsupportedURL("Not an amazon.in URL")
        m = _ASIN_RE.search(urlsplit(url).path + "/")
        if not m:
            raise UnsupportedURL("Could not find an ASIN in the Amazon URL (expected /dp/<ASIN>)")
        asin = m.group(1)
        return ListingRef(self.marketplace, asin, f"https://www.amazon.in/dp/{asin}")

    def fetch(self, ref: ListingRef) -> FetchResult:
        try:
            _, html = http.get_html(ref.canonical_url)
        except http.BlockedError as exc:
            return FetchResult(ok=False, error=f"blocked: {exc}")
        except Exception as exc:
            return FetchResult(ok=False, error=f"{type(exc).__name__}: {exc}")
        return parse_product_page(html)

    def search(self, query: str, limit: int = 8) -> list[IntakeCandidate]:
        _, html = http.get_html(f"https://www.amazon.in/s?k={quote_plus(query)}")
        for asin, url in parse_search_images(html).items():
            images.remember(self.marketplace, asin, url)
        return parse_search_page(html, limit)


def _product_image(soup: BeautifulSoup) -> str | None:
    img = soup.select_one("#landingImage, #imgBlkFront, #main-image-container img")
    for attr in ("src", "data-old-hires"):
        if img is not None and (url := thumb_url(img.get(attr))):
            return url
    og = soup.select_one("meta[property='og:image']")
    return thumb_url(og.get("content")) if og else None


def parse_product_page(html: str) -> FetchResult:
    soup = BeautifulSoup(html, "lxml")
    title = clean_text(_first_text(soup, ("#productTitle", "#title")))
    price = parse_inr(_first_text(soup, _PRICE_SELECTORS))
    mrp = parse_inr(_first_text(soup, _MRP_SELECTORS))
    seller = clean_text(_first_text(soup, _SELLER_SELECTORS), 200)

    availability = (_first_text(soup, ("#availability",)) or "").lower()
    has_cart = soup.select_one("#add-to-cart-button, #buy-now-button") is not None
    if any(s in availability for s in ("currently unavailable", "out of stock", "unavailable")):
        in_stock = False
    elif has_cart or "in stock" in availability or price is not None:
        in_stock = True
    else:
        in_stock = None

    if title is None and price is None:
        return FetchResult(ok=False, error="parse: no title or price found (layout changed?)")
    if price is None and in_stock is not False:
        return FetchResult(ok=False, title=title, error="parse: price not found")
    return FetchResult(
        ok=True,
        price_inr=price,
        mrp_inr=mrp,
        in_stock=in_stock,
        seller=seller,
        title=title,
        image_url=_product_image(soup),
    )


def _search_title(card) -> str | None:
    """Current layout: a brand-only <h2> followed by an <h2 aria-label="full title">."""
    headings = card.select("h2")
    full = next((h.get("aria-label") for h in headings if h.get("aria-label")), None)
    texts = [h.get_text(" ", strip=True) for h in headings if h.get_text(strip=True)]
    if full is None:
        return " ".join(texts) or None
    brand = texts[0] if texts and len(headings) > 1 and not headings[0].get("aria-label") else ""
    return f"{brand} {full}" if brand and not full.lower().startswith(brand.lower()) else full


def parse_search_images(html: str) -> dict[str, str]:
    """ASIN → thumbnail URL for each search result that shows a product photo."""
    soup = BeautifulSoup(html, "lxml")
    out: dict[str, str] = {}
    for card in soup.select("div[data-component-type='s-search-result'][data-asin]"):
        asin = (card.get("data-asin") or "").strip()
        img = card.select_one("img.s-image")
        if asin and img is not None and (url := thumb_url(img.get("src"))):
            out[asin] = url
    return out


def parse_search_page(html: str, limit: int = 8) -> list[IntakeCandidate]:
    soup = BeautifulSoup(html, "lxml")
    out: list[IntakeCandidate] = []
    for card in soup.select("div[data-component-type='s-search-result'][data-asin]"):
        asin = (card.get("data-asin") or "").strip()
        title = _search_title(card)
        if not re.fullmatch(r"[A-Z0-9]{10}", asin) or not title:
            continue
        price_el = card.select_one(".a-price .a-offscreen")
        out.append(
            IntakeCandidate(
                marketplace="amazon_in",
                external_id=asin,
                title=clean_text(title, 300) or asin,
                price_inr=float(p) if (p := parse_inr(price_el.get_text() if price_el else None)) else None,
                url=f"https://www.amazon.in/dp/{asin}",
                match_score=0,
            )
        )
        if len(out) >= limit:
            break
    return out
