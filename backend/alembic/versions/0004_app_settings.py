"""App-wide settings editable from the dashboard (e.g. the ops team's alert emails).

A value here overrides the matching environment default (OPS_ALERT_EMAILS); deleting the row
falls back to the environment again.

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-30
"""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE app_settings (
            key         TEXT PRIMARY KEY,
            value       JSONB NOT NULL,
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_by  TEXT
        );
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE app_settings;")
