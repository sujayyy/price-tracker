"""send_email picks implicit TLS or STARTTLS by port; no network is touched."""

import pytest

from app.core.config import Settings
from app.services.notifier import email


class FakeSMTP:
    instances: list["FakeSMTP"] = []

    def __init__(self, host, port, context=None, timeout=None):
        self.host, self.port, self.ssl_context = host, port, context
        self.calls: list[str] = []
        FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self, context=None):
        self.calls.append("starttls")

    def login(self, user, password):
        self.calls.append("login")

    def send_message(self, msg):
        self.calls.append(f"send:{msg['To']}")


@pytest.fixture
def fake_smtp(monkeypatch):
    FakeSMTP.instances.clear()
    monkeypatch.setattr(email.smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(email.smtplib, "SMTP_SSL", FakeSMTP)
    return FakeSMTP.instances


def configure(monkeypatch, **kw):
    settings = Settings(smtp_user="me@gmail.com", smtp_app_password="abcdabcdabcdabcd", **kw)
    monkeypatch.setattr(email, "get_settings", lambda: settings)


@pytest.mark.parametrize(
    ("port", "expected"),
    [(587, ["starttls", "login", "send:you@example.com"]), (465, ["login", "send:you@example.com"])],
)
def test_send_email_tls_mode_follows_port(monkeypatch, fake_smtp, port, expected):
    configure(monkeypatch, smtp_port=port)
    email.send_email("you@example.com", "subject", "<p>hi</p>", "hi")
    (conn,) = fake_smtp
    assert conn.port == port and conn.calls == expected


def test_send_email_without_credentials_raises(monkeypatch, fake_smtp):
    monkeypatch.setattr(email, "get_settings", lambda: Settings(smtp_user="", smtp_app_password=""))
    with pytest.raises(email.EmailNotConfigured):
        email.send_email("you@example.com", "subject", "<p>hi</p>", "hi")
    assert fake_smtp == []


def _decision(**kw):
    from app.ai.schemas import RepricingDecision

    base = dict(
        product_id=1,
        event="price_drop",
        competitor_price_inr=899,
        our_price_inr=979,
        action="lower_price",
        recommended_price_inr=889,
        market_read="sustained_change",
        urgency="high",
        reasoning="Competitor dropped to ₹899.",
        confidence=0.9,
        data_issues=["guardrail: stopped at the floor ₹889"],
    )
    return RepricingDecision(**(base | kw))


def test_ops_alert_for_a_pending_proposal():
    from app.ai.schemas import CompetitorView, Proposal

    proposal = Proposal(
        action="lower_price", from_price_inr=979, to_price_inr=889, change_pct=-9.19, competitor_price_inr=899
    )
    competitors = [
        CompetitorView(
            listing_id=1, marketplace="amazon_in", price_inr=899, in_stock=True, previous_price_inr=999,
            change_pct=-10.01, trend="down", suspect=False, is_reference=True,
        ),
        CompetitorView(
            listing_id=2, marketplace="flipkart", price_inr=949, in_stock=True, previous_price_inr=949,
            change_pct=0, trend="flat", suspect=False, is_reference=False,
        ),
    ]  # fmt: skip
    subject, html, text = email.render_ops_alert(
        title="Wireless Earbuds <script>",
        sku="SKU-7",
        marketplace="amazon_in",
        review_url="http://localhost:5173/products/1",
        trigger="price_drop",
        decision=_decision(),
        status="pending_review",
        proposal=proposal,
        competitor_prev=999,
        competitor_now=899,
        competitor_in_stock=True,
        floor=850,
        competitors=competitors,
        listing_urls={1: "https://www.amazon.in/dp/B0X"},
    )
    assert subject == "[Approval needed] Lower to ₹889 · Amazon.in dropped to ₹899 · Wireless Earbuds <script>"
    assert "Review &amp; approve" in html and "http://localhost:5173/products/1" in html
    assert "&lt;script&gt;" in html and "<script>" not in html  # scraped text is escaped
    assert "LOWEST" in html and "Flipkart" in html and "https://www.amazon.in/dp/B0X" in html
    assert "₹80 above the lowest competitor" in html and "stopped at the floor" in html
    assert "Amazon.in: ₹899 (lowest)" in text and "Flipkart: ₹949" in text
    assert "AI recommendation: Lower to ₹889 (-9.2%)" in text


def test_ops_alert_hold_and_out_of_stock():
    subject, _, _ = email.render_ops_alert(
        title="Earbuds",
        sku=None,
        marketplace="flipkart",
        review_url="r",
        trigger="out_of_stock",
        decision=_decision(action="hold", recommended_price_inr=None, data_issues=[]),
        status="no_change",
        proposal=None,
        competitor_prev=899,
        competitor_now=None,
        competitor_in_stock=False,
        floor=None,
    )
    assert subject == "[FYI] Hold at ₹979 · Flipkart is out of stock · Earbuds"
