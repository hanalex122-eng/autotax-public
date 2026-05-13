"""Background-job tracking — context-manager wrapper for periodic loops.

Pattern:
    from autotax.jobs import track_job
    with track_job("email_sync", user_id=u.id, payload={"folder": "INBOX"}):
        ... do the work ...

On enter we write a row with status='running'. On exit we set
status='success' (or 'failed' with the exception text), finished_at,
and duration_ms. Always safe: any failure inside track_job logging
itself is swallowed so the wrapped work never breaks because of
monitoring.
"""

from __future__ import annotations

import json
import logging
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator, Optional

logger = logging.getLogger("autotax.jobs")


def _new_row(job_type: str, user_id: Optional[int], payload: Optional[dict]) -> Optional[int]:
    try:
        from autotax.db import SessionLocal
        from autotax.models import BackgroundJob
    except Exception:
        return None
    db = SessionLocal()
    try:
        payload_json: Optional[str] = None
        if payload:
            try:
                payload_json = json.dumps(payload, default=str, ensure_ascii=False)[:5000]
            except Exception:
                payload_json = None
        row = BackgroundJob(
            job_type=job_type,
            user_id=user_id,
            status="running",
            payload=payload_json,
        )
        db.add(row)
        db.commit()
        return row.id
    except Exception:
        logger.exception("track_job: failed to open row for %s", job_type)
        try:
            db.rollback()
        except Exception:
            pass
        return None
    finally:
        db.close()


def _finish_row(row_id: int, status: str, error: Optional[str], duration_ms: int) -> None:
    try:
        from autotax.db import SessionLocal
        from autotax.models import BackgroundJob
    except Exception:
        return
    db = SessionLocal()
    try:
        row = db.query(BackgroundJob).filter(BackgroundJob.id == row_id).first()
        if row:
            row.status = status
            row.error = error[:5000] if error else None
            row.finished_at = datetime.now(timezone.utc)
            row.duration_ms = duration_ms
            db.commit()
    except Exception:
        logger.exception("track_job: failed to close row %s", row_id)
        try:
            db.rollback()
        except Exception:
            pass
    finally:
        db.close()


@contextmanager
def track_job(
    job_type: str,
    user_id: Optional[int] = None,
    payload: Optional[dict] = None,
) -> Iterator[Any]:
    """Records a background-job lifecycle row.

    Wrapping never raises on its own. If row creation fails we still
    let the work run; the call site behaves identically with or
    without monitoring.
    """
    started = time.monotonic()
    row_id = _new_row(job_type, user_id, payload)
    try:
        yield row_id
    except Exception as exc:
        duration_ms = int((time.monotonic() - started) * 1000)
        if row_id is not None:
            _finish_row(row_id, "failed", repr(exc), duration_ms)
        raise
    else:
        duration_ms = int((time.monotonic() - started) * 1000)
        if row_id is not None:
            _finish_row(row_id, "success", None, duration_ms)
