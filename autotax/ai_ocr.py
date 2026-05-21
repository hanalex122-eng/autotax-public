"""AI-powered OCR fallback: Anthropic Claude Haiku extracts invoice data
from PDF when local OCR (pypdf + OCR.space) + parse_invoice yields weak
results (vendor=Unbekannt, amount=0, etc.).

DESIGN PRINCIPLE (kullanici talebi):
- AI invoice OCR pipeline'inin DEFAULT akisi DEGIL.
- Yerel OCR ve parse_invoice once dener (deterministik, hizli, ucuz).
- Sonuc ZAYIF ise (veya kullanici 'AI ile dene' butonuna basarsa) AI cagrilir.
- AI bu modul icinde izole — main code'a baglanmaz, bu sayede istenirse
  ENV ile tamamen kapatilabilir.

CONFIG:
- ANTHROPIC_API_KEY env zorunlu. Yoksa is_configured() False, fonksiyon None
  doner — caller'lar bu durumu graceful handle eder.
- AI_OCR_FALLBACK=0 ile manuel olarak kapat (default: 1 = acik).
- AI_OCR_MODEL env override (default: 'claude-haiku-4-5-20251001').
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


_PROMPT = """You are an invoice/receipt parser. Extract structured data from this German/English/French invoice.

Return ONLY a valid JSON object matching this exact schema. Use null for unknown fields:

{
  "vendor": "Official company name (e.g. 'Anthropic, PBC', 'Adobe Inc.', 'Lidl', 'Stripe'). NOT 'Page 1', 'Invoice', or generic labels.",
  "total_amount": 107.10,
  "vat_amount": 17.10,
  "vat_rate": "19%",
  "date": "YYYY-MM-DD",
  "due_date": "YYYY-MM-DD or null",
  "invoice_number": "R9AMD1LM",
  "currency": "EUR",
  "category": "software|hosting|office|travel|fuel|restaurant|telecom|insurance|advertising|professional|hardware|other",
  "vendor_email": "support@anthropic.com or null",
  "vendor_domain": "anthropic.com or null",
  "vendor_address": "street + city or null",
  "vendor_iban": "IBAN or null",
  "vendor_ust_id": "DE123456789 or null",
  "invoice_type": "expense or income (expense unless clearly outgoing invoice you sent)"
}

Rules:
- total_amount = GROSS (Brutto, incl. VAT). vat_amount separate. If VAT not visible, vat_amount=0.
- date in ISO format YYYY-MM-DD always.
- currency: EUR, USD, GBP, CHF, TRY only. Default EUR if symbol unclear.
- category: pick best fit from list above. AI/SaaS subscriptions -> "software".
- vendor: prefer the entity that issued the invoice (not "Bill to" recipient).
- Return ONLY JSON. No markdown fences, no commentary. Empty result -> {"vendor": null, "total_amount": null, ...}

