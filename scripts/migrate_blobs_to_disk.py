"""One-shot migration: move invoices.file_data BLOBs to disk via autotax.storage.

Idempotent — only touches rows where file_path IS NULL and file_data IS NOT NULL.
After running, file_data is NOT cleared automatically; do that in a follow-up
migration once you have verified everything still serves correctly.

Usage:
    UPLOADS_DIR=./data/uploads python -m scripts.migrate_blobs_to_disk
    UPLOADS_DIR=./data/uploads python -m scripts.migrate_blobs_to_disk --clear-blobs
"""
import argparse
import logging
import sys

from autotax import storage
from autotax.db import SessionLocal
from autotax.models import Invoice

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("migrate")

BATCH = 100


def migrate(clear_blobs: bool = False) -> int:
    db = SessionLocal()
    moved = 0
    failed = 0
    try:
        # Process in batches to keep memory bounded.
        while True:
            rows = (
                db.query(Invoice)
                .filter(Invoice.file_path.is_(None), Invoice.file_data.isnot(None))
                .limit(BATCH)
                .all()
            )
            if not rows:
                break

            for inv in rows:
                try:
                    rel = storage.save_file(inv.user_id, bytes(inv.file_data), inv.filename)
                    inv.file_path = rel
                    inv.file_size = len(inv.file_data)
                    if clear_blobs:
                        inv.file_data = None
                    moved += 1
                except Exception:
                    log.exception("Invoice %s failed", inv.id)
                    failed += 1

            db.commit()
            log.info("Batch committed — moved=%d failed=%d", moved, failed)

        log.info("Done. moved=%d failed=%d clear_blobs=%s", moved, failed, clear_blobs)
        return 0 if failed == 0 else 1
    finally:
        db.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument(
        "--clear-blobs",
        action="store_true",
        help="Also NULL out invoices.file_data after a successful disk write",
    )
    args = p.parse_args()
    sys.exit(migrate(clear_blobs=args.clear_blobs))
