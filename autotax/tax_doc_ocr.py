"""Tax-document OCR via Claude Vision.

Phase 3 of tax_intake_architecture: customer uploads a Lohnsteuerbescheinigung
(or other tax doc) PDF/image, we extract structured fields with confidence
scores, then apply high-confidence fields to TaxDeclaration automatically.

Uses the same Anthropic API as autotax/ai_ocr.py (model: claude-haiku-4-5).

Supported document types (MVP):
- lohnsteuerbescheinigung — annual employer wage statement
- rentenbescheid — DRV pension notice
- versicherungsnachweis — KV/PKV insurance certificate
- spendenbescheinigung — donation receipt
- generic — fallback when doc type unknown
"""
from __future__ import annotations

import base64
import json
import logging
import os
import re
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


# ───────────────────────────────────────────────────────────────────
# Doc-type specific prompts.
# ───────────────────────────────────────────────────────────────────

_PROMPT_LOHNSTEUER = """You are a German tax document parser. Extract data from this Lohnsteuerbescheinigung (annual wage statement from a German employer).

Return ONLY a valid JSON object with this exact schema. Use null for unknown fields.

{
  "doc_type": "lohnsteuerbescheinigung",
  "confidence": 0.0,
  "year": 2024,
  "employer_name": "Acme GmbH",
  "employer_address": "Musterstr. 1, 80331 München",
  "employer_steuernummer": "string or null",
  "employee_name": "Hans Mueller",
  "employee_steuer_id": "12345678901 or null",
  "employee_birthdate": "YYYY-MM-DD or null",
  "tax_class": 1,
  "religion": "ev|rk|none|other",
  "brutto_arbeitslohn": 50000.00,
  "lohnsteuer": 8000.00,
  "solidaritaetszuschlag": 0.00,
  "kirchensteuer": 720.00,
  "sv_kv": 3500.00,
  "sv_rv": 4500.00,
  "sv_av": 600.00,
  "sv_pv": 1200.00,
  "werbungskosten_arbeitnehmer": 1230.00
}

Field meanings:
- Zeile 3 (Bruttoarbeitslohn) -> brutto_arbeitslohn
- Zeile 4 (Einbehaltene Lohnsteuer) -> lohnsteuer
- Zeile 5 (Einbehaltener Solidaritätszuschlag) -> solidaritaetszuschlag
- Zeile 6 (Einbehaltene Kirchensteuer) -> kirchensteuer
- Zeile 22a (AN-Anteil Krankenversicherung) -> sv_kv
- Zeile 23a (AN-Anteil Rentenversicherung) -> sv_rv
- Zeile 24a (AN-Anteil Arbeitslosenversicherung) -> sv_av
- Zeile 25a (AN-Anteil Pflegeversicherung) -> sv_pv

Confidence: 0.95 if all numeric fields clearly readable, 0.7 if partial, 0.4 if doc looks like LSB but text fuzzy.

Return ONLY JSON. No markdown fences."""

_PROMPT_RENTENBESCHEID = """You are a German tax document parser. Extract data from this Rentenbescheid (DRV pension notice).

Return ONLY a valid JSON object:

{
  "doc_type": "rentenbescheid",
  "confidence": 0.0,
  "rente_beginn": "YYYY-MM-DD or null",
  "rente_jahresbetrag": 0.00,
  "rente_typ": "altersrente|erwerbsminderung|witwen|other",
  "anpassungsbetrag": 0.00,
  "beitrag_kv": 0.00,
  "beitrag_pflege": 0.00
}

Return ONLY JSON."""

_PROMPT_VERSICHERUNG = """You are a German tax document parser. Extract data from this Versicherungsnachweis (health/pension insurance annual certificate per §10 EStG).

Return ONLY a valid JSON object:

{
  "doc_type": "versicherungsnachweis",
  "confidence": 0.0,
  "versicherer": "Techniker Krankenkasse",
  "versicherungs_typ": "kv_basis|kv_zusatz|pflege|rurup|drv|bu|sonstige",
  "jahresbeitrag": 0.00,
  "basisbeitrag": 0.00,
  "zusatzbeitrag": 0.00,
  "year": 2024
}

If the document covers multiple coverages (e.g., KV Basis + Zusatz + Pflege), set versicherungs_typ to the dominant one and split amounts into basisbeitrag / zusatzbeitrag where possible.

Return ONLY JSON."""

