"""Gmail SMTP notifier for the operations team (app password). Plain backend code: the agent never sends email."""

from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage
from pathlib import Path

import certifi
import structlog
from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.ai.schemas import CompetitorView, Proposal, RepricingDecision
from app.core.config import get_settings

log = structlog.get_logger()

_env = Environment(
    loader=FileSystemLoader(Path(__file__).parent / "templates"),
    autoescape=select_autoescape(["html", "j2"]),
)

EVENT_LABELS = {
    "price_drop": "Competitor price drop",
    "price_increase": "Competitor price increase",
    "out_of_stock": "Competitor out of stock",
    "back_in_stock": "Competitor back in stock",
    "needs_attention": "Listing needs a check",
}
MARKETPLACES = {"amazon_in": "Amazon.in", "flipkart": "Flipkart"}


class EmailNotConfigured(RuntimeError):
    pass


def format_inr(value: float | None) -> str:
    if value is None:
        return "—"
    whole, frac = f"{value:.2f}".split(".")
    # Indian digit grouping: 1,23,45,678
    head, tail = whole[:-3], whole[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    grouped = ",".join([*groups, tail]) if groups else tail
    return f"₹{grouped}" + (f".{frac}" if frac != "00" else "")


def _movement(trigger: str, marketplace: str, now: str) -> str:
    return {
        "price_drop": f"{marketplace} dropped to {now}",
        "price_increase": f"{marketplace} raised to {now}",
        "out_of_stock": f"{marketplace} is out of stock",
        "back_in_stock": f"{marketplace} is back in stock at {now}",
    }.get(trigger, f"{marketplace} reading needs a check ({now})")


def render_ops_alert(
    *,
    title: str,
    sku: str | None,
    marketplace: str,
    review_url: str,
    trigger: str,
    decision: RepricingDecision,
    status: str,
    proposal: Proposal | None,
    competitor_prev: float | None,
    competitor_now: float | None,
    competitor_in_stock: bool | None,
    floor: float | None,
    competitors: list[CompetitorView] | None = None,
    listing_urls: dict[int, str] | None = None,
) -> tuple[str, str, str]:
    """The operations-team email for one product: what moved, every platform's price, where we stand, what to do."""
    mk = MARKETPLACES.get(marketplace, marketplace)
    now = "out of stock" if competitor_in_stock is False else format_inr(competitor_now)
    our = decision.our_price_inr
    if status == "pending_review" and proposal:
        tag, color = "Approval needed", "#b45309"
        verb = "Lower" if proposal.action == "lower_price" else "Raise"
        action_line = f"{verb} to {format_inr(proposal.to_price_inr)} ({proposal.change_pct:+.1f}%)"
        button = "Review & approve"
    elif status == "auto_approved" and proposal:
        tag, color = "Auto-applied", "#047857"
        verb = "Lowered" if proposal.action == "lower_price" else "Raised"
        action_line = f"{verb} to {format_inr(proposal.to_price_inr)} ({proposal.change_pct:+.1f}%)"
        button = "View in dashboard"
    elif decision.action == "investigate" or trigger == "needs_attention":
        tag, color = "Check needed", "#be123c"
        action_line = "Investigate before changing our price"
        button = "Open in dashboard"
    else:
        tag, color = "FYI", "#57534e"
        action_line = f"Hold at {format_inr(our)}" if our is not None else "No price action (our price not set)"
        button = "Open in dashboard"

    lowest = decision.competitor_price_inr
    gap = None
    if our is not None and lowest is not None:
        diff = our - lowest
        gap = (
            "same as the lowest competitor"
            if abs(diff) < 0.5
            else (f"{format_inr(abs(diff))} {'above' if diff > 0 else 'below'} the lowest competitor")
        )
    movement = _movement(trigger, mk, now)
    subject = f"[{tag}] {action_line.split(' (')[0]} · {movement} · {title[:60]}"
    ctx = dict(
        tag=tag,
        tag_color=color,
        event_label=EVENT_LABELS.get(trigger, trigger),
        title=title,
        sku=sku,
        marketplace=mk,
        competitor_prev=format_inr(competitor_prev) if competitor_prev is not None else None,
        competitor_now=now,
        rows=[
            dict(
                marketplace=MARKETPLACES.get(c.marketplace, c.marketplace),
                price="out of stock" if c.in_stock is False else format_inr(c.price_inr),
                previous=format_inr(c.previous_price_inr) if c.previous_price_inr is not None else None,
                changed=c.change_pct is not None and c.change_pct != 0,
                lowest=c.is_reference,
                suspect=c.suspect,
                url=(listing_urls or {}).get(c.listing_id, ""),
            )
            for c in (competitors or [])
        ],
        our_price=format_inr(our),
        gap=gap,
        floor=format_inr(floor) if floor is not None else None,
        action_line=action_line,
        d=decision,
        notes=decision.data_issues,
        review_url=review_url,
        button=button,
        auto_note=status == "auto_approved",
    )
    html = _env.get_template("ops_alert.html.j2").render(**ctx)
    flags = {True: " (lowest)", False: ""}
    table = "".join(
        f"  {r['marketplace']}: {r['price']}{flags[r['lowest']]}{' (suspect reading)' if r['suspect'] else ''}\n"
        for r in ctx["rows"]
    )
    text = (
        f"[{tag}] {EVENT_LABELS.get(trigger, trigger)}: {title}\n\n"
        f"What changed ({mk}): {ctx['competitor_prev'] + ' -> ' if ctx['competitor_prev'] else ''}{now}\n"
        + (f"Competitors:\n{table}" if table else "")
        + f"Our price: {ctx['our_price']}{f' ({gap})' if gap else ''}\n"
        f"AI recommendation: {action_line}\n\n{decision.reasoning}\n\n"
        + "".join(f"- {n}\n" for n in decision.data_issues)
        + f"\n{button}: {review_url}\n"
    )
    return subject, html, text


def send_email(to: str, subject: str, html: str, text: str) -> None:
    s = get_settings()
    if not (s.smtp_user and s.smtp_app_password):
        raise EmailNotConfigured("SMTP_USER / SMTP_APP_PASSWORD are not set")
    msg = EmailMessage()
    msg["From"] = s.smtp_user
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")
    # certifi's CA bundle: some Python builds (e.g. python.org on macOS) ship without one.
    ctx = ssl.create_default_context(cafile=certifi.where())
    if s.smtp_port == 465:
        smtp = smtplib.SMTP_SSL(s.smtp_host, s.smtp_port, context=ctx, timeout=30)
    else:
        smtp = smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=30)
    with smtp:
        if s.smtp_port != 465:
            smtp.starttls(context=ctx)
        smtp.login(s.smtp_user, s.smtp_app_password)
        smtp.send_message(msg)
    log.info("email_sent", to=to, subject=subject)
