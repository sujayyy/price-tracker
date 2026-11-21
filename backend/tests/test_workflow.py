"""The repricing StateGraph: analyze → guardrails → pause for review → finalize.

Real LangGraph runtime with an in-memory checkpointer and a scripted model: no LLM, no database.
"""

import pytest
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver

from app.ai import (
    NotAwaitingReview,
    ProductSettings,
    ReviewAnswer,
    build_repricing_workflow,
    resume_repricing,
    start_repricing,
)
from app.ai.checkpoint import _SERDE
from app.ai.testing import InMemoryProvider, ScriptedChatModel, tool_call

ITEM = 3


def provider(**settings) -> InMemoryProvider:
    p = InMemoryProvider()
    p.add_series(
        ProductSettings(
            product_id=ITEM,
            title="Wireless Earbuds",
            **({"our_price_inr": 979, "floor_price_inr": 850, "undercut_by_inr": 10} | settings),
        ),
        [999, 999, 999, 999, 899],
    )
    return p


def answer(action="lower_price", price=889.0, **kw) -> AIMessage:
    decision = (
        dict(
            product_id=ITEM,
            event="price_drop",
            competitor_price_inr=899,
            our_price_inr=979,
            action=action,
            recommended_price_inr=price,
            market_read="sustained_change",
            urgency="high",
            reasoning="Competitor dropped to ₹899, ₹80 below our ₹979.",
            confidence=0.9,
        )
        | kw
    )
    return AIMessage(content="", tool_calls=[tool_call("RepricingDecision", decision)])


def workflow(p, *responses):
    model = ScriptedChatModel(
        responses=[
            AIMessage(content="", tool_calls=[tool_call("get_pricing_context", {"product_id": ITEM})]),
            *responses,
        ]
    )
    return build_repricing_workflow(p, model=model, checkpointer=InMemorySaver(serde=_SERDE))


def test_price_change_pauses_for_review_then_applies_on_approval():
    p = provider()
    wf = workflow(p, answer())
    out = start_repricing(wf, ITEM, "price_drop", "Latest ₹899.")
    assert out.status == "pending_review"
    assert out.proposal.from_price_inr == 979 and out.proposal.to_price_inr == 889
    assert wf.get_state({"configurable": {"thread_id": out.thread_id}}).next == ("human_review",)

    done = resume_repricing(wf, out.thread_id, ReviewAnswer(approved=True, by="asha", price_inr=895))
    assert done.status == "approved" and done.final_price_inr == 895
    with pytest.raises(NotAwaitingReview):  # a finished run cannot be approved twice
        resume_repricing(wf, out.thread_id, ReviewAnswer(approved=True, by="asha"))


def test_rejection_finishes_the_run_without_a_price():
    wf = workflow(provider(), answer())
    out = start_repricing(wf, ITEM, "price_drop", "")
    done = resume_repricing(wf, out.thread_id, ReviewAnswer(approved=False, by="asha", note="flash sale"))
    assert done.status == "rejected" and done.final_price_inr is None


def test_approval_is_stale_if_our_price_changed_meanwhile():
    p = provider()
    wf = workflow(p, answer())
    out = start_repricing(wf, ITEM, "price_drop", "")
    p.settings[ITEM] = p.settings[ITEM].model_copy(update={"our_price_inr": 949})
    done = resume_repricing(wf, out.thread_id, ReviewAnswer(approved=True, by="asha"))
    assert done.status == "stale" and "₹949" in done.reason


def test_hold_ends_without_review():
    wf = workflow(provider(), answer(action="hold", price=None))
    out = start_repricing(wf, ITEM, "price_drop", "")
    assert out.status == "no_change" and out.proposal is None


def test_small_confident_move_is_auto_applied():
    p = provider(auto_apply=True, auto_apply_max_pct=10)
    out = start_repricing(workflow(p, answer(confidence=0.95)), ITEM, "price_drop", "")
    assert out.status == "auto_approved" and out.final_price_inr == 889


def test_guardrails_override_a_made_up_price():
    out = start_repricing(workflow(provider(), answer(price=500)), ITEM, "price_drop", "")
    assert out.proposal.to_price_inr == 889 and out.decision.recommended_price_inr == 889
    assert any("replaced by the allowed ₹889" in n for n in out.decision.data_issues)


def test_second_platform_is_priced_against_the_lowest():
    p = provider()
    flipkart = p.add_series(p.settings[ITEM], [999, 999, 999, 849], marketplace="flipkart")
    ctx = p.get_pricing_context(ITEM)
    assert ctx.reference_listing_id == flipkart and ctx.competitor_price_inr == 849
    wf = workflow(p, answer(price=882.0, competitor_price_inr=849))
    out = start_repricing(wf, ITEM, "price_drop", "Flipkart cut to ₹849.")
    assert out.status == "pending_review" and out.proposal.to_price_inr == 882  # 10% max move from ₹979
    assert out.proposal.competitor_price_inr == 849
