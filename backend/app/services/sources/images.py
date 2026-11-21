"""Product images seen in marketplace search results, kept briefly for the search API.

Search candidates pass through the intake agent, whose schema deliberately carries no image
(the model never needs to see or echo image URLs). Each source's `search()` records the images
here, and the API re-attaches them to the candidates it returns. Process-local and bounded.
"""

from __future__ import annotations

from collections import OrderedDict
from threading import Lock

_MAX = 2000
_seen: OrderedDict[tuple[str, str], str] = OrderedDict()
_lock = Lock()


def remember(marketplace: str, external_id: str, url: str | None) -> None:
    if not url:
        return
    with _lock:
        _seen[(marketplace, external_id)] = url
        _seen.move_to_end((marketplace, external_id))
        while len(_seen) > _MAX:
            _seen.popitem(last=False)


def lookup(marketplace: str, external_id: str) -> str | None:
    with _lock:
        return _seen.get((marketplace, external_id))
