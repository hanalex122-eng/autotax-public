"""IMAP inbox sync: fetch UNSEEN invoices (PDF/XML) and run them through
the existing processing pipeline. Credentials are stored in the DB
encrypted with Fernet (EMAIL_CREDS_KEY env var)."""
from __future__ import annotations

import asyncio
import email
import imaplib
import io
import logging
import os
import ssl
from datetime import datetime, timezone
from email.header import decode_header
from typing import Optional

logger = logging.getLogger(__name__)

PROVIDERS: dict[str, tuple[str, int]] = {
    "gmail":   ("imap.gmail.com", 993),
    "outlook": ("outlook.office365.com", 993),
}

SUBJECT_KEYWORDS = ("rechnung", "invoice", "beleg", "faktura", "facture", "quittung")

IMAP_TIMEOUT_SEC = 30
MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024  # 10 MB per attachment

# --- Auto-sync loop configuration ---
AUTO_SYNC_INTERVAL_SEC = int(os.getenv("EMAIL_AUTO_SYNC_INTERVAL", "600"))  # every 10 min
AUTO_SYNC_MIN_GAP_SEC = 540        # skip if last_sync < 9 min ago (respects 6/h limit)
AUTO_SYNC_STARTUP_DELAY_SEC = 45   # let app warm up before first tick
AUTO_SYNC_USER_STAGGER_SEC = 2     # small gap between users to smooth IMAP load

# Postgres advisory-lock keyspace offset — keeps email-sync locks disjoint
# from any other app-level advisory locks.
_ADVISORY_LOCK_NAMESPACE = 914372000


_auto_sync_task: Optional[asyncio.Task] = None


def _try_acquire_user_lock(db_session, user_id: int) -> bool:
    """Try to acquire a Postgres advisory lock for this user. Returns True
    on acquisition, False if another worker/request already holds it.
    On non-Postgres backends (e.g. SQLite local), returns True (no-op)."""
    try:
        dialect = db_session.bind.dialect.name if db_session.bind else ""
    except Exception:
        dialect = ""
    if dialect != "postgresql":
        return True
    try:
        from sqlalchemy import text
        key = _ADVISORY_LOCK_NAMESPACE + int(user_id)
        got = db_session.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": key}).scalar()
        return bool(got)
    except Exception:
        logger.exception("advisory lock acquire failed for user=%s; proceeding without lock", user_id)
        return True


def _release_user_lock(db_session, user_id: int) -> None:
    try:
        dialect = db_session.bind.dialect.name if db_session.bind else ""
    except Exception:
        dialect = ""
    if dialect != "postgresql":
        return
    try:
        from sqlalchemy import text
        key = _ADVISORY_LOCK_NAMESPACE + int(user_id)
        db_session.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": key})
        db_session.commit()
    except Exception:
        logger.warning("advisory lock release failed for user=%s", user_id)


# ----------------------------- credentials -----------------------------

def _fernet():
    from cryptography.fernet import Fernet
    key = os.getenv("EMAIL_CREDS_KEY", "").strip()
    if not key:
        raise RuntimeError("EMAIL_CREDS_KEY environment variable is not set")
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt_password(password: str) -> str:
    return _fernet().encrypt(password.encode()).decode()


def decrypt_password(token: str) -> str:
    return _fernet().decrypt(token.encode()).decode()


# ------------------------------ helpers --------------------------------

def _decode_header(raw: Optional[str]) -> str:
    if not raw:
        return ""
    try:
        parts = decode_header(raw)
        out = []
        for value, charset in parts:
            if isinstance(value, bytes):
                out.append(value.decode(charset or "utf-8", errors="ignore"))
            else:
                out.append(value)
        return "".join(out)
    except Exception:
        return raw


def _connect_imap(host: str, port: int, email_addr: str, password: str) -> imaplib.IMAP4_SSL:
    ctx = ssl.create_default_context()
    M = imaplib.IMAP4_SSL(host, port, ssl_context=ctx, timeout=IMAP_TIMEOUT_SEC)
    M.login(email_addr, password)
    return M


def _file_type(filename: str, content: bytes) -> str:
    fn = (filename or "").lower()
    if fn.endswith(".pdf") or content[:4] == b"%PDF":
        return "pdf"
    if fn.endswith(".xml"):
        return "xml"
    head = content.lstrip()[:100].lower()
    if head.startswith(b"<?xml") or (head.startswith(b"<") and b"invoice" in head):
        return "xml"
    return ""


def _subject_looks_like_invoice(subject: str) -> bool:
    s = (subject or "").lower()
    return any(kw in s for kw in SUBJECT_KEYWORDS)


