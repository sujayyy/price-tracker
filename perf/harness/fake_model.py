"""A deterministic stand-in for the analyst LLM, for load and workflow benchmarks.

It behaves like a well-behaved analyst in exactly two model calls, like the real one usually does:
1. call `get_pricing_context` for the product named in the trigger;
2. read the options from that tool result and return a `RepricingDecision` that picks
   lower_price, else raise_price, else hold, copying the option's price.

So the real LangGraph workflow, tools, guardrails, checkpointer and database all run; only the
provider call is replaced. `latency_s` can add a fixed delay per model call to imitate a provider.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult


class OptionPickingModel(BaseChatModel):
    latency_s: float = 0.0

    @property
    def _llm_type(self) -> str:
        return "perf-option-picking"

    def bind_tools(self, tools: Any, **kwargs: Any) -> OptionPickingModel:
        return self

    def _generate(self, messages: list[BaseMessage], stop=None, run_manager=None, **kwargs) -> ChatResult:
        if self.latency_s:
            time.sleep(self.latency_s)
        return ChatResult(generations=[ChatGeneration(message=self._next(messages))])

    def _next(self, messages: list[BaseMessage]) -> AIMessage:
        human = next(m for m in messages if isinstance(m, HumanMessage))
        product_id = int(re.search(r"product (\d+)", str(human.content)).group(1))
        results = [m for m in messages if isinstance(m, ToolMessage)]
        if not results:
            call = {
                "name": "get_pricing_context",
                "args": {"product_id": product_id},
                "id": f"ctx-{product_id}",
            }
            return AIMessage(content="", tool_calls=[call])
        ctx = json.loads(str(results[-1].content))
        options = {o["action"]: o for o in ctx.get("options", [])}
        pick = options.get("lower_price") or options.get("raise_price")
        action = pick["action"] if pick else "hold"
        decision = {
            "product_id": product_id,
            "event": "price_drop"
            if action == "lower_price"
            else "price_increase"
            if action == "raise_price"
            else "none",
            "competitor_price_inr": ctx.get("competitor_price_inr"),
            "our_price_inr": ctx.get("our_price_inr"),
            "action": action,
            "recommended_price_inr": pick["price_inr"] if pick else None,
            "market_read": "sustained_change",
            "urgency": "high" if action == "lower_price" else "low",
            "reasoning": f"Perf model: chose {action} from {len(options)} option(s).",
            "confidence": 0.8,
        }
        call = {
            "name": "RepricingDecision",
            "args": decision,
            "id": f"dec-{product_id}",
        }
        return AIMessage(content="", tool_calls=[call])
