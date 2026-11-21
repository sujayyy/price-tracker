"""Flipkart adapter (HTML). Prefers JSON-LD; class-name fallbacks are best-effort because
Flipkart's CSS class names are generated and change without notice."""

from __future__ import annotations

import json
import re
from urllib.parse import parse_qs, quote_plus, urlsplit

from bs4 import BeautifulSoup

from app.ai.schemas import IntakeCandidate
from app.services.sources import http, images
from app.services.sources.base import FetchResult, ListingRef, UnsupportedURL, clean_text, parse_inr, thumb_url

_HOSTS = {"flipkart.com", "www.flipkart.com", "dl.flipkart.com"}
_ITM_RE = re.compile(r"/p/(itm[0-9a-z]+)", re.I)
_PID_RE = re.compile(r"^[A-Z0-9]{16}$")

_TITLE_SELECTORS = ("h1 span.VU-ZEz", "span.B_NuCI", "h1 span", "h1")
_PRICE_SELECTORS = ("div.Nx9bqj.CxhGGd", "div._30jeq3._16Jk6d", "div.Nx9bqj", "div._30jeq3")
_MRP_SELECTORS = ("div.yRaY8j.A6\\+E6v", "div._3I9_wc._2p6lqe", "div.yRaY8j", "div._3I9_wc")
_SELLER_SELECTORS = ("#sellerName span span", "#sellerName span", "#sellerName")


def _first_text(soup: BeautifulSoup, selectors: tuple[str, ...]) -> str | None:
    for sel in selectors:
        el = soup.select_one(sel)
        if el and el.get_text(strip=True):
            return el.get_text(" ", strip=True)
    return None


class FlipkartSource:
    marketplace = "flipkart"

    def matches(self, url: str) -> bool:
        return (urlsplit(url).hostname or "").lower() in _HOSTS

    def parse_url(self, url: str) -> ListingRef:
        parts = urlsplit(url)
        if (parts.hostname or "").lower() not in _HOSTS:
            raise UnsupportedURL("Not a flipkart.com URL")
        pid = (parse_qs(parts.query).get("pid") or [""])[0].upper()
        itm = _ITM_RE.search(parts.path)
        if not itm and not pid:
            raise UnsupportedURL("Could not find a product id in the Flipkart URL (expected /p/itm…?pid=…)")
        path = parts.path if itm else "/"
        external_id = pid if _PID_RE.match(pid) else itm.group(1).lower()
        canonical = f"https://www.flipkart.com{path}" + (f"?pid={pid}" if pid else "")
        return ListingRef(self.marketplace, external_id, canonical)

    def fetch(self, ref: ListingRef) -> FetchResult:
        try:
            _, html = http.get_html(ref.canonical_url)
        except http.BlockedError as exc:
            return FetchResult(ok=False, error=f"blocked: {exc}")
        except Exception as exc:
            return FetchResult(ok=False, error=f"{type(exc).__name__}: {exc}")
        return parse_product_page(html)

    def search(self, query: str, limit: int = 8) -> list[IntakeCandidate]:
        _, html = http.get_html(f"https://www.flipkart.com/search?q={quote_plus(query)}")
        for pid, url in parse_search_images(html).items():
            images.remember(self.marketplace, pid, url)
        return parse_search_page(html, limit)


def _json_ld_product(soup: BeautifulSoup) -> dict | None:
    for script in soup.select("script[type='application/ld+json']"):
        try:
            data = json.loads(script.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        for node in data if isinstance(data, list) else [data]:
            if isinstance(node, dict) and node.get("@type") == "Product":
                return node
    return None


def parse_product_page(html: str) -> FetchResult:
    soup = BeautifulSoup(html, "lxml")
    title = price = in_stock = seller = image = None

    if (ld := _json_ld_product(soup)) is not None:
        title = clean_text(ld.get("name"))
        pic = ld.get("image")
        image = thumb_url(pic[0] if isinstance(pic, list) and pic else pic if isinstance(pic, str) else None)
        offers = ld.get("offers") or {}
        offers = offers[0] if isinstance(offers, list) and offers else offers
        if isinstance(offers, dict):
            price = parse_inr(str(offers.get("price") or ""))
            avail = str(offers.get("availability") or "")
            if avail:
                in_stock = avail.endswith("InStock")
            s = offers.get("seller")
            seller = clean_text(s.get("name") if isinstance(s, dict) else None, 200)

    title = title or clean_text(_first_text(soup, _TITLE_SELECTORS))
    price = price or parse_inr(_first_text(soup, _PRICE_SELECTORS))
    mrp = parse_inr(_first_text(soup, _MRP_SELECTORS))
    seller = seller or clean_text(_first_text(soup, _SELLER_SELECTORS), 200)
    if image is None and (og := soup.select_one("meta[property='og:image']")) is not None:
        image = thumb_url(og.get("content"))

    if in_stock is None:
        page_text = soup.get_text(" ", strip=True).lower()
        if "sold out" in page_text or "currently unavailable" in page_text:
            in_stock = False
        elif price is not None:
            in_stock = True

    if price is None and in_stock is None and "enable javascript" in soup.get_text(" ", strip=True).lower():
        # Flipkart intermittently serves a JS-challenge shell with no product data. Report it;
        # never try to get around it. The gate escalates only if failures persist.
        return FetchResult(ok=False, error="blocked: Flipkart served a JavaScript challenge page")
    if title is None and price is None:
        return FetchResult(ok=False, error="parse: no title or price found (layout changed?)")
    if price is None and in_stock is not False:
        return FetchResult(ok=False, title=title, error="parse: price not found")
    if mrp is not None and price is not None and mrp < price:
        mrp = None
    return FetchResult(
        ok=True, price_inr=price, mrp_inr=mrp, in_stock=in_stock, seller=seller, title=title, image_url=image
    )


def parse_search_images(html: str) -> dict[str, str]:
    """Product id → thumbnail URL for each search result that shows a product photo."""
    soup = BeautifulSoup(html, "lxml")
    out: dict[str, str] = {}
    for card in soup.select("div[data-id]"):
        pid = (card.get("data-id") or "").strip().upper()
        img = card.select_one("img[src*='flixcart.com/image/']")
        if _PID_RE.match(pid) and pid not in out and img is not None and (url := thumb_url(img.get("src"))):
            out[pid] = url
    return out


def parse_search_page(html: str, limit: int = 8) -> list[IntakeCandidate]:
    soup = BeautifulSoup(html, "lxml")
    out: list[IntakeCandidate] = []
    seen: set[str] = set()
    for card in soup.select("div[data-id]"):
        pid = (card.get("data-id") or "").strip().upper()
        link = card.select_one("a[href*='/p/itm']")
        if not _PID_RE.match(pid) or pid in seen or link is None:
            continue
        href = link.get("href", "")
        itm = _ITM_RE.search(href)
        if not itm:
            continue
        title_el = card.select_one("a[title]")
        img = card.select_one("img[alt]")
        title = (
            (title_el.get("title") if title_el else None)
            or (img.get("alt") if img else None)
            or link.get_text(" ", strip=True)
        )
        price_match = re.search(r"₹\s?[\d,]+", card.get_text(" ", strip=True))
        price = parse_inr(price_match.group(0)) if price_match else None
        seen.add(pid)
        out.append(
            IntakeCandidate(
                marketplace="flipkart",
                external_id=pid,
                title=clean_text(title, 300) or pid,
                price_inr=float(price) if price else None,
                url=f"https://www.flipkart.com{urlsplit(href).path}?pid={pid}",
                match_score=0,
            )
        )
        if len(out) >= limit:
            break
    return out