OCR text (may be incomplete, use as supplement to PDF):
"""


def is_configured() -> bool:
    """True if Anthropic API key is set AND fallback not explicitly disabled."""
    if not (os.getenv("ANTHROPIC_API_KEY") or "").strip():
        return False
    if (os.getenv("AI_OCR_FALLBACK") or "1").strip() == "0":
        return False
    return True


def _strip_json_fences(text: str) -> str:
    """LLM bazen ```json ... ``` ile sariyor. Soyalim."""
    text = text.strip()
    # Leading fence
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    # Trailing fence
    text = re.sub(r"\s*```\s*$", "", text)
    return text.strip()


async def ai_extract_invoice(
    pdf_bytes: Optional[bytes] = None,
    ocr_text: str = "",
    filename: str = "",
) -> Optional[dict]:
    """Anthropic API'sine PDF + OCR text gondererek invoice data extract et.

    Args:
        pdf_bytes: Original PDF bytes (Anthropic supports up to ~32 MB via
            document block). 5 MB ustu eklenmez (cost/latency icin).
        ocr_text: Local OCR'in cikardigi text — AI'a context olarak verilir.
        filename: Log icin.

    Returns:
        dict with keys: vendor, total_amount, vat_amount, vat_rate, date,
        due_date, invoice_number, currency, category, vendor_email,
        vendor_domain, vendor_address, vendor_iban, vendor_ust_id,
        invoice_type. Bilinmeyen alanlar null.

        None doner: API key yok, API hatasi, JSON parse fail, vs.

    Maliyet (Haiku 4.5, Jan 2026 fiyatlari): tipik 1-sayfa PDF parse
    ~$0.005-0.01 — kullanici tarafindan manuel cagrildiginda ucuz.
    """
    api_key = (os.getenv("ANTHROPIC_API_KEY") or "").strip()
    if not api_key:
        logger.debug("AI OCR skip: ANTHROPIC_API_KEY not set")
        return None
    if (os.getenv("AI_OCR_FALLBACK") or "1").strip() == "0":
        logger.debug("AI OCR skip: AI_OCR_FALLBACK=0")
        return None

    model = (os.getenv("AI_OCR_MODEL") or "claude-haiku-4-5-20251001").strip()
    # OCR text cap — prompt cok uzun olmasin
    ocr_text = (ocr_text or "")[:4000]

    content: list[dict] = []

    # PDF document block — Anthropic vision direkt PDF okur (sayfa sayfa).
    # 5 MB ustu skip (latency + maliyet). Boyle PDF'leri zaten local OCR
    # handle ediyor, AI'a gerek yok genelde.
    if pdf_bytes and len(pdf_bytes) <= 5 * 1024 * 1024:
        try:
            content.append({
                "type": "document",
                "source": {
                    "type": "base64",
                    "media_type": "application/pdf",
                    "data": base64.b64encode(pdf_bytes).decode(),
                },
            })
        except Exception as e:
            logger.warning("AI OCR: PDF attach failed: %s", e)
    elif pdf_bytes:
        logger.info("AI OCR: PDF too large (%d bytes), using OCR text only", len(pdf_bytes))

    content.append({
        "type": "text",
        "text": _PROMPT + (ocr_text or "[no OCR text available]"),
    })

    payload = {
        "model": model,
        "max_tokens": 1024,
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
                logger.warning(
                    "AI OCR Anthropic API %d for %s: %s",
                    r.status_code, filename, r.text[:300],
                )
                return None
            data = r.json()
            # Response: { content: [{ type:"text", text:"..." }], ... }
            blocks = data.get("content") or []
            if not blocks:
                logger.warning("AI OCR empty response for %s", filename)
                return None
            text = ""
            for b in blocks:
                if b.get("type") == "text":
                    text += b.get("text") or ""
            text = _strip_json_fences(text)
            if not text:
                logger.warning("AI OCR no text content for %s", filename)
                return None
            try:
                result = json.loads(text)
            except json.JSONDecodeError as je:
                # Belki LLM ekstra metin yazdi — JSON'i regex'le cikar
                m = re.search(r"\{[\s\S]*\}", text)
                if m:
                    try:
                        result = json.loads(m.group(0))
                    except Exception:
                        logger.warning("AI OCR JSON parse failed for %s: %s", filename, je)
                        return None
                else:
                    logger.warning("AI OCR no JSON found in response for %s: %s", filename, text[:200])
                    return None
            if not isinstance(result, dict):
                logger.warning("AI OCR returned non-dict for %s: %r", filename, type(result))
                return None
            # Normalize: total_amount/vat_amount sayisal olsun
            for k in ("total_amount", "vat_amount"):
                v = result.get(k)
                if v is None:
                    continue
                try:
                    result[k] = float(v)
                except (TypeError, ValueError):
                    result[k] = None
            logger.info(
                "AI OCR extracted for %s: vendor=%r total=%s date=%s",
                filename, result.get("vendor"), result.get("total_amount"),
                result.get("date"),
            )
            return result
    except httpx.TimeoutException:
        logger.warning("AI OCR timeout for %s", filename)
        return None
    except Exception:
        logger.exception("AI OCR fallback failed for %s", filename)
        return None


# ─── Merge helper (caller'lar icin kolaylik) ──────────────────────────

# 'Empty' kabul edilen degerler — bunlardan biri varsa AI degeri ile uzersine yaz.
_EMPTY_VALUES = (None, "", 0, 0.0, "Unbekannt", "unknown", "0%")


_ROW_PROMPT = """You are a German Kassenbuch (cash book) row parser.

