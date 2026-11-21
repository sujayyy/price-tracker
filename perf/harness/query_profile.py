"""Per-endpoint evidence: SQL statements, time inside the database, and total time, per request.

    .venv/bin/python perf/harness/query_profile.py [--repeat 5] [--profile /api/products]

Runs the real FastAPI app in-process (TestClient) against the seeded perf database and hooks
SQLAlchemy's engine events to count every statement and time how long each spent in Postgres.
`--profile PATH` also runs cProfile on that endpoint and prints where the Python time goes.
"""

from __future__ import annotations

import argparse
import cProfile
import io
import json
import pstats
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from perf.harness import env

ENDPOINTS = [
    "/api/products",
    "/api/proposals?status=pending",
    "/api/monitoring",
    "/api/activity?days=14",
    "/api/products/{id}",
    "/api/products/{id}/history?days=7",
    "/api/products/{id}/decisions",
    "/health",
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="tracker_perf")
    ap.add_argument("--repeat", type=int, default=5)
    ap.add_argument("--profile", help="endpoint to profile with cProfile, e.g. /api/products")
    ap.add_argument("--label", default="")
    args = ap.parse_args()
    env.apply(args.db)

    from fastapi.testclient import TestClient
    from sqlalchemy import event

    from app.db.base import engine
    from app.main import app

    stats = {"n": 0, "db_s": 0.0}

    @event.listens_for(engine, "before_cursor_execute")
    def _before(conn, cursor, statement, parameters, context, executemany):
        conn.info["t0"] = time.perf_counter()

    @event.listens_for(engine, "after_cursor_execute")
    def _after(conn, cursor, statement, parameters, context, executemany):
        stats["n"] += 1
        stats["db_s"] += time.perf_counter() - conn.info.pop("t0")

    client = TestClient(app)
    pid = client.get("/api/products").json()[0]["id"]
    client.get("/health")  # warm-up
    rows = []
    for ep in ENDPOINTS:
        path = ep.format(id=pid)
        walls, dbs, counts = [], [], []
        for _ in range(args.repeat):
            stats.update(n=0, db_s=0.0)
            t0 = time.perf_counter()
            r = client.get(path)
            walls.append((time.perf_counter() - t0) * 1000)
            assert r.status_code == 200, (path, r.status_code)
            dbs.append(stats["db_s"] * 1000)
            counts.append(stats["n"])
        wall, db = statistics.median(walls), statistics.median(dbs)
        rows.append(
            {
                "endpoint": ep,
                "statements": counts[-1],
                "wall_ms": round(wall, 1),
                "db_ms": round(db, 1),
                "db_share": round(db / wall, 2) if wall else 0,
                "response_kb": round(len(r.content) / 1024, 1),
            }
        )
    print("| endpoint | SQL statements | median ms | in Postgres ms | DB share | response KB |")
    print("|---|---:|---:|---:|---:|---:|")
    for r in rows:
        print(
            f"| {r['endpoint']} | {r['statements']} | {r['wall_ms']} | {r['db_ms']} | {int(100 * r['db_share'])}% "
            f"| {r['response_kb']} |"
        )
    out = env.RESULTS / f"queries{('-' + args.label) if args.label else ''}.json"
    out.write_text(json.dumps(rows, indent=2))

    if args.profile:
        prof = cProfile.Profile()
        prof.enable()
        for _ in range(3):
            client.get(args.profile)
        prof.disable()
        buf = io.StringIO()
        pstats.Stats(prof, stream=buf).sort_stats("cumulative").print_stats(28)
        text = buf.getvalue()
        (env.RESULTS / f"profile{('-' + args.label) if args.label else ''}.txt").write_text(text)
        print("\n".join(line for line in text.splitlines() if line.strip())[:6000])


if __name__ == "__main__":
    main()
