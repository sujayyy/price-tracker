"""The eval scenarios are internally consistent and the harness runs end to end (scripted model)."""

from langchain_core.messages import AIMessage

from app.ai.testing import ScriptedChatModel, tool_call
from evals.dataset_builder import BY_NAME, ITEM_ID, SCENARIOS, reference_for
from evals.evaluators import EVALUATORS, run_scenario


def test_scenarios_build_providers_with_the_options_they_expect():
    for s in SCENARIOS:
        p = s.provider()
        assert p.get_price_history(ITEM_ID, 90).latest_price_inr == s.prices[-1], s.name
        offered = set(reference_for(s)["option_prices"]) | {"investigate"}
        assert s.expected_actions & offered, f"{s.name}: no expected action is offered"


def test_scenario_option_prices():
    assert reference_for(BY_NAME["sustained_drop_we_are_pricier"])["option_prices"] == {"hold": 979, "lower_price": 889}
    assert reference_for(BY_NAME["drop_below_our_floor"])["option_prices"]["lower_price"] == 900
    assert reference_for(BY_NAME["floor_blocks_any_cut"])["option_prices"] == {"hold": 900}
    assert reference_for(BY_NAME["competitor_out_of_stock"])["option_prices"]["raise_price"] == 1028
    assert reference_for(BY_NAME["flipkart_undercuts_while_amazon_holds"])["option_prices"]["lower_price"] == 711
    assert reference_for(BY_NAME["cheapest_platform_goes_out_of_stock"])["option_prices"]["raise_price"] == 790


def test_harness_scores_a_correct_answer():
    s = BY_NAME["sustained_drop_we_are_pricier"]
    answer = dict(
        product_id=ITEM_ID,
        event="price_drop",
        competitor_price_inr=899,
        our_price_inr=979,
        action="lower_price",
        recommended_price_inr=889,
        market_read="sustained_change",
        urgency="high",
        reasoning="The competitor dropped to ₹899, ₹80 below our ₹979.",
        confidence=0.9,
    )
    model = ScriptedChatModel(
        responses=[
            AIMessage(content="", tool_calls=[tool_call("get_pricing_context", {"product_id": ITEM_ID})]),
            AIMessage(content="", tool_calls=[tool_call("RepricingDecision", answer)]),
        ]
    )
    out = run_scenario(s, model).model_dump()
    assert all(ev(out, reference_for(s))["score"] == 1 for ev in EVALUATORS)
