"""Weekly PostgreSQL backup -> Cloudflare R2.

Akis: pg_dump (custom format) -> gzip -> R2 upload -> retention prune
-> Telegram bildirim.

ENV:
  R2_BACKUP_ENABLED=1                kapalisa loop hic baslamaz
  R2_ACCOUNT_ID                      Cloudflare hesap ID (dashboard)
  R2_ACCESS_KEY_ID                   R2 API token access key
  R2_SECRET_ACCESS_KEY               R2 API token secret
  R2_BUCKET=autotax-backups          (default)
  BACKUP_RETENTION_WEEKS=4           (default) eski backup'lar silinir
  BACKUP_INTERVAL_HOURS=168          (default 1 hafta)

Telegram bildirim icin reminders.py'daki TELEGRAM_TOKEN+CHAT_ID kullanilir
(tekrar env tanimlamadan, mevcut altyapi).

Manuel tetikleme: POST /admin/backup/run (admin middleware koruyor).
"""
from __future__ import annotations

import asyncio
import gzip
import logging
import os
import shutil
import subprocess
import tempfile
import time
from datetime import datetime, timezone

logger = logging.getLogger("autotax.backup")

# ----------------------------------------------------------------------
# Config (env)
# ----------------------------------------------------------------------

_ENABLED = (os.getenv("R2_BACKUP_ENABLED", "0").strip() == "1")
_ACCOUNT_ID = (os.getenv("R2_ACCOUNT_ID") or "").strip()
_ACCESS_KEY = (os.getenv("R2_ACCESS_KEY_ID") or "").strip()
_SECRET_KEY = (os.getenv("R2_SECRET_ACCESS_KEY") or "").strip()
_BUCKET = (os.getenv("R2_BUCKET") or "autotax-backups").strip()
_DATABASE_URL = (os.getenv("DATABASE_URL") or "").strip()
_RETENTION_WEEKS = max(1, int(os.getenv("BACKUP_RETENTION_WEEKS", "4") or "4"))
_INTERVAL_HOURS = max(1, int(os.getenv("BACKUP_INTERVAL_HOURS", "168") or "168"))
_PG_DUMP_TIMEOUT_SEC = int(os.getenv("BACKUP_PG_DUMP_TIMEOUT", "1200") or "1200")  # 20 min

_INITIAL_DELAY_SEC = 5 * 60  # startup'tan 5 dk sonra ilk tick (sistemin stabilize olmasi icin)


def is_configured() -> bool:
    """True if all required env vars are set AND feature enabled."""
    return bool(
        _ENABLED
        and _ACCOUNT_ID
        and _ACCESS_KEY
        and _SECRET_KEY
        and _DATABASE_URL
    )


def config_summary() -> dict:
    """Diagnostic output for /health-like endpoints. No secrets returned."""
    return {
        "enabled": _ENABLED,
        "account_id_set": bool(_ACCOUNT_ID),
        "access_key_set": bool(_ACCESS_KEY),
        "secret_key_set": bool(_SECRET_KEY),
        "bucket": _BUCKET,
        "database_url_set": bool(_DATABASE_URL),
        "retention_weeks": _RETENTION_WEEKS,
        "interval_hours": _INTERVAL_HOURS,
        "pg_dump_available": shutil.which("pg_dump") is not None,
    }


# ----------------------------------------------------------------------
# pg_dump runner
# ----------------------------------------------------------------------

