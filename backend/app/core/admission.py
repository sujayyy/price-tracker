"""Admission control: a bound on how many /api requests run at once.

Endpoints are sync, so each request hops between the event loop and the shared worker-thread pool
(40 threads): once to run the endpoint and once more to validate its response. Its database session
holds a pooled connection (15 at most) across those hops. Under a burst, all 40 threads can end up
blocked waiting for a connection while the 15 connections belong to requests waiting for a thread
to finish on; nothing moves until the pool's 30 s timeout fails requests. The stress test hit
exactly that (perf/REPORT.md).

Letting at most `limit` requests in at a time keeps both pools from running dry: the rest wait
here, on the event loop, without holding a thread or a connection, and get a quick 503 with
Retry-After if they wait longer than `max_wait_s`.
"""

from __future__ import annotations

import anyio
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send


class AdmissionLimit:
    def __init__(self, app: ASGIApp, *, limit: int, max_wait_s: float, prefix: str = "/api/"):
        self.app = app
        self.limit = limit
        self.max_wait_s = max_wait_s
        self.prefix = prefix
        self._slots: anyio.Semaphore | None = None  # created on first use, inside the event loop

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope["path"].startswith(self.prefix):
            await self.app(scope, receive, send)
            return
        if self._slots is None:
            self._slots = anyio.Semaphore(self.limit)
        admitted = False
        with anyio.move_on_after(self.max_wait_s):
            await self._slots.acquire()
            admitted = True
        if not admitted:
            busy = JSONResponse({"detail": "Server busy, retry shortly"}, status_code=503, headers={"Retry-After": "1"})
            await busy(scope, receive, send)
            return
        try:
            await self.app(scope, receive, send)
        finally:
            self._slots.release()
