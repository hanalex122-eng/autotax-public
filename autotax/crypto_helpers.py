"""Cryptographic + signed-URL helpers (Phase 2.5 modularization, 2026-05-27).

Pure crypto utilities + URL builders. Reads secrets from env, but does no
DB / HTTP / FastAPI work.
"""
from __future__ import annotations

import hashlib as _hashlib
import hmac as _hmac
import os as _os


def _ai_reviewer_sign(payload_bytes: bytes) -> str:
    """HMAC-SHA256 signature of a payload using AI_REVIEWER_SECRET env.

    Used to prevent webhook spoofing — the external AI reviewer service
    signs each callback with this secret, and our /webhooks/ai-review
    endpoint verifies the signature before processing.

    Returns empty string if AI_REVIEWER_SECRET is unset (signature
    verification on the receive side will then reject the callback).
    """
    secret = (_os.environ.get("AI_REVIEWER_SECRET") or "").strip().encode()
    if not secret:
        return ""
    return _hmac.new(secret, payload_bytes, _hashlib.sha256).hexdigest()


def _advisor_invite_link(token: str) -> str:
    """Build a Steuerberater (tax advisor) invitation deep link.

    Format: {PUBLIC_APP_URL}/app#advisor-invite/{token}
    Falls back to the legacy Railway preview URL if PUBLIC_APP_URL is unset.
    """
    base = (_os.getenv("PUBLIC_APP_URL") or "").rstrip("/")
    if not base:
        base = "https://autotax-public-production-3f2a.up.railway.app"
    return f"{base}/app#advisor-invite/{token}"


__all__ = [
    "_ai_reviewer_sign",
    "_advisor_invite_link",
]