# --------------------------- parsing logic ------------------------------

def _parse_xml_invoice(xml_bytes: bytes) -> Optional[dict]:
    import re as _re
    import xml.etree.ElementTree as ET

    text = xml_bytes.decode("utf-8", errors="ignore")
    # XXE defence
    text = _re.sub(r'<!DOCTYPE[^>]*>', '', text, flags=_re.IGNORECASE | _re.DOTALL)
    text = _re.sub(r'<!ENTITY[^>]*>', '', text, flags=_re.IGNORECASE | _re.DOTALL)

    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return None

    def _find(el, tags):
        for tag in tags:
            for child in el.iter():
                if tag.lower() in child.tag.lower() and child.text and child.text.strip():
                    return child.text.strip()
        return ""

    vendor = _find(root, ["PartyName", "Name", "SellerTradeParty"]) or "E-Rechnung"
    inv_num = _find(root, ["InvoiceNumber", "DocumentNumber"]) or _find(root, ["ID"]) or ""
    date_str = _find(root, ["IssueDate", "DateTimeString", "InvoiceDate"]) or ""
    total_str = _find(root, ["PayableAmount", "TaxInclusiveAmount", "GrandTotalAmount", "DuePayableAmount"]) or ""
    tax_str = _find(root, ["TaxAmount", "TaxTotalAmount"]) or ""
    vat_rate_str = _find(root, ["Percent", "RateApplicablePercent"]) or ""

    def _f(s: str) -> float:
        try:
            return float((s or "").replace(",", "."))
        except (ValueError, AttributeError):
            return 0.0

    total = _f(total_str)
    tax = _f(tax_str)
    vat_rate = "19%"
    try:
        r = float((vat_rate_str or "").replace(",", "."))
        if 0 < r <= 30:
            vat_rate = f"{r}%"
    except (ValueError, AttributeError):
        pass

    return {
        "vendor": vendor,
        "invoice_number": inv_num,
        "date": date_str,
        "total_amount": total,
        "vat_amount": tax if tax > 0 else round(total * 19 / 119, 2),
        "vat_rate": vat_rate,
        "invoice_type": "expense",
        "category": "other",
        "payment_method": "",
        "raw_text": text[:2000],
    }


def _extract_zugferd_xml(pdf_bytes: bytes) -> Optional[bytes]:
    try:
        from pypdf import PdfReader
    except Exception:
        return None
    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        attachments = getattr(reader, "attachments", {}) or {}
        preferred = ("factur-x.xml", "zugferd-invoice.xml", "xrechnung.xml", "zugferd.xml")
        for name in preferred:
            for k, v in attachments.items():
                if k.lower() == name and v:
                    return v[0] if isinstance(v, list) else v
        for k, v in attachments.items():
            if k.lower().endswith(".xml") and v:
                return v[0] if isinstance(v, list) else v
    except Exception:
        logger.warning("pypdf attachment scan failed")
    return None


async def _ocr_parse_pdf(pdf_bytes: bytes, filename: str) -> Optional[dict]:
    try:
        from fastapi import UploadFile
        from starlette.datastructures import Headers
        from autotax.ocr import extract_text_and_qr
        from autotax.parser import parse_invoice
        fake = UploadFile(filename=filename or "email.pdf", file=io.BytesIO(pdf_bytes),
                          headers=Headers({"content-type": "application/pdf"}))
        raw_text, qr_data = await asyncio.wait_for(
            extract_text_and_qr(fake, handwriting=False, file_bytes=pdf_bytes), timeout=45
        )
        parsed = parse_invoice(raw_text or "")
        if qr_data:
            if qr_data.get("company") and parsed.get("vendor") in ("Unbekannt", "", None):
                parsed["vendor"] = qr_data["company"]
            if qr_data.get("amount") and not parsed.get("total_amount"):
                parsed["total_amount"] = qr_data["amount"]
            if qr_data.get("date") and not parsed.get("date"):
                parsed["date"] = qr_data["date"]
        return parsed
    except Exception:
        logger.exception("OCR parse failed for %s", filename)
        return None


# ------------------------------- sync ----------------------------------

