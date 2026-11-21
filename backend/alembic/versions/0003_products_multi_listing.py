"""Products with several competitor listings.

`products` now holds our side (SKU, our price, floor, limits, alert rules, schedule); every
`tracked_items` row becomes one competitor listing of a product, on one marketplace. Existing
rows become one product each, keeping their ids (so product N = old item N). Proposals, the
price audit log and decisions become per-product; decisions keep the listing that triggered them.

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-29
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE products (
            id                     BIGSERIAL PRIMARY KEY,
            title                  TEXT NOT NULL,
            our_sku                TEXT,
            our_price_inr          NUMERIC(12,2),
            floor_price_inr        NUMERIC(12,2),
            max_change_pct         NUMERIC(5,2) NOT NULL DEFAULT 10,
            undercut_by_inr        NUMERIC(12,2) NOT NULL DEFAULT 0,
            auto_apply             BOOLEAN NOT NULL DEFAULT false,
            auto_apply_max_pct     NUMERIC(5,2) NOT NULL DEFAULT 3,
            min_change_pct         NUMERIC(5,2),
            alert_on_stock_change  BOOLEAN NOT NULL DEFAULT true,
            check_every_hours      INT NOT NULL DEFAULT 6,
            notify_email           TEXT,
            active                 BOOLEAN NOT NULL DEFAULT true,
            created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
            deleted_at             TIMESTAMPTZ,
            CONSTRAINT ck_products_floor_le_price
                CHECK (floor_price_inr IS NULL OR our_price_inr IS NULL OR floor_price_inr <= our_price_inr)
        );

        INSERT INTO products (id, title, our_sku, our_price_inr, floor_price_inr, max_change_pct, undercut_by_inr,
                              auto_apply, auto_apply_max_pct, min_change_pct, alert_on_stock_change,
                              check_every_hours, notify_email, active, created_at, deleted_at)
        SELECT id, title, our_sku, our_price_inr, floor_price_inr, max_change_pct, undercut_by_inr,
               auto_apply, auto_apply_max_pct, min_change_pct, alert_on_stock_change,
               check_every_hours, notify_email, active, created_at, deleted_at
        FROM tracked_items;
        SELECT setval(pg_get_serial_sequence('products', 'id'), COALESCE((SELECT MAX(id) FROM products), 0) + 1, false);

        ALTER TABLE tracked_items ADD COLUMN product_id BIGINT REFERENCES products(id) ON DELETE CASCADE;
        UPDATE tracked_items SET product_id = id;
        ALTER TABLE tracked_items ALTER COLUMN product_id SET NOT NULL;
        CREATE INDEX ix_tracked_items_product ON tracked_items (product_id);
        ALTER TABLE tracked_items
            DROP CONSTRAINT ck_tracked_items_floor_le_price,
            DROP COLUMN our_sku,
            DROP COLUMN our_price_inr,
            DROP COLUMN floor_price_inr,
            DROP COLUMN max_change_pct,
            DROP COLUMN undercut_by_inr,
            DROP COLUMN auto_apply,
            DROP COLUMN auto_apply_max_pct,
            DROP COLUMN min_change_pct,
            DROP COLUMN alert_on_stock_change,
            DROP COLUMN check_every_hours,
            DROP COLUMN notify_email;

        -- Decisions: per product, still remembering the listing that triggered them.
        ALTER TABLE decisions ADD COLUMN product_id BIGINT REFERENCES products(id) ON DELETE CASCADE;
        UPDATE decisions SET product_id = item_id;
        ALTER TABLE decisions ALTER COLUMN product_id SET NOT NULL;
        CREATE INDEX ix_decisions_product_time ON decisions (product_id, created_at DESC);
        UPDATE decisions
            SET decision = (decision - 'item_id') || jsonb_build_object('product_id', decision->'item_id')
            WHERE decision ? 'action' AND decision ? 'item_id';

        -- Proposals: per product; item_id is now the listing whose change led to it.
        ALTER TABLE reprice_proposals ADD COLUMN product_id BIGINT REFERENCES products(id) ON DELETE CASCADE;
        UPDATE reprice_proposals SET product_id = item_id;
        ALTER TABLE reprice_proposals ALTER COLUMN product_id SET NOT NULL;
        ALTER TABLE reprice_proposals ALTER COLUMN item_id DROP NOT NULL;
        CREATE INDEX ix_proposals_product_time ON reprice_proposals (product_id, created_at DESC);
        -- Paused workflow runs from before this change carry the old state shape; close them.
        UPDATE reprice_proposals
            SET status = 'superseded', resolved_at = now(), resolved_by = 'system',
                resolution_note = 'Closed by the multi-platform upgrade'
            WHERE status = 'pending';

        -- Our price log: per product.
        ALTER TABLE our_price_changes ADD COLUMN product_id BIGINT REFERENCES products(id) ON DELETE CASCADE;
        UPDATE our_price_changes SET product_id = item_id;
        ALTER TABLE our_price_changes ALTER COLUMN product_id SET NOT NULL;
        DROP INDEX ix_our_price_changes_item_time;
        ALTER TABLE our_price_changes DROP COLUMN item_id;
        CREATE INDEX ix_our_price_changes_product_time ON our_price_changes (product_id, changed_at DESC);
        """
    )


