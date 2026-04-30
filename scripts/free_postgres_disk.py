"""Emergency cleanup: NULL out invoices.file_data one row at a time to free
Postgres disk when it is near 100% full. Runs small autocommitted UPDATEs
so MVCC overhead is tiny, and periodically calls VACUUM to reclaim space
from the TOAST table.

Use only when the DB is disk-full and migrate_blobs_to_disk cannot commit.
Original receipt images/PDFs for rows whose file_data is cleared WILL BE
LOST — OCR text, totals, vendor etc. are preserved.

Usage:
    python -m scripts.free_postgres_disk
"""
import logging
import sys

from sqlalchemy import text

from autotax.db import engine

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("free_disk")

VACUUM_EVERY = 25  # rows


def main() -> int:
    # Autocommit — each UPDATE commits immediately, minimising MVCC bloat
    conn = engine.connect().execution_options(isolation_level="AUTOCOMMIT")

    # Grab ids where there's still a BLOB to clear. Descending so biggest/newest first.
    ids = [r[0] for r in conn.execute(
        text("SELECT id FROM invoices WHERE file_data IS NOT NULL ORDER BY id DESC")
    )]
    total = len(ids)
    log.info("Rows with BLOB still set: %d", total)
    if total == 0:
        log.info("Nothing to do.")
        return 0

    cleared = 0
    failed = 0
    for i, inv_id in enumerate(ids, 1):
        try:
            conn.execute(
                text("UPDATE invoices SET file_data = NULL WHERE id = :id"),
                {"id": inv_id},
            )
            cleared += 1
        except Exception as e:
            failed += 1
            log.warning("Row %s failed: %s", inv_id, e)
            # If disk is still full, pause and try a vacuum
            try:
                conn.execute(text("VACUUM (VERBOSE) invoices"))
            except Exception:
                pass

        if i % VACUUM_EVERY == 0:
            log.info("Progress: %d/%d cleared (%d failed) — vacuuming", i, total, failed)
            try:
                conn.execute(text("VACUUM invoices"))
            except Exception as e:
                log.warning("Vacuum failed: %s", e)

    log.info("Final vacuum (full) on invoices — may take a while")
    try:
        conn.execute(text("VACUUM FULL invoices"))
    except Exception as e:
        log.warning("Final VACUUM FULL failed (ok if disk still tight): %s", e)

    log.info("Done. cleared=%d failed=%d total=%d", cleared, failed, total)
    conn.close()
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
