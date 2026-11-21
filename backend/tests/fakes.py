"""A recording repricer and mailer for pipeline tests (no LLM calls, no email)."""

from app.ai.schemas import Proposal, RepricingDecision, RepricingOutcome


class Recorder:
    def __init__(self, status="pending_review", **decision):
        self.calls, self.mails = [], []
        self.status = status
        self.decision = decision
        self.fail = False

    def repricer(self, product_id, trigger, summary, run_tag):
        self.calls.append((product_id, trigger, summary))
        if self.fail:
            raise RuntimeError("model unavailable")
        d = RepricingDecision(
            **(
                dict(
                    product_id=product_id,
                    event=trigger,
                    competitor_price_inr=800,
                    our_price_inr=900,
                    action="lower_price",
                    recommended_price_inr=810,
                    market_read="sustained_change",
                    urgency="high",
                    reasoning="The competitor is at ₹800, ₹100 below our ₹900.",
                    confidence=0.9,
                )
                | self.decision
            )
        )
        proposal = None
        if d.action in ("lower_price", "raise_price") and self.status in ("pending_review", "auto_approved"):
            proposal = Proposal(
                action=d.action,
                from_price_inr=d.our_price_inr,
                to_price_inr=d.recommended_price_inr,
                change_pct=round((d.recommended_price_inr - d.our_price_inr) / d.our_price_inr * 100, 2),
                competitor_price_inr=d.competitor_price_inr,
            )
        status = self.status if proposal else "no_change"
        return RepricingOutcome(
            thread_id=f"t-{len(self.calls)}",
            decision=d,
            status=status,
            proposal=proposal,
            final_price_inr=d.recommended_price_inr if status == "auto_approved" else None,
        )

    def mailer(self, to, subject, html, text):
        self.mails.append((to, subject))
