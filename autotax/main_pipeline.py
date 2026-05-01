"""Ana fis isleme pipeline'i — guvenli, fallback'li, asla crash etmez.

Akis:
    OCR text -> basic_parser -> ai_parser -> merge -> vendor identity match

Tasarim ilkeleri:
- Her adim bagimsiz: biri patlasa digerleri yine calisir.
- AI bos veya hatali ise basic sonuclari kullanilir (fallback).
- Donus her zaman bir sozluk; en kotu durumda DEFAULT_RESULT'in kopyasi.
- Mevcut autotax/parser.py, llm_extract.py, vendor_identity.py modullerini
  KULLANIR ama degistirmez.
"""

import asyncio
import logging
from typing import Optional

from autotax import basic_parser, ai_parser

logger = logging.getLogger("autotax")

# AI alanini basic alanina cevirme — _merge sirasinda kullanilir.
_AI_TO_BASIC = ai_parser.AI_FIELD_MAP

# AI'in ezebilecegi 'default' kabul edilen degerler.
_DEFAULT_VALUES = {"", None, 0, 0.0, "Unbekannt", "other", "0%"}


def _is_default(value) -> bool:
    if value in _DEFAULT_VALUES:
        return True
    if isinstance(value, str) and not value.strip():
        return True
    return False


def _merge(basic: dict, ai: dict) -> dict:
    """basic'i temel al; AI alanlari sadece basic'te bos/default ise doldurur.

    Asla raise etmez. AI bos veya gecersizse basic aynen doner.
    """
    if not isinstance(basic, dict):
        basic = basic_parser._empty_result()
    if not ai or not isinstance(ai, dict):
        return dict(basic)

    merged = dict(basic)
    for ai_key, basic_key in _AI_TO_BASIC.items():
        ai_val = ai.get(ai_key)
        if ai_val in (None, ""):
            continue
        if _is_default(merged.get(basic_key)):
            merged[basic_key] = ai_val

    # Numerik alanlari guvenli sekilde float'a cevir
    for fkey in ("total_amount", "vat_amount"):
        try:
            v = merged.get(fkey)
            if v not in (None, ""):
                merged[fkey] = float(v)
        except (TypeError, ValueError):
            merged[fkey] = 0.0

    return merged


def _apply_vendor_match(merged: dict, user_id: int) -> dict:
    """vendor_identity.match_vendor cagirir; eslesme varsa vendor adi kilitle."""
    try:
        from autotax.vendor_identity import match_vendor
    except Exception as e:
        logger.warning("[PIPELINE] vendor_identity import basarisiz: %s", e)
        return merged

    try:
        identity_fields = {
            "ust_id": merged.get("vendor_ust_id"),
            "iban": merged.get("vendor_iban"),
            "hrb": merged.get("vendor_hrb"),
            "email": merged.get("vendor_email"),
            "domain": merged.get("vendor_domain"),
            "phone": merged.get("vendor_phone"),
        }
        v = match_vendor(user_id, identity_fields=identity_fields)
        if not v:
            return merged

        cur_vendor = (merged.get("vendor") or "").strip()
        # Yuksek guven esigi: ust_id/iban/hrb (>= 0.90). Phone/email/domain
        # gibi zayif anahtarlarda yanlis vendor adi kilitlenmesin.
        HIGH_CONF = 0.90
        high_conf = v.score >= HIGH_CONF

        if high_conf and (
            not cur_vendor
            or cur_vendor in ("Unbekannt", "Manual Entry")
            or len(cur_vendor) < 3
            or v.score >= 0.95
        ):
            merged["vendor"] = v.vendor_name

        # Default'lar yalnizca yuksek guvenli eslesmede ezilir
        if high_conf:
            if v.default_vat_rate and _is_default(merged.get("vat_rate")):
                merged["vat_rate"] = v.default_vat_rate
            if v.default_category and _is_default(merged.get("category")):
                merged["category"] = v.default_category
            if v.default_payment_method and _is_default(merged.get("payment_method")):
                merged["payment_method"] = v.default_payment_method
    except Exception as e:
        logger.warning("[PIPELINE] vendor match patladi: %s", e)

    return merged


async def process(ocr_text: str, user_id: Optional[int] = None) -> dict:
    """Tum akisi tek cagrida calistir. Asla raise etmez.

    ocr_text: OCR'den gelen ham metin (caller asagidaki extract_text_and_qr
              gibi bir fonksiyonla once OCR yapmali).
    user_id:  vendor_identity eslesmesi icin gerekli; None ise vendor match adimi atlanir.

    Donus: her zaman bir sozluk. Anahtar kumesi basic_parser.DEFAULT_RESULT
           ile aynidir.
    """
    # 1) Basic parser
    try:
        basic_result = basic_parser.parse(ocr_text or "")
    except Exception as e:
        logger.warning("[PIPELINE] basic adim patladi: %s", e)
        basic_result = basic_parser._empty_result()

    # 2) AI parser
    try:
        ai_result = await ai_parser.parse(ocr_text or "")
    except Exception as e:
        logger.warning("[PIPELINE] ai adim patladi: %s", e)
        ai_result = {}

    # 3) Merge — AI fail olursa basic aynen kalir
    try:
        merged = _merge(basic_result, ai_result)
    except Exception as e:
        logger.warning("[PIPELINE] merge patladi: %s", e)
        merged = dict(basic_result)

    # 4) Vendor identity match (opsiyonel)
    if user_id is not None:
        merged = _apply_vendor_match(merged, user_id)

    return merged


def process_sync(ocr_text: str, user_id: Optional[int] = None) -> dict:
    """Senkron sarmalayici — async olmayan kontekstler icin."""
    try:
        return asyncio.run(process(ocr_text, user_id))
    except RuntimeError:
        # Zaten event loop var — async process() cagrilmali
        logger.warning("[PIPELINE] process_sync mevcut loop icinde cagrildi; "
                       "await process() kullanin")
        # Yine de basic + (varsa) vendor match calistir, AI'i atla
        try:
            basic_result = basic_parser.parse(ocr_text or "")
            if user_id is not None:
                basic_result = _apply_vendor_match(basic_result, user_id)
            return basic_result
        except Exception as e:
            logger.warning("[PIPELINE] sync fallback patladi: %s", e)
            return basic_parser._empty_result()
    except Exception as e:
        logger.warning("[PIPELINE] process_sync hatasi: %s", e)
        return basic_parser._empty_result()
