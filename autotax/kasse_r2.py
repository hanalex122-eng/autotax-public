"""Kasa MVP (Sprint 2) — original document storage in Cloudflare R2.

Stores uploaded receipt/Z-Report images & PDFs for auditability, support,
dispute handling and the learning system. Reuses the same R2 credentials as
backups (R2_ACCOUNT_ID/ACCESS_KEY_ID/SECRET_ACCESS_KEY). Falls back to local
disk (storage.save_file) when R2 is not configured — never blocks an upload.

Read-light: callers dedup via KasseDocument(user_id, sha256) before storing.
"""
from __future__ import annotations

import hashlib
import logging
import os
from datetime import date

from autotax import storage

logger = logging.getLogger("autotax.kasse")

_ACCOUNT_ID = (os.getenv("R2_ACCOUNT_ID") or "").strip()
_ACCESS_KEY = (os.getenv("R2_ACCESS_KEY_ID") or "").strip()
_SECRET_KEY = (os.getenv("R2_SECRET_ACCESS_KEY") or "").strip()
_BUCKET = (os.getenv("R2_KASSE_BUCKET") or os.getenv("R2_BUCKET") or "autotax-backups-de").strip()

_EXT = {"image/jpeg": "jpg", "image/jpg": "jpg", "image/png": "png", "application/pdf": "pdf"}


def is_configured() -> bool:
    if not (_ACCOUNT_ID and _ACCESS_KEY and _SECRET_KEY and _BUCKET):
        return False
    try:
        import boto3  # noqa: F401
        return True
    except ImportError:
        return False


def _client():
    import boto3  # lazy
    return boto3.client(
        "s3",
        endpoint_url=f"https://{_ACCOUNT_ID}.r2.cloudflarestorage.com",
        aws_access_key_id=_ACCESS_KEY,
        aws_secret_access_key=_SECRET_KEY,
        region_name="auto",
    )


def sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _key(user_id: int, digest: str, content_type: str) -> str:
    ext = _EXT.get((content_type or "").lower(), "bin")
    ym = date.today().strftime("%Y%m")
    return f"kasse/{user_id}/{ym}/{digest}.{ext}"


def put_image(user_id: int, content: bytes, content_type: str = "image/jpeg") -> dict:
    """Store original document. Returns {storage, key, sha256}.

    R2 if configured, else local disk fallback (key prefixed 'local:').
    Idempotent by content hash (same bytes → same key).
    """
    digest = sha256(content)
    if is_configured():
        key = _key(user_id, digest, content_type)
        try:
            _client().put_object(Bucket=_BUCKET, Key=key, Body=content, ContentType=content_type)
            return {"storage": "r2", "key": key, "sha256": digest}
        except Exception:
            logger.exception("kasse_r2: R2 put failed, falling back to local")
    # Local fallback
    rel = storage.save_file(user_id, content, f"{digest}.{_EXT.get((content_type or '').lower(), 'bin')}")
    return {"storage": "local", "key": f"local:{rel}", "sha256": digest}


def get_image(key: str) -> bytes:
    if key.startswith("local:"):
        return storage.read_file(key[len("local:"):])
    obj = _client().get_object(Bucket=_BUCKET, Key=key)
    return obj["Body"].read()


def presign(key: str, ttl: int = 300) -> str | None:
    """Short-lived GET URL for viewing (support/dispute). None for local keys."""
    if key.startswith("local:") or not is_configured():
        return None
    try:
        return _client().generate_presigned_url(
            "get_object", Params={"Bucket": _BUCKET, "Key": key}, ExpiresIn=ttl
        )
    except Exception:
        logger.exception("kasse_r2: presign failed")
        return None
