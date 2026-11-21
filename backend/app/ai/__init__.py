"""Public API of the AI layer. The rest of the backend imports only from here (and `app.ai.schemas`)."""

from app.ai.agents.analyst import DEFAULT_MODEL, build_analyst_agent, decide
from app.ai.agents.intake import build_intake_agent, resolve_query
from app.ai.checkpoint import close_checkpointers, get_checkpointer, setup_checkpointer
from app.ai.errors import AgentDecisionError
from app.ai.guardrails import ListingSnapshot, build_pricing_context, looks_suspect, position, validate_review
from app.ai.provider import DataProvider
from app.ai.schemas import (
    AlertRules,
    HistoryStats,
    IntakeCandidate,
    IntakeResolution,
    ListingInfo,
    ObservationView,
    PricePoint,
    PricingContext,
    PricingRules,
    ProductSettings,
    Proposal,
    RepricingDecision,
    RepricingOutcome,
    ReviewAnswer,
)
from app.ai.workflow import NotAwaitingReview, build_repricing_workflow, resume_repricing, start_repricing

__all__ = [
    "DEFAULT_MODEL",
    "AgentDecisionError",
    "AlertRules",
    "DataProvider",
    "HistoryStats",
    "IntakeCandidate",
    "IntakeResolution",
    "ListingInfo",
    "ListingSnapshot",
    "NotAwaitingReview",
    "ObservationView",
    "PricePoint",
    "PricingContext",
    "PricingRules",
    "ProductSettings",
    "Proposal",
    "RepricingDecision",
    "RepricingOutcome",
    "ReviewAnswer",
    "build_analyst_agent",
    "build_intake_agent",
    "build_pricing_context",
    "build_repricing_workflow",
    "close_checkpointers",
    "decide",
    "get_checkpointer",
    "looks_suspect",
    "position",
    "resolve_query",
    "resume_repricing",
    "setup_checkpointer",
    "start_repricing",
    "validate_review",
]
