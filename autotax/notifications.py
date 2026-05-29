"""Transactional notification helpers (Phase 2.6 modularization, 2026-05-29).

Outbound email + Telegram helpers consolidated in one module. All functions
are safe to call from anywhere: they read config from env, log on failure,
and degrade gracefully when integrations aren't configured.

Sending paths:
- Email (Resend HTTP API)  -> _send_resend_email(to, subject, html)
- Telegram (Bot API)       -> _send_telegram_message(text)

Convenience wrappers for known message types live here so the routes
don't have to reassemble the HTML each time.
"""
from __future__ import annotations

import logging as _logging
import os as _os
from typing import Optional

logger = _logging.getLogger("autotax.notifications")


# ----------------------------------------------------------------------
# Generic Resend wrapper
# ----------------------------------------------------------------------

def _send_resend_email(to: str, subject: str, html: str, *, from_: Optional[str] = None) -> bool:
    """Send a single transactional email via Resend HTTP API.
    Returns True on send, False on transport / API error.
    No-op (returns True) if RESEND_API_KEY env not set (graceful degradation)."""
    resend_key = (_os.getenv("RESEND_API_KEY") or "").strip()
    if not resend_key:
        logger.warning("Email skipped (RESEND_API_KEY not set): subject=%r", subject[:60])
        return True  # don't block caller if email isn't configured

    sender = (from_ or _os.getenv("RESEND_FROM") or "AutoTax <noreply@autotax.cloud>").strip()
    try:
        import httpx as _httpx
        r = _httpx.post(
            "https://api.resend.com/emails",
            json={"from": sender, "to": [to], "subject": subject, "html": html},
            headers={"Authorization": f"Bearer {resend_key}"},
            timeout=15,
        )
        if r.status_code in (200, 201, 202):
            return True
        logger.warning("Resend returned %d: %s", r.status_code, r.text[:200])
        return False
    except Exception:
        logger.exception("Resend send failed (subject=%r)", subject[:60])
        return False


# ----------------------------------------------------------------------
# Verification email (used by /auth/register)
# ----------------------------------------------------------------------

def _send_verification_email(email: str, token: str) -> bool:
    """Send the 'please verify your email' link to a newly registered user.
    Returns True on send (or graceful no-op), False on error."""
    public_base = (_os.getenv("PUBLIC_APP_URL") or "https://autotax.cloud").rstrip("/")
    verify_url = f"{public_base}/auth/verify-email?token={token}"
    subject = "AutoTax — Bitte bestätige deine E-Mail-Adresse"
    html = f"""<!DOCTYPE html><html><body style="font-family:Arial,Helvetica,sans-serif;max-width:560px;margin:0 auto;padding:24px;color:#111">
<h2 style="color:#10b981;margin:0 0 16px">Willkommen bei AutoTax!</h2>
<p>Danke für deine Registrierung. Klicke auf den Button unten, um deine E-Mail-Adresse zu bestätigen.</p>
<p style="margin:24px 0">
  <a href="{verify_url}" style="background:#10b981;color:#fff;padding:12px 24px;text-decoration:none;border-radius:8px;display:inline-block;font-weight:600">E-Mail bestätigen</a>
</p>
<p style="font-size:13px;color:#555">Falls der Button nicht funktioniert, kopiere diesen Link in deinen Browser:</p>
<p style="font-size:12px;word-break:break-all;background:#f3f4f6;padding:10px;border-radius:6px;color:#374151">{verify_url}</p>
<p style="font-size:12px;color:#666;margin-top:24px">Dieser Link ist 24 Stunden gültig. Falls du dich nicht registriert hast, kannst du diese E-Mail einfach ignorieren.</p>
<hr style="border:none;border-top:1px solid #e5e7eb;margin:24px 0">
<p style="font-size:11px;color:#9ca3af">AutoTax-Cloud · Hüseyin Hancer · Saarbrücken</p>
</body></html>"""
    ok = _send_resend_email(email, subject, html)
    if ok:
        # Email is masked at caller site to avoid duplicating mask helper here.
        logger.info("Verification email dispatched")
    return ok


# ----------------------------------------------------------------------
# Password reset email (used by /auth/reset-password)
# ----------------------------------------------------------------------

def _send_password_reset_email(email: str, token: str) -> bool:
    """Send the 'reset your password' link. Returns True on send / no-op."""
    public_base = (_os.getenv("PUBLIC_APP_URL") or "https://autotax.cloud").rstrip("/")
    reset_url = f"{public_base}/auth/reset?token={token}"
    subject = "AutoTax — Passwort zurücksetzen"
    html = f"""<!DOCTYPE html><html><body style="font-family:Arial,Helvetica,sans-serif;max-width:560px;margin:0 auto;padding:24px;color:#111">
<h2 style="color:#10b981;margin:0 0 16px">Passwort zurücksetzen</h2>
<p>Hallo,</p>
<p>jemand hat ein Zurücksetzen deines AutoTax-Passworts angefordert. Klicke auf den Link unten, um ein neues Passwort zu setzen. <strong>Der Link ist 1 Stunde gültig.</strong></p>
<p style="margin:24px 0">
  <a href="{reset_url}" style="background:#10b981;color:#fff;padding:12px 24px;text-decoration:none;border-radius:8px;display:inline-block;font-weight:600">Passwort zurücksetzen</a>
</p>
<p style="font-size:13px;color:#555">Falls der Button nicht funktioniert, kopiere diesen Link in deinen Browser:</p>
<p style="font-size:12px;word-break:break-all;background:#f3f4f6;padding:10px;border-radius:6px;color:#374151">{reset_url}</p>
<hr style="border:none;border-top:1px solid #e5e7eb;margin:24px 0">
<p style="font-size:12px;color:#666">Hast du diese Anfrage <strong>nicht</strong> gestellt? Dann ignoriere diese E-Mail — dein Passwort bleibt unverändert.</p>
<p style="font-size:11px;color:#9ca3af;margin-top:24px">AutoTax-Cloud · Hüseyin Hancer · Saarbrücken<br>Diese E-Mail wurde automatisch generiert.</p>
</body></html>"""
    return _send_resend_email(email, subject, html)


# ----------------------------------------------------------------------
# Telegram bot send
# ----------------------------------------------------------------------

def _send_telegram_message(
    text: str,
    *,
    chat_id: Optional[str] = None,
    parse_mode: str = "Markdown",
) -> bool:
    """Send a Telegram message via the Bot API. Returns True on send / no-op.
    chat_id defaults to TELEGRAM_CHAT_ID env. parse_mode is Markdown by default."""
    token = (_os.getenv("TELEGRAM_TOKEN") or _os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    target = (chat_id or _os.getenv("TELEGRAM_CHAT_ID") or "").strip()
    if not (token and target):
        return True  # silently skip if not configured
    try:
        import httpx as _httpx
        with _httpx.Client(timeout=10.0) as client:
            r = client.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={
                    "chat_id": target,
                    "text": text,
                    "parse_mode": parse_mode,
                    "disable_web_page_preview": True,
                },
            )
            if r.status_code == 200:
                return True
            logger.warning("Telegram returned %d: %s", r.status_code, r.text[:200])
            return False
    except Exception:
        logger.exception("Telegram send failed")
        return False


__all__ = [
    "_send_resend_email",
    "_send_verification_email",
    "_send_password_reset_email",
    "_send_telegram_message",
]
