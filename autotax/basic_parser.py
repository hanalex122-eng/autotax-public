"""Basic parser — basit, guvenli, hicbir zaman crash etmez.

Mevcut autotax/parser.py:parse_invoice fonksiyonunu sarmalar. Eger o
patlarsa, bu modul yine de bir sozluk doner — pipeline akmaya devam eder.

Cikti her zaman ayni anahtarlari icerir (eksik alan = bos string / 0).
"""

import logging

logger = logging.getLogger("autotax")

# Pipeline'in her zaman ayni anahtarlari gormesi icin sabit sablon.
DEFAULT_RESULT: dict = {
    "vendor": "",
    "total_amount": 0.0,
    "vat_rate": "",
    "vat_amount": 0.0,
    "date": "",
    "invoice_number": "",
    "payment_method": "",
    "category": "",
    "vendor_iban": "",
    "vendor_email": "",
    "vendor_phone": "",
    "vendor_address": "",
    "vendor_ust_id": "",
    "vendor_hrb": "",
    "vendor_domain": "",
    "raw_text": "",
}


def _empty_result() -> dict:
    return dict(DEFAULT_RESULT)


def parse(ocr_text: str) -> dict:
    """OCR metninden alanlari cikartir.

    Hata olursa: bos default sozluk doner (raw_text icinde OCR metni).
    Asla raise etmez. Asla None donmez.
    """
    if not ocr_text or not isinstance(ocr_text, str):
        return _empty_result()

    try:
        from autotax.parser import parse_invoice
        raw = parse_invoice(ocr_text) or {}
    except Exception as e:
        logger.warning("[BASIC] parse_invoice patladi: %s", e)
        result = _empty_result()
        result["raw_text"] = ocr_text[:5000]
        return result

    # Bilinmeyen alanlar duser, eksikler default ile doldurulur.
    result = _empty_result()
    for key in DEFAULT_RESULT.keys():
        if key in raw and raw[key] is not None:
            result[key] = raw[key]
    if not result.get("raw_text"):
        result["raw_text"] = ocr_text[:5000]
    return result
