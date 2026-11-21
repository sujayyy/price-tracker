"""Changing our price: the single write path, always with an audit row.

Manual edits, approved proposals and auto-applied proposals all come through `set_our_price`.
Today "applying" means updating our catalogue price in this database; pushing it to a sales
channel (Amazon Seller Central, Flipkart Seller Hub, Shopify…) would be one call added here.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from sqlalchemy.orm import Session

from app.db import repo
from app.db.models import OurPriceChange, Product

Source = Literal["manual", "approved", "auto"]


class PriceRejected(ValueError):
    pass


def check_price(product: Product, price: float, floor: float | None = None) -> None:
    """Hard limits that bind people too: positive, and never below the floor."""
    floor = (
        floor
        if floor is not None
        else (float(product.floor_price_inr) if product.floor_price_inr is not None else None)
    )
    if price <= 0:
        raise PriceRejected("Price must be greater than zero")
    if floor is not None and price < floor:
        raise PriceRejected(f"₹{price:,.2f} is below the floor price ₹{floor:,.2f}")


def set_our_price(
    session: Session,
    product: Product,
    new_price: float,
    *,
    source: Source,
    actor: str,
    proposal_id: int | None = None,
    note: str | None = None,
) -> OurPriceChange | None:
    """Update our price and record who changed it and why. Returns None if nothing changed."""
    check_price(product, new_price)
    new = Decimal(str(round(new_price, 2)))
    old = product.our_price_inr
    if old is not None and old == new:
        return None
    product.our_price_inr = new
    row = repo.add_price_change(
        session,
        product_id=product.id,
        old_price_inr=old,
        new_price_inr=new,
        source=source,
        actor=actor,
        proposal_id=proposal_id,
        note=note,
    )
    if source == "manual":
        repo.supersede_pending(session, product.id, "Our price was changed manually")
    return row