_PROMPT_SPENDE = """You are a German tax document parser. Extract data from this Spendenbescheinigung (donation receipt §10b EStG).

Return ONLY a valid JSON object:

{
  "doc_type": "spendenbescheinigung",
  "confidence": 0.0,
  "empfaenger": "Deutsches Rotes Kreuz e.V.",
  "betrag": 0.00,
  "datum": "YYYY-MM-DD",
  "spende_typ": "geldspende|sachspende|mitgliedsbeitrag",
  "verwendungszweck": "string or null",
  "year": 2024
}

Return ONLY JSON."""

_PROMPT_GENERIC = """You are a German tax document classifier. Determine what type of tax-relevant document this is and extract key fields.

Return ONLY a valid JSON object:

{
  "doc_type": "lohnsteuerbescheinigung|rentenbescheid|versicherungsnachweis|spendenbescheinigung|nebenkostenabrechnung|handwerkerrechnung|kontoauszug|steuerbescheid|other",
  "confidence": 0.0,
  "key_fields": {
    "year": 2024,
    "issuer": "string or null",
    "total_amount": 0.00,
    "summary_text": "1-sentence description"
  }
}

Return ONLY JSON."""

_PROMPTS = {
    "lohnsteuerbescheinigung": _PROMPT_LOHNSTEUER,
    "rentenbescheid": _PROMPT_RENTENBESCHEID,
    "versicherungsnachweis": _PROMPT_VERSICHERUNG,
    "spendenbescheinigung": _PROMPT_SPENDE,
    "generic": _PROMPT_GENERIC,
}


# Mapping from extracted LSB fields → TaxDeclaration data keys.
# Allows /tax/document/{id}/apply to merge into the form automatically.
LSB_TO_DECLARATION_MAP = {
    "brutto_arbeitslohn": "lohn_brutto",
    "lohnsteuer": "lohnsteuer",
    "solidaritaetszuschlag": "soli_n",
    "kirchensteuer": "kirchensteuer",
    "werbungskosten_arbeitnehmer": "werbungskosten_n",
    "employee_steuer_id": "steuer_id",
    "employee_birthdate": "geburtsdatum",
    "tax_class": None,  # tax class not in current schema yet
    "religion": "religion",
}

VERS_TO_DECLARATION_MAP_BY_TYPE = {
    "kv_basis": "kv_basis",
    "kv_zusatz": "kv_zusatz",
    "pflege": "pflege",
    "drv": "rente_gesetz",
    "rurup": "rurup",
    "bu": "bu",
}


# ───────────────────────────────────────────────────────────────────
# Public helpers.
# ───────────────────────────────────────────────────────────────────

def is_configured() -> bool:
    return bool((os.getenv("ANTHROPIC_API_KEY") or "").strip())


def _strip_json_fences(text: str) -> str:
    """Remove ``` markdown fences (LLM sometimes ignores 'no markdown' rule)."""
    text = (text or "").strip()
    if text.startswith("```"):
        # Strip first line and trailing ```
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        while lines and lines[-1].strip().startswith("```"):
            lines.pop()
        text = "\n".join(lines).strip()
    return text