def _pg_dump_to_file(dest_path: str) -> int:
    """Run pg_dump --format=custom. Returns dump file size in bytes.
    Raises RuntimeError on non-zero exit."""
    if not shutil.which("pg_dump"):
        raise RuntimeError("pg_dump binary not found in PATH")

    cmd = [
        "pg_dump",
        "--no-owner",
        "--no-acl",
        "--format=custom",
        "--compress=0",  # gzip'i biz sonradan yapacagiz, custom format compress'i atlayalim
        "-f", dest_path,
        _DATABASE_URL,
    ]
    logger.info("Backup: running pg_dump (timeout=%ds)", _PG_DUMP_TIMEOUT_SEC)
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=_PG_DUMP_TIMEOUT_SEC,
    )
    if proc.returncode != 0:
        # stderr genelde sifre/host icermez (DATABASE_URL arg olarak gecti, log'a yansimaz)
        stderr_safe = (proc.stderr or "")[:500]
        raise RuntimeError(f"pg_dump exited {proc.returncode}: {stderr_safe}")
    size = os.path.getsize(dest_path)
    if size < 1024:  # 1 KB altinda anlamsiz, bos dump
        raise RuntimeError(f"pg_dump produced suspiciously small file: {size} bytes")
    return size


# ----------------------------------------------------------------------
# Gzip
# ----------------------------------------------------------------------

def _gzip_file(src_path: str, dst_path: str) -> int:
    """Gzip-compress src into dst. Returns compressed size."""
    with open(src_path, "rb") as fin, gzip.open(dst_path, "wb", compresslevel=6) as fout:
        while True:
            chunk = fin.read(64 * 1024)
            if not chunk:
                break
            fout.write(chunk)
    return os.path.getsize(dst_path)


# ----------------------------------------------------------------------
# R2 client (lazy import boto3 — opsiyonel dependency)
# ----------------------------------------------------------------------

def _r2_client():
    """Build a boto3 S3-compatible client for R2."""
    try:
        import boto3  # type: ignore
    except ImportError:
        raise RuntimeError("boto3 not installed (pip install boto3)")
    endpoint = f"https://{_ACCOUNT_ID}.r2.cloudflarestorage.com"
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=_ACCESS_KEY,
        aws_secret_access_key=_SECRET_KEY,
        region_name="auto",
    )


def _upload_to_r2(local_path: str, key: str) -> None:
    """Upload file to R2 bucket under the given key."""
    s3 = _r2_client()
    s3.upload_file(local_path, _BUCKET, key)


def _prune_old_backups() -> int:
    """Delete backups older than RETENTION_WEEKS. Returns count deleted."""
    s3 = _r2_client()
    cutoff_ts = time.time() - (_RETENTION_WEEKS * 7 * 24 * 3600)
    deleted = 0
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=_BUCKET):
        for obj in page.get("Contents", []) or []:
            if obj["LastModified"].timestamp() < cutoff_ts:
                try:
                    s3.delete_object(Bucket=_BUCKET, Key=obj["Key"])
                    deleted += 1
                except Exception:
                    logger.exception("Prune: failed to delete %s", obj["Key"])
    return deleted


# ----------------------------------------------------------------------
# Telegram notification (re-use reminders.py env vars)
# ----------------------------------------------------------------------

