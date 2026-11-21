"""The repricing workflow: a LangGraph StateGraph around the analyst, with a human in the loop.

    analyze ──▶ guardrails ──┬─▶ (no change) ─────────────────────▶ END
                             ├─▶ auto_apply ─────────▶ finalize ──▶ END
                             └─▶ human_review ⏸ ─────▶ finalize ──▶ END
                                 (interrupt: waits, possibly for hours, in the Postgres checkpoint)

- analyze: the LLM agent recommends a move (read-only tools, structured output).
- guardrails: code holds the recommendation to the allowed options, then routes it.
- human_review: `interrupt()` pauses the run. The dashboard's Approve/Reject resumes it with
  `Command(resume=ReviewAnswer)`, from any process, because the state lives in Postgres.
- finalize: re-checks the approval against *fresh* pricing data (our price may have changed
  while the proposal waited) and returns the verdict.

The workflow never writes: the backend applies an approved price and records the audit trail.
"""

from __future__ import annotations

import uuid
from typing import TypedDict

from langchain_core.language_models import BaseChatModel
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from app.ai.agents.analyst import DEFAULT_MODEL, build_analyst_agent, run_analyst
from app.ai.guardrails import enforce, validate_review
from app.ai.provider import DataProvider
from app.ai.schemas import Proposal, RepricingDecision, RepricingOutcome, ReviewAnswer, TriggerType


class RepricingState(TypedDict, total=False):
    # Plain JSON values only, so checkpoints stay readable and serializer-safe.
    product_id: int
    trigger: str
    summary: str
    decision: dict
    route: str
    proposal: dict | None
    review: dict | None
    result: dict | None


def build_repricing_workflow(
    provider: DataProvider,
    *,
    model: str | BaseChatModel = DEFAULT_MODEL,
    checkpointer: BaseCheckpointSaver | None = None,
    low_confidence: float = 0.7,
    auto_min_confidence: float = 0.85,
):
    """Compile the workflow. A checkpointer is required to pause for review and resume later."""
    # The workflow checkpoints the whole run, so the inner agent keeps no checkpoints of its own.
    analyst = build_analyst_agent(provider, model=model, checkpointer=False)

    def analyze(state: RepricingState) -> dict:
        settings = provider.get_product_settings(state["product_id"])
        if settings is None:
            raise LookupError(f"Unknown product {state['product_id']}")
        decision = run_analyst(
            analyst,
            state["product_id"],
            state["trigger"],  # type: ignore[arg-type]
            state["summary"],
            listing_ids=tuple(listing.listing_id for listing in settings.listings),
        )
        return {"decision": decision.model_dump(mode="json")}

    def guardrails(state: RepricingState) -> dict:
        ctx = provider.get_pricing_context(state["product_id"])
        if ctx is None:
            raise LookupError(f"Unknown product {state['product_id']}")
        result = enforce(
            RepricingDecision.model_validate(state["decision"]),
            ctx,
            low_confidence=low_confidence,
            auto_min_confidence=auto_min_confidence,
        )
        return {
            "decision": result.decision.model_dump(mode="json"),
            "route": result.route,
            "proposal": result.proposal.model_dump(mode="json") if result.proposal else None,
        }

    def route(state: RepricingState) -> str:
        return {"needs_review": "human_review", "auto_apply": "finalize"}.get(state["route"], END)

    def human_review(state: RepricingState) -> dict:
        # Everything before interrupt() re-runs on resume, so this node does nothing else.
        answer = interrupt(
            {"product_id": state["product_id"], "proposal": state["proposal"], "decision": state["decision"]}
        )
        return {"review": ReviewAnswer.model_validate(answer).model_dump(mode="json")}

    def finalize(state: RepricingState) -> dict:
        ctx = provider.get_pricing_context(state["product_id"])
        if ctx is None:
            raise LookupError(f"Unknown product {state['product_id']}")
        answer = (
            ReviewAnswer(approved=True, by="auto-apply")
            if state["route"] == "auto_apply"
            else ReviewAnswer.model_validate(state["review"])
        )
        verdict = validate_review(Proposal.model_validate(state["proposal"]), ctx, answer)
        return {"result": verdict.model_dump(mode="json")}

    graph = StateGraph(RepricingState)
    graph.add_node("analyze", analyze)
    graph.add_node("guardrails", guardrails)
    graph.add_node("human_review", human_review)
    graph.add_node("finalize", finalize)
    graph.add_edge(START, "analyze")
    graph.add_edge("analyze", "guardrails")
    graph.add_conditional_edges("guardrails", route, ["human_review", "finalize", END])
    graph.add_edge("human_review", "finalize")
    graph.add_edge("finalize", END)
    return graph.compile(checkpointer=checkpointer, name="repricing_workflow")


def _outcome(thread_id: str, state: dict, *, paused: bool) -> RepricingOutcome:
    decision = RepricingDecision.model_validate(state["decision"])
    proposal = Proposal.model_validate(state["proposal"]) if state.get("proposal") else None
    if paused:
        return RepricingOutcome(thread_id=thread_id, decision=decision, status="pending_review", proposal=proposal)
    result = state.get("result")
    if not result:
        return RepricingOutcome(thread_id=thread_id, decision=decision, status="no_change")
    status = result["status"]
    if status == "approved" and state.get("route") == "auto_apply":
        status = "auto_approved"
    return RepricingOutcome(
        thread_id=thread_id,
        decision=decision,
        status=status,
        proposal=proposal,
        final_price_inr=result.get("final_price_inr"),
        reason=result.get("reason"),
    )


def start_repricing(
    workflow, product_id: int, trigger_type: TriggerType, latest_summary: str, *, run_tag: str | None = None
) -> RepricingOutcome:
    """Run the workflow for one triggered product until it finishes or pauses for review."""
    thread_id = f"reprice-{product_id}-{run_tag or 'adhoc'}-{uuid.uuid4().hex[:8]}"
    config = {
        "configurable": {"thread_id": thread_id},
        "tags": ["repricing", f"trigger:{trigger_type}"],
        "metadata": {"product_id": product_id, "trigger_type": trigger_type},
    }
    state = workflow.invoke({"product_id": product_id, "trigger": trigger_type, "summary": latest_summary}, config)
    return _outcome(thread_id, state, paused=bool(state.get("__interrupt__")))


class NotAwaitingReview(LookupError):
    pass


def resume_repricing(workflow, thread_id: str, answer: ReviewAnswer) -> RepricingOutcome:
    """Resume a paused run with the reviewer's answer."""
    config = {"configurable": {"thread_id": thread_id}, "tags": ["repricing", "review"]}
    if "human_review" not in workflow.get_state(config).next:
        raise NotAwaitingReview(f"Workflow {thread_id} is not waiting for a review")
    state = workflow.invoke(Command(resume=answer.model_dump(mode="json")), config)
    return _outcome(thread_id, state, paused=bool(state.get("__interrupt__")))
