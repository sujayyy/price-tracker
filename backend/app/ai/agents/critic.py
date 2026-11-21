"""The critic: a second agent that challenges a proposed price change before it is applied or reviewed.

It runs inside the repricing workflow only when the analyst proposed a move that the guardrails
accepted, reads the same data through read-only tools (no live refetch), and returns a
CriticReview. Code decides what the review does (app.ai.guardrails.apply_second_opinion).
"""

from __future__ import annotations

import json

from langchain.agents import create_agent
from langchain.agents.structured_output import ToolStrategy
from langchain_core.language_models import BaseChatModel

from app.ai.errors import AgentDecisionError
from app.ai.middleware import critic_middleware
from app.ai.prompts.critic_system import CRITIC_SYSTEM_PROMPT
from app.ai.provider import DataProvider
from app.ai.schemas import CriticReview, Proposal, RepricingDecision
from app.ai.tools import AnalystContext, make_analyst_tools

# The critic checks what is stored; it never fetches a marketplace page itself.
CRITIC_TOOLS = {"get_pricing_context", "get_price_history", "get_latest_observation", "get_product_settings"}


def build_critic_agent(provider: DataProvider, *, model: str | BaseChatModel):
    tools = [t for t in make_analyst_tools(provider) if t.name in CRITIC_TOOLS]
    return create_agent(
        model=model,
        tools=tools,
        system_prompt=CRITIC_SYSTEM_PROMPT,
        response_format=ToolStrategy(CriticReview),
        context_schema=AnalystContext,
        checkpointer=False,  # the workflow checkpoints the whole run
        middleware=critic_middleware(),
        name="pricing_critic",
    )


def run_critic(
    agent,
    product_id: int,
    decision: RepricingDecision,
    proposal: Proposal,
    *,
    listing_ids: tuple[int, ...],
) -> CriticReview:
    """Ask the critic about one proposed move. Raises AgentDecisionError if it ends without a review."""
    brief = {
        "proposed_move": proposal.model_dump(mode="json"),
        "analyst": decision.model_dump(
            mode="json", include={"action", "market_read", "urgency", "reasoning", "confidence", "data_issues"}
        ),
    }
    result = agent.invoke(
        {
            "messages": [
                {
                    "role": "user",
                    "content": f"Review this proposed price change for product {product_id}:\n{json.dumps(brief)}",
                }
            ]
        },
        config={"tags": ["critic"], "metadata": {"product_id": product_id}},
        context=AnalystContext(product_id=product_id, listing_ids=tuple(listing_ids)),
    )
    review = result.get("structured_response")
    if not isinstance(review, CriticReview):
        raise AgentDecisionError("Critic run ended without a review (call limit?).")
    return review
