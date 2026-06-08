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
MAX_ATTACHMENT_BYTES = 25 * 1024 * 1024  # 25 MB per attachment (PDF rechnungen bazen buyuk)

# --- Auto-sync loop configuration ---
AUTO_SYNC_INTERVAL_SEC = int(os.getenv("EMAIL_AUTO_SYNC_INTERVAL", "600"))  # every 10 min
AUTO_SYNC_MIN_GAP_SEC = 540        # skip if last_sync < 9 min ago (respects 6/h limit)
AUTH_FAIL_LIMIT = 3                 # auto-disable email auto-sync after N consecutive IMAP auth failures
AUTO_SYNC_STARTUP_DELAY_SEC = 45   # let app warm up before first tick
AUTO_SYNC_USER_STAGGER_SEC = 2     # small gap between users to smooth IMAP load

# Postgres advisory-lock keyspace offset — keeps email-sync locks disjoint
# from any other app-level advisory locks.
_ADVISORY_LOCK_NAMESPACE = 914372000


_auto_sync_task: Optional[asyncio.Task] = None


# ---------------------------------------------------------------------------
# In-memory per-user sync progress tracking.
# Single uvicorn worker yeterli — multi-worker'da paylasilmaz, ama bizim
# kullanim icin (kisisel SaaS, dusuk concurrency) tek worker yeterli.
# Frontend GET /email/status ile 2 sn'de bir poll eder.
# ---------------------------------------------------------------------------
_SYNC_STATUS: dict[int, dict] = {}
_RECENT_CAP = 100  # her kullanici icin son N mail'in detayini sakla (164 mail testi icin yeterli)


def _status_init(user_id: int, total: int, mode: str) -> None:
    _SYNC_STATUS[user_id] = {
        "running": True,
        "mode": mode,                      # "all" | "unseen"
        "total": total,                    # taranacak toplam mail sayisi
        "scanned": 0,                      # simdiye kadar tarananlar
        "imported": 0,                     # eklenen yeni Belege
        "duplicates": 0,                   # dup hash atlanan
        "errors": 0,                       # IMAP/parse hatalari
        # Attachment-level diagnostics (PDF'lerin neden gorunmedigini hizli teshis icin)
        "att_total": 0,                    # taranan toplam ek sayisi (her tip)
        "att_pdf": 0,                      # PDF tipi tespit edilen ekler
        "att_xml": 0,                      # XML tipi tespit edilen ekler
        "att_too_big": 0,                  # MAX_ATTACHMENT_BYTES asti
        "att_unsupported": 0,              # PDF/XML disi (image, docx, vs.)
        "current_sender": "",              # surdurulen mail'in sender'i
        "last_error": "",                  # son hata stringi (UI gosterir)
        "started_at": datetime.now(timezone.utc).isoformat(),
        "finished_at": None,
        "recent": [],                      # son N mail'in {subject, sender, status, reason} kaydi
    }


def _status_update(user_id: int, **kwargs) -> None:
    st = _SYNC_STATUS.get(user_id)
    if not st:
        return
    for k, v in kwargs.items():
        if k == "inc":  # {"inc": {"scanned": 1, "imported": 1}}
            for ck, cv in (v or {}).items():
                st[ck] = (st.get(ck) or 0) + cv
        else:
            st[k] = v


def _status_record(user_id: int, subject: str, sender: str, status: str, reason: str = "") -> None:
    st = _SYNC_STATUS.get(user_id)
    if not st:
        return
    entry = {
        "subject": (subject or "")[:120],
        "sender": (sender or "")[:120],
        "status": status,         # "imported" | "duplicate" | "no_attach" | "parse_fail" | "error"
        "reason": reason[:200] if reason else "",
        "at": datetime.now(timezone.utc).isoformat(),
    }
    st["recent"].append(entry)
    # Cap'le: sadece son N'i tut (LIFO icin: append + slice baslangictan)
    if len(st["recent"]) > _RECENT_CAP:
        st["recent"] = st["recent"][-_RECENT_CAP:]