async def extract_tax_document(
    file_bytes: bytes,
    media_type: str,
    *,
    doc_type_hint: Optional[str] = None,
) -> Optional[dict]:
    """Extract structured fields from a tax document via Claude Vision.

    `media_type` should be 'application/pdf', 'image/png', or 'image/jpeg'.
    `doc_type_hint` is one of the keys in _PROMPTS; defaults to 'generic'.

    Returns a dict on success, None on any failure. Includes a 'confidence'
    field (0.0-1.0). Callers decide auto-apply vs. manual-confirm based on
    confidence threshold (suggested: ≥0.85 auto, 0.7-0.85 confirm, <0.7 manual).
    """
    api_key = (os.getenv("ANTHROPIC_API_KEY") or "").strip()
    if not api_key:
        logger.debug("tax_doc_ocr skip: ANTHROPIC_API_KEY not set")
        return None

    if not file_bytes:
        return None
    if len(file_bytes) > 8 * 1024 * 1024:  # 8 MB cap
        logger.warning("tax_doc_ocr: file too large (%d bytes), skipping",
                       len(file_bytes))
        return None

    doc_key = (doc_type_hint or "generic").lower()
    prompt = _PROMPTS.get(doc_key, _PROMPT_GENERIC)

    model = (os.getenv("AI_OCR_MODEL") or "claude-haiku-4-5-20251001").strip()

    # Build content: document/image block + prompt text
    content: list[dict] = []
    try:
        b64 = base64.b64encode(file_bytes).decode()
        if media_type == "application/pdf":
            content.append({
                "type": "document",
                "source": {"type": "base64", "media_type": "application/pdf", "data": b64},
            })
        elif media_type in ("image/png", "image/jpeg", "image/jpg", "image/webp"):
            content.append({
                "type": "image",
                "source": {"type": "base64", "media_type": media_type, "data": b64},
            })
        else:
            logger.warning("tax_doc_ocr: unsupported media_type %s", media_type)
            return None
    except Exception:
        logger.exception("tax_doc_ocr: encode failed")
        return None
    content.append({"type": "text", "text": prompt})

    payload = {
        "model": model,
        "max_tokens": 2048,
        "messages": [{"role": "user", "content": content}],
    }

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(
                "https://api.anthropic.com/v1/messages",
                json=payload,
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
            )
            if r.status_code != 200:
                logger.warning("tax_doc_ocr API %d: %s", r.status_code, r.text[:300])
                return None
            data = r.json()
            blocks = data.get("content") or []
            text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
            text = _strip_json_fences(text)
            if not text:
                return None
            try:
                result = json.loads(text)
            except json.JSONDecodeError:
                m = re.search(r"\{[\s\S]*\}", text)
                if not m:
                    return None
                try:
                    result = json.loads(m.group(0))
                except Exception:
                    return None
            if not isinstance(result, dict):
                return None
            # Clamp confidence
            try:
                conf = float(result.get("confidence") or 0.0)
                result["confidence"] = max(0.0, min(1.0, conf))
            except Exception:
                result["confidence"] = 0.0
            # Track tokens for cost analytics
            try:
                usage = data.get("usage") or {}
                result["_usage"] = {
                    "input_tokens": usage.get("input_tokens"),
                    "output_tokens": usage.get("output_tokens"),
                }
            except Exception:
                pass
            return result
    except Exception:
        logger.exception("tax_doc_ocr network/parse failure")
        return None


def declaration_fields_from_extraction(extraction: dict) -> dict:
    """Map extracted tax-doc fields → TaxDeclaration data keys.

    For LSB: maps brutto/lohnsteuer/etc. to anlage_n fields.
    For Versicherung: maps amount to the right Vorsorge field per type.
    For others: returns {}.

    Caller still applies confidence threshold + user confirmation.
    """
    if not extraction or not isinstance(extraction, dict):
        return {}
    out: dict = {}
    doc_type = extraction.get("doc_type")

    if doc_type == "lohnsteuerbescheinigung":
        for src, dst in LSB_TO_DECLARATION_MAP.items():
            if dst is None:
                continue
            val = extraction.get(src)
            if val in (None, ""):
                continue
            out[dst] = val

    elif doc_type == "versicherungsnachweis":
        vtype = extraction.get("versicherungs_typ")
        if vtype in VERS_TO_DECLARATION_MAP_BY_TYPE:
            field = VERS_TO_DECLARATION_MAP_BY_TYPE[vtype]
            # Prefer split fields when available (KV)
            if vtype == "kv_basis":
                basis = extraction.get("basisbeitrag") or extraction.get("jahresbeitrag")
                zusatz = extraction.get("zusatzbeitrag")
                if basis:
                    out["kv_basis"] = float(basis)
                if zusatz:
                    out["kv_zusatz"] = float(zusatz)
            else:
                amt = extraction.get("jahresbeitrag")
                if amt:
                    out[field] = float(amt)

    elif doc_type == "rentenbescheid":
        amt = extraction.get("rente_jahresbetrag")
        if amt:
            out["rente_gesetz"] = float(amt)

    return out


__all__ = [
    "is_configured",
    "extract_tax_document",
    "declaration_fields_from_extraction",
    "LSB_TO_DECLARATION_MAP",
    "VERS_TO_DECLARATION_MAP_BY_TYPE",
]
