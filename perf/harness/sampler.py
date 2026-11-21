"""Sample the perf backend's resources while a k6 test runs.

    .venv/bin/python perf/harness/sampler.py --pid $(cat perf/results/server-8100.pid) --out perf/results/load-x.csv &

Every `--every` seconds: process CPU% and RSS (MB) of the server and its children (uvicorn
workers), thread count, and the number of Postgres connections to the perf database (by state).
Stops on its own when the server process exits or after `--max` seconds.
"""

from __future__ import annotations

import argparse
import csv
import subprocess
import time

import psycopg


def proc_stats(pid: int) -> tuple[float, float, int]:
    """(cpu %, rss MB, threads) summed over the process and its children."""
    pids = [str(pid)] + subprocess.run(["pgrep", "-P", str(pid)], capture_output=True, text=True).stdout.split()
    cpu = rss = threads = 0.0
    for p in pids:
        out = subprocess.run(["ps", "-o", "%cpu=,rss=", "-p", p], capture_output=True, text=True).stdout.split()
        if len(out) == 2:
            cpu += float(out[0])
            rss += float(out[1]) / 1024
        th = subprocess.run(["ps", "-M", "-p", p], capture_output=True, text=True).stdout.count("\n") - 1
        threads += max(th, 0)
    return cpu, rss, int(threads)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--db", default="tracker_perf")
    ap.add_argument("--every", type=float, default=2.0)
    ap.add_argument("--max", type=float, default=7200)
    args = ap.parse_args()
    conn = psycopg.connect("postgresql://tracker:tracker@localhost:5432/postgres", autocommit=True)
    t0 = time.time()
    with open(args.out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["t_s", "cpu_pct", "rss_mb", "threads", "db_conns", "db_active", "db_idle"])
        while time.time() - t0 < args.max:
            if subprocess.run(["kill", "-0", str(args.pid)], capture_output=True).returncode != 0:
                break
            cpu, rss, threads = proc_stats(args.pid)
            rows = conn.execute(
                "SELECT state, count(*) FROM pg_stat_activity WHERE datname = %s GROUP BY state",
                (args.db,),
            ).fetchall()
            by = {s or "none": n for s, n in rows}
            w.writerow(
                [
                    round(time.time() - t0, 1),
                    round(cpu, 1),
                    round(rss, 1),
                    threads,
                    sum(by.values()),
                    by.get("active", 0),
                    by.get("idle", 0),
                ]
            )
            f.flush()
            time.sleep(args.every)


if __name__ == "__main__":
    main()