async def sync_user_inbox(user_id: int, max_messages: int = 20) -> dict:
    """Connect to the user's configured IMAP inbox, pull UNSEEN messages,
    extract PDF/XML attachments, run them through the invoice pipeline,
    and mark the messages as SEEN. Never raises on bad email — logs and
    continues. Returns counts."""
    from autotax.db import SessionLocal, save_invoice
    from autotax.duplicate_service import generate_file_hash, find_hard_duplicate
    from autotax.models import EmailConfig, Invoice

    db = SessionLocal()
    _holds_lock = False
    try:
        cfg = db.query(EmailConfig).filter(
            EmailConfig.user_id == user_id, EmailConfig.enabled == True  # noqa: E712
        ).first()
        if not cfg:
            return {"processed": 0, "skipped": 0, "errors": 0, "message": "Keine Email-Konfiguration aktiv"}

        # Multi-worker / concurrent-request guard: only one sync per user
        # can run at a time (Postgres advisory lock; no-op on SQLite).
        _holds_lock = _try_acquire_user_lock(db, user_id)
        if not _holds_lock:
            logger.info("sync_user_inbox: user=%s already in progress; skipping", user_id)
            return {"processed": 0, "skipped": 0, "errors": 0, "message": "Sync läuft bereits"}

        if cfg.provider in PROVIDERS:
            host, port = PROVIDERS[cfg.provider]
        else:
            host, port = cfg.host, cfg.port or 993
        if not host:
            return {"processed": 0, "skipped": 0, "errors": 0, "message": "Ungültige Provider-Konfiguration"}

        try:
            password = decrypt_password(cfg.encrypted_password)
        except Exception:
            logger.warning("Password decryption failed for user %s", user_id)
            return {"processed": 0, "skipped": 0, "errors": 0, "message": "Passwort-Entschlüsselung fehlgeschlagen — bitte Konfiguration neu speichern"}

        processed = 0
        skipped = 0
        errors = 0

        M = None
        try:
            try:
                M = _connect_imap(host, port, cfg.email, password)
            except imaplib.IMAP4.error:
                return {"processed": 0, "skipped": 0, "errors": 0, "message": "IMAP-Login fehlgeschlagen — prüfe Email und App-Passwort"}
            except (OSError, ssl.SSLError):
                return {"processed": 0, "skipped": 0, "errors": 0, "message": "IMAP-Server nicht erreichbar"}

            typ, _ = M.select("INBOX")
            if typ != "OK":
                return {"processed": 0, "skipped": 0, "errors": 0, "message": "Posteingang nicht verfügbar"}

            typ, data = M.search(None, "UNSEEN")
            if typ != "OK" or not data or not data[0]:
                cfg.last_sync = datetime.now(timezone.utc)
                db.commit()
                return {"processed": 0, "skipped": 0, "errors": 0}

            ids = data[0].split()
            ids = ids[-max_messages:]

            for msg_id in ids:
                try:
                    typ, msg_data = M.fetch(msg_id, "(RFC822)")
                    if typ != "OK" or not msg_data or not msg_data[0]:
                        errors += 1
                        continue
                    msg = email.message_from_bytes(msg_data[0][1])
                    subject = _decode_header(msg.get("Subject"))
                    sender = _decode_header(msg.get("From"))
                    logger.info("Email sync user=%s msg=%s subj=%r from=%r", user_id, msg_id.decode() if isinstance(msg_id, bytes) else msg_id, subject[:80], sender[:80])

                    for part in msg.walk():
                        if part.get_content_maintype() == "multipart":
                            continue
                        fn = _decode_header(part.get_filename() or "")
                        try:
                            payload = part.get_payload(decode=True)
                        except Exception:
                            payload = None
                        if not payload:
                            continue
                        if len(payload) > MAX_ATTACHMENT_BYTES:
                            continue
                        ftype = _file_type(fn, payload)
                        if ftype not in ("xml", "pdf"):
                            continue

                        fh = generate_file_hash(payload)
                        dup = find_hard_duplicate(db, user_id, fh)
                        if dup:
                            skipped += 1
                            continue

                        parsed: Optional[dict] = None
                        if ftype == "xml":
                            parsed = _parse_xml_invoice(payload)
                        else:
                            xml_bytes = _extract_zugferd_xml(payload)
                            if xml_bytes:
                                parsed = _parse_xml_invoice(xml_bytes)
                            else:
                                parsed = await _ocr_parse_pdf(payload, fn)

                        if not parsed:
                            skipped += 1
                            continue

                        parsed.setdefault("invoice_type", "expense")
                        parsed.setdefault("raw_text", "")
                        parsed.setdefault("category", "other")

                        try:
                            inv_id = save_invoice(
                                parsed, user_id=user_id,
                                filename=fn or "email-attachment",
                                file_data=payload,
                                file_content_type="application/xml" if ftype == "xml" else "application/pdf",
                                file_hash=fh,
                            )
                        except TypeError:
                            # Older save_invoice signature fallback
                            inv_id = save_invoice(parsed, user_id=user_id, filename=fn or "email-attachment")
                            try:
                                inv = db.query(Invoice).filter(Invoice.id == inv_id, Invoice.user_id == user_id).first()
                                if inv:
                                    inv.file_data = payload
                                    inv.file_hash = fh
                                    inv.file_content_type = "application/xml" if ftype == "xml" else "application/pdf"
                                    db.commit()
                            except Exception:
                                db.rollback()

                        try:
                            from autotax.main import auto_create_cash_entry
                            auto_create_cash_entry(inv_id, user_id, parsed)
                        except Exception:
                            logger.exception("auto_create_cash_entry failed for invoice %s", inv_id)

                        processed += 1

                    # Mark seen after handling attachments (even if no attachments matched)
                    try:
                        M.store(msg_id, "+FLAGS", "\\Seen")
                    except Exception:
                        logger.warning("Failed to mark message %s as seen", msg_id)
                except Exception:
                    errors += 1
                    logger.exception("Email processing failed for msg %s", msg_id)

            cfg.last_sync = datetime.now(timezone.utc)
            db.commit()
            return {"processed": processed, "skipped": skipped, "errors": errors}
        finally:
            if M is not None:
                try:
                    M.close()
                except Exception:
                    pass
                try:
                    M.logout()
                except Exception:
                    pass
    finally:
        if _holds_lock:
            _release_user_lock(db, user_id)
        db.close()


