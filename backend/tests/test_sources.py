from decimal import Decimal
from pathlib import Path

import pytest

from app.services.notifier.email import format_inr
from app.services.sources import UnsupportedURL, amazon_in, flipkart, source_for_url
from app.services.sources.base import parse_inr, thumb_url

FIX = Path(__file__).parent / "fixtures"


def read(name: str) -> str:
    return (FIX / name).read_text()


def test_parse_inr():
    assert parse_inr("₹1,23,999.00") == Decimal("123999.00")
    assert parse_inr("Rs. 499") == Decimal("499")
    assert parse_inr("") is None and parse_inr("free") is None


def test_format_inr_indian_grouping():
    assert format_inr(123999) == "₹1,23,999"
    assert format_inr(999.5) == "₹999.50"
    assert format_inr(None) == "—"


@pytest.mark.parametrize(
    "url, marketplace, ext",
    [
        ("https://www.amazon.in/Example-Phone/dp/B0EXAMPLE1/ref=sr_1_1?keywords=x", "amazon_in", "B0EXAMPLE1"),
        ("https://amazon.in/gp/product/B0EXAMPLE1", "amazon_in", "B0EXAMPLE1"),
        (
            "https://www.flipkart.com/example-phone/p/itmabc123def456?pid=MOBEXAMPLE000001&lid=x",
            "flipkart",
            "MOBEXAMPLE000001",
        ),
        ("https://www.flipkart.com/example-phone/p/itmabc123def456", "flipkart", "itmabc123def456"),
    ],
)
def test_url_parsing(url, marketplace, ext):
    ref = source_for_url(url).parse_url(url)
    assert (ref.marketplace, ref.external_id) == (marketplace, ext)


def test_unsupported_urls():
    with pytest.raises(UnsupportedURL):
        source_for_url("https://www.example.com/dp/B0EXAMPLE1")
    with pytest.raises(UnsupportedURL):
        source_for_url("https://www.amazon.in/s?k=phone").parse_url("https://www.amazon.in/s?k=phone")


def test_amazon_product():
    r = amazon_in.parse_product_page(read("amazon_product.html"))
    assert r.ok and r.price_inr == Decimal("17999.00") and r.mrp_inr == Decimal("24999.00")
    assert r.in_stock is True and r.seller == "Example Retail Pvt Ltd"
    assert r.title.startswith("Example Phone 5G")
    # The landing image, re-sized through the CDN URL for thumbnails.
    assert r.image_url == "https://m.media-amazon.com/images/I/41Example._SL400_.jpg"


def test_amazon_unavailable_is_ok_and_out_of_stock():
    r = amazon_in.parse_product_page(read("amazon_unavailable.html"))
    assert r.ok and r.in_stock is False and r.price_inr is None


def test_amazon_garbage_is_not_ok():
    r = amazon_in.parse_product_page("<html><body>Something else</body></html>")
    assert not r.ok and "parse" in r.error


def test_amazon_search():
    results = amazon_in.parse_search_page(read("amazon_search.html"))
    assert [c.external_id for c in results] == ["B0EXAMPLE1", "B0EXAMPLE2"]
    assert results[0].price_inr == 17999 and str(results[0].url) == "https://www.amazon.in/dp/B0EXAMPLE1"
    assert results[0].title == "Example Phone 5G (Midnight Black, 128GB)"
    assert results[1].title == "Example Phone 5G (Ocean Blue, 256GB)"


def test_flipkart_product_prefers_json_ld():
    r = flipkart.parse_product_page(read("flipkart_product.html"))
    assert r.ok and r.price_inr == Decimal("17499") and r.mrp_inr == Decimal("24999")
    assert r.in_stock is True and r.seller == "RetailNet"
    assert r.image_url == "https://rukminim2.flixcart.com/image/400/400/xif0q/mobile/a/b/c/-original-example.jpeg?q=70"


def test_flipkart_search():
    results = flipkart.parse_search_page(read("flipkart_search.html"))
    assert [c.external_id for c in results] == ["MOBEXAMPLE000001", "MOBEXAMPLE000002"]
    assert results[1].title == "Example Phone 5G (Ocean Blue, 256 GB)" and results[1].price_inr == 20499
    # The candidate URL round-trips through the URL parser to the same external id.
    ref = flipkart.FlipkartSource().parse_url(str(results[0].url))
    assert ref.external_id == "MOBEXAMPLE000001"


def test_search_pages_expose_product_photos():
    assert amazon_in.parse_search_images(read("amazon_search.html")) == {
        "B0EXAMPLE1": "https://m.media-amazon.com/images/I/71Example._SL400_.jpg"
    }
    # A placeholder src (not a flixcart CDN image) is skipped rather than guessed.
    assert flipkart.parse_search_images(read("flipkart_search.html")) == {
        "MOBEXAMPLE000002": "https://rukminim2.flixcart.com/image/400/400/xif0q/mobile/x/y/z/-original-blue.jpeg?q=70"
    }


@pytest.mark.parametrize(
    "raw, expected",
    [
        (None, None),
        ("data:image/gif;base64,R0lGOD", None),
        ("http://example.com/a.jpg", None),
        ("//m.media-amazon.com/images/I/1.jpg", "https://m.media-amazon.com/images/I/1.jpg"),
        ("https://m.media-amazon.com/images/I/61X._SL1500_.jpg", "https://m.media-amazon.com/images/I/61X._SL400_.jpg"),
    ],
)
def test_thumb_url(raw, expected):
    assert thumb_url(raw) == expected


def test_flipkart_js_challenge_is_reported_as_blocked():
    r = flipkart.parse_product_page(read("flipkart_js_challenge.html"))
    assert not r.ok and r.error.startswith("blocked:")


def test_amazon_short_link_follows_get_redirect(monkeypatch):
    """Regression: amzn.in answers HEAD with 404 and only redirects on GET."""
    import httpx

    from app.services.sources import http

    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.host))
        if request.method == "HEAD":
            return httpx.Response(404)
        return httpx.Response(301, headers={"location": "https://www.amazon.in/dp/B01L8ZNWN2?ref=share"})

    monkeypatch.setattr(http, "_client", httpx.Client(transport=httpx.MockTransport(handler)))
    ref = amazon_in.AmazonInSource().parse_url("https://amzn.in/d/02T4M3vP")
    assert ref.external_id == "B01L8ZNWN2" and ref.canonical_url == "https://www.amazon.in/dp/B01L8ZNWN2"
    assert seen == [("GET", "amzn.in")]  # the product page itself is not downloaded
