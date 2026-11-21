"""Code evaluators for the repricing analyst, plus a local runner.

    # Run every scenario against a real model and print a scorecard:
    python -m evals.evaluators --model anthropic:claude-haiku-4-5

    # Same, as a LangSmith experiment over the pushed dataset:
    python -m evals.evaluators --model ... --langsmith price-tracker-repricing

Evaluators take (outputs, reference) dicts so they work both locally and with
`langsmith.evaluate` (which passes `outputs` and `reference_outputs`).
"""

from __future__ import annotations

import argparse
import re

from app.ai import build_analyst_agent, decide
from app.ai.schemas import RepricingDecision
from evals.dataset_builder import BY_NAME, ITEM_ID, SCENARIOS, Scenario, reference_for


def action_acceptable(outputs: dict, reference_outputs: dict) -> dict:
    return {"key": "action_acceptable", "score": int(outputs["action"] in reference_outputs["actions"])}


def event_acceptable(outputs: dict, reference_outputs: dict) -> dict:
    return {"key": "event_acceptable", "score": int(outputs["event"] in reference_outputs["events"])}


def price_follows_option(outputs: dict, reference_outputs: dict) -> dict:
    """The model must copy a guardrail-priced option, never invent a number (prompt rule 3)."""
    if outputs["action"] in ("lower_price", "raise_price"):
        ok = outputs["recommended_price_inr"] == reference_outputs["option_prices"].get(outputs["action"])
    else:
        ok = outputs["recommended_price_inr"] is None
    return {"key": "price_follows_option", "score": int(ok)}


def urgency_acceptable(outputs: dict, reference_outputs: dict) -> dict:
    allowed = reference_outputs.get("urgency") or []
    return {"key": "urgency_acceptable", "score": int(not allowed or outputs["urgency"] in allowed)}


def market_read_acceptable(outputs: dict, reference_outputs: dict) -> dict:
    allowed = reference_outputs.get("market_read") or []
    return {"key": "market_read_acceptable", "score": int(not allowed or outputs["market_read"] in allowed)}


def reasoning_cites_number(outputs: dict, reference_outputs: dict | None = None) -> dict:
    return {"key": "reasoning_cites_number", "score": int(bool(re.search(r"\d", outputs["reasoning"])))}


def reasoning_is_short(outputs: dict, reference_outputs: dict | None = None) -> dict:
    sentences = [s for s in re.split(r"(?<=[.!?])\s+", outputs["reasoning"].strip()) if s]
    return {"key": "reasoning_at_most_3_sentences", "score": int(len(sentences) <= 3)}


EVALUATORS = [
    action_acceptable,
    event_acceptable,
    price_follows_option,
    urgency_acceptable,
    market_read_acceptable,
    reasoning_cites_number,
    reasoning_is_short,
]


def run_scenario(s: Scenario, model) -> RepricingDecision:
    agent = build_analyst_agent(s.provider(), model=model)
    return decide(agent, ITEM_ID, s.trigger, s.latest_summary(), listing_ids=s.listing_ids())  # type: ignore[arg-type]


def run_local(model) -> float:
    totals: dict[str, list[int]] = {}
    for s in SCENARIOS:
        try:
            out = run_scenario(s, model).model_dump()
        except Exception as exc:  # a failed run counts as wrong on every metric
            print(f"✗ {s.name}: {type(exc).__name__}: {exc}")
            for ev in EVALUATORS:
                totals.setdefault(ev.__name__, []).append(0)
            continue
        scores = [ev(out, reference_for(s)) for ev in EVALUATORS]
        for ev, sc in zip(EVALUATORS, scores, strict=True):
            totals.setdefault(ev.__name__, []).append(sc["score"])
        mark = "✓" if scores[0]["score"] else "✗"
        price = out["recommended_price_inr"]
        print(
            f"{mark} {s.name:34} action={out['action']:12} price={price if price is not None else '-'!s:7} "
            f"read={out['market_read']:18} urgency={out['urgency']:6} conf={out['confidence']:.2f}"
        )
    print()
    for name, vals in totals.items():
        print(f"{name:28} {sum(vals)}/{len(vals)}")
    return sum(totals["action_acceptable"]) / len(SCENARIOS)


def run_langsmith(model, dataset_name: str) -> None:
    from langsmith import evaluate

    def target(inputs: dict) -> dict:
        return run_scenario(BY_NAME[inputs["scenario"]], model).model_dump()

    evaluate(target, data=dataset_name, evaluators=EVALUATORS, experiment_prefix="repricing")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True, help='"provider:model" string, e.g. anthropic:claude-haiku-4-5')
    parser.add_argument("--langsmith", metavar="DATASET_NAME")
    args = parser.parse_args()
    if args.langsmith:
        run_langsmith(args.model, args.langsmith)
    else:
        acc = run_local(args.model)
        print(f"\naction accuracy: {acc:.0%}")
