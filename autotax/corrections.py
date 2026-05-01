"""Kullanici duzeltmelerinin ham log servisi.

_do_update_invoice her PATCH/PUT'ta bu modulu cagirir; degisen alanlari
Correction tablosuna yazar. LearningRule sadece anahtar kelime + son deger
tutarken, bu tablo tam diff + duzeltme anindaki OCR snapshot saklar.

learn_from_corrections.py gece job'u bu kayitlardan vendor basina altin
ornek (PromptExample) cikarir — few-shot RAG'in yakiti.
"""

import json
import logging

from autotax.db import SessionLocal
from autotax.models import Correction

logger = logging.getLogger("autotax")

# Sadece bu alanlar correction olarak loglanir. processed/status gibi
# meta-alanlar duzeltme degil, sistem alanidir — atlanir.
LOGGABLE_FIELDS = {
    "vendor", "category", "total_amount", "vat_amount", "vat_rate",
    "date", "invoice_type", "invoice_number", "payment_method",
}

# OCR snapshot icin maksimum boyut — disk/DB tasmasini onler.
OCR_SNAPSHOT_MAX = 4000


def _serialize(value) -> str:
    """Herhangi bir degeri stabil JSON string'e cevir. None -> 'null'."""
    try:
        return json.dumps(value, default=str, ensure_ascii=False)
    except Exception:
        return json.dumps(str(value), ensure_ascii=False)


def log_corrections(
    invoice_id: int,
    user_id: int,
    original: dict,
    edited: dict,
    ocr_text: str = "",
    vendor: str = "",
) -> int:
    """Original ile edited arasindaki farklari Correction tablosuna yazar.

    - original: PATCH'ten ONCEKI tum izlenebilir alanlarin sozlugu
    - edited: PATCH body'sinin None olmayan alanlari
    - ocr_text: duzeltme aninda invoice.raw_text — snapshot olarak saklanir
    - vendor: invoice.vendor (snapshot indeksleme icin)

    Donus: kaydedilen Correction sayisi. Hata olursa 0 doner ve loglanir;
    asla raise etmez (PATCH akisini bozmamali).
    """
    if not edited:
        return 0

    snapshot = (ocr_text or "")[:OCR_SNAPSHOT_MAX]
    vendor_snap = (vendor or "")[:200]

    saved = 0
    db = SessionLocal()
    try:
        for field, new_val in edited.items():
            if field not in LOGGABLE_FIELDS:
                continue
            if new_val is None:
                continue
            old_val = original.get(field)
            # Esit degerleri loglamiyoruz — gercek bir duzeltme degil
            if str(old_val).strip() == str(new_val).strip():
                continue
            db.add(Correction(
                invoice_id=invoice_id,
                user_id=user_id,
                field_name=field,
                old_value=_serialize(old_val),
                new_value=_serialize(new_val),
                ocr_text_snapshot=snapshot,
                vendor_at_correction=vendor_snap,
            ))
            saved += 1

        if saved > 0:
            db.commit()
            logger.info(
                "[CORRECTIONS] %d alan loglandi invoice_id=%s vendor=%r",
                saved, invoice_id, vendor_snap,
            )
    except Exception as e:
        db.rollback()
        logger.warning("[CORRECTIONS] yazma basarisiz invoice_id=%s: %s", invoice_id, e)
        saved = 0
    finally:
        db.close()

    return saved
