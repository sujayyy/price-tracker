"""Small operational commands.

python -m app.cli init-db     # alembic upgrade head + LangGraph checkpointer setup
python -m app.cli run-once    # one scheduler cycle from the command line (cron-friendly)
python -m app.cli backfill-images   # fetch a photo for listings that don't have one yet
"""

import argparse
import json
from pathlib import Path

from alembic import command
from alembic.config import Config

from app.core.logging import configure_logging


def init_db() -> None:
    from app.services import ai_bridge

    cfg = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    cfg.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "alembic"))
    command.upgrade(cfg, "head")
    ai_bridge.setup_checkpointer()
    print("Database migrated and checkpointer tables ready.")


def backfill_images() -> None:
    """Fetch each monitored listing that has no photo yet and store only its image.

    No price reading is recorded, so no rule, recommendation or email can fire.
    """
    from app.db import repo
    from app.db.base import SessionLocal
    from app.services.sources import source_for_marketplace
    from app.services.sources.base import ListingRef

    with SessionLocal() as session:
        for listing in repo.active_listings(session):
            if listing.image_url:
                continue
            ref = ListingRef(listing.marketplace, listing.external_id, listing.canonical_url)
            result = source_for_marketplace(listing.marketplace).fetch(ref)
            if result.image_url:
                listing.image_url = result.image_url
                session.commit()
            found = result.image_url or f"no image ({result.error or 'none on the page'})"
            print(f"{listing.marketplace:9} #{listing.id}: {found}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="app.cli")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init-db")
    run = sub.add_parser("run-once")
    run.add_argument("--force", action="store_true")
    sub.add_parser("backfill-images")
    args = parser.parse_args()

    configure_logging()
    if args.cmd == "init-db":
        init_db()
    elif args.cmd == "run-once":
        from app.services.runner import run_once

        s = run_once(force=args.force)
        print(json.dumps(s.__dict__, default=str, indent=2))
    elif args.cmd == "backfill-images":
        backfill_images()


if __name__ == "__main__":
    main()