Given a single row from a user's imported cash-book table (often handwritten OCR or partial spreadsheet text), return a structured JSON object with:
  - description: cleaned-up text describing the transaction (vendor or item) — short, no junk chars
  - vendor: best-guess vendor/business name (or null if generic like "Tankstelle")
  - income: positive number if this row is incoming money for the user, else 0
  - expense: positive number if this row is outgoing money for the user, else 0
  - vat_rate: "19%" | "7%" | "0%" | null — German default 19% for most business, 7% for groceries/books, null if unclear
  - category: one of: food | restaurant | fuel | clothing | electronics | office | telecom | transport | drugstore | service | other
  - confidence: 0.0–1.0, how confident you are
  - reason: 1 short sentence in German explaining the choice (e.g. "Aral = Tankstelle, Kraftstoff")

Rules:
- Exactly ONE of income/expense > 0 (the other is 0). If you can't tell, guess "expense" since most cash-book entries are expenses.
- Round amounts to 2 decimals.
- If the row mentions a vendor like Lidl, Rewe, Edeka, Aldi → category=food.
- Aral, Shell, Total, Esso, Jet → category=fuel.
- Restaurant/café/Pizzeria/Imbiss → category=restaurant.
- Telekom, Vodafone, O2 → category=telecom.
- Privat einzahlung/Geldeingang → income.
- Return ONLY the JSON object. No fences, no comments.

Input:
"""


async def ai_parse_table_row(description: str, date: str = "", hint_amount: float = 0.0) -> Optional[dict]:
    """Single table-import row → structured fields via Claude Haiku.

    Use case: user imports a 32-row Excel; parser flags 8 rows as 'uncertain'
    (no amount detected). User clicks '🤖 KI' on a row → backend calls this
    function → AI suggests income/expense/category/vendor.

    Returns dict with: description, vendor, income, expense, vat_rate,
    category, confidence, reason. None on failure (API key, timeout, JSON).
    """
    api_key = (os.getenv("ANTHROPIC_API_KEY") or "").strip()
    if not api_key:
        return None
    if (os.getenv("AI_OCR_FALLBACK") or "1").strip() == "0":
        return None

    model = (os.getenv("AI_OCR_MODEL") or "claude-haiku-4-5-20251001").strip()
    raw = (description or "").strip()[:500]
    if not raw:
        return None

    hint = ""
    if date:
        hint += f"date={date}; "
    if hint_amount and hint_amount > 0:
        hint += f"detected_amount={hint_amount:.2f}; "
    user_text = _ROW_PROMPT + (hint + "row=" + raw if hint else "row=" + raw)

    payload = {
        "model": model,
        "max_tokens": 400,
        "messages": [{"role": "user", "content": user_text}],
    }
    try:
        async with httpx.AsyncClient(timeout=20) as client:
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
                logger.warning("ai_parse_table_row Anthropic %d: %s", r.status_code, r.text[:200])
                return None
            data = r.json()
            blocks = data.get("content") or []
            text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
            text = _strip_json_fences(text)
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
            # Normalize
            for k in ("income", "expense"):
                try:
                    result[k] = round(float(result.get(k) or 0), 2)
                except (TypeError, ValueError):
                    result[k] = 0.0
            try:
                result["confidence"] = float(result.get("confidence") or 0.0)
            except (TypeError, ValueError):
                result["confidence"] = 0.0
            logger.info(
                "AI row parse: desc=%r → vendor=%r income=%.2f expense=%.2f cat=%s conf=%.2f",
                raw[:60], result.get("vendor"), result.get("income", 0),
                result.get("expense", 0), result.get("category"), result.get("confidence", 0),
            )
            return result
    except httpx.TimeoutException:
        logger.warning("ai_parse_table_row timeout for %r", raw[:60])
        return None
    except Exception:
        logger.exception("ai_parse_table_row failed for %r", raw[:60])
        return None


_TABLE_VISION_PROMPT = """You are a parser for German handwritten or scanned Kassenbuch (cash book) tables.

