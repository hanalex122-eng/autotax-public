"""AI parser — Claude Haiku ile yapilandirilmis cikartim.

Mevcut autotax/llm_extract.py:llm_extract_invoice fonksiyonunu sarmalar.
Hicbir durumda raise etmez — hata, timeout, API_KEY yok, bos OCR — hepsi
bos dict ({}) ile sonuclanir. Pipeline akmaya devam eder.
"""

import asyncio
import logging

logger = logging.getLogger("autotax")

# AI tarafindan donen alan adlari basic parser ile farkli — merge sirasinda
# main_pipeline._merge() bu eslemeyi kullanir.
AI_FIELD_MAP: dict = {
    "vendor_name": "vendor",
    "total_amount": "total_amount",
    "vat_rate": "vat_rate",
    "vat_amount": "vat_amount",
    "date": "date",
    "invoice_number": "invoice_number",
    "payment_method": "payment_method",
    "category": "category",
    "vendor_iban": "vendor_iban",
    "vendor_email": "vendor_email",
    "vendor_phone": "vendor_phone",
    "vendor_address": "vendor_address",
}


async def parse(ocr_text: str) -> dict:
    """OCR metnini LLM'e verir, yapilandirilmis sozluk doner.

    Donus AI sema'sinda (vendor_name, total_amount, ...). Bos veya hata: {}.
    """
    if not ocr_text or not isinstance(ocr_text, str):
        return {}
    if len(ocr_text.strip()) < 20:
        # Cok kisa metin — LLM'e harcamaya degmez
        return {}

    try:
        from autotax.llm_extract import llm_extract_invoice
        result = await llm_extract_invoice(ocr_text)
        return result or {}
    except Exception as e:
        logger.warning("[AI] llm_extract_invoice patladi: %s", e)
        return {}


def parse_sync(ocr_text: str) -> dict:
    """Senkron sarmalayici — async event-loop disindan cagriler icin."""
    try:
        return asyncio.run(parse(ocr_text))
    except RuntimeError:
        # Zaten bir event loop calisiyor — bu durumda async parse() kullan
        logger.warning("[AI] parse_sync mevcut loop icinde cagrildi; await parse() kullanin")
        return {}
    except Exception as e:
        logger.warning("[AI] parse_sync hatasi: %s", e)
        return {}
