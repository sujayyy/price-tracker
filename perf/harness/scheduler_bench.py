"""How long one scheduler cycle takes as the catalogue grows, with every outside call faked.

    .venv/bin/python perf/harness/scheduler_bench.py                    # sizes 10 50 100 250 500
    .venv/bin/python perf/harness/scheduler_bench.py --sizes 100 --model-latency 1.5

For each size, in a fresh process and a freshly reset `tracker_perf_sched` database: seed N
products (2 listings each, 60 readings per listing), make ~20% of products' competitors drop 8%,
then run the real `run_once` (due-listing query, observation writes, the gate, the real LangGraph
workflow with Postgres checkpoints, proposal rows) with:
- a fake fetch (no Amazon/Flipkart traffic, so the per-domain politeness delay is not exercised),
- the deterministic OptionPickingModel (no Claude call; `--model-latency` adds a fixed delay per
  model call to see how provider latency adds up in a sequential cycle),
- a no-op mailer.

Measured: cycle wall time, listings/s, SQL statements and time inside Postgres (SQLAlchemy events),
time spent in the workflow, peak RSS of the process. The scraping time a real cycle adds is NOT
measured here (see REPORT.md for the calculated bound).
"""

from __future__ import annotations

import argparse
import json
import resource
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from perf.harness import env

DB = "tracker_perf_sched"


def one(n: int, model_latency: float, drop_share: float) -> dict:
    url = env.apply(DB)
    env.ensure_database(DB)
    env.reset_database()

    import random

    from sqlalchemy import event

    from app import ai
    from app.db import repo
    from app.db.base import SessionLocal, engine
    from app.services.runner import run_once
    from perf.harness.seed import build_workflow, drop_fetcher, make_dataset

    with SessionLocal() as s:
        ids = make_dataset(s, n, history=60)
        dropped = set(random.Random(11).sample(ids, max(1, int(n * drop_share))))
        fetch = drop_fetcher(s, dropped, 0.08)
        t = time.perf_counter()
        due = len(repo.due_listings(s))
        due_query_ms = (time.perf_counter() - t) * 1000
    wf = build_workflow(url, model_latency)

    sql = {"n": 0, "s": 0.0}

    @event.listens_for(engine, "before_cursor_execute")
    def _before(conn, cursor, statement, parameters, context, executemany):
        conn.info["t0"] = time.perf_counter()

    @event.listens_for(engine, "after_cursor_execute")
    def _after(conn, cursor, statement, parameters, context, executemany):
        sql["n"] += 1
        sql["s"] += time.perf_counter() - conn.info.pop("t0")

    workflow = {"n": 0, "s": 0.0, "max": 0.0}

    def repricer(pid, trig, summ, tag):
        t = time.perf_counter()
        try:
            return ai.start_repricing(wf, pid, trig, summ, run_tag=tag)
        finally:
            d = time.perf_counter() - t
            workflow["n"] += 1
            workflow["s"] += d
            workflow["max"] = max(workflow["max"], d)

    mails = []
    t0 = time.perf_counter()
    summary = run_once(fetch=fetch, repricer=repricer, mailer=lambda *a: mails.append(a[1]))
    wall = time.perf_counter() - t0
    # SQL issued inside the workflow (its data provider) is counted in both columns; the check
    # phase is the cycle minus the workflow.
    rss_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024 * 1024 if sys.platform == "darwin" else 1024)
    return {
        "products": n,
        "listings_due": due,
        "listings_checked": summary.items_checked,
        "errors": summary.errors,
        "triggers": len(summary.triggers),
        "workflow_runs": workflow["n"],
        "emails": len(mails),
        "cycle_s": round(wall, 2),
        "listings_per_s": round(summary.items_checked / wall, 1),
        "check_phase_s": round(wall - workflow["s"], 2),
        "workflow_total_s": round(workflow["s"], 2),
        "workflow_avg_ms": round(1000 * workflow["s"] / workflow["n"], 1) if workflow["n"] else None,
        "workflow_max_ms": round(1000 * workflow["max"], 1),
        "sql_statements": sql["n"],
        "sql_per_listing": round(sql["n"] / max(summary.items_checked, 1), 1),
        "sql_time_s": round(sql["s"], 2),
        "due_query_ms": round(due_query_ms, 1),
        "peak_rss_mb": round(rss_mb, 1),
        "model_latency_s": model_latency,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sizes", type=int, nargs="+", default=[10, 50, 100, 250, 500])
    ap.add_argument(
        "--model-latency",
        type=float,
        default=0.0,
        help="seconds added to each fake model call",
    )
    ap.add_argument("--drop-share", type=float, default=0.2)
    ap.add_argument("--label", default="")
    ap.add_argument("--one", type=int, help=argparse.SUPPRESS)
    args = ap.parse_args()

    if args.one:
        print(json.dumps(one(args.one, args.model_latency, args.drop_share)))
        return

    rows = []
    for n in args.sizes:
        cmd = [
            sys.executable,
            __file__,
            "--one",
            str(n),
            "--model-latency",
            str(args.model_latency),
        ]
        cmd += ["--drop-share", str(args.drop_share)]
        out = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
        row = json.loads(out.strip().splitlines()[-1])
        rows.append(row)
        print(
            f"{n:>4} products: cycle {row['cycle_s']} s · {row['listings_per_s']} listings/s · "
            f"{row['workflow_runs']} workflow runs ({row['workflow_avg_ms']} ms avg) · "
            f"{row['sql_statements']} SQL ({row['sql_per_listing']}/listing, {row['sql_time_s']} s) · "
            f"RSS {row['peak_rss_mb']} MB",
            flush=True,
        )
    name = f"scheduler{('-' + args.label) if args.label else ''}.json"
    (env.RESULTS / name).write_text(json.dumps(rows, indent=2))
    print(f"saved perf/results/{name}")


if __name__ == "__main__":
    main()
