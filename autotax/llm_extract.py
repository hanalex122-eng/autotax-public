"""LLM-based invoice extraction fallback.

Called ONLY when parser.py returns weak results (Unbekannt vendor,
zero total, empty date). Uses Claude Haiku for speed + low cost.

Cost: ~$0.001 per receipt (500 input tokens avg).
Latency: ~1-2 seconds.
Fallback: returns empty dict on any error — never blocks upload.

Does NOT replace parser.py. Fills gaps only.
"""

import os
import json
import logging
import httpx

logger = logging.getLogger("autotax")

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
MODEL = "claude-haiku-4-5-20251001"

_EXTRACT_PROMPT = """Extract structured data from this receipt/invoice OCR text.
Return ONLY a JSON object with these fields (use null if not found):

{
  "vendor_name": "store or company name",
  "total_amount": 0.00,
  "vat_rate": "19%",
  "vat_amount": 0.00,
  "date": "YYYY-MM-DD",
  "invoice_number": "RE-2026-001",
  "payment_method": "card|cash|transfer|paypal|null",
  "category": "food|fuel|clothing|electronics|office|restaurant|health|transport|telecom|other",
  "vendor_iban": "DE89 3704 0044 0532 0130 00",
  "vendor_email": "info@example.de",
  "vendor_phone": "+49 681 12345",
  "vendor_address": "Musterstr. 1, 66111 Saarbrücken"
}

CRITICAL RULE — NO HALLUCINATION:
This rule overrides every other rule below.
- NEVER invent or guess any field value. If a value is not LITERALLY visible
  in the OCR text below, return null for that field.
- vendor_iban: ONLY return a value if the OCR text contains the literal word
  "IBAN" followed by a country code (DE/AT/CH/...) and digits that you can
  read character-by-character. If the IBAN is not literally typed in the
  text, return null. NEVER fabricate digits to "complete" a partial IBAN.
- vendor_phone: ONLY return a value if a phone-style label ("Tel", "Telefon",
  "Phone", "Fax") appears in the text followed by digits. Dates and invoice
  numbers are NOT phone numbers. If unsure, null.
- vendor_email: ONLY return if a literal "@" character appears in the text
  with letters before and after it. Otherwise null.
- vendor_address: ONLY return if a street keyword (Str./Strasse/Weg/Platz/...)
  or a 5-digit German postal code appears in the text. Otherwise null.
- vendor_name: vendor_name is the company/store. If multiple candidates,
  prefer ALL-UPPERCASE words at the top of the receipt (ARAL, LIDL, REWE,
  SHELL etc.). If you cannot identify a clear name, return null.
- total_amount: ONLY return a number that LITERALLY appears in the text near
  a total label (Gesamt, Summe, Total, Endbetrag, Brutto, zu zahlen). If no
  such number is visible, return 0.

Other rules:
- total_amount = the FINAL amount the customer pays (brutto, not netto)
- vat_rate = the main VAT rate shown (e.g. "19%" or "7%")
- date format MUST be YYYY-MM-DD
- Return ONLY the JSON, no explanation

REMEMBER: Returning null is ALWAYS better than guessing. Wrong data
corrupts the user's accounting. Empty data is fixable; fabricated data is not.

OCR text:
"""


# Few-shot konfigurasyonu — token tasarrufu vs dogruluk arasindaki denge.
# Cok ornek = pahali ama dogru; az ornek = ucuz ama daha az ogrenme.
FEW_SHOT_LIMIT = 3                 # Her cagrida en fazla N ornek
FEW_SHOT_OCR_TRUNC = 800           # Her ornegin OCR metni bu boyuta kirpilir
FEW_SHOT_MIN_PATTERN_LEN = 3       # Cok kisa pattern'ler (1-2 char) atlanir


