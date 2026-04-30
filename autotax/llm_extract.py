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

Rules:
- total_amount = the FINAL amount the customer pays (brutto, not netto)
- vat_rate = the main VAT rate shown (e.g. "19%" or "7%")
- date format MUST be YYYY-MM-DD
- If a field is uncertain, use null — do NOT guess
- Return ONLY the JSON, no explanation

OCR text:
"""


async def llm_extract_invoice(raw_text: str) -> dict:
    """Call Claude Haiku to extract structured invoice data from OCR text.

    Returns dict with extracted fields, or empty dict on any error.
    Never raises — safe to call in any context.
    """
    if not ANTHROPIC_API_KEY or not raw_text or len(raw_text.strip()) < 20:
        return {}

    # Truncate to save tokens (receipts rarely need >2000 chars)
    text = raw_text[:2000]

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
                        {"role": "user", "content": _EXTRACT_PROMPT + text}
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
