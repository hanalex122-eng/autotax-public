"""Audit logging — append-only trail of write actions.

Designed for two readers:
  1) the user themselves (DSGVO Art. 15 — Auskunftsrecht)
  2) the user's Steuerberater (once advisor-access ships) — needs to
     prove "Vollständigkeit und Unveränderbarkeit der Aufzeichnungen"
     per GoBD §3.

Rules:
- audit() never raises. A failed log row must NEVER fail a real request.
- Payload is JSON-serialized and capped at 5000 chars. Store only the
  changed fields + before/after, not whole objects.
- IP is masked to /24 (last octet → xxx) per DSGVO Art. 25.
- Actions follow "<resource>.<verb>" naming: invoice.create,
  auth.login_success, cash_entry.delete, etc.
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger("autotax.audit")


def _mask_ip(ip: str) -> str:
    if not ip:
        return ""
    parts = ip.split(".")
    if len(parts) == 4:
        return f"{parts[0]}.{parts[1]}.{parts[2]}.xxx"
    return (ip[:10] + "***") if len(ip) > 10 else ip


def _client_meta(request: Any) -> tuple[str | None, str | None]:
    if request is None:
        return None, None
    try:
        ip = _mask_ip(request.client.host if request.client else "")
        ua = (request.headers.get("user-agent") or "")[:255]
        return ip or None, ua or None
    except Exception:
        return None, None


def audit(
    action: str,
    user_id: int | None = None,
    resource_type: str | None = None,
    resource_id: int | None = None,
    payload: dict | None = None,
    request: Any = None,
) -> None:
    """Append a single row to audit_log. Safe to call from any endpoint.

    Example:
        audit("invoice.delete", user_id=user["sub"],
              resource_type="invoice", resource_id=inv.id,
              payload={"vendor": inv.vendor, "amount": inv.total_amount},
              request=request)
    """
    ip, ua = _client_meta(request)
    # Lazy imports — avoid pulling SQLAlchemy at module load time
    try:
        from autotax.db import SessionLocal
        from autotax.models import AuditLog
    except Exception:
        logger.exception("audit() bootstrap failed for action=%s", action)
        return

    db = SessionLocal()
    try:
        payload_json: str | None = None
        if payload:
            try:
                payload_json = json.dumps(payload, default=str, ensure_ascii=False)[:5000]
            except Exception:
                payload_json = None
        row = AuditLog(
            user_id=user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            payload=payload_json,
            ip=ip,
            user_agent=ua,
        )
        db.add(row)
        db.commit()
    except Exception:
        logger.exception("audit() write failed for action=%s", action)
        try:
            db.rollback()
        except Exception:
            pass
    finally:
        db.close()
