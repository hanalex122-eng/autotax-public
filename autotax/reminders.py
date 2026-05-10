"""Rechnung Reminder System.

Kullanicinin yukledigi A4 faturalari (Rechnungen) icin otomatik odeme
hatirlatmasi gonderir. due_date'e gore 4 reminder code:
  - 7d        : son odeme tarihinden 7 gun once
  - 1d        : 1 gun once
  - on_day    : odeme gunu
  - overdue   : gecikmis (her 7 gunde bir tekrar)

Her reminder code 'reminder_sent_codes' alaninda saklanir, ayni reminder
ikinci kez gonderilmez. Paid faturalar gorulmez.

Kanallar:
  - Telegram (TELEGRAM_TOKEN + TELEGRAM_CHAT_ID env)
  - Email (SMTP_HOST + SMTP_USER + SMTP_PASS env, opsiyonel)

Cron: gunluk 09:00 (Avrupa/Berlin) — APScheduler veya basit asyncio loop.
"""

import os
import json
import logging
import asyncio
import smtplib
from datetime import datetime, date, timedelta, timezone
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional

import httpx
from sqlalchemy import text as sql_text

from autotax.db import SessionLocal
from autotax.models import Invoice, User
from datetime import timedelta as _td

logger = logging.getLogger("autotax.reminders")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
# Alternatif: uptime-bot webhook'una gondererek Telegram'a forward
# (autotax-hub'a TELEGRAM_TOKEN duplicate etmemek icin temiz mimari).
NOTIFY_WEBHOOK_URL = os.getenv("NOTIFY_WEBHOOK_URL", "").strip()
SMTP_HOST = os.getenv("SMTP_HOST", "").strip()
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "").strip()
SMTP_PASS = os.getenv("SMTP_PASS", "").strip()
SMTP_FROM = os.getenv("SMTP_FROM", SMTP_USER).strip()


# ───────────────────────────────────────────────────────────────────
# Reminder code logic
# ───────────────────────────────────────────────────────────────────

REMINDER_CODES = ("7d", "1d", "on_day", "overdue")


def _parse_codes(s: Optional[str]) -> list[str]:
    if not s:
        return []
    try:
        out = json.loads(s)
        return [str(c) for c in out] if isinstance(out, list) else []
    except Exception:
        return []


def _serialize_codes(codes: list[str]) -> str:
    return json.dumps(sorted(set(codes)))