def _notify(message: str) -> None:
    """Send Telegram message. Silent on missing config / errors."""
    try:
        token = (os.getenv("TELEGRAM_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
        chat_id = (os.getenv("TELEGRAM_CHAT_ID") or "").strip()
        if not (token and chat_id):
            return
        import httpx
        with httpx.Client(timeout=10.0) as client:
            client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": message, "parse_mode": "Markdown", "disable_web_page_preview": True},
            )
    except Exception:
        logger.exception("Backup: Telegram notify failed (non-fatal)")


# ----------------------------------------------------------------------
# Public API
# ----------------------------------------------------------------------

def run_backup_once() -> dict:
    """Take one backup end-to-end. Returns status dict.

    Result keys (always):
      ok: bool
      filename: str (R2 key) — only on success
      raw_size_mb / gz_size_mb: float
      pruned: int — eski backup sayisi (silinmis)
      error: str — only on failure
    """
    if not is_configured():
        return {"ok": False, "error": "R2 backup not configured (check env vars)"}

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")
    filename = f"autotax_db_{ts}.dump.gz"

    raw_path = None
    gz_path = None
    try:
        # Temp dosya isimlerini olustur (subprocess icin disk yolu lazim)
        with tempfile.NamedTemporaryFile(suffix=".dump", delete=False) as f:
            raw_path = f.name
        gz_path = raw_path + ".gz"

        # 1. pg_dump
        t0 = time.time()
        raw_size = _pg_dump_to_file(raw_path)
        t_dump = time.time() - t0
        logger.info("Backup: pg_dump done — %.1f MB in %.1fs", raw_size / 1024 / 1024, t_dump)

        # 2. gzip
        t0 = time.time()
        gz_size = _gzip_file(raw_path, gz_path)
        t_gzip = time.time() - t0
        compression_pct = 100 * (1 - gz_size / raw_size) if raw_size else 0
        logger.info("Backup: gzip done — %.1f MB (%.0f%% compression) in %.1fs",
                    gz_size / 1024 / 1024, compression_pct, t_gzip)

        # 3. R2 upload
        t0 = time.time()
        _upload_to_r2(gz_path, filename)
        t_upload = time.time() - t0
        logger.info("Backup: R2 upload done — %s in %.1fs", filename, t_upload)

        # 4. Prune old
        pruned = _prune_old_backups()
        logger.info("Backup: pruned %d old backups (retention=%d weeks)", pruned, _RETENTION_WEEKS)

        # 5. Telegram notify
        _notify(
            f"✅ *AutoTax DB Backup OK*\n"
            f"`{filename}`\n"
            f"Size: {gz_size / 1024 / 1024:.1f} MB (gz)\n"
            f"Compression: {compression_pct:.0f}%\n"
            f"Pruned: {pruned} old\n"
            f"Total time: {(t_dump + t_gzip + t_upload):.0f}s"
        )

        return {
            "ok": True,
            "filename": filename,
            "raw_size_mb": round(raw_size / 1024 / 1024, 2),
            "gz_size_mb": round(gz_size / 1024 / 1024, 2),
            "compression_pct": round(compression_pct, 1),
            "pruned": pruned,
            "duration_sec": round(t_dump + t_gzip + t_upload, 1),
        }
    except Exception as e:
        err_msg = str(e)[:300]
        logger.exception("Backup: FAILED")
        _notify(f"❌ *AutoTax DB Backup FAILED*\n`{err_msg}`")
        return {"ok": False, "error": err_msg}
    finally:
        for p in (raw_path, gz_path):
            if p:
                try:
                    os.unlink(p)
                except FileNotFoundError:
                    pass
                except Exception:
                    logger.warning("Backup: temp cleanup failed for %s", p)


# ----------------------------------------------------------------------
# Background loop (haftalik)
# ----------------------------------------------------------------------

async def backup_loop():
    """Weekly backup loop. Skips if not configured."""
    if not is_configured():
        logger.info("Backup loop: not configured (R2_BACKUP_ENABLED!=1 or env eksik), skipping")
        return

    interval_sec = _INTERVAL_HOURS * 3600
    logger.info(
        "Backup loop scheduled — interval=%dh, retention=%dw, bucket=%s",
        _INTERVAL_HOURS, _RETENTION_WEEKS, _BUCKET,
    )

    # Stabilize edilmesi icin baslangic gecikmesi
    await asyncio.sleep(_INITIAL_DELAY_SEC)

    while True:
        try:
            # Sync function — event loop'u bloklamamak icin threadpool'e at
            result = await asyncio.to_thread(run_backup_once)
            if result.get("ok"):
                logger.info(
                    "Weekly backup OK: %s (%.1f MB gz, pruned %d)",
                    result.get("filename"), result.get("gz_size_mb", 0), result.get("pruned", 0),
                )
            else:
                logger.warning("Weekly backup FAILED: %s", result.get("error"))
        except Exception:
            logger.exception("Backup loop iteration crashed")
        await asyncio.sleep(interval_sec)