def _status_finish(user_id: int, message: str = "") -> None:
    st = _SYNC_STATUS.get(user_id)
    if not st:
        return
    st["running"] = False
    st["finished_at"] = datetime.now(timezone.utc).isoformat()
    if message:
        st["last_error"] = message  # finish'te varsa hata mesaji yansisin


def get_sync_status(user_id: int) -> dict:
    """Kullanicinin son sync durumunu doner (running=False ise tamamlanmis;
    yoksa hic baslamamis). Frontend polling icin kullanilir."""
    st = _SYNC_STATUS.get(user_id)
    if not st:
        return {"running": False, "exists": False}
    out = dict(st)
    out["exists"] = True
    return out


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

async def sync_user_inbox(user_id: int, max_messages: int = 20, all_messages: bool = False) -> dict:
    """Connect to the user's configured IMAP inbox, pull UNSEEN messages,
    extract PDF/XML attachments, run them through the invoice pipeline,
    and mark the messages as SEEN. Never raises on bad email — logs and
    continues. Returns counts.

    all_messages=True: One-off mode triggered by user. Searches ALL messages
    (not just UNSEEN) and does NOT mark them as SEEN — preserves the user's
    read/unread state in their email client. Duplicate protection via file
    hash prevents reimport. Caps max_messages at 200.

    Progress: _SYNC_STATUS[user_id] dict'i her adimda guncellenir; frontend
    GET /email/status ile poll eder."""
    from autotax.db import SessionLocal, save_invoice
    from autotax.duplicate_service import generate_file_hash, find_hard_duplicate
    from autotax.models import EmailConfig, Invoice

    mode_label = "all" if all_messages else "unseen"
    _status_init(user_id, total=0, mode=mode_label)

    db = SessionLocal()
    _holds_lock = False
    try:
        cfg = db.query(EmailConfig).filter(
            EmailConfig.user_id == user_id, EmailConfig.enabled == True  # noqa: E712
        ).first()
        if not cfg:
            _status_finish(user_id, "Keine Email-Konfiguration aktiv")
            return {"processed": 0, "skipped": 0, "errors": 0, "message": "Keine Email-Konfiguration aktiv"}

        # Multi-worker / concurrent-request guard: only one sync per user
        # can run at a time (Postgres advisory lock; no-op on SQLite).
        _holds_lock = _try_acquire_user_lock(db, user_id)
        if not _holds_lock:
            logger.info("sync_user_inbox: user=%s already in progress; skipping", user_id)
            _status_finish(user_id, "Sync läuft bereits")
            return {"processed": 0, "skipped": 0, "errors": 0, "message": "Sync läuft bereits"}

        if cfg.provider in PROVIDERS:
            host, port = PROVIDERS[cfg.provider]
        else:
            host, port = cfg.host, cfg.port or 993
        if not host:
            _status_finish(user_id, "Ungültige Provider-Konfiguration")
            return {"processed": 0, "skipped": 0, "errors": 0, "message": "Ungültige Provider-Konfiguration"}

        try:
            password = decrypt_password(cfg.encrypted_password)
        except Exception:
            logger.warning("Password decryption failed for user %s", user_id)
            _status_finish(user_id, "Passwort-Entschlüsselung fehlgeschlagen")
            return {"processed": 0, "skipped": 0, "errors": 0, "message": "Passwort-Entschlüsselung fehlgeschlagen — bitte Konfiguration neu speichern"}

        processed = 0
        skipped = 0
        errors = 0

        M = None
        try:
            try:
                M = _connect_imap(host, port, cfg.email, password)
            except imaplib.IMAP4.error as _e:
                logger.warning("IMAP login failed user=%s host=%s: %s", user_id, host, _e)
                # Auth-Fail-Backoff: zähle Login-Fehler; ab Limit auto-sync deaktivieren,
                # um Gmail-Sperre + Log-Spam (Tick alle ~9 min) zu vermeiden.
                _disabled = False
                try:
                    cfg.auth_fail_count = (getattr(cfg, "auth_fail_count", 0) or 0) + 1
                    if cfg.auth_fail_count >= AUTH_FAIL_LIMIT:
                        cfg.enabled = False
                        _disabled = True
                        logger.warning("Auto-sync DISABLED user=%s after %d auth failures (wrong app password?)",
                                       user_id, cfg.auth_fail_count)
                    db.commit()
                except Exception:
                    db.rollback()
                _status_finish(user_id, f"IMAP-Login fehlgeschlagen: {_e}")
                _m = ("Auto-Sync deaktiviert nach mehreren fehlgeschlagenen Logins — bitte App-Passwort "
                      "prüfen und Email-Import erneut speichern." if _disabled
                      else "IMAP-Login fehlgeschlagen — prüfe Email und App-Passwort")
                return {"processed": 0, "skipped": 0, "errors": 0, "message": _m}
            except (OSError, ssl.SSLError, TimeoutError) as _e:
                logger.warning("IMAP connection failed user=%s host=%s: %s", user_id, host, _e)
                _status_finish(user_id, f"IMAP-Verbindung fehlgeschlagen: {_e}")
                return {"processed": 0, "skipped": 0, "errors": 0, "message": "IMAP-Server nicht erreichbar"}

            # Login erfolgreich -> Auth-Fail-Zähler zurücksetzen
            if getattr(cfg, "auth_fail_count", 0):
                try:
                    cfg.auth_fail_count = 0
                    db.commit()
                except Exception:
                    db.rollback()

            # Gmail icin ozel arama: 'All Mail' folder + X-GM-RAW has:attachment
            # boylece Kaufe/Abos kategorisindeki, arsivlenmis Rechnungen de yakalanir.
            # Diger provider'lar icin INBOX + UNSEEN/ALL klasik akis.
            is_gmail = (cfg.provider == "gmail")
            folder_selected = "INBOX"
            search_query = "ALL" if all_messages else "UNSEEN"
            ids: list[bytes] = []

            if is_gmail and all_messages:
                # Tum mailler taranacaksa Gmail'in 'All Mail' folder'ina geç + has:attachment ile filtrele
                gmail_folders = ['"[Gmail]/All Mail"', '"[Gmail]/Alle Nachrichten"', '"[Google Mail]/All Mail"']
                selected_ok = False
                for gf in gmail_folders:
                    typ, _ = M.select(gf)
                    if typ == "OK":
                        folder_selected = gf
                        selected_ok = True
                        break
                if not selected_ok:
                    # Fallback: INBOX
                    typ, _ = M.select("INBOX")
                    if typ != "OK":
                        _status_finish(user_id, "Posteingang nicht verfügbar")
                        return {"processed": 0, "skipped": 0, "errors": 0, "message": "Posteingang nicht verfügbar"}
                    folder_selected = "INBOX"

                # X-GM-RAW: Gmail-spesifik arama. has:attachment cok genis bir filtre — sadece
                # eki olan mailleri getirir, hem INBOX hem Kaufe/Abos hem archive dahil.
                try:
                    typ, data = M.search(None, 'X-GM-RAW', '"has:attachment"')
                    search_query = "X-GM-RAW has:attachment"
                except Exception as _xe:
                    logger.warning("Gmail X-GM-RAW search failed user=%s: %s — fallback to ALL", user_id, _xe)
                    typ, data = M.search(None, "ALL")
                    search_query = "ALL (fallback)"
            else:
                # Normal akis: INBOX + UNSEEN/ALL
                typ, _ = M.select("INBOX")
                if typ != "OK":
                    _status_finish(user_id, "Posteingang nicht verfügbar")
                    return {"processed": 0, "skipped": 0, "errors": 0, "message": "Posteingang nicht verfügbar"}
                typ, data = M.search(None, search_query)

            if typ != "OK" or not data or not data[0]:
                cfg.last_sync = datetime.now(timezone.utc)
                db.commit()
                _status_finish(user_id)
                logger.info("sync_user_inbox empty result user=%s folder=%s query=%s", user_id, folder_selected, search_query)
                return {"processed": 0, "skipped": 0, "errors": 0, "mode": search_query, "folder": folder_selected}

            ids = data[0].split()
            cap = 200 if all_messages else max_messages
            ids = ids[-cap:]  # son N mesaj (en yeniler — IMAP UID artarak gider)
            _status_update(user_id, total=len(ids))
            logger.info("sync_user_inbox user=%s folder=%s query=%s -> %d mails to scan (capped to %d)", user_id, folder_selected, search_query, len(ids), cap)

            for msg_id in ids:
                try:
                    typ, msg_data = M.fetch(msg_id, "(RFC822)")
                    if typ != "OK" or not msg_data or not msg_data[0]:
                        errors += 1
                        _status_update(user_id, inc={"scanned": 1, "errors": 1}, last_error=f"IMAP fetch fail msg={msg_id}")
                        _status_record(user_id, "", "", "error", f"IMAP fetch fail msg={msg_id}")
                        continue
                    msg = email.message_from_bytes(msg_data[0][1])
                    subject = _decode_header(msg.get("Subject"))
                    sender = _decode_header(msg.get("From"))
                    logger.info("Email sync user=%s msg=%s subj=%r from=%r", user_id, msg_id.decode() if isinstance(msg_id, bytes) else msg_id, subject[:80], sender[:80])
                    _status_update(user_id, current_sender=sender[:80])

                    # Bu mail icindeki ek istatistikleri (diagnostics icin) + ana sebep
                    mail_imported = 0
                    mail_imported_weak = 0  # OCR/parser zayif (amount=0 veya vendor=Unbekannt)
                    mail_dup = 0
                    mail_parse_fail = 0
                    mail_has_relevant_attach = False
                    mail_att_seen = []     # her ek icin (fn, size, ftype, status) — debug satirina yazilir
                    last_reason = ""

                    for part in msg.walk():
                        if part.get_content_maintype() == "multipart":
                            continue
                        fn = _decode_header(part.get_filename() or "")
                        ctype = part.get_content_type() or "?"
                        try:
                            payload = part.get_payload(decode=True)
                        except Exception as _pe:
                            payload = None
                            last_reason = f"payload decode error: {_pe}"
                            logger.warning("Attachment decode failed user=%s msg=%s fn=%r: %s", user_id, msg_id, fn, _pe)
                        if not payload:
                            continue
                        # Bos body/text/html part'lari da burdan geciyor — sadece ek olanlari say
                        # (Content-Disposition: attachment veya filename var ise gercek ek kabul et;
                        # text/html main body'leri filename'siz ve content-type=text/html olur).
                        has_fn = bool(fn)
                        is_html_or_text_body = ctype in ("text/plain", "text/html") and not has_fn
                        if is_html_or_text_body:
                            continue
                        _status_update(user_id, inc={"att_total": 1})

                        if len(payload) > MAX_ATTACHMENT_BYTES:
                            last_reason = f"attachment too large ({len(payload)//1024} KB > {MAX_ATTACHMENT_BYTES//1024} KB) fn={fn or '(unnamed)'}"
                            logger.warning("Attachment too large user=%s fn=%r size=%d ctype=%s", user_id, fn, len(payload), ctype)
                            mail_att_seen.append(f"{fn or '(unnamed)'} [{ctype}, {len(payload)//1024}KB] TOO BIG")
                            _status_update(user_id, inc={"att_too_big": 1})
                            continue
                        ftype = _file_type(fn, payload)
                        if ftype not in ("xml", "pdf"):
                            # Non-invoice attachment (image/word/etc.) — atla, debug listesine yaz
                            last_reason = f"unsupported attach: fn={fn or '(unnamed)'} ctype={ctype} {len(payload)//1024}KB"
                            mail_att_seen.append(f"{fn or '(unnamed)'} [{ctype}, {len(payload)//1024}KB] SKIP")
                            _status_update(user_id, inc={"att_unsupported": 1})
                            continue

                        mail_has_relevant_attach = True
                        _status_update(user_id, inc={("att_pdf" if ftype == "pdf" else "att_xml"): 1})
                        mail_att_seen.append(f"{fn or '(unnamed)'} [{ftype.upper()}, {len(payload)//1024}KB]")
                        fh = generate_file_hash(payload)
                        dup = find_hard_duplicate(db, user_id, fh)
                        if dup:
                            skipped += 1
                            mail_dup += 1
                            last_reason = f"duplicate hash (already imported as invoice #{dup.id if hasattr(dup,'id') else '?'})"
                            _status_update(user_id, inc={"duplicates": 1})
                            continue

                        parsed: Optional[dict] = None
                        try:
                            if ftype == "xml":
                                parsed = _parse_xml_invoice(payload)
                                if not parsed:
                                    last_reason = "XML parse failed (kein erkanntes XRechnung/UBL-Format)"
                                    logger.warning("XML parse failed user=%s fn=%r", user_id, fn)
                            else:
                                xml_bytes = _extract_zugferd_xml(payload)
                                if xml_bytes:
                                    parsed = _parse_xml_invoice(xml_bytes)
                                    if not parsed:
                                        last_reason = "ZUGFeRD XML extracted but parse failed"
                                        logger.warning("ZUGFeRD XML parse failed user=%s fn=%r", user_id, fn)
                                else:
                                    parsed = await _ocr_parse_pdf(payload, fn)
                                    if not parsed:
                                        last_reason = "OCR/parse failed for PDF (kein Betrag/Datum erkannt)"
                                        logger.warning("OCR parse failed user=%s fn=%r", user_id, fn)
                        except Exception as _pe:
                            last_reason = f"parse exception: {_pe}"
                            logger.exception("Parse exception user=%s fn=%r", user_id, fn)
                            parsed = None

                        if not parsed:
                            skipped += 1
                            mail_parse_fail += 1
                            _status_update(user_id, inc={"errors": 0})  # parse fail = soft skip (errors degil)
                            continue

                        # OCR/parser sonucu ZAYIF mi? (vendor='Unbekannt' VEYA amount=0)
                        # -> Hala import ediyoruz ama recent[]'e flag dusurelim ki kullanici
                        # 'OCR 0 okudu' durumunu hemen anlasin.
                        _v = (parsed.get("vendor") or "").strip()
                        _amt = float(parsed.get("total_amount") or 0) or 0.0
                        _rt_len = len((parsed.get("raw_text") or ""))
                        _weak = (_v in ("", "Unbekannt") or _amt <= 0)
                        if _weak:
                            # OCR ne kadar text okudu ki? raw_text uzunlugundan anlasilir.
                            last_reason = (
                                f"OCR schwach: vendor={_v or 'Unbekannt'} amount={_amt:.2f} "
                                f"raw_text={_rt_len} chars (PDF gescannt/bildbasiert?)"
                            )
                            logger.warning("OCR weak result user=%s fn=%r vendor=%r amount=%s raw_len=%d",
                                           user_id, fn, _v, _amt, _rt_len)
                        else:
                            last_reason = f"OCR ok: vendor={_v} amount={_amt:.2f}€"

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
                        except Exception as _se:
                            last_reason = f"save_invoice fail: {_se}"
                            logger.exception("save_invoice failed user=%s fn=%r", user_id, fn)
                            errors += 1
                            mail_parse_fail += 1
                            _status_update(user_id, inc={"errors": 1}, last_error=last_reason)
                            continue

                        try:
                            from autotax.main import auto_create_cash_entry
                            auto_create_cash_entry(inv_id, user_id, parsed)
                        except Exception:
                            logger.exception("auto_create_cash_entry failed for invoice %s", inv_id)

                        processed += 1
                        mail_imported += 1
                        if _weak:
                            mail_imported_weak += 1
                        _status_update(user_id, inc={"imported": 1})
                        logger.info("Email import OK user=%s invoice=%s vendor=%r amount=%s weak=%s", user_id, inv_id, parsed.get("vendor"), parsed.get("total_amount"), _weak)

                    # Mail icin tek bir recent-row yaz (en cok bilgi tasiyan durumu sec)
                    # Ekleri reason'a ekle ki kullanici mail'de NE oldugunu hemen gorsun
                    att_summary = ("; ".join(mail_att_seen)[:160]) if mail_att_seen else "kein Anhang"
                    if mail_imported > 0:
                        if mail_imported_weak >= mail_imported:
                            # Hepsi zayif OCR — kullanici 'ozellikle bakmali' isareti
                            _status_record(user_id, subject, sender, "imported_weak",
                                           f"{mail_imported} Beleg(e) gespeichert ABER OCR schwach · {last_reason}")
                        elif mail_imported_weak > 0:
                            _status_record(user_id, subject, sender, "imported",
                                           f"{mail_imported} Beleg(e) ({mail_imported_weak} schwach) · {last_reason}")
                        else:
                            _status_record(user_id, subject, sender, "imported",
                                           f"{mail_imported} Beleg(e) importiert · {last_reason or att_summary}")
                    elif mail_dup > 0:
                        _status_record(user_id, subject, sender, "duplicate",
                                       f"{mail_dup} Anhang bereits importiert · {att_summary}")
                    elif mail_parse_fail > 0:
                        _status_record(user_id, subject, sender, "parse_fail",
                                       f"{last_reason or 'Anhang konnte nicht gelesen werden'} · Anhange: {att_summary}")
                    elif not mail_has_relevant_attach:
                        # Bu mail PDF/XML icermeyen ekler tasiyabilir (jpg vs.) — sebep listelenir
                        _status_record(user_id, subject, sender, "no_attach",
                                       f"Kein PDF/XML im Anhang · {att_summary}")

                    _status_update(user_id, inc={"scanned": 1})

                    # Mark seen after handling attachments (even if no attachments matched).
                    # all_messages mode (manuel tum-tarama): okundu/okunmadi durumunu
                    # kullanicinin email istemcisi acisindan degistirmiyoruz.
                    if not all_messages:
                        try:
                            M.store(msg_id, "+FLAGS", "\\Seen")
                        except Exception:
                            logger.warning("Failed to mark message %s as seen", msg_id)
                except Exception as _me:
                    errors += 1
                    _status_update(user_id, inc={"scanned": 1, "errors": 1}, last_error=f"msg processing error: {_me}")
                    _status_record(user_id, "", "", "error", f"msg processing: {_me}")
                    logger.exception("Email processing failed for msg %s", msg_id)

            cfg.last_sync = datetime.now(timezone.utc)
            db.commit()
            _status_finish(user_id)
            logger.info("sync_user_inbox done user=%s processed=%d skipped=%d errors=%d scanned=%d", user_id, processed, skipped, errors, len(ids))
            return {"processed": processed, "skipped": skipped, "errors": errors, "mode": search_query, "scanned": len(ids)}
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
        # Eger _status_finish henuz cagrilmadiysa (yukaridan exception sizdi) defensive olarak kapat
        st = _SYNC_STATUS.get(user_id)
        if st and st.get("running"):
            _status_finish(user_id, "Sync abgebrochen (interner Fehler)")


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
            try:
                from autotax.jobs import track_job
                with track_job("email_sync", payload={"interval_sec": AUTO_SYNC_INTERVAL_SEC}):
                    await _auto_sync_iteration()
            except ImportError:
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
