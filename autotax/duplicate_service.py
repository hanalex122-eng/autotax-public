"""Invoice duplicate detection.

Hard duplicate: same user uploaded exact same file bytes (md5 match).
Soft duplicate: same user has another invoice with same vendor + amount + date.
"""
import hashlib
from datetime import date as date_type
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from autotax.models import Invoice


def generate_file_hash(file_bytes: bytes) -> str:
    """MD5 hex digest of raw file bytes."""
    return hashlib.md5(file_bytes).hexdigest()


def find_hard_duplicate(
    db: Session,
    user_id: int,
    file_hash: str,
) -> Optional[Invoice]:
    """Return existing (non-deleted) invoice with same user + file_hash, else None."""
    if not file_hash:
        return None
    return (
        db.query(Invoice)
        .filter(
            Invoice.user_id == user_id,
            Invoice.file_hash == file_hash,
            (Invoice.is_deleted == False) | (Invoice.is_deleted == None),  # noqa: E711,E712
        )
        .first()
    )


def check_soft_duplicate(
    db: Session,
    user_id: int,
    vendor: Optional[str],
    amount: Optional[float],
    date,
) -> bool:
    """True if another non-deleted invoice for this user matches
    vendor (case-insensitive) + amount + date."""
    if not vendor or amount is None or not date:
        return False

    date_str = date.isoformat() if isinstance(date, date_type) else str(date)

    exists = (
        db.query(Invoice.id)
        .filter(
            Invoice.user_id == user_id,
            func.lower(func.trim(Invoice.vendor)) == vendor.strip().lower(),
            Invoice.total_amount == amount,
            Invoice.date == date_str,
            (Invoice.is_deleted == False) | (Invoice.is_deleted == None),  # noqa: E711,E712
        )
        .first()
    )
    return exists is not None
