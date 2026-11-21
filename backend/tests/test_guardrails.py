"""The deterministic pricing guardrails: options, enforcement of the model's choice, review checks."""

from datetime import UTC, datetime

from app.ai.guardrails import ListingSnapshot, build_pricing_context, enforce, validate_review
from app.ai.schemas import HistoryStats, ObservationView, PricingRules, RepricingDecision, ReviewAnswer


def obs(price, in_stock=True, ok=True, listing_id=1):
    return ObservationView(
        listing_id=listing_id,
        fetched_at=datetime.now(UTC),
        price_inr=price,
        mrp_inr=None,
        in_stock=in_stock,
        seller=None,
        source="html",
        ok=ok,
    )


def ctx(competitor, our=979, floor=850, max_change=10, undercut=10, in_stock=True, **kw):
    rules = PricingRules(
        our_price_inr=our, floor_price_inr=floor, max_change_pct=max_change, undercut_by_inr=undercut, **kw
    )
    return build_pricing_context(1, rules, [snap(competitor, in_stock)])


def snap(price, in_stock=True, previous=None, listing_id=1, marketplace="amazon_in", atl=None):
    stats = None
    if atl is not None:
        stats = HistoryStats(
            listing_id=listing_id,
            window_days=90,
            points_in_window=10,
            min_inr=atl,
            median_inr=atl,
            max_inr=atl,
            median_30d_inr=atl,
            all_time_low_inr=atl,
            all_time_high_inr=atl,
            latest_price_inr=price,
        )
    return ListingSnapshot(
        listing_id=listing_id,
        marketplace=marketplace,
        latest=obs(price, in_stock, listing_id=listing_id),
        previous_price=previous,
        last_known_price=price,
        stats=stats,
    )


def options(c):
    return {o.action: o for o in c.options}


def decision(action="lower_price", price=889.0, **kw):
    base = dict(
        product_id=1,
        event="price_drop",
        competitor_price_inr=899,
        our_price_inr=979,
        action=action,
        recommended_price_inr=price,
        market_read="sustained_change",
        urgency="high",
        reasoning="Competitor at ₹899 is ₹80 below us.",
        confidence=0.9,
    )
    return RepricingDecision(**(base | kw))


def test_competitor_drop_offers_an_undercut_price():
    c = ctx(899)
    assert c.position == "we_are_pricier" and c.gap_inr == 80
    lower = options(c)["lower_price"]
    assert lower.price_inr == 889 and lower.limited_by is None and lower.change_pct == -9.19
    assert "raise_price" not in options(c)


def test_floor_and_max_move_clamp_the_option():
    lower = options(ctx(799, floor=900))["lower_price"]
    assert lower.price_inr == 900 and lower.limited_by == "floor"
    lower = options(ctx(699, floor=None))["lower_price"]  # 10% max move from ₹979
    assert lower.price_inr == 882 and lower.limited_by == "max_change"


def test_floor_at_our_price_leaves_only_hold():
    c = ctx(799, our=900, floor=900)
    assert list(options(c)) == ["hold"] and "floor" in c.options[0].note


def test_competitor_raise_and_out_of_stock_offer_a_raise():
    raise_ = options(ctx(1149, our=989))["raise_price"]
    assert raise_.price_inr == 1087 and raise_.limited_by == "max_change"  # 10% cap on ₹989
    oos = ctx(None, our=1000, in_stock=False)
    assert oos.position == "competitor_unavailable" and options(oos)["raise_price"].price_inr == 1050


def test_no_our_price_means_no_options():
    c = build_pricing_context(1, PricingRules(), [snap(899)])
    assert c.position == "our_price_not_set" and c.options == []


def test_enforce_snaps_to_the_allowed_price_and_routes_to_review():
    g = enforce(decision(price=880), ctx(899))
    assert g.route == "needs_review" and g.decision.recommended_price_inr == 889
    assert g.proposal.to_price_inr == 889 and g.proposal.from_price_inr == 979
    assert any("replaced by the allowed ₹889" in n for n in g.decision.data_issues)


def test_enforce_refuses_moves_that_are_not_offered_or_on_suspect_data():
    g = enforce(decision(action="raise_price", price=2000), ctx(899))
    assert g.route == "no_change" and g.decision.action == "hold" and g.proposal is None
    g = enforce(decision(market_read="data_glitch"), ctx(899))
    assert g.decision.action == "investigate" and g.proposal is None


