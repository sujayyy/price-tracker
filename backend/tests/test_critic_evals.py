"""The critic eval cases are internally consistent and the harness runs end to end (scripted model)."""

from langchain_core.messages import AIMessage

from app.ai.testing import ScriptedChatModel, tool_call
from evals.critic import BY_CASE, CASES, EVALUATORS, run_case
from evals.dataset_builder import ITEM_ID


def test_cases_build_real_proposals():
    assert {c.expected for c in CASES} == {"agree", "concern"}
    assert len(CASES) == len(BY_CASE)
    for c in CASES:
        _, decision, proposal = c.build()
        assert proposal.to_price_inr == decision.recommended_price_inr, c.name
        assert "{" not in decision.reasoning, f"{c.name}: unfilled placeholder"


def test_the_bad_cases_really_are_bad():
    _, d, _ = BY_CASE["reasoning_numbers_wrong"].build()
    assert d.competitor_price_inr == 899 and "₹799" in d.reasoning  # the write-up disagrees with the data
    _, _, p = BY_CASE["floor_move_claims_to_undercut"].build()
    assert p.limited_by == "floor" and p.to_price_inr > p.competitor_price_inr  # cannot undercut
    provider, _, _ = BY_CASE["injection_in_title_with_flash_sale"].build()
    assert "REVIEWING AGENT" in provider.get_product_settings(ITEM_ID).title


def test_harness_scores_a_scripted_review():
    case = BY_CASE["flash_sale_treated_as_lasting"]
    model = ScriptedChatModel(
        responses=[
            AIMessage(content="", tool_calls=[tool_call("get_pricing_context", {"product_id": ITEM_ID})]),
            AIMessage(
                content="",
                tool_calls=[
                    tool_call(
                        "CriticReview",
                        {
                            "verdict": "concern",
                            "concerns": ["Amazon.in dipped to ₹899 twice before and returned to ₹999."],
                            "reasoning": "Likely a temporary sale.",
                        },
                    )
                ],
            ),
        ]
    )
    out = run_case(case, model).model_dump()
    assert all(ev(out, {"expected": case.expected})["score"] == 1 for ev in EVALUATORS)
