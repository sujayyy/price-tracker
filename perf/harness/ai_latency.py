"""AI decision latency: what the application adds, and (opt-in, small) what the provider adds.

    .venv/bin/python perf/harness/ai_latency.py              # application side only, no provider
    .venv/bin/python perf/harness/ai_latency.py --real 20    # + 20 real decisions (calls the model API)

Part 1, no provider (always): the production repricing workflow (LangGraph graph, analyst agent,
tools, guardrails, Postgres checkpointer, BackendDataProvider over a seeded `tracker_perf_ai`
database) with the deterministic OptionPickingModel. Each run is timed end to end and split into
time inside model calls and the rest (application). A second pass adds a fixed delay per model
call to show how provider latency adds up.

Part 2, `--real N` (opt-in, keep N at 10-30): the analyst agent, i.e. the step that calls the LLM,
over the offline eval scenarios (InMemoryProvider: no database, no scraping), with AGENT_MODEL from
infra/.env. Per decision: wall time, time inside provider calls (network + provider), number of
calls, tokens, and a cost estimate. A few unauthenticated requests to the API host estimate the
network round trip. LangSmith tracing stays off.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from perf.harness import env

DB = "tracker_perf_ai"
# USD per million tokens (input, output), from Anthropic's published pricing for these models.
PRICES = {"claude-haiku-4-5": (1.0, 5.0)}


def pct(xs: list[float], p: float) -> float:
    xs = sorted(xs)
    if not xs:
        return float("nan")
    k = (len(xs) - 1) * p / 100
    lo, hi = int(k), min(int(k) + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def summary(name: str, xs: list[float]) -> dict:
    return {
        "name": name,
        "n": len(xs),
        "p50": round(pct(xs, 50), 1),
        "p90": round(pct(xs, 90), 1),
        "p95": round(pct(xs, 95), 1),
        "max": round(max(xs), 1),
        "mean": round(statistics.fmean(xs), 1),
    }


class ModelTimer:
    """Times every `_generate` call of a chat model class and keeps its token usage."""

    def __init__(self, cls):
        self.calls: list[dict] = []
        orig = cls._generate

        def _generate(model, messages, stop=None, run_manager=None, **kw):
            t = time.perf_counter()
            res = orig(model, messages, stop=stop, run_manager=run_manager, **kw)
            usage = getattr(res.generations[0].message, "usage_metadata", None) or {}
            self.calls.append(
                {
                    "ms": (time.perf_counter() - t) * 1000,
                    "in": usage.get("input_tokens", 0),
                    "out": usage.get("output_tokens", 0),
                }
            )
            return res

        cls._generate = _generate

    def take(self) -> list[dict]:
        calls, self.calls = self.calls, []
        return calls


def print_table(rows: list[dict]) -> None:
    print("| measure | n | p50 ms | p90 ms | p95 ms | max ms | mean ms |")
    print("|---|---:|---:|---:|---:|---:|---:|")
    for r in rows:
        print(f"| {r['name']} | {r['n']} | {r['p50']} | {r['p90']} | {r['p95']} | {r['max']} | {r['mean']} |")


def fake(runs: int, delayed_runs: int, delay: float) -> dict:
    url = env.apply(DB)
    env.ensure_database(DB)
    env.reset_database()
    from app import ai
    from app.db.base import SessionLocal
    from perf.harness.fake_model import OptionPickingModel
    from perf.harness.seed import build_workflow, make_dataset

    with SessionLocal() as s:
        ids = make_dataset(s, 50, history=60)
    timer = ModelTimer(OptionPickingModel)
    out = {}
    for label, n, latency in (
        ("no_delay", runs, 0.0),
        (f"delay_{delay}s_per_call", delayed_runs, delay),
    ):
        wf = build_workflow(url, latency)
        ai.start_repricing(wf, ids[0], "price_drop", "warm-up", run_tag="warmup")
        timer.take()
        total, model, app, statuses, ncalls = [], [], [], {}, []
        for i in range(n):
            pid = ids[i % len(ids)]
            t = time.perf_counter()
            res = ai.start_repricing(
                wf,
                pid,
                "price_drop",
                f"amazon_in listing of product {pid}: price_drop",
                run_tag=f"perf{i}",
            )
            ms = (time.perf_counter() - t) * 1000
            calls = timer.take()
            m = sum(c["ms"] for c in calls)
            total.append(ms)
            model.append(m)
            app.append(ms - m)
            ncalls.append(len(calls))
            statuses[res.status] = statuses.get(res.status, 0) + 1
        out[label] = {
            "model_latency_s_per_call": latency,
            "rows": [
                summary("workflow run, end to end", total),
                summary("inside model calls", model),
                summary("application (graph, tools, DB, checkpoints)", app),
            ],
            "model_calls_per_run": statistics.fmean(ncalls),
            "outcomes": statuses,
        }
        print(f"\n### fake model, {label} ({n} runs; outcomes {statuses}; model calls/run {statistics.fmean(ncalls)})")
        print_table(out[label]["rows"])
    return out


def rtt(url: str, n: int = 3) -> list[float]:
    """Round trip to the provider host: an unauthenticated GET (no model call, nothing billed)."""
    import httpx

    times = []
    with httpx.Client(timeout=10) as c:
        c.get(url)  # connection + TLS set up once, like the SDK's pooled client
        for _ in range(n):
            t = time.perf_counter()
            c.get(url)
            times.append((time.perf_counter() - t) * 1000)
    return times


def real(n: int) -> dict:
    env.apply(DB, allow_real_model=True)
    from langchain_anthropic import ChatAnthropic

    from app.ai import build_analyst_agent, decide
    from app.core.config import get_settings
    from evals.dataset_builder import ITEM_ID, SCENARIOS, reference_for
    from evals.evaluators import action_acceptable

    model_name = get_settings().agent_model
    if not model_name.startswith("anthropic:"):
        raise SystemExit(f"--real expects an anthropic: AGENT_MODEL, got {model_name!r}")
    short = model_name.split(":", 1)[1]
    timer = ModelTimer(ChatAnthropic)
    network = rtt("https://api.anthropic.com/")
    rows, failures = [], 0
    for i in range(n):
        s = SCENARIOS[i % len(SCENARIOS)]
        t0 = time.perf_counter()
        agent = build_analyst_agent(s.provider(), model=model_name)
        t1 = time.perf_counter()
        try:
            d = decide(
                agent,
                ITEM_ID,
                s.trigger,
                s.latest_summary(),
                listing_ids=s.listing_ids(),
            )
            action = d.action
            correct = action_acceptable(d.model_dump(), reference_for(s))["score"]
        except Exception as exc:  # noqa: BLE001 - count it, keep measuring
            failures += 1
            action, correct = f"error: {type(exc).__name__}", 0
        t2 = time.perf_counter()
        calls = timer.take()
        rows.append(
            {
                "scenario": s.name,
                "action": action,
                "action_acceptable": correct,
                "build_ms": (t1 - t0) * 1000,
                "decision_ms": (t2 - t1) * 1000,
                "model_ms": sum(c["ms"] for c in calls),
                "calls": len(calls),
                "call_ms": [c["ms"] for c in calls],
                "in": sum(c["in"] for c in calls),
                "out": sum(c["out"] for c in calls),
            }
        )
        print(f"  {i + 1:>2}/{n} {s.name:34} {action:14} {rows[-1]['decision_ms']:7.0f} ms  {len(calls)} calls")
    pin, pout = PRICES.get(short, (None, None))
    tin, tout = sum(r["in"] for r in rows), sum(r["out"] for r in rows)
    cost = (tin * pin + tout * pout) / 1e6 if pin is not None else None
    table = [
        summary("decision, end to end", [r["decision_ms"] for r in rows]),
        summary("inside provider calls (network + model)", [r["model_ms"] for r in rows]),
        summary(
            "application (agent loop, tools, parsing)",
            [r["decision_ms"] - r["model_ms"] for r in rows],
        ),
        summary("per provider call", [ms for r in rows for ms in r["call_ms"]]),
        summary("network round trip (unauthenticated GET)", network),
    ]
    accepted = sum(r["action_acceptable"] for r in rows)
    print(f"\n### real model {model_name}: {n} decisions, {failures} failed, action acceptable {accepted}/{n}")
    print_table(table)
    print(
        f"\nprovider calls per decision: {statistics.fmean(r['calls'] for r in rows):.2f} · "
        f"tokens in/out per decision: {tin / n:,.0f} / {tout / n:,.0f} · "
        + (f"estimated cost: ${cost:.4f} total, ${cost / n:.5f} per decision" if cost is not None else "cost: unknown")
    )
    return {
        "model": model_name,
        "n": n,
        "failures": failures,
        "action_acceptable": accepted,
        "rows": table,
        "decisions": rows,
        "tokens_in": tin,
        "tokens_out": tout,
        "usd_estimate": cost,
        "usd_per_mtok": [pin, pout],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=100)
    ap.add_argument("--delayed-runs", type=int, default=10)
    ap.add_argument(
        "--delay",
        type=float,
        default=1.0,
        help="seconds per fake model call in the second pass",
    )
    ap.add_argument(
        "--real",
        type=int,
        default=0,
        help="also run N real decisions (10-30; calls the model API)",
    )
    args = ap.parse_args()
    if args.real > 30:
        raise SystemExit("Keep the real-model benchmark small: --real 30 at most.")
    if args.real:
        result = {"real": real(args.real)}
        (env.RESULTS / "ai-latency-real.json").write_text(json.dumps(result, indent=2))
    else:
        result = {"fake": fake(args.runs, args.delayed_runs, args.delay)}
        (env.RESULTS / "ai-latency-fake.json").write_text(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