# ------------------------ automatic sync loop --------------------------

async def _auto_sync_iteration():
    """Single tick: select enabled users whose last_sync is old enough,
    then sync each one sequentially. One failing user must not affect
    the others."""
    from autotax.db import SessionLocal
    from autotax.models import EmailConfig

    targets: list[int] = []
    db = SessionLocal()
    try:
        cfgs = db.query(EmailConfig).filter(EmailConfig.enabled == True).all()  # noqa: E712
        now = datetime.now(timezone.utc)
        for cfg in cfgs:
            if cfg.last_sync is not None:
                last = cfg.last_sync
                if last.tzinfo is None:
                    last = last.replace(tzinfo=timezone.utc)
                if (now - last).total_seconds() < AUTO_SYNC_MIN_GAP_SEC:
                    continue
            targets.append(cfg.user_id)
    except Exception:
        logger.exception("auto-sync: failed to enumerate EmailConfig")
        return
    finally:
        db.close()

    if not targets:
        logger.debug("auto-sync: no users due")
        return

    logger.info("auto-sync: ticking %d user(s)", len(targets))
    for uid in targets:
        try:
            r = await sync_user_inbox(uid)
            logger.info(
                "auto-sync user=%s processed=%s skipped=%s errors=%s msg=%s",
                uid, r.get("processed", 0), r.get("skipped", 0),
                r.get("errors", 0), r.get("message") or "-",
            )
        except Exception:
            # A crash on one user must not halt the iteration
            logger.exception("auto-sync: sync_user_inbox raised for user=%s", uid)
        try:
            await asyncio.sleep(AUTO_SYNC_USER_STAGGER_SEC)
        except asyncio.CancelledError:
            raise


async def _auto_sync_loop():
    logger.info("Email auto-sync loop starting (interval=%ss, delay=%ss)",
                AUTO_SYNC_INTERVAL_SEC, AUTO_SYNC_STARTUP_DELAY_SEC)
    try:
        await asyncio.sleep(AUTO_SYNC_STARTUP_DELAY_SEC)
    except asyncio.CancelledError:
        return

    while True:
        try:
            await _auto_sync_iteration()
        except asyncio.CancelledError:
            logger.info("Email auto-sync loop cancelled")
            raise
        except Exception:
            # Swallow + continue — never let the loop die from a transient error
            logger.exception("auto-sync iteration crashed; continuing after interval")
        try:
            await asyncio.sleep(AUTO_SYNC_INTERVAL_SEC)
        except asyncio.CancelledError:
            logger.info("Email auto-sync loop cancelled")
            raise


def start_auto_sync() -> Optional[asyncio.Task]:
    """Idempotent: spawn the background loop if not already running."""
    global _auto_sync_task
    if _auto_sync_task and not _auto_sync_task.done():
        return _auto_sync_task
    try:
        _auto_sync_task = asyncio.create_task(_auto_sync_loop(), name="email-auto-sync")
        return _auto_sync_task
    except RuntimeError:
        # No running loop (called outside async context) — caller must await from lifespan
        logger.warning("start_auto_sync called without a running loop")
        return None


def stop_auto_sync() -> None:
    global _auto_sync_task
    t = _auto_sync_task
    _auto_sync_task = None
    if t and not t.done():
        t.cancel()
