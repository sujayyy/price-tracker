from typing import Annotated

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db import repo
from app.db.base import get_session
from app.db.models import Product, TrackedItem

SessionDep = Annotated[Session, Depends(get_session)]


def get_product_or_404(product_id: int, session: SessionDep) -> Product:
    product = repo.get_product(session, product_id)
    if product is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Product not found")
    return product


def get_listing_or_404(listing_id: int, session: SessionDep) -> TrackedItem:
    listing = repo.get_listing(session, listing_id)
    if listing is None or repo.get_product(session, listing.product_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Listing not found")
    return listing


ProductDep = Annotated[Product, Depends(get_product_or_404)]
ListingDep = Annotated[TrackedItem, Depends(get_listing_or_404)]
