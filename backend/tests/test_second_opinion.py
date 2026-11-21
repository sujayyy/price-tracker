"""The second opinion: a critic agent reviews proposed price changes inside the repricing workflow.

Code decides what its review may do (apply_second_opinion): record it, and turn an auto-apply into a
human review. It never changes the price, the action or the confidence, and never skips a review.
Real LangGraph runtime with scripted models: no LLM, no database.
"""

from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver

from app.ai import CriticReview, ReviewAnswer, apply_second_opinion, build_repricing_workflow
from app.ai.agents.critic import CRITIC_TOOLS, build_critic_agent
from app.ai.checkpoint import _SERDE
from app.ai.guardrails import SECOND_OPINION
from app.ai.testing import InMemoryProvider, ScriptedChatModel, tool_call
from app.ai.workflow import resume_repricing, start_repricing
from tests.test_workflow import ITEM, answer, provider

CONTEXT_CALL = AIMessage(content="", tool_calls=[tool_call("get_pricing_context", {"product_id": ITEM})])


def review(verdict="agree", concerns=(), reasoning="The drop to ₹899 is a new low held for 12 hours.") -> AIMessage:
    args = {"verdict": verdict, "concerns": list(concerns), "reasoning": reasoning}
    return AIMessage(content="", tool_calls=[tool_call("CriticReview", args)])


def workflow(p: InMemoryProvider, analyst_answer: AIMessage, *critic_responses: AIMessage):
    analyst = ScriptedChatModel(responses=[CONTEXT_CALL, analyst_answer])
    critic = ScriptedChatModel(responses=list(critic_responses))
    wf = build_repricing_workflow(
        p, model=analyst, checkpointer=InMemorySaver(serde=_SERDE), second_opinion=True, critic_model=critic
    )
    return wf, critic


def opinions(decision) -> list[str]:
    return [n for n in decision.data_issues if n.startswith(SECOND_OPINION)]


# --- the code policy, on its own ---------------------------------------------------------------


def _decision():
    p = provider()
    return start_repricing(
        build_repricing_workflow(p, model=ScriptedChatModel(responses=[CONTEXT_CALL, answer()]),
                                 checkpointer=InMemorySaver(serde=_SERDE)),
        ITEM, "price_drop", "",
    ).decision  # fmt: skip


def test_a_concern_only_ever_moves_auto_apply_to_a_person():
    d = _decision()
    concern = CriticReview(verdict="concern", concerns=["Flipkart dipped to ₹899 last week too."], reasoning="x")
    for route, expected in [("auto_apply", "needs_review"), ("needs_review", "needs_review")]:
        new, new_route = apply_second_opinion(d, route, concern)
        assert new_route == expected
        # The price, the action and the confidence are untouched.
        assert (new.action, new.recommended_price_inr, new.confidence) == (d.action, d.recommended_price_inr,
                                                                           d.confidence)  # fmt: skip
        assert f"{SECOND_OPINION}concern: Flipkart dipped to ₹899 last week too." in new.data_issues


def test_agreement_keeps_the_route_and_no_review_means_a_person_decides():
    d = _decision()
    agree = CriticReview(verdict="agree", reasoning="Sound move.")
    assert apply_second_opinion(d, "auto_apply", agree)[1] == "auto_apply"
    assert apply_second_opinion(d, "needs_review", agree)[1] == "needs_review"
    unavailable, route = apply_second_opinion(d, "auto_apply", None)
    assert route == "needs_review" and any("unavailable" in n for n in opinions(unavailable))


def test_the_critic_cannot_fetch_marketplace_pages():
    agent = build_critic_agent(provider(), model=ScriptedChatModel(responses=[]))
    tool_names = set(agent.nodes["tools"].bound.tools_by_name)
    assert tool_names == CRITIC_TOOLS and "refetch_listing" not in tool_names


# --- inside the workflow ------------------------------------------------------------------------


def test_a_concern_stops_an_auto_apply_and_reaches_the_reviewer():
    p = provider(auto_apply=True, auto_apply_max_pct=10)
    wf, critic = workflow(
        p,
        answer(confidence=0.95),
        CONTEXT_CALL,
        review("concern", ["Amazon.in sold at ₹899 three days ago and went back to ₹999."]),
    )
    out = start_repricing(wf, ITEM, "price_drop", "Latest ₹899.")
    assert out.status == "pending_review" and out.proposal.to_price_inr == 889  # same price, now for a person
    notes = opinions(out.decision)
    assert any("went back to ₹999" in n for n in notes) and any("instead of being applied" in n for n in notes)
    assert len(critic.calls) == 2

    done = resume_repricing(wf, out.thread_id, ReviewAnswer(approved=True, by="asha"))
    assert done.status == "approved" and done.final_price_inr == 889


def test_agreement_lets_a_small_confident_move_apply():
    p = provider(auto_apply=True, auto_apply_max_pct=10)
    wf, _ = workflow(p, answer(confidence=0.95), CONTEXT_CALL, review("agree"))
    out = start_repricing(wf, ITEM, "price_drop", "")
    assert out.status == "auto_approved" and out.final_price_inr == 889
    assert any(n.startswith(f"{SECOND_OPINION}agrees") for n in out.decision.data_issues)


def test_holds_are_never_sent_to_the_critic():
    wf, critic = workflow(provider(), answer(action="hold", price=None))  # no critic responses scripted
    out = start_repricing(wf, ITEM, "price_drop", "")
    assert out.status == "no_change" and critic.calls == [] and opinions(out.decision) == []


def test_a_failing_critic_sends_the_move_to_a_person():
    p = provider(auto_apply=True, auto_apply_max_pct=10)
    wf, _ = workflow(p, answer(confidence=0.95))  # the critic model has nothing to say: it errors
    out = start_repricing(wf, ITEM, "price_drop", "")
    assert out.status == "pending_review" and out.proposal.to_price_inr == 889
    assert any("unavailable" in n for n in opinions(out.decision))


def test_without_the_option_the_workflow_is_unchanged():
    p = provider(auto_apply=True, auto_apply_max_pct=10)
    wf = build_repricing_workflow(
        p, model=ScriptedChatModel(responses=[CONTEXT_CALL, answer(confidence=0.95)]),
        checkpointer=InMemorySaver(serde=_SERDE),
    )  # fmt: skip
    assert "second_opinion" not in wf.get_graph().nodes
    out = start_repricing(wf, ITEM, "price_drop", "")
    assert out.status == "auto_approved" and opinions(out.decision) == []


def test_settings_turn_the_second_opinion_on_by_default():
    from app.core.config import Settings

    s = Settings(_env_file=None)
    assert s.second_opinion_enabled is True and s.second_opinion_model == ""
