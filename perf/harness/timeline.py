"""Per-window view of a k6 run, from its `--out json=…gz` points: how latency and errors moved over time.

    .venv/bin/python perf/harness/timeline.py perf/results/spike-after-points.json.gz [--window 10]
    .venv/bin/python perf/harness/timeline.py perf/results/stress-after-points.json.gz --by-vus

Each request is counted in the window where it finished (k6 timestamps a request when it ends).
`--by-vus` merges the windows where the number of virtual users held steady, one row per level: the
table to read "where did it start to degrade" from.
"""

from __future__ import annotations

import argparse
import gzip
import json
from collections import defaultdict
from datetime import datetime


def pct(xs: list[float], p: float) -> float:
    xs = sorted(xs)
    k = (len(xs) - 1) * p / 100
    lo, hi = int(k), min(int(k) + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def fmt(ms: float) -> str:
    return f"{ms / 1000:.1f} s" if ms >= 1000 else f"{ms:.0f} ms"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("points")
    ap.add_argument("--window", type=float, default=10.0)
    ap.add_argument("--by-vus", action="store_true", help="one row per steady VU level")
    ap.add_argument("--statuses", action="store_true", help="HTTP status distribution (0 = no response)")
    args = ap.parse_args()

    points: dict[str, list[tuple[float, float]]] = defaultdict(list)  # metric -> (time, value)
    statuses: dict[str, int] = defaultdict(int)
    with gzip.open(args.points, "rt") as f:
        for line in f:
            row = json.loads(line)
            if row.get("type") == "Point" and row["metric"] in ("http_req_duration", "http_req_failed", "vus"):
                t = datetime.fromisoformat(row["data"]["time"]).timestamp()
                points[row["metric"]].append((t, row["data"]["value"]))
                if row["metric"] == "http_req_duration":
                    statuses[row["data"].get("tags", {}).get("status", "?")] += 1
    if args.statuses:
        total = sum(statuses.values())
        print(" · ".join(f"{code}: {n} ({100 * n / total:.1f}%)" for code, n in sorted(statuses.items())))
        return
    t0 = min(t for series in points.values() for t, _ in series)

    def window(t: float) -> int:
        return int((t - t0) // args.window)

    by_window: dict[int, list[float]] = defaultdict(list)
    errors: dict[int, float] = defaultdict(float)
    vus: dict[int, float] = defaultdict(float)
    vus_min: dict[int, float] = {}
    for t, v in points["http_req_duration"]:
        by_window[window(t)].append(v)
    for t, v in points["http_req_failed"]:
        errors[window(t)] += v
    for t, v in points["vus"]:
        vus[window(t)] = max(vus[window(t)], v)
        vus_min[window(t)] = min(vus_min.get(window(t), v), v)

    if args.by_vus:
        levels: dict[int, dict] = {}
        for i in vus:  # windows where nothing finished count too: they are the stalls
            if vus_min.get(i) == vus[i] and vus[i] > 0:
                lv = levels.setdefault(int(vus[i]), {"windows": 0, "xs": [], "errors": 0.0})
                lv["windows"] += 1
                lv["xs"] += by_window.get(i, [])
                lv["errors"] += errors.get(i, 0)
        print("| VUs (steady) | seconds | requests | req/s | errors | error % | p50 | p95 | p99 |")
        print("|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
        for n, lv in sorted(levels.items()):
            xs, secs = lv["xs"], lv["windows"] * args.window
            if lv["windows"] < 2 or not xs:  # a ramp's last second, not a level
                continue
            share = 100 * lv["errors"] / len(xs)
            print(
                f"| {n} | {secs:.0f} | {len(xs)} | {len(xs) / secs:.1f} | {int(lv['errors'])} | {share:.1f}% "
                f"| {fmt(pct(xs, 50))} | {fmt(pct(xs, 95))} | {fmt(pct(xs, 99))} |"
            )
        return

    print("| t (s) | VUs | requests | req/s | errors | p50 | p95 | max |")
    print("|---:|---:|---:|---:|---:|---:|---:|---:|")
    for i in range(max(list(by_window) + list(vus)) + 1):
        xs = by_window.get(i, [])
        start = int(i * args.window)
        span = f"{start}–{start + int(args.window)}"
        if xs:
            print(
                f"| {span} | {int(vus.get(i, 0))} | {len(xs)} | {len(xs) / args.window:.1f} | {int(errors.get(i, 0))} "
                f"| {fmt(pct(xs, 50))} | {fmt(pct(xs, 95))} | {fmt(max(xs))} |"
            )
        else:
            print(f"| {span} | {int(vus.get(i, 0))} | 0 | 0.0 | 0 | - | - | - |")


if __name__ == "__main__":
    main()
