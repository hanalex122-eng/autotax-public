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
  "category": "software|hosting|hardware|office|telecom|advertising|professional|travel|fuel|kfz|transport|bewirtung|restaurant|food|electronics|clothing|health|insurance|bank|fortbildung|miete|other",
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


def _prep_image_for_vision(image_bytes: bytes, content_type: Optional[str]) -> tuple:
    """Resize/normalize a receipt PHOTO for Claude vision — keep COLOR, cap to
    ~2200 px / <4.5 MB. (Grayscale OCR-preprocessing would HURT vision, so this
    is a light color resize only.) On any failure, return the original bytes."""
    try:
        import io as _io
        from PIL import Image, ImageOps
        img = Image.open(_io.BytesIO(image_bytes))
        try:
            img = ImageOps.exif_transpose(img)
        except Exception:
            pass
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        longest = max(img.size)
        if longest > 2200:
            sc = 2200.0 / longest
            img = img.resize((int(img.width * sc), int(img.height * sc)), Image.LANCZOS)
        buf = _io.BytesIO(); img.save(buf, format="JPEG", quality=85)
        out = buf.getvalue()
        if len(out) > 4_500_000:
            img.thumbnail((1600, 1600), Image.LANCZOS)
            buf = _io.BytesIO(); img.save(buf, format="JPEG", quality=80)
            out = buf.getvalue()
        return out, "image/jpeg"
    except Exception as e:
        logger.warning("AI OCR: image prep failed (%s), sending original", e)
        return image_bytes, (content_type or "image/jpeg")


async def ai_extract_invoice(
    pdf_bytes: Optional[bytes] = None,
    ocr_text: str = "",
    filename: str = "",
    model: Optional[str] = None,
    image_bytes: Optional[bytes] = None,
    content_type: Optional[str] = None,
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

    model = (model or os.getenv("AI_OCR_MODEL") or "claude-haiku-4-5-20251001").strip()
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
    elif image_bytes:
        # Receipt PHOTO — send the pixels to Claude vision. Local OCR is weak on
        # receipts (logo/vendor + date area), so the image is primary and the
        # OCR text below is only a supplement.
        try:
            _img, _mt = _prep_image_for_vision(image_bytes, content_type)
            content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": _mt,
                    "data": base64.b64encode(_img).decode(),
                },
            })
        except Exception as e:
            logger.warning("AI OCR: image attach failed: %s", e)

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


# ─── POS / Z-Report parser (Kasa MVP Sprint 2, income side) ───────────

_POS_PROMPT = """You are a German POS daily-closing (Tagesabschluss / Z-Bon) parser for a {business_type} business.

From the attached image/PDF of a daily POS report or receipt, return ONE JSON object with EXACTLY these keys (use null when truly unknown, never invent):
  - business_name: string or null
  - date: "YYYY-MM-DD" or null (the closing/business day)
  - gross_revenue: number (total gross turnover for the day, EUR)
  - net_revenue: number (gross minus VAT)
  - vat_total: number (total VAT)
  - vat_rates: array of objects [{{"rate":"19","net":0,"vat":0}}, {{"rate":"7","net":0,"vat":0}}] — split per VAT rate
  - cash: number (Bar)
  - card: number (Karte/EC/Kreditkarte)
  - tips: number (Trinkgeld) or 0
  - confidence: integer 0-100 (your confidence in the overall extraction)

Rules:
- Amounts as numbers (dot decimal), rounded to 2 decimals. No currency symbols.
- German gastronomy: Speisen außer Haus 7%, Verzehr vor Ort 19%, Getränke usually 19%.
- If gross = net + vat_total does not hold or the figures look inconsistent, LOWER confidence accordingly.
- Return ONLY the JSON object. No fences, no commentary.
"""


