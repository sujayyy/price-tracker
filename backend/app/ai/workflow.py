"""The repricing workflow: a LangGraph StateGraph around two agents, with a human in the loop.

    analyze ──▶ guardrails ──┬─▶ (no change) ────────────────────────────────────▶ END
                             └─▶ second_opinion ──┬─▶ auto_apply ──────▶ finalize ──▶ END
                                                  └─▶ human_review ⏸ ──▶ finalize ──▶ END
                                 (interrupt: waits, possibly for hours, in the Postgres checkpoint)

- analyze: the analyst agent recommends a move (read-only tools, structured output).
- guardrails: code holds the recommendation to the allowed options, then routes it.
- second_opinion: only for a proposed price change, the critic agent looks for a data-backed
  reason the move is wrong. Code (apply_second_opinion) records its review and can only send an
  auto-apply to a person; the price, action and confidence never change. Off unless enabled.
- human_review: `interrupt()` pauses the run. The dashboard's Approve/Reject resumes it with
  `Command(resume=ReviewAnswer)`, from any process, because the state lives in Postgres.
- finalize: re-checks the approval against *fresh* pricing data (our price may have changed
  while the proposal waited) and returns the verdict.

The workflow never writes: the backend applies an approved price and records the audit trail.
"""

from __future__ import annotations

import logging
import uuid
from typing import TypedDict

from langchain_core.language_models import BaseChatModel
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from app.ai.agents.analyst import DEFAULT_MODEL, build_analyst_agent, run_analyst
from app.ai.agents.critic import build_critic_agent, run_critic
from app.ai.guardrails import apply_second_opinion, enforce, validate_review
from app.ai.provider import DataProvider
from app.ai.schemas import CriticReview, Proposal, RepricingDecision, RepricingOutcome, ReviewAnswer, TriggerType

log = logging.getLogger(__name__)


class RepricingState(TypedDict, total=False):
    # Plain JSON values only, so checkpoints stay readable and serializer-safe.
    product_id: int
    trigger: str
    summary: str
    decision: dict
    route: str
    proposal: dict | None
    second_opinion: dict | None
    review: dict | None
    result: dict | None


def build_repricing_workflow(
    provider: DataProvider,
    *,
    model: str | BaseChatModel = DEFAULT_MODEL,
    checkpointer: BaseCheckpointSaver | None = None,
    low_confidence: float = 0.7,
    auto_min_confidence: float = 0.85,
    second_opinion: bool = False,
    critic_model: str | BaseChatModel | None = None,
):
    """Compile the workflow. A checkpointer is required to pause for review and resume later.

    second_opinion=True adds the critic agent (on critic_model, default: the analyst's model).
    """
    # The workflow checkpoints the whole run, so the inner agents keep no checkpoints of their own.
    analyst = build_analyst_agent(provider, model=model, checkpointer=False)
    critic = build_critic_agent(provider, model=critic_model or model) if second_opinion else None

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

    def after_guardrails(state: RepricingState) -> str:
        # The critic only looks at a price change the guardrails accepted; holds stay cheap.
        if critic is not None and state["route"] in ("needs_review", "auto_apply"):
            return "second_opinion"
        return route(state)

    def second_opinion_node(state: RepricingState) -> dict:
        decision = RepricingDecision.model_validate(state["decision"])
        settings = provider.get_product_settings(state["product_id"])
        review: CriticReview | None = None
        try:
            review = run_critic(
                critic,
                state["product_id"],
                decision,
                Proposal.model_validate(state["proposal"]),
                listing_ids=tuple(x.listing_id for x in settings.listings) if settings else (),
            )
        except Exception as exc:  # model error or call limit: fail safe, a person reviews the move
            log.warning("critic_unavailable product_id=%s error=%s", state["product_id"], type(exc).__name__)
        decision, new_route = apply_second_opinion(decision, state["route"], review)  # type: ignore[arg-type]
        return {
            "decision": decision.model_dump(mode="json"),
            "route": new_route,
            "second_opinion": review.model_dump(mode="json") if review else None,
        }

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
    if critic is not None:
        graph.add_node("second_opinion", second_opinion_node)
        graph.add_conditional_edges("guardrails", after_guardrails, ["second_opinion", "human_review", "finalize", END])
        graph.add_conditional_edges("second_opinion", route, ["human_review", "finalize"])
    else:
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
