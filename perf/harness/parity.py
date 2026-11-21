"""Prove an optimization changed speed, not answers: identical JSON before and after.

    # serve the OLD code on :8100 (PERF_BACKEND=<copy> perf/run.sh serve), then
    .venv/bin/python perf/harness/parity.py capture perf/results/parity/before
    # serve the NEW code on :8100, then
    .venv/bin/python perf/harness/parity.py capture perf/results/parity/after
    .venv/bin/python perf/harness/parity.py diff perf/results/parity/before perf/results/parity/after

Covers every response the batched reads feed: the product list, every product, every product's
proposals, the proposal queue (pending and all) and monitoring. Both captures go through the same
server setup, and the database must not change in between (the perf backend does no background work).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def paths(get) -> list[str]:
    ids = [p["id"] for p in get("/api/products")]
    out = [
        "/api/products",
        "/api/proposals?status=pending",
        "/api/proposals",
        "/api/monitoring",
    ]
    for i in ids:
        out += [f"/api/products/{i}", f"/api/products/{i}/proposals"]
    return out


def key(path: str) -> str:
    return path.strip("/").replace("/", "_").replace("?", "_").replace("=", "-") + ".json"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["capture", "diff"])
    ap.add_argument("dirs", nargs="+")
    ap.add_argument("--base", default="http://127.0.0.1:8100")
    args = ap.parse_args()

    if args.mode == "capture":
        import httpx

        out = Path(args.dirs[0])
        out.mkdir(parents=True, exist_ok=True)
        with httpx.Client(base_url=args.base, timeout=60) as c:

            def get(p):
                return c.get(p).raise_for_status().json()

            ps = paths(get)
            for p in ps:
                (out / key(p)).write_text(json.dumps(get(p), sort_keys=True, indent=1))
        print(f"captured {len(ps)} responses from {args.base} into {out}")
        return

    a, b = (Path(d) for d in args.dirs[:2])
    names = sorted({f.name for f in a.glob("*.json")} | {f.name for f in b.glob("*.json")})
    diffs = [
        n for n in names if not (a / n).exists() or not (b / n).exists() or (a / n).read_text() != (b / n).read_text()
    ]
    print(f"compared {len(names)} responses: {len(names) - len(diffs)} identical, {len(diffs)} different")
    for n in diffs[:10]:
        print("  differs:", n)
    sys.exit(1 if diffs else 0)


if __name__ == "__main__":
    main()