The image shows a table with columns like: Nr, Datum, Beschreibung, Einnahmen, Ausgaben, Saldo.

Extract EVERY visible row as JSON. Return ONLY a JSON array (no markdown, no text before/after):

[
  {
    "date": "YYYY-MM-DD",
    "description": "Tragetasche Leukotape",
    "income": 0,
    "expense": 26.99,
    "saldo": -8148.23
  },
  ...
]

Rules:
- date: convert any format (12.9.21, 9.9.21, 13/09/2021, etc.) to YYYY-MM-DD. Use 20YY for 2-digit years (21→2021).
- income/expense: exactly ONE of them > 0 per row. The other is 0. Round to 2 decimals.
- saldo: optional, the running balance (last column). 0 or null if not visible.
- description: clean the text — fix obvious OCR mistakes if confident (e.g. "Tragetache" → "Tragetasche"). Keep as-is if unsure.
- Skip header rows (Nr/Datum/Beschreibung etc.) and total/sum rows.
- If a row's amount column is empty, skip the row (don't invent amounts).
- Return rows in the order they appear on the image.
- Output ONLY the JSON array. No commentary. No code fences."""


async def ai_parse_table_image(image_bytes: bytes, filename: str = "table.jpg") -> Optional[list]:
    """Anthropic Claude Vision ile el yazısı/taranmış Kassenbuch tablosunu
    structured rows olarak parse et.

    OCR.space + parser tek satırlık tablo formatı bekliyor, ama el yazısı
    OCR'sinde her tablo satırı 2-3 OCR satırına bölünüyor → parser kayıp.
    Bu fonksiyon resmi DIREKT Claude Vision'a yollar, AI tabloyu görüp
    structured rows döner.

    Returns: list of dicts (date, description, income, expense, saldo)
             None on failure.

    Maliyet (Haiku 4.5, Jan 2026): 1 sayfa ~$0.02-0.04.
    """
    api_key = (os.getenv("ANTHROPIC_API_KEY") or "").strip()
    if not api_key:
        logger.debug("Vision table parse skip: ANTHROPIC_API_KEY not set")
        return None
    if (os.getenv("AI_OCR_FALLBACK") or "1").strip() == "0":
        return None
    if not image_bytes:
        return None

    # 5MB üstünü PIL ile yeniden boyutlandır (Anthropic vision limit)
    max_size = 5 * 1024 * 1024
    if len(image_bytes) > max_size:
        try:
            from PIL import Image as _Image
            import io as _io
            img = _Image.open(_io.BytesIO(image_bytes))
            # Genişliği 2000px'e indir (kalite koru)
            w, h = img.size
            if w > 2000:
                new_w = 2000
                new_h = int(h * (new_w / w))
                img = img.resize((new_w, new_h), _Image.LANCZOS)
            buf = _io.BytesIO()
            img.convert("RGB").save(buf, format="JPEG", quality=85)
            image_bytes = buf.getvalue()
            logger.info("Vision table: resized %dx%d → %dx%d (%d KB)",
                        w, h, img.width, img.height, len(image_bytes) // 1024)
        except Exception as e:
            logger.warning("Vision table: resize failed (%s) — sending original", e)

    # Media type detect
    media_type = "image/jpeg"
    fn_lower = filename.lower()
    if fn_lower.endswith(".png"):
        media_type = "image/png"
    elif fn_lower.endswith(".webp"):
        media_type = "image/webp"
    elif fn_lower.endswith(".gif"):
        media_type = "image/gif"

    model = (os.getenv("AI_OCR_MODEL") or "claude-haiku-4-5-20251001").strip()
    content = [
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": media_type,
                "data": base64.b64encode(image_bytes).decode(),
            },
        },
        {"type": "text", "text": _TABLE_VISION_PROMPT},
    ]

    payload = {
        "model": model,
        "max_tokens": 4096,  # 50 satır için bol miktarda
        "messages": [{"role": "user", "content": content}],
    }
    try:
        async with httpx.AsyncClient(timeout=90) as client:
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
                logger.warning("Vision table parse Anthropic %d: %s", r.status_code, r.text[:300])
                return None
            data = r.json()
            blocks = data.get("content") or []
            text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
            text = _strip_json_fences(text).strip()
            if not text:
                return None
            # Parse JSON array
            try:
                rows = json.loads(text)
            except json.JSONDecodeError:
                m = re.search(r"\[[\s\S]*\]", text)
                if not m:
                    logger.warning("Vision table: no JSON array in response: %s", text[:200])
                    return None
                try:
                    rows = json.loads(m.group(0))
                except Exception as je:
                    logger.warning("Vision table: JSON parse failed: %s", je)
                    return None
            if not isinstance(rows, list):
                logger.warning("Vision table: result is not a list (%s)", type(rows))
                return None
            # Normalize
            cleaned = []
            for r in rows:
                if not isinstance(r, dict):
                    continue
                try:
                    income = round(float(r.get("income") or 0), 2)
                except (TypeError, ValueError):
                    income = 0.0
                try:
                    expense = round(float(r.get("expense") or 0), 2)
                except (TypeError, ValueError):
                    expense = 0.0
                if income == 0 and expense == 0:
                    continue  # skip rows with no amount
                cleaned.append({
                    "date": (r.get("date") or "").strip(),
                    "description": (r.get("description") or "").strip(),
                    "income": income,
                    "expense": expense,
                    "saldo": r.get("saldo"),
                    "is_uncertain": False,
                })
            logger.info("Vision table parse: %d rows extracted from %s", len(cleaned), filename)
            return cleaned
    except httpx.TimeoutException:
        logger.warning("Vision table parse timeout for %s", filename)
        return None
    except Exception:
        logger.exception("Vision table parse failed for %s", filename)
        return None


def merge_ai_into_parsed(parsed: dict, ai_result: dict) -> dict:
    """parse_invoice'in ciktisina AI sonucunu merge eder.

    Politika: AI degeri SADECE local degeri bos/zayif ise ustune yazar.
    Boylece guvenilir local extractions korunur, AI sadece bosluklari doldurur.
    """
    if not parsed or not isinstance(parsed, dict):
        parsed = {}
    if not ai_result or not isinstance(ai_result, dict):
        return parsed
    mergeable = (
        "vendor", "total_amount", "vat_amount", "vat_rate",
        "date", "due_date", "invoice_number", "currency",
        "category", "vendor_email", "vendor_domain",
        "vendor_address", "vendor_iban", "vendor_ust_id",
        "invoice_type",
    )
    changed = []
    for k in mergeable:
        ai_v = ai_result.get(k)
        if ai_v in _EMPTY_VALUES:
            continue
        local_v = parsed.get(k)
        if local_v in _EMPTY_VALUES:
            parsed[k] = ai_v
            changed.append(k)
    if changed:
        parsed["ai_fallback_used"] = True
        parsed["ai_fields_filled"] = changed
    return parsed
