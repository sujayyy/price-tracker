"""Competitor listings remember their product photo (display only; refreshed on each fetch).

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-30
"""

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE tracked_items ADD COLUMN image_url TEXT;")


def downgrade() -> None:
    op.execute("ALTER TABLE tracked_items DROP COLUMN image_url;")