def find_similar_examples(raw_text: str, limit: int = FEW_SHOT_LIMIT) -> list:
    """PromptExample tablosundan, vendor_pattern'i raw_text'in icinde gecen
    ornekleri ceker. quality_score azalan + son kullanim eski once siralanir.

    Esleme: case-insensitive substring. Kisa pattern (< 3 char) atlanir.
    Donus: list[PromptExample]. Hata olursa boş liste — asla raise etmez.
    """
    if not raw_text or len(raw_text) < 10:
        return []
    try:
        from autotax.db import SessionLocal
        from autotax.models import PromptExample
    except Exception:
        return []

    text_lower = raw_text.lower()
    db = SessionLocal()
    try:
        all_examples = db.query(PromptExample).all()
        if not all_examples:
            return []
        matched = []
        for ex in all_examples:
            pat = (ex.vendor_pattern or "").strip().lower()
            if len(pat) < FEW_SHOT_MIN_PATTERN_LEN:
                continue
            if pat in text_lower:
                matched.append(ex)
        # Yuksek skor + cok kullanilmis once
        matched.sort(key=lambda e: (-(e.quality_score or 0), -(e.use_count or 0)))
        selected = matched[:limit]

        # Kullanim sayaci + zaman damgasi guncelle (best-effort)
        if selected:
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc)
            for ex in selected:
                ex.use_count = (ex.use_count or 0) + 1
                ex.last_used_at = now
            try:
                db.commit()
            except Exception:
                db.rollback()
            logger.info(
                "[LLM] few-shot %d ornek bulundu (patterns=%s)",
                len(selected),
                [e.vendor_pattern for e in selected],
            )
        return selected
    except Exception as e:
        logger.warning("[LLM] few-shot lookup basarisiz: %s", e)
        return []
    finally:
        db.close()


def _build_few_shot_block(examples: list) -> str:
    """Few-shot ornek listesini prompt'a enjekte edilebilir text bloga cevir."""
    if not examples:
        return ""
    parts = ["Once benzer fislerden bazi dogru cevap ornekleri:\n"]
    for i, ex in enumerate(examples, 1):
        ocr = (ex.ocr_text or "")[:FEW_SHOT_OCR_TRUNC]
        expected = ex.expected_json or "{}"
        parts.append(
            f"\n--- ORNEK {i} (vendor pattern: {ex.vendor_pattern}) ---\n"
            f"OCR:\n{ocr}\n"
            f"Beklenen JSON:\n{expected}\n"
        )
    parts.append("\n--- Simdi asagidaki fisi ayni formatta cikar ---\n")
    return "".join(parts)


async def llm_extract_invoice(raw_text: str) -> dict:
    """Call Claude Haiku to extract structured invoice data from OCR text.

    Few-shot RAG: PromptExample tablosunda eslesen ornek varsa prompt'a
    enjekte edilir; yoksa ham (eski) prompt kullanilir.

    Returns dict with extracted fields, or empty dict on any error.
    Never raises — safe to call in any context.
    """
    if not ANTHROPIC_API_KEY or not raw_text or len(raw_text.strip()) < 20:
        return {}

    # Truncate to save tokens (receipts rarely need >2000 chars)
    text = raw_text[:2000]

    # Few-shot ornekleri al (varsa) ve prompt'i kur
    examples = find_similar_examples(text)
    few_shot_block = _build_few_shot_block(examples)
    user_content = _EXTRACT_PROMPT + few_shot_block + text

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                ANTHROPIC_API_URL,
                headers={
                    "x-api-key": ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": MODEL,
                    "max_tokens": 500,
                    "messages": [
                        {"role": "user", "content": user_content}
                    ],
                },
            )
            resp.raise_for_status()
            data = resp.json()

            # Extract text content from Claude response
            content = data.get("content", [])
            if not content:
                return {}
            response_text = content[0].get("text", "").strip()

            # Parse JSON from response (handle markdown code blocks)
            if response_text.startswith("```"):
                response_text = response_text.split("```")[1]
                if response_text.startswith("json"):
                    response_text = response_text[4:]
            response_text = response_text.strip()

            result = json.loads(response_text)
            # Defensive validation — LLM uydurma yapsa bile yakala.
            # Aral fisi gibi durumlarda model "muhtemelen ARAL'in IBAN'i sudur"
            # diye 22 haneli sayi uretmisti. Bu katman onu null'a duser.
            result = _validate_against_ocr(result, raw_text)
            logger.info("[LLM] extracted: vendor=%s total=%s date=%s",
                        result.get("vendor_name"), result.get("total_amount"), result.get("date"))
            return result

    except httpx.TimeoutException:
        logger.warning("[LLM] timeout after 15s")
        return {}
    except json.JSONDecodeError as e:
        logger.warning("[LLM] invalid JSON response: %s", e)
        return {}
    except Exception as e:
        logger.warning("[LLM] extraction failed: %s", e)
        return {}