def _parse_due(d: Optional[str]) -> Optional[date]:
    if not d or len(d) < 10:
        return None
    try:
        return datetime.strptime(d[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def determine_reminder_code(due_date_str: Optional[str], today: Optional[date] = None) -> Optional[str]:
    """Return which reminder code applies today, or None.
    7d:       7 days before due
    1d:       1 day before
    on_day:   due day
    overdue:  past due (any day after — caller dedupes via sent_codes)
    """
    if today is None:
        today = date.today()
    due = _parse_due(due_date_str)
    if due is None:
        return None
    diff = (due - today).days
    if diff == 7:
        return "7d"
    if diff == 1:
        return "1d"
    if diff == 0:
        return "on_day"
    if diff < 0:
        return "overdue"
    return None


# ───────────────────────────────────────────────────────────────────
# Notification senders
# ───────────────────────────────────────────────────────────────────

async def send_telegram(text: str) -> bool:
    """Telegram'a mesaj gonder. Iki yol:
    1) NOTIFY_WEBHOOK_URL set ise -> uptime-bot'un webhook'una POST et
       (uptime-bot Telegram'a forward eder; credentials orada saklanir).
    2) TELEGRAM_TOKEN+CHAT_ID set ise -> direkt Telegram Bot API'ye gonder.
    """
    # Yol 1: webhook (tercih edilen — credentials autotax-hub'da yok)
    if NOTIFY_WEBHOOK_URL:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.post(NOTIFY_WEBHOOK_URL, json={"text": text})
                if r.status_code == 200:
                    return True
                logger.warning("[REMINDER] webhook failed %s: %s", r.status_code, r.text[:200])
        except Exception as e:
            logger.warning("[REMINDER] webhook error: %s", e)
            # Fall through — direkt API'yi dene

    # Yol 2: direkt Telegram API
    if TELEGRAM_TOKEN and TELEGRAM_CHAT_ID:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.post(url, json={
                    "chat_id": TELEGRAM_CHAT_ID,
                    "text": text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                })
                if r.status_code == 200:
                    return True
                logger.warning("[REMINDER] telegram API failed %s: %s", r.status_code, r.text[:200])
                return False
        except Exception as e:
            logger.warning("[REMINDER] telegram error: %s", e)
            return False

    logger.debug("[REMINDER] no telegram channel configured")
    return False


def send_email(to_addr: str, subject: str, body_html: str) -> bool:
    """SMTP ile email gonderir. Hicbir env yoksa skip."""
    if not (SMTP_HOST and SMTP_USER and SMTP_PASS and to_addr):
        logger.debug("[REMINDER] email skipped — SMTP not configured or no recipient")
        return False
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = SMTP_FROM or SMTP_USER
        msg["To"] = to_addr
        msg.attach(MIMEText(body_html, "html", "utf-8"))
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as s:
            s.starttls()
            s.login(SMTP_USER, SMTP_PASS)
            s.send_message(msg)
        return True
    except Exception as e:
        logger.warning("[REMINDER] email error to %s: %s", to_addr, e)
        return False


# ───────────────────────────────────────────────────────────────────
# Reminder formatter
# ───────────────────────────────────────────────────────────────────

_CODE_LABEL_DE = {
    "7d": "7 Tage bis Fälligkeit",
    "1d": "Morgen fällig",
    "on_day": "Heute fällig",
    "overdue": "ÜBERFÄLLIG",
}


def _format_telegram(inv: Invoice, code: str) -> str:
    """Telegram HTML format."""
    company = inv.vendor or "(unbekannter Lieferant)"
    amount = inv.total_amount or 0
    due = inv.due_date or "—"
    label = _CODE_LABEL_DE.get(code, code)
    if code == "overdue":
        head = "🚨 <b>RECHNUNG ÜBERFÄLLIG</b>"
        status = f"⚠️ Bitte sofort bezahlen — {label}"
    elif code == "on_day":
        head = "🔴 <b>HEUTE FÄLLIG</b>"
        status = "Bitte heute bezahlen."
    elif code == "1d":
        head = "🟠 <b>MORGEN FÄLLIG</b>"
        status = label
    else:
        head = "🧾 <b>Rechnung Reminder</b>"
        status = label
    return (
        f"{head}\n\n"
        f"<b>Firma:</b> {company}\n"
        f"<b>Betrag:</b> {amount:.2f} €\n"
        f"<b>Fällig am:</b> {due}\n"
        f"<b>Rechnungs-Nr.:</b> {inv.invoice_number or '—'}\n\n"
        f"<i>{status}</i>"
    )


def _format_email_body(inv: Invoice, code: str) -> str:
    company = inv.vendor or "(unbekannter Lieferant)"
    amount = inv.total_amount or 0
    due = inv.due_date or "—"
    label = _CODE_LABEL_DE.get(code, code)
    bg = "#fee2e2" if code == "overdue" else "#fef3c7" if code in ("on_day", "1d") else "#dbeafe"
    accent = "#dc2626" if code == "overdue" else "#f59e0b" if code in ("on_day", "1d") else "#2563eb"
    return f"""<!DOCTYPE html><html><body style="font-family:sans-serif;max-width:560px;margin:auto;padding:20px">
<div style="background:{bg};border-left:4px solid {accent};padding:16px;border-radius:8px">
  <h2 style="margin:0 0 8px;color:{accent}">🧾 Rechnung Reminder — {label}</h2>
  <p style="margin:4px 0"><strong>Firma:</strong> {company}</p>
  <p style="margin:4px 0"><strong>Betrag:</strong> {amount:.2f} €</p>
  <p style="margin:4px 0"><strong>Fällig am:</strong> {due}</p>
  <p style="margin:4px 0"><strong>Rechnungs-Nr.:</strong> {inv.invoice_number or '—'}</p>
</div>
<p style="color:#64748b;font-size:13px;margin-top:24px">AutoTax-HUB · Automatische Erinnerung</p>
</body></html>"""


# ───────────────────────────────────────────────────────────────────
# Core: scan + send
# ───────────────────────────────────────────────────────────────────

async def process_trial_expiry() -> dict:
    """Trial'i dolmus kullanicilari plan=free'ye dusur, admin'e Telegram alert.
    Trial 3/1 gun kala kullaniciya hatirlatma da burada gonderilir
    ('upgrade et yoksa free'ye dusersin')."""
    db = SessionLocal()
    stats = {"checked": 0, "downgraded": 0, "warnings_sent": 0}
    try:
        now_utc = datetime.now(timezone.utc)
        users = db.query(User).filter(User.trial_ends_at.isnot(None)).all()
        stats["checked"] = len(users)

        for u in users:
            try:
                if not u.trial_ends_at:
                    continue
                delta = u.trial_ends_at - now_utc
                days_left = delta.days

                # Trial dolmus -> free'ye dusur
                if u.trial_ends_at <= now_utc:
                    if u.plan == "pro":
                        u.plan = "free"
                        u.trial_ends_at = None  # bir daha dusurmemek icin temizle
                        stats["downgraded"] += 1
                        await send_telegram(
                            f"⏰ <b>Trial bitti — Free'ye düşürüldü</b>\n"
                            f"Müşteri: {u.email}\n"
                            f"Kayıt: {u.registered_at.strftime('%Y-%m-%d') if u.registered_at else '—'}\n"
                            f"<i>Müşteri ödeme yaparsa admin panelden Pro'ya geri çevir.</i>"
                        )
                # 3 gun kala uyari (sadece bir kez)
                elif days_left == 3:
                    await send_telegram(
                        f"⚠️ <b>Trial 3 gün kaldı</b>\n"
                        f"Müşteri: {u.email}"
                    )
                    stats["warnings_sent"] += 1
                elif days_left == 1:
                    await send_telegram(
                        f"🔔 <b>Trial yarın bitiyor</b>\n"
                        f"Müşteri: {u.email}\n"
                        f"<i>Müşteri ile iletişime geç.</i>"
                    )
                    stats["warnings_sent"] += 1
            except Exception as e:
                logger.exception("[TRIAL] error processing user %s: %s", u.id, e)

        db.commit()
        if stats["downgraded"] or stats["warnings_sent"]:
            logger.info("[TRIAL] cycle: %s", stats)
    except Exception:
        db.rollback()
        logger.exception("[TRIAL] fatal error")
    finally:
        db.close()
    return stats


async def process_reminders() -> dict:
    """Tum kullanicilarin unpaid faturalarini tarar, gerekli reminder
    kodunu hesaplar, daha once gonderilmediyse Telegram + email atar.
    Return: {checked, sent_telegram, sent_email, errors}."""
    today = date.today()
    db = SessionLocal()
    stats = {"checked": 0, "sent_telegram": 0, "sent_email": 0, "errors": 0,
             "by_code": {c: 0 for c in REMINDER_CODES}}
    try:
        # Sadece odenmemis + due_date'i olan + silinmemis faturalar
        invoices = (
            db.query(Invoice)
            .filter(Invoice.due_date.isnot(None))
            .filter(Invoice.payment_status != "paid")
            .filter((Invoice.is_deleted == False) | (Invoice.is_deleted == None))
            .all()
        )
        stats["checked"] = len(invoices)

        for inv in invoices:
            try:
                code = determine_reminder_code(inv.due_date, today)
                if code is None:
                    continue

                sent_codes = _parse_codes(inv.reminder_sent_codes)

                # Overdue tekrar gonderilebilir — haftada bir
                if code == "overdue":
                    last_overdue_key = None
                    for c in sent_codes:
                        if c.startswith("overdue:"):
                            last_overdue_key = c
                    week_key = f"overdue:{today.isocalendar().week}"
                    if week_key in sent_codes:
                        continue
                    sent_codes.append(week_key)
                else:
                    if code in sent_codes:
                        continue
                    sent_codes.append(code)

                # Auto-update payment_status to overdue
                if code == "overdue" and inv.payment_status != "overdue":
                    inv.payment_status = "overdue"

                # Send notifications
                tg_text = _format_telegram(inv, code)
                ok_tg = await send_telegram(tg_text)
                if ok_tg:
                    stats["sent_telegram"] += 1

                # Email — kullanicinin email'ine
                u = db.query(User).filter(User.id == inv.user_id).first()
                if u and u.email:
                    email_subject = f"🧾 Rechnung Reminder: {inv.vendor or 'Rechnung'} — {_CODE_LABEL_DE.get(code, code)}"
                    email_body = _format_email_body(inv, code)
                    if send_email(u.email, email_subject, email_body):
                        stats["sent_email"] += 1

                inv.reminder_sent_codes = _serialize_codes(sent_codes)
                stats["by_code"][code if code != "overdue" else "overdue"] += 1

            except Exception as e:
                logger.exception("[REMINDER] error processing invoice %s: %s", inv.id, e)
                stats["errors"] += 1

        db.commit()
        logger.info("[REMINDER] cycle done: %s", stats)
    except Exception as e:
        db.rollback()
        logger.exception("[REMINDER] fatal: %s", e)
    finally:
        db.close()
    return stats


# ───────────────────────────────────────────────────────────────────
# Background scheduler — daily at 09:00 Europe/Berlin
# ───────────────────────────────────────────────────────────────────

_BERLIN_OFFSET_HOURS = 1  # CET; CEST=2 — handled by zoneinfo where available
_DAILY_HOUR = 9


def _seconds_until_next_run() -> int:
    """09:00 Europe/Berlin'a kadar kaç saniye."""
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("Europe/Berlin")
        now = datetime.now(tz)
        target = now.replace(hour=_DAILY_HOUR, minute=0, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        return int((target - now).total_seconds())
    except Exception:
        # Fallback UTC + offset
        now = datetime.now(timezone.utc) + timedelta(hours=_BERLIN_OFFSET_HOURS)
        target = now.replace(hour=_DAILY_HOUR, minute=0, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        return int((target - now).total_seconds())


async def reminder_loop():
    """Sonsuz dongu — her 09:00 Europe/Berlin process_reminders calistirir.
    Startup'tan sonra kisa bir gecikme, sonra daily.
    """
    if os.getenv("REMINDERS_ENABLED", "1").strip() == "0":
        logger.info("[REMINDER] disabled via REMINDERS_ENABLED=0")
        return
    logger.info("[REMINDER] background loop starting")
    # Startup'tan 60 sn sonra ilk check (uygulama tam aciksin)
    await asyncio.sleep(60)
    while True:
        try:
            await process_reminders()
            await process_trial_expiry()
            try:
                from autotax.steuer import process_steuer_reminders
                await process_steuer_reminders()
            except Exception:
                logger.exception("[STEUER] tick failed")
        except Exception as e:
            logger.exception("[REMINDER] loop tick error: %s", e)
        # Sonraki 09:00'a kadar uyu (en az 60 sn, en cok 24 saat)
        sleep_s = max(60, min(_seconds_until_next_run(), 86400))
        logger.info("[REMINDER] next run in %d sec", sleep_s)
        await asyncio.sleep(sleep_s)
