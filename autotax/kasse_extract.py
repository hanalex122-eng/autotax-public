"""Kasa MVP (Sprint 2) — extraction orchestrator + model routing.

Pilot policy (trust > cost): default model = Sonnet for BOTH expense receipts
and POS/Z-Reports; escalate to Opus 4.8 on ANY fallback condition (JSON
invalid / missing critical fields / confidence < 70 / extraction
inconsistency). NO Haiku during pilot. Model ids env-overridable.

Confidence band → CashEntry.status:  ≥90 auto (confirmed) · 70-89 review
(pending_review) · <70 manual (pending_review). Low confidence is NEVER
auto-booked.
"""
from __future__ import annotations

import os
from typing import Any, Optional

from autotax import ai_ocr

DEFAULT_MODEL = (os.getenv("KASSE_MODEL_DEFAULT") or "claude-sonnet-4-6").strip()
FALLBACK_MODEL = (os.getenv("KASSE_MODEL_FALLBACK") or "claude-opus-4-8").strip()
CONF_THRESHOLD = 70


# POS / daily-closing (Z-Bon, Tagesabschluss) signal words → income document.
# If none present we default to "expense" (the common single-receipt case).
_POS_SIGNALS = (
    "z-bon", "z bon", "z-abschluss", "zabschluss", "z-nr", "tagesabschluss",
    "tagesbericht", "tagesumsatz", "tagessumme", "kassenbericht", "kassenschnitt",
    "x-bon", "bediener", "kassier", "gesamtumsatz", "umsatz gesamt", "tse-signatur",
    "trinkgeld", "bar gesamt", "ec gesamt", "kartenzahlung gesamt",
)


def classify_doc_kind(ocr_text: str) -> str:
    """Heuristic doc-kind detection so the USER is never asked 'Beleg or Z-Report?'.
    Returns 'pos' for a daily-closing/Z-Bon (income), else 'expense'. Conservative:
    needs an explicit POS signal, otherwise defaults to expense.
    """
    t = (ocr_text or "").lower()
    if not t:
        return "expense"
    hits = sum(1 for kw in _POS_SIGNALS if kw in t)
    return "pos" if hits >= 1 else "expense"


def route_model(attempt: int) -> str:
    """attempt 1 → Sonnet (default); attempt 2 → Opus 4.8 (fallback). No Haiku."""
    return DEFAULT_MODEL if attempt <= 1 else FALLBACK_MODEL


def band(confidence: float) -> str:
    if confidence >= 90:
        return "auto"
    if confidence >= CONF_THRESHOLD:
        return "review"
    return "manual"


def status_for_band(b: str) -> str:
    return "confirmed" if b == "auto" else "pending_review"


def _f(v: Any) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _confidence(kind: str, result: Optional[dict]) -> float:
    if not result:
        return 0.0
    raw = result.get("confidence")
    if raw is not None:
        try:
            c = float(raw)
            return c if c > 1 else c * 100  # accept 0-1 or 0-100
        except (TypeError, ValueError):
            pass
    # Expense extractions may omit confidence → heuristic from completeness.
    if kind == "expense":
        if result.get("total_amount") is not None and result.get("date"):
            return 85.0
        return 55.0
    return 60.0


def _missing_critical(kind: str, result: Optional[dict]) -> bool:
    if not result:
        return True
    if kind == "expense":
        return result.get("total_amount") is None or not result.get("date")
    return result.get("gross_revenue") is None or not result.get("date")


def _inconsistent(kind: str, result: Optional[dict]) -> bool:
    if not result:
        return True
    if kind == "expense":
        total, vat = _f(result.get("total_amount")), _f(result.get("vat_amount"))
        return total is not None and vat is not None and vat > total + 0.01
    gross, net, vat = _f(result.get("gross_revenue")), _f(result.get("net_revenue")), _f(result.get("vat_total"))
    if gross and net is not None and vat is not None:
        if abs(gross - (net + vat)) > max(0.02 * gross, 0.02):
            return True
    cash, card, tips = _f(result.get("cash")), _f(result.get("card")), _f(result.get("tips")) or 0.0
    if gross and cash is not None and card is not None:
        if abs((cash + card) - (gross + (tips or 0.0))) > max(0.05 * gross, 1.0) and abs((cash + card) - gross) > max(0.05 * gross, 1.0):
            return True
    return False


def needs_fallback(kind: str, result: Optional[dict]) -> bool:
    return (
        result is None
        or _missing_critical(kind, result)
        or _confidence(kind, result) < CONF_THRESHOLD
        or _inconsistent(kind, result)
    )


def _wrap(kind: str, result: Optional[dict], model: str, fallback_used: bool) -> dict:
    conf = _confidence(kind, result)
    b = band(conf)
    return {
        "kind": kind,
        "fields": result or {},
        "confidence": round(conf, 1),
        "band": b,
        "status": status_for_band(b),
        "model": model,
        "fallback_used": fallback_used,
        "ok": result is not None and not _missing_critical(kind, result),
    }


async def extract_expense(pdf_bytes: Optional[bytes] = None, ocr_text: str = "", filename: str = "expense",
                          image_bytes: Optional[bytes] = None, content_type: Optional[str] = None) -> dict:
    r1 = await ai_ocr.ai_extract_invoice(pdf_bytes=pdf_bytes, ocr_text=ocr_text, filename=filename, model=route_model(1),
                                         image_bytes=image_bytes, content_type=content_type)
    if not needs_fallback("expense", r1):
        return _wrap("expense", r1, route_model(1), False)
    r2 = await ai_ocr.ai_extract_invoice(pdf_bytes=pdf_bytes, ocr_text=ocr_text, filename=filename, model=route_model(2),
                                         image_bytes=image_bytes, content_type=content_type)
    # Keep the better of the two (fallback unless it failed and first was usable)
    chosen = r2 if r2 is not None else r1
    return _wrap("expense", chosen, route_model(2 if r2 is not None else 1), r2 is not None)


async def extract_pos(image_bytes: bytes, business_type: str = "", content_type: str = "image/jpeg", filename: str = "pos") -> dict:
    r1 = await ai_ocr.ai_parse_pos_receipt(image_bytes, business_type=business_type, content_type=content_type, model=route_model(1), filename=filename)
    if not needs_fallback("pos", r1):
        return _wrap("pos", r1, route_model(1), False)
    r2 = await ai_ocr.ai_parse_pos_receipt(image_bytes, business_type=business_type, content_type=content_type, model=route_model(2), filename=filename)
    chosen = r2 if r2 is not None else r1
    return _wrap("pos", chosen, route_model(2 if r2 is not None else 1), r2 is not None)