def _digits_in(text: str) -> str:
    """Return only the digits in `text`, used for substring search of numeric IDs."""
    return "".join(c for c in (text or "") if c.isdigit())


def _validate_against_ocr(result: dict, raw_text: str) -> dict:
    """LLM ciktisini OCR text'ine karsi dogrular. OCR'da iz olmayan alanlari
    null'a duser — uydurma karsi son savunma katmani.

    Kontroller:
    - vendor_iban: IBAN'in tum rakamlari OCR'da art arda gecmiyorsa null
    - vendor_phone: telefonun rakam dizisi OCR'da gecmiyorsa null
    - vendor_email: tam @ adresi OCR'da yoksa null
    - vendor_address: temel parcalardan biri (PLZ, Strasse, vb.) OCR'da yoksa null

    Asla raise etmez. Donus: ayni dict, riskli alanlar null yapilmis.
    """
    if not result or not isinstance(result, dict):
        return result or {}
    if not raw_text:
        return result

    text_lower = raw_text.lower()
    text_digits = _digits_in(raw_text)

    # IBAN — rakam dizisi OCR'da art arda yoksa null. Cok agresif: LLM sahte
    # olusturduysa rakamlarin hicbiri OCR'da yan yana gozukmez.
    iban = (result.get("vendor_iban") or "").strip()
    if iban:
        iban_digits = _digits_in(iban)
        # En az son 8 rakaminin OCR digit-stream'inde art arda olmasi beklenir
        if len(iban_digits) >= 8 and iban_digits[-8:] not in text_digits:
            logger.warning("[LLM_VALIDATE] uydurma IBAN reddedildi: %s", iban[:6] + "...")
            result["vendor_iban"] = None

    # Phone — rakam dizisi OCR'da art arda yoksa null
    phone = (result.get("vendor_phone") or "").strip()
    if phone:
        phone_digits = _digits_in(phone)
        if len(phone_digits) >= 7 and phone_digits[-7:] not in text_digits:
            logger.warning("[LLM_VALIDATE] uydurma telefon reddedildi: %s", phone)
            result["vendor_phone"] = None

    # Email — tam adres OCR'da olmali
    email = (result.get("vendor_email") or "").strip().lower()
    if email and email not in text_lower:
        logger.warning("[LLM_VALIDATE] uydurma email reddedildi: %s", email)
        result["vendor_email"] = None

    # Address — sokak anahtar kelimesi veya 5-haneli PLZ OCR'da olmali
    address = (result.get("vendor_address") or "").strip()
    if address:
        addr_lower = address.lower()
        has_keyword = any(kw in addr_lower for kw in
                          ("str.", "straße", "strasse", "weg", "platz", "allee",
                           "gasse", "ring", "damm", "ufer"))
        # PLZ kontrolu — adresteki 5 haneli kod OCR'da bulunmali
        import re as _re_inner
        plz_match = _re_inner.search(r"\b\d{5}\b", address)
        plz_ok = plz_match and plz_match.group() in raw_text
        # En az birinin OCR'da iz birakmasi gerekir
        text_words = text_lower.split()
        addr_words = [w for w in addr_lower.split() if len(w) >= 4]
        any_word_in_text = any(w in text_lower for w in addr_words)
        if not (has_keyword and any_word_in_text) and not plz_ok:
            logger.warning("[LLM_VALIDATE] uydurma adres reddedildi: %s", address[:40])
            result["vendor_address"] = None

    # USt-IdNr — DE + 9 rakam OCR'da olmali
    ust = (result.get("vendor_ust_id") or "").strip().upper().replace(" ", "")
    if ust:
        ust_digits = _digits_in(ust)
        if len(ust_digits) >= 9 and ust_digits not in text_digits:
            logger.warning("[LLM_VALIDATE] uydurma USt-IdNr reddedildi: %s", ust)
            result["vendor_ust_id"] = None

    return result