async def ai_parse_pos_receipt(
    image_bytes: bytes,
    business_type: str = "",
    content_type: str = "image/jpeg",
    model: Optional[str] = None,
    filename: str = "pos",
) -> Optional[dict]:
    """Parse a POS daily-closing / Z-Report image|PDF into the Kasa income schema.

    Vision-first (Tesseract is weak on receipts). `model` lets the caller route
    (Sonnet default, Opus fallback). Returns the POS dict or None on failure.
    """
    api_key = (os.getenv("ANTHROPIC_API_KEY") or "").strip()
    if not api_key:
        logger.debug("POS parse skip: ANTHROPIC_API_KEY not set")
        return None
    model = (model or os.getenv("KASSE_MODEL_DEFAULT") or "claude-sonnet-4-6").strip()

    block_type = "document" if (content_type or "").lower() == "application/pdf" else "image"
    media_type = "application/pdf" if block_type == "document" else (content_type or "image/jpeg")
    try:
        source = {"type": "base64", "media_type": media_type, "data": base64.b64encode(image_bytes).decode()}
    except Exception as e:
        logger.warning("POS parse: attach failed: %s", e)
        return None

    prompt = _POS_PROMPT.format(business_type=(business_type or "general retail/gastronomy"))
    payload = {
        "model": model,
        "max_tokens": 1024,
        "messages": [{"role": "user", "content": [{"type": block_type, "source": source}, {"type": "text", "text": prompt}]}],
    }
    try:
        async with httpx.AsyncClient(timeout=90) as client:
            r = await client.post(
                "https://api.anthropic.com/v1/messages",
                json=payload,
                headers={"x-api-key": api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            )
            if r.status_code != 200:
                logger.warning("POS parse Anthropic %d for %s: %s", r.status_code, filename, r.text[:300])
                return None
            blocks = (r.json().get("content") or [])
            text = "".join(b.get("text") or "" for b in blocks if b.get("type") == "text")
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
            for k in ("gross_revenue", "net_revenue", "vat_total", "cash", "card", "tips"):
                v = result.get(k)
                if v is not None:
                    try:
                        result[k] = float(v)
                    except (TypeError, ValueError):
                        result[k] = None
            result["_model"] = model
            logger.info("POS parse %s: gross=%s date=%s conf=%s model=%s",
                        filename, result.get("gross_revenue"), result.get("date"), result.get("confidence"), model)
            return result
    except httpx.TimeoutException:
        logger.warning("POS parse timeout for %s", filename)
        return None
    except Exception:
        logger.exception("POS parse failed for %s", filename)
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

Extract EVERY visible data row as JSON. Return ONLY a JSON array — no markdown, no commentary.

CRITICAL: Return ALL rows you can see, including UNCERTAIN ones. Mark uncertainty with "is_uncertain": true.

[
  {
    "row_no": 1,
    "date": "YYYY-MM-DD",
    "description": "Tragetasche Leukotape",
    "income": 0,
    "expense": 26.99,
    "saldo": -8148.23,
    "is_uncertain": false
  },
  ...
]

Rules:
- row_no: sequential row number from the visible table (1, 2, 3 ...). Helps users locate gaps.
- date: convert any format (12.9.21, 9.9.21, 13/09/2021) to YYYY-MM-DD. Use 20YY for 2-digit years.
- income/expense: usually exactly ONE is > 0. income comes ONLY from the Einnahmen column, expense ONLY from the Ausgaben column. If you can't read the amount but the row exists, use null and mark is_uncertain=true.
- CRITICAL: NEVER use the Saldo (running balance, rightmost column) as income or expense. The Saldo is a cumulative total, not the row's amount. If a row's Einnahmen AND Ausgaben are both empty/unreadable, set income=0, expense=null, is_uncertain=true — do NOT fall back to the Saldo value.
- saldo: optional running balance (last column), for reference only — never the amount. null if not visible.
- description: clean if confident, keep as-is if unsure.
- Skip header rows ("Nr/Datum/Beschreibung") and TOTAL/SUMME rows.
- DO include partial rows — mark is_uncertain=true if amount/date unclear.
- Return rows in TABLE ORDER (top to bottom).
- Output ONLY the JSON array. Be COMPLETE — don't stop early."""


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
    # Handwriting için 3500px (önceki 2000 düşüktü, detay kayboluyordu)
    max_size = 5 * 1024 * 1024
    target_width = 3500  # 2000 -> 3500 (handwriting detail)
    jpeg_quality = 92    # 85 -> 92 (better handwriting recognition)
    if len(image_bytes) > max_size or True:  # always reprocess for quality
        try:
            from PIL import Image as _Image
            import io as _io
            img = _Image.open(_io.BytesIO(image_bytes))
            w, h = img.size
            if w > target_width:
                new_w = target_width
                new_h = int(h * (new_w / w))
                img = img.resize((new_w, new_h), _Image.LANCZOS)
            buf = _io.BytesIO()
            img.convert("RGB").save(buf, format="JPEG", quality=jpeg_quality)
            new_bytes = buf.getvalue()
            # Only swap if it fits or smaller than original
            if len(new_bytes) <= max_size:
                image_bytes = new_bytes
                logger.info("Vision table: resized %dx%d → %dx%d (%d KB, q=%d)",
                            w, h, img.width, img.height,
                            len(image_bytes) // 1024, jpeg_quality)
            elif len(image_bytes) > max_size:
                # Original too big, must compress harder
                buf2 = _io.BytesIO()
                img.convert("RGB").save(buf2, format="JPEG", quality=75)
                image_bytes = buf2.getvalue()
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

    # Vision tablo modeli için ayri env override (handwriting -> Sonnet/Opus daha iyi).
    # Default Haiku, Railway env AI_VISION_TABLE_MODEL ile override.
    model = (
        os.getenv("AI_VISION_TABLE_MODEL")
        or os.getenv("AI_OCR_MODEL")
        or "claude-haiku-4-5-20251001"
    ).strip()
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
        # 8192: 50+ satir el yazisi icin (her satir ~150-200 token).
        # Eski 4096'de 32 satir kesiliyordu (4800 token > 4096).
        "max_tokens": 8192,
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
            # Parse JSON array — robust 3-tier fallback
            rows = None
            # 1) Direkt parse
            try:
                rows = json.loads(text)
            except json.JSONDecodeError:
                pass
            # 2) Regex array extract
            if rows is None:
                m = re.search(r"\[[\s\S]*\]", text)
                if m:
                    try:
                        rows = json.loads(m.group(0))
                    except Exception:
                        pass
            # 3) Tek tek satır kurtarma — { } regex tarayarak her satırı dene
            if rows is None:
                rows = []
                row_pattern = re.compile(
                    r'\{\s*"row_no".*?\}', re.DOTALL,
                )
                for m2 in row_pattern.finditer(text):
                    try:
                        single = json.loads(m2.group(0))
                        if isinstance(single, dict):
                            rows.append(single)
                    except Exception:
                        pass
                if rows:
                    logger.warning(
                        "Vision table: JSON cut off but recovered %d rows via regex for %s",
                        len(rows), filename,
                    )
            if not isinstance(rows, list) or not rows:
                logger.warning(
                    "Vision table: zero rows recovered for %s. Response head: %s",
                    filename, text[:300],
                )
                return None

            # Normalize — KEEP uncertain rows (don't silently drop)
            cleaned = []
            uncertain_count = 0
            for r in rows:
                if not isinstance(r, dict):
                    continue
                inc_raw = r.get("income")
                exp_raw = r.get("expense")
                try:
                    income = round(float(inc_raw), 2) if inc_raw not in (None, "") else None
                except (TypeError, ValueError):
                    income = None
                try:
                    expense = round(float(exp_raw), 2) if exp_raw not in (None, "") else None
                except (TypeError, ValueError):
                    expense = None
                ai_uncertain = bool(r.get("is_uncertain"))
                # Mark uncertain if amount fully missing
                is_uncertain = ai_uncertain or (income is None and expense is None)
                if is_uncertain:
                    uncertain_count += 1
                cleaned.append({
                    "row_no": r.get("row_no"),
                    "date": (r.get("date") or "").strip(),
                    "description": (r.get("description") or "").strip(),
                    "income": income if income is not None else 0.0,
                    "expense": expense if expense is not None else 0.0,
                    "saldo": r.get("saldo"),
                    "is_uncertain": is_uncertain,
                })
            logger.info(
                "Vision table parse: %d rows extracted from %s (model=%s, uncertain=%d)",
                len(cleaned), filename, model, uncertain_count,
            )
            # Stash model used so endpoint can include in response
            try:
                cleaned[0]["_meta_model"] = model
                cleaned[0]["_meta_uncertain_count"] = uncertain_count
            except Exception:
                pass
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