def test_auto_apply_only_for_small_confident_moves():
    small = ctx(969, auto_apply=True, auto_apply_max_pct=3)  # 979 -> 959 = -2.04%
    assert enforce(decision(price=959), small).route == "auto_apply"
    assert enforce(decision(price=959, confidence=0.8), small).route == "needs_review"
    assert enforce(decision(price=959, market_read="flash_sale"), small).route == "needs_review"
    big = ctx(899, auto_apply=True, auto_apply_max_pct=3)  # -9.19% is over the limit
    assert enforce(decision(), big).route == "needs_review"


def test_validate_review_rechecks_fresh_data():
    proposal = enforce(decision(), ctx(899)).proposal
    ok = validate_review(proposal, ctx(899), ReviewAnswer(approved=True, by="asha"))
    assert ok.status == "approved" and ok.final_price_inr == 889
    override = validate_review(proposal, ctx(899), ReviewAnswer(approved=True, by="asha", price_inr=895))
    assert override.final_price_inr == 895
    assert validate_review(proposal, ctx(899), ReviewAnswer(approved=True, by="a", price_inr=800)).status == "invalid"
    assert validate_review(proposal, ctx(899, our=949), ReviewAnswer(approved=True, by="a")).status == "stale"
    assert validate_review(proposal, ctx(899), ReviewAnswer(approved=False, by="a")).status == "rejected"


def test_never_raise_while_the_competitor_is_cutting():
    rules = PricingRules(our_price_inr=999, floor_price_inr=900, undercut_by_inr=10)
    falling = build_pricing_context(1, rules, [snap(1099, previous=1199)])
    assert falling.competitor_trend == "down" and list(options(falling)) == ["hold"]
    assert "never raise" in falling.options[0].note
    rising = build_pricing_context(1, rules, [snap(1099, previous=999)])
    assert options(rising)["raise_price"].price_inr == 1089


def test_capped_cut_says_we_stay_above_the_competitor():
    lower = options(ctx(719, our=849, floor=749))["lower_price"]
    assert lower.price_inr == 765 and lower.limited_by == "max_change"
    assert "still be ₹46 ABOVE the competitor" in lower.note and lower.note.startswith("Part of the way toward")


RULES = PricingRules(our_price_inr=789, floor_price_inr=650, undercut_by_inr=10)


def test_prices_against_the_lowest_platform():
    c = build_pricing_context(
        1, RULES, [snap(799, listing_id=1), snap(699, previous=799, listing_id=2, marketplace="flipkart")]
    )
    assert c.reference_marketplace == "flipkart" and c.competitor_price_inr == 699 and c.position == "we_are_pricier"
    assert [x.is_reference for x in c.competitors] == [False, True]
    lower = options(c)["lower_price"]
    assert lower.price_inr == 711 and "on flipkart" in lower.note  # 10% max move from ₹789


def test_a_suspect_reading_is_never_the_reference():
    c = build_pricing_context(
        1, RULES, [snap(799, listing_id=1), snap(39, listing_id=2, marketplace="flipkart", atl=699)]
    )
    assert c.competitors[1].suspect and c.reference_listing_id == 1 and c.competitor_price_inr == 799


def test_cheapest_going_out_of_stock_makes_the_next_one_the_reference():
    c = build_pricing_context(
        1,
        PricingRules(our_price_inr=719, floor_price_inr=650, undercut_by_inr=10),
        [snap(849, listing_id=1), snap(None, in_stock=False, listing_id=2, marketplace="flipkart")],
    )
    assert c.competitor_in_stock is True and c.competitor_price_inr == 849
    assert options(c)["raise_price"].price_inr == 790  # capped at +10%


def test_step_up_only_when_every_competitor_is_out_of_stock():
    both_out = [
        snap(None, in_stock=False, listing_id=1),
        snap(None, in_stock=False, listing_id=2, marketplace="flipkart"),
    ]
    c = build_pricing_context(1, PricingRules(our_price_inr=1000), both_out)
    assert c.competitor_in_stock is False and options(c)["raise_price"].price_inr == 1050


def test_no_raise_while_any_platform_is_cutting():
    c = build_pricing_context(
        1,
        PricingRules(our_price_inr=699, undercut_by_inr=0),
        [snap(799, previous=749, listing_id=1), snap(749, previous=799, listing_id=2, marketplace="flipkart")],
    )
    assert c.competitor_trend == "down" and list(options(c)) == ["hold"]


def test_options_report_where_we_land_against_the_lowest_competitor():
    c = ctx(719, our=849, floor=749)
    assert options(c)["lower_price"].gap_after_inr == 46  # capped: still above
    assert options(c)["hold"].gap_after_inr == 130
    assert options(ctx(899))["lower_price"].gap_after_inr == -10  # the full undercut