def merge_with_parser(parser_result: dict, llm_result: dict) -> dict:
    """Merge LLM extraction with parser result. Parser wins when it has
    a meaningful value; LLM fills gaps where parser returned defaults.

    Rules:
      - vendor: LLM wins if parser returned 'Unbekannt'
      - total_amount: LLM wins if parser returned 0
      - date: LLM wins if parser returned '' or today's date
      - vat_rate: LLM wins if parser returned '0%'
      - Other fields: LLM fills only if parser field is empty/null
    """
    if not llm_result:
        return parser_result

    merged = dict(parser_result)

    # Vendor
    if merged.get("vendor") in ("Unbekannt", "", None) and llm_result.get("vendor_name"):
        merged["vendor"] = llm_result["vendor_name"]
        logger.info("[LLM] filled vendor: %s", merged["vendor"])

    # Total
    if (not merged.get("total_amount") or merged["total_amount"] == 0) and llm_result.get("total_amount"):
        try:
            merged["total_amount"] = float(llm_result["total_amount"])
            logger.info("[LLM] filled total: %s", merged["total_amount"])
        except (ValueError, TypeError):
            pass

    # Date — only fill if parser returned NOTHING (empty/None).
    # Do NOT override today's date: parser uses today as fallback when
    # it can't find a date, but sometimes today IS the real receipt date.
    # The needs_llm_fallback() function already uses the "today = weak"
    # heuristic for TRIGGERING the LLM call, but once in merge we should
    # only fill genuinely empty dates to avoid false overrides.
    if merged.get("date") in ("", None) and llm_result.get("date"):
        merged["date"] = llm_result["date"]
        logger.info("[LLM] filled date: %s", merged["date"])

    # VAT rate
    if merged.get("vat_rate") in ("0%", "", None) and llm_result.get("vat_rate"):
        merged["vat_rate"] = llm_result["vat_rate"]

    # VAT amount
    if (not merged.get("vat_amount") or merged["vat_amount"] == 0) and llm_result.get("vat_amount"):
        try:
            merged["vat_amount"] = float(llm_result["vat_amount"])
        except (ValueError, TypeError):
            pass

    # Invoice number
    if not merged.get("invoice_number") and llm_result.get("invoice_number"):
        merged["invoice_number"] = llm_result["invoice_number"]

    # Payment method
    if not merged.get("payment_method") and llm_result.get("payment_method"):
        merged["payment_method"] = llm_result["payment_method"]

    # Category — only if parser defaulted to 'other'
    if merged.get("category") in ("other", "", None) and llm_result.get("category"):
        merged["category"] = llm_result["category"]

    # Contact info — LLM fills if parser missed
    llm_fields = []
    for field in ("vendor_iban", "vendor_email", "vendor_phone", "vendor_address"):
        if not merged.get(field) and llm_result.get(field):
            merged[field] = llm_result[field]
            llm_fields.append(field)
    if llm_fields:
        logger.info("[LLM] filled contact: %s", ", ".join(llm_fields))

    return merged


def needs_llm_fallback(parser_result: dict) -> bool:
    """Check if parser result is weak enough to justify an LLM call.

    Returns True if TWO OR MORE of these conditions are true:
      - vendor is 'Unbekannt' or empty
      - total_amount is 0 or missing
      - date is empty or today's date

    Single weak field = not worth the API cost.
    Multiple weak fields = OCR or parser struggled, LLM can help.
    """
    weak = 0
    if parser_result.get("vendor") in ("Unbekannt", "", None):
        weak += 1
    if not parser_result.get("total_amount") or parser_result["total_amount"] == 0:
        weak += 1
    from datetime import datetime
    today = datetime.now().strftime("%Y-%m-%d")
    if parser_result.get("date") in ("", None, today):
        weak += 1
    return weak >= 2
