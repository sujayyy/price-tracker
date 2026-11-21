from app.services.sources.amazon_in import AmazonInSource
from app.services.sources.base import FetchResult, ListingRef, PriceSource, UnsupportedURL
from app.services.sources.flipkart import FlipkartSource

SOURCES: dict[str, PriceSource] = {
    "amazon_in": AmazonInSource(),
    "flipkart": FlipkartSource(),
}


def source_for_marketplace(marketplace: str) -> PriceSource:
    return SOURCES[marketplace]


def source_for_url(url: str) -> PriceSource:
    for source in SOURCES.values():
        if source.matches(url):
            return source
    raise UnsupportedURL("Only amazon.in and flipkart.com product URLs are supported")


__all__ = [
    "SOURCES",
    "FetchResult",
    "ListingRef",
    "PriceSource",
    "UnsupportedURL",
    "source_for_marketplace",
    "source_for_url",
]
