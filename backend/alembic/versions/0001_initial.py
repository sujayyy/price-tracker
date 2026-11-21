"""Initial schema (spec §5) + tracked_items.deleted_at for soft delete.

Revision ID: 0001
Revises:
Create Date: 2026-09-25
"""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE tracked_items (
            id                      BIGSERIAL PRIMARY KEY,
            marketplace             TEXT NOT NULL,
            external_id             TEXT NOT NULL,
            canonical_url           TEXT NOT NULL,
            title                   TEXT NOT NULL,
            variant                 TEXT,
            target_price_inr        NUMERIC(12,2),
            min_drop_pct            NUMERIC(5,2),
            alert_on_back_in_stock  BOOLEAN NOT NULL DEFAULT true,
            cooldown_hours          INT NOT NULL DEFAULT 24,
            check_every_hours       INT NOT NULL DEFAULT 6,
            notify_email            TEXT NOT NULL,
            active                  BOOLEAN NOT NULL DEFAULT true,
            created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
            deleted_at              TIMESTAMPTZ,
            CONSTRAINT ck_tracked_items_marketplace CHECK (marketplace IN ('amazon_in','flipkart')),
            CONSTRAINT uq_tracked_items_marketplace_external_id UNIQUE (marketplace, external_id)
        );

        CREATE TABLE price_observations (
            id           BIGSERIAL PRIMARY KEY,
            item_id      BIGINT NOT NULL REFERENCES tracked_items(id) ON DELETE CASCADE,
            fetched_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
            price_inr    NUMERIC(12,2),
            mrp_inr      NUMERIC(12,2),
            in_stock     BOOLEAN,
            seller       TEXT,
            source       TEXT NOT NULL,
            ok           BOOLEAN NOT NULL,
            error        TEXT
        );
        CREATE INDEX ix_price_obs_item_time ON price_observations (item_id, fetched_at DESC);

        CREATE TABLE decisions (
            id           BIGSERIAL PRIMARY KEY,
            item_id      BIGINT NOT NULL REFERENCES tracked_items(id) ON DELETE CASCADE,
            trigger_type TEXT NOT NULL,
            decision     JSONB NOT NULL,
            created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX ix_decisions_item_time ON decisions (item_id, created_at DESC);

        CREATE TABLE alerts_sent (
            id           BIGSERIAL PRIMARY KEY,
            item_id      BIGINT NOT NULL REFERENCES tracked_items(id) ON DELETE CASCADE,
            decision_id  BIGINT REFERENCES decisions(id),
            sent_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            alert_type   TEXT NOT NULL
        );
        CREATE INDEX ix_alerts_item_time ON alerts_sent (item_id, sent_at DESC);

        CREATE TABLE runs (
            id                BIGSERIAL PRIMARY KEY,
            started_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
            finished_at       TIMESTAMPTZ,
            items_checked     INT,
            agent_invocations INT,
            errors            INT,
            notes             TEXT
        );
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP TABLE runs; DROP TABLE alerts_sent; DROP TABLE decisions; "
        "DROP TABLE price_observations; DROP TABLE tracked_items;"
    )
