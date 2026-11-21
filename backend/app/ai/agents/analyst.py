"""The repricing analyst: one `create_agent` loop, read-only tools, structured output.

It only *recommends*. `app.ai.workflow` wraps it with the guardrails and the human approval step.
"""

from __future__ import annotations

import uuid

from langchain.agents import create_agent
from langchain.agents.structured_output import ToolStrategy
from langchain_core.language_models import BaseChatModel
from langgraph.checkpoint.base import BaseCheckpointSaver

from app.ai.errors import AgentDecisionError
from app.ai.middleware import analyst_middleware
from app.ai.prompts.analyst_system import ANALYST_SYSTEM_PROMPT
from app.ai.provider import DataProvider
from app.ai.schemas import RepricingDecision, TriggerType
from app.ai.tools import AnalystContext, make_analyst_tools

DEFAULT_MODEL = "google_genai:gemini-3.6-flash"


def build_analyst_agent(
    provider: DataProvider,
    *,
    model: str | BaseChatModel = DEFAULT_MODEL,
    checkpointer: BaseCheckpointSaver | bool | None = None,
):
    """Build the analyst agent. Standalone runs (evals) may pass a checkpointer; inside the
    workflow it runs with `checkpointer=False`, since the workflow checkpoints the whole run."""
    return create_agent(
        model=model,
        tools=make_analyst_tools(provider),
        system_prompt=ANALYST_SYSTEM_PROMPT,
        # ToolStrategy works with any tool-calling model and re-prompts on validation errors.
        response_format=ToolStrategy(RepricingDecision),
        context_schema=AnalystContext,
        checkpointer=checkpointer,
        middleware=analyst_middleware(),
        name="repricing_analyst",
    )


def run_analyst(
    agent,
    product_id: int,
    trigger_type: TriggerType,
    latest_summary: str,
    *,
    listing_ids: tuple[int, ...],
    config: dict | None = None,
) -> RepricingDecision:
    """Invoke the agent once and return its validated decision (inherits the caller's run config)."""
    result = agent.invoke(
        {
            "messages": [
                {
                    "role": "user",
                    "content": f"Trigger for product {product_id}: {trigger_type}. {latest_summary}",
                }
            ]
        },
        config={
            **(config or {}),
            "tags": ["analyst", f"trigger:{trigger_type}"],
            "metadata": {"product_id": product_id, "trigger_type": trigger_type},
        },
        context=AnalystContext(product_id=product_id, listing_ids=tuple(listing_ids)),
    )
    decision = result.get("structured_response")
    if not isinstance(decision, RepricingDecision):
        raise AgentDecisionError("Analyst run ended without a structured decision (call limit?).")
    if decision.product_id != product_id:
        # The model mislabelled the product; the decision is still about this run's product.
        decision = decision.model_copy(
            update={
                "product_id": product_id,
                "data_issues": [*decision.data_issues, "model returned a different product_id"],
            }
        )
    return decision


def decide(
    agent,
    product_id: int,
    trigger_type: TriggerType,
    latest_summary: str,
    *,
    listing_ids: tuple[int, ...],
    run_tag: str | None = None,
) -> RepricingDecision:
    """Run the analyst standalone (evals, tests). Each run gets its own checkpoint thread."""
    thread_id = f"product-{product_id}-{run_tag or uuid.uuid4().hex}"
    return run_analyst(
        agent,
        product_id,
        trigger_type,
        latest_summary,
        listing_ids=listing_ids,
        config={"configurable": {"thread_id": thread_id}},
    )
