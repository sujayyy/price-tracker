"""Call-limit and retry middleware for both agents.

Limits use exit_behavior="end" for the model (the run stops without a structured response,
which the backend treats as "no LLM judgment available") and "continue" for tools (further
calls are refused with an error message the model can see).
"""

from __future__ import annotations

from langchain.agents.middleware import (
    AgentMiddleware,
    ModelCallLimitMiddleware,
    ModelRetryMiddleware,
    ToolCallLimitMiddleware,
)


def analyst_middleware() -> list[AgentMiddleware]:
    return [
        ModelRetryMiddleware(max_retries=2, on_failure="error"),
        ModelCallLimitMiddleware(run_limit=6, exit_behavior="end"),
        ToolCallLimitMiddleware(run_limit=8),
        # Prompt rule 6, enforced in code rather than trusted to the model.
        ToolCallLimitMiddleware(tool_name="refetch_listing", run_limit=1),
    ]


def intake_middleware() -> list[AgentMiddleware]:
    return [
        ModelRetryMiddleware(max_retries=2, on_failure="error"),
        ModelCallLimitMiddleware(run_limit=6, exit_behavior="end"),
        ToolCallLimitMiddleware(run_limit=6),
    ]
