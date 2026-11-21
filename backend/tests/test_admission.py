"""Admission control: at most `limit` /api requests run at once; the rest wait, or get a fast 503."""

import time

import anyio
import httpx
import pytest
from fastapi import FastAPI

from app.core.admission import AdmissionLimit


def make_app(limit: int, max_wait_s: float, work_s: float):
    app = FastAPI()
    running = {"now": 0, "peak": 0}

    @app.get("/api/slow")
    async def slow():
        running["now"] += 1
        running["peak"] = max(running["peak"], running["now"])
        await anyio.sleep(work_s)
        running["now"] -= 1
        return {"ok": True}

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    app.add_middleware(AdmissionLimit, limit=limit, max_wait_s=max_wait_s)
    return app, running


async def burst(app, n: int, path: str = "/api/slow") -> list[httpx.Response]:
    results: list[httpx.Response] = []
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:

        async def one():
            results.append(await c.get(path))

        async with anyio.create_task_group() as tg:
            for _ in range(n):
                tg.start_soon(one)
    return results


@pytest.mark.anyio
async def test_requests_beyond_the_limit_queue_instead_of_running():
    app, running = make_app(limit=2, max_wait_s=5, work_s=0.1)
    t = time.perf_counter()
    results = await burst(app, 6)
    assert [r.status_code for r in results] == [200] * 6
    assert running["peak"] == 2  # never more than the limit in flight
    assert time.perf_counter() - t >= 0.3  # 6 requests, 2 at a time, 0.1 s each


@pytest.mark.anyio
async def test_a_request_that_waits_too_long_gets_503_with_retry_after():
    app, _ = make_app(limit=1, max_wait_s=0.05, work_s=0.3)
    results = await burst(app, 3)
    codes = sorted(r.status_code for r in results)
    assert codes == [200, 503, 503]
    busy = next(r for r in results if r.status_code == 503)
    assert busy.headers["retry-after"] == "1"


@pytest.mark.anyio
async def test_paths_outside_the_api_are_not_limited():
    app, _ = make_app(limit=1, max_wait_s=0.01, work_s=0.3)
    results = await burst(app, 5, "/health")
    assert [r.status_code for r in results] == [200] * 5


@pytest.fixture
def anyio_backend():
    return "asyncio"
