"""The product-intake agent: resolves a free-text query to a concrete listing at add-time.

This is a separate prompt and tool set built with the same `create_agent` API. It is not
orchestrated by, and never calls, the analyst agent.
"""

from __future__ import annotations

import uuid

from langchain.agents import create_agent
from langchain.agents.structured_output import ToolStrategy
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import ToolMessage
from langgraph.checkpoint.base import BaseCheckpointSaver

from app.ai.agents.analyst import DEFAULT_MODEL
from app.ai.errors import AgentDecisionError
from app.ai.middleware import intake_middleware
from app.ai.prompts.intake_system import INTAKE_SYSTEM_PROMPT
from app.ai.provider import DataProvider
from app.ai.schemas import IntakeCandidate, IntakeResolution
from app.ai.tools import make_intake_tools

MIN_CHOSEN_SCORE = 0.8


def build_intake_agent(
    provider: DataProvider,
    *,
    model: str | BaseChatModel = DEFAULT_MODEL,
    checkpointer: BaseCheckpointSaver | None = None,
):
    return create_agent(
        model=model,
        tools=make_intake_tools(provider),
        system_prompt=INTAKE_SYSTEM_PROMPT,
        response_format=ToolStrategy(IntakeResolution),
        checkpointer=checkpointer,
        middleware=intake_middleware(),
        name="product_intake",
    )


def resolve_query(agent, query: str) -> IntakeResolution:
    result = agent.invoke(
        {"messages": [{"role": "user", "content": f"Find this product: {query}"}]},
        config={
            "configurable": {"thread_id": f"intake-{uuid.uuid4().hex}"},
            "tags": ["intake"],
        },
    )
    resolution = result.get("structured_response")
    if not isinstance(resolution, IntakeResolution):
        raise AgentDecisionError("Intake run ended without a structured resolution.")
    seen = _seen_candidates(result.get("messages", []))
    return ground_resolution(resolution, seen)


def _seen_candidates(messages) -> dict[tuple[str, str], IntakeCandidate]:
    seen: dict[tuple[str, str], IntakeCandidate] = {}
    for msg in messages:
        if isinstance(msg, ToolMessage) and isinstance(msg.artifact, list):
            for raw in msg.artifact:
                cand = IntakeCandidate.model_validate(raw)
                seen[(cand.marketplace, cand.external_id)] = cand
    return seen


def ground_resolution(resolution: IntakeResolution, seen: dict[tuple[str, str], IntakeCandidate]) -> IntakeResolution:
    """Drop anything the model did not get from a tool, and restore tool-provided fields.

    The model keeps its match_score (its judgement); title/url/price come from the search
    results so a hallucinated or altered listing can never reach the user.
    """

    def grounded(c: IntakeCandidate) -> IntakeCandidate | None:
        real = seen.get((c.marketplace, c.external_id))
        return real.model_copy(update={"match_score": c.match_score}) if real else None

    dropped = 0
    candidates: list[IntakeCandidate] = []
    for c in resolution.candidates:
        g = grounded(c)
        if g is None:
            dropped += 1
        elif all((g.marketplace, g.external_id) != (x.marketplace, x.external_id) for x in candidates):
            candidates.append(g)

    chosen = grounded(resolution.chosen) if resolution.chosen else None
    if resolution.chosen and chosen is None:
        dropped += 1

    resolved = resolution.resolved and chosen is not None and chosen.match_score >= MIN_CHOSEN_SCORE
    if not resolved and chosen is not None:
        # A weakly-held or inconsistent pick becomes one of the options to confirm.
        if all((chosen.marketplace, chosen.external_id) != (x.marketplace, x.external_id) for x in candidates):
            candidates.insert(0, chosen)
        chosen = None

    candidates.sort(key=lambda c: c.match_score, reverse=True)
    reasoning = resolution.reasoning
    if dropped:
        reasoning += f" ({dropped} candidate(s) not found in search results were discarded.)"
    return IntakeResolution(
        resolved=resolved,
        needs_confirmation=not resolved and bool(candidates),
        chosen=chosen if resolved else None,
        candidates=candidates,
        reasoning=reasoning,
    )
