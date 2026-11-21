"""Approving or rejecting a proposed price change.

The proposal row is locked, the paused LangGraph run is resumed with the reviewer's answer, and
the workflow's verdict (re-checked against fresh data) decides what is written.
"""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy.orm import Session, sessionmaker

from app.ai.schemas import RepricingOutcome, ReviewAnswer
from app.db import repo
from app.db.base import SessionLocal
from app.db.models import RepriceProposal
from app.services import ai_bridge, pricing

Resumer = Callable[[str, ReviewAnswer], RepricingOutcome]

_STATUS = {"approved": "approved", "rejected": "rejected", "stale": "stale"}


class ProposalNotFound(LookupError):
    pass


class ProposalClosed(RuntimeError):
    pass


def review(
    proposal_id: int,
    answer: ReviewAnswer,
    *,
    session_factory: sessionmaker[Session] = SessionLocal,
    resume: Resumer | None = None,
) -> RepriceProposal:
    resume = resume or ai_bridge.resume_reprice
    with session_factory() as s:
        proposal = repo.get_proposal(s, proposal_id, for_update=True)  # a double click waits here
        if proposal is None:
            raise ProposalNotFound(f"Proposal {proposal_id} not found")
        if proposal.status != "pending":
            raise ProposalClosed(f"Proposal {proposal_id} is already {proposal.status}")
        product = repo.get_product(s, proposal.product_id)
        if product is None:
            raise ProposalClosed(f"Product {proposal.product_id} is no longer monitored")
        if answer.approved and answer.price_inr is not None:
            pricing.check_price(product, answer.price_inr)  # fail fast, before the run is consumed

        outcome = resume(proposal.thread_id, answer)
        proposal.status = _STATUS.get(outcome.status, "failed")
        proposal.resolved_at = repo.utcnow()
        proposal.resolved_by = answer.by
        proposal.resolution_note = answer.note or outcome.reason
        if outcome.status == "approved" and outcome.final_price_inr is not None:
            pricing.set_our_price(
                s,
                product,
                outcome.final_price_inr,
                source="approved",
                actor=answer.by,
                proposal_id=proposal.id,
                note=answer.note,
            )
            proposal.final_price_inr = outcome.final_price_inr
        s.commit()
        return proposal