def downgrade() -> None:
    # Folds each product back onto its lowest-id listing; extra listings keep their own history
    # but lose our price settings.
    op.execute(
        """
        ALTER TABLE our_price_changes ADD COLUMN item_id BIGINT REFERENCES tracked_items(id) ON DELETE CASCADE;
        UPDATE our_price_changes c
            SET item_id = (SELECT MIN(t.id) FROM tracked_items t WHERE t.product_id = c.product_id);
        DELETE FROM our_price_changes WHERE item_id IS NULL;
        ALTER TABLE our_price_changes ALTER COLUMN item_id SET NOT NULL, DROP COLUMN product_id;
        CREATE INDEX ix_our_price_changes_item_time ON our_price_changes (item_id, changed_at DESC);

        UPDATE reprice_proposals p SET item_id = COALESCE(item_id,
            (SELECT MIN(t.id) FROM tracked_items t WHERE t.product_id = p.product_id));
        DELETE FROM reprice_proposals WHERE item_id IS NULL;
        ALTER TABLE reprice_proposals ALTER COLUMN item_id SET NOT NULL, DROP COLUMN product_id;

        UPDATE decisions
            SET decision = (decision - 'product_id') || jsonb_build_object('item_id', decision->'product_id')
            WHERE decision ? 'product_id';
        ALTER TABLE decisions DROP COLUMN product_id;

        ALTER TABLE tracked_items
            ADD COLUMN our_sku TEXT,
            ADD COLUMN our_price_inr NUMERIC(12,2),
            ADD COLUMN floor_price_inr NUMERIC(12,2),
            ADD COLUMN max_change_pct NUMERIC(5,2) NOT NULL DEFAULT 10,
            ADD COLUMN undercut_by_inr NUMERIC(12,2) NOT NULL DEFAULT 0,
            ADD COLUMN auto_apply BOOLEAN NOT NULL DEFAULT false,
            ADD COLUMN auto_apply_max_pct NUMERIC(5,2) NOT NULL DEFAULT 3,
            ADD COLUMN min_change_pct NUMERIC(5,2),
            ADD COLUMN alert_on_stock_change BOOLEAN NOT NULL DEFAULT true,
            ADD COLUMN check_every_hours INT NOT NULL DEFAULT 6,
            ADD COLUMN notify_email TEXT;
        UPDATE tracked_items t SET
            our_sku = p.our_sku, our_price_inr = p.our_price_inr, floor_price_inr = p.floor_price_inr,
            max_change_pct = p.max_change_pct, undercut_by_inr = p.undercut_by_inr, auto_apply = p.auto_apply,
            auto_apply_max_pct = p.auto_apply_max_pct, min_change_pct = p.min_change_pct,
            alert_on_stock_change = p.alert_on_stock_change, check_every_hours = p.check_every_hours,
            notify_email = p.notify_email
        FROM products p
        WHERE p.id = t.product_id AND t.id = (SELECT MIN(id) FROM tracked_items WHERE product_id = p.id);
        ALTER TABLE tracked_items ADD CONSTRAINT ck_tracked_items_floor_le_price
            CHECK (floor_price_inr IS NULL OR our_price_inr IS NULL OR floor_price_inr <= our_price_inr);
        ALTER TABLE tracked_items DROP COLUMN product_id;
        DROP TABLE products;
        """
    )
