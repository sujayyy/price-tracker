"""Turn a k6 --summary-export JSON into the tables used in perf/REPORT.md.

.venv/bin/python perf/harness/summarize.py perf/results/load-before.json [--sampler load-before-sampler.csv]
"""

from __future__ import annotations

import csv
import json
import statistics
import sys


def fmt(v: float | None) -> str:
    if v is None:
        return "-"
    return f"{v:,.0f}" if v >= 100 else f"{v:,.1f}"


def main(path: str) -> None:
    with open(path) as f:
        m = json.load(f)["metrics"]
    reqs = m.get("http_reqs", {})
    failed = m.get("http_req_failed", {})
    dur = m.get("http_req_duration", {})
    it = m.get("iterations", {})
    print(f"source: {path}")
    print(
        f"requests {reqs.get('count', 0):,} · throughput {reqs.get('rate', 0):,.1f} req/s · "
        f"error rate {100 * failed.get('value', failed.get('rate', 0)):.2f}% · iterations {it.get('count', 0):,} · "
        f"max VUs {m.get('vus_max', {}).get('value', m.get('vus_max', {}).get('max', '-'))}"
    )
    print()
    print("| endpoint | count | p50 ms | p90 ms | p95 ms | p99 ms | max ms |")
    print("|---|---:|---:|---:|---:|---:|---:|")
    rows = [("all requests", dur)] + sorted(
        ((k.split("name:", 1)[1].rstrip("}"), v) for k, v in m.items() if k.startswith("http_req_duration{name:")),
        key=lambda kv: -(kv[1].get("p(95)") or 0),
    )
    for name, v in rows:
        print(
            f"| {name} | {v.get('count', '-')} | {fmt(v.get('med'))} | {fmt(v.get('p(90)'))} | {fmt(v.get('p(95)'))} "
            f"| {fmt(v.get('p(99)'))} | {fmt(v.get('max'))} |"
        )


def sampler(path: str) -> None:
    """One line of server resources from perf/harness/sampler.py's CSV."""
    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        print(f"sampler: no samples in {path}")
        return
    cpu = [float(r["cpu_pct"]) for r in rows]
    rss = [float(r["rss_mb"]) for r in rows]
    conns = [int(r["db_conns"]) for r in rows]
    in_tx = [int(r["db_conns"]) - int(r["db_active"]) - int(r["db_idle"]) for r in rows]
    print(
        f"server ({len(rows)} samples): CPU median {statistics.median(cpu):.0f}% max {max(cpu):.0f}% · "
        f"RSS start {rss[0]:.0f} MB max {max(rss):.0f} MB end {rss[-1]:.0f} MB · "
        f"DB connections max {max(conns)} · held by a request (idle in transaction) max {max(in_tx)} "
        f"· executing a query max {max(int(r['db_active']) for r in rows)}"
    )


if __name__ == "__main__":
    args = sys.argv[1:]
    if "--sampler" in args:
        i = args.index("--sampler")
        csv_path = args[i + 1]
        del args[i : i + 2]
    else:
        csv_path = None
    for p in args:
        main(p)
        print()
    if csv_path:
        sampler(csv_path)
