"""Ops repricing: our price and its limits on each tracked listing, proposals, and a price audit log.

A tracked item is now a competitor listing mapped to one of our products. Consumer-deal settings
(target price, per-item email cooldown) are replaced by our price, floor, max move and undercut;
`min_drop_pct` becomes `min_change_pct` (a move in either direction, vs the previous reading).

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-29
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE tracked_items RENAME COLUMN min_drop_pct TO min_change_pct;
        ALTER TABLE tracked_items RENAME COLUMN alert_on_back_in_stock TO alert_on_stock_change;
        -- The old value was a drop vs the 30-day median; it has no meaning as a change threshold.
        UPDATE tracked_items SET min_change_pct = NULL;
        ALTER TABLE tracked_items DROP COLUMN target_price_inr;
        ALTER TABLE tracked_items DROP COLUMN cooldown_hours;
        ALTER TABLE tracked_items ALTER COLUMN notify_email DROP NOT NULL;
        ALTER TABLE tracked_items
            ADD COLUMN our_sku             TEXT,
            ADD COLUMN our_price_inr       NUMERIC(12,2),
            ADD COLUMN floor_price_inr     NUMERIC(12,2),
            ADD COLUMN max_change_pct      NUMERIC(5,2) NOT NULL DEFAULT 10,
            ADD COLUMN undercut_by_inr     NUMERIC(12,2) NOT NULL DEFAULT 0,
            ADD COLUMN auto_apply          BOOLEAN NOT NULL DEFAULT false,
            ADD COLUMN auto_apply_max_pct  NUMERIC(5,2) NOT NULL DEFAULT 3,
            ADD CONSTRAINT ck_tracked_items_floor_le_price
                CHECK (floor_price_inr IS NULL OR our_price_inr IS NULL OR floor_price_inr <= our_price_inr);

        CREATE TABLE reprice_proposals (
            id                   BIGSERIAL PRIMARY KEY,
            item_id              BIGINT NOT NULL REFERENCES tracked_items(id) ON DELETE CASCADE,
            decision_id          BIGINT REFERENCES decisions(id),
            thread_id            TEXT NOT NULL,
            status               TEXT NOT NULL,
            action               TEXT NOT NULL,
            competitor_price_inr NUMERIC(12,2),
            from_price_inr       NUMERIC(12,2) NOT NULL,
            to_price_inr         NUMERIC(12,2) NOT NULL,
            final_price_inr      NUMERIC(12,2),
            change_pct           NUMERIC(7,2) NOT NULL,
            limited_by           TEXT,
            created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
            resolved_at          TIMESTAMPTZ,
            resolved_by          TEXT,
            resolution_note      TEXT,
            CONSTRAINT ck_reprice_proposals_status CHECK
                (status IN ('pending','approved','rejected','auto_applied','superseded','stale','failed')),
            CONSTRAINT ck_reprice_proposals_action CHECK (action IN ('lower_price','raise_price'))
        );
        CREATE INDEX ix_proposals_item_time ON reprice_proposals (item_id, created_at DESC);
        CREATE INDEX ix_proposals_pending ON reprice_proposals (created_at DESC) WHERE status = 'pending';

        CREATE TABLE our_price_changes (
            id             BIGSERIAL PRIMARY KEY,
            item_id        BIGINT NOT NULL REFERENCES tracked_items(id) ON DELETE CASCADE,
            old_price_inr  NUMERIC(12,2),
            new_price_inr  NUMERIC(12,2) NOT NULL,
            changed_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
            source         TEXT NOT NULL,
            actor          TEXT NOT NULL,
            proposal_id    BIGINT REFERENCES reprice_proposals(id),
            note           TEXT,
            CONSTRAINT ck_our_price_changes_source CHECK (source IN ('manual','approved','auto'))
        );
        CREATE INDEX ix_our_price_changes_item_time ON our_price_changes (item_id, changed_at DESC);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE our_price_changes;
        DROP TABLE reprice_proposals;
        ALTER TABLE tracked_items
            DROP CONSTRAINT ck_tracked_items_floor_le_price,
            DROP COLUMN our_sku,
            DROP COLUMN our_price_inr,
            DROP COLUMN floor_price_inr,
            DROP COLUMN max_change_pct,
            DROP COLUMN undercut_by_inr,
            DROP COLUMN auto_apply,
            DROP COLUMN auto_apply_max_pct;
        UPDATE tracked_items SET notify_email = '' WHERE notify_email IS NULL;
        ALTER TABLE tracked_items ALTER COLUMN notify_email SET NOT NULL;
        ALTER TABLE tracked_items ADD COLUMN cooldown_hours INT NOT NULL DEFAULT 24;
        ALTER TABLE tracked_items ADD COLUMN target_price_inr NUMERIC(12,2);
        ALTER TABLE tracked_items RENAME COLUMN alert_on_stock_change TO alert_on_back_in_stock;
        ALTER TABLE tracked_items RENAME COLUMN min_change_pct TO min_drop_pct;
        """
    )
