"""Confirmed fislerden vendor basina altin ornek cikarip prompt_examples'a yazar.

Manuel veya gece cron olarak calistirilir:
    python -m scripts.learn_from_corrections
    python -m scripts.learn_from_corrections --dry-run
    python -m scripts.learn_from_corrections --limit 100

Algoritma:
    1) status='confirmed' (kullanici PATCH yapmis) + silinmemis fisleri al
    2) Vendor adindan kisa pattern uret (learning.py ile ayni mantik)
    3) Her pattern icin en yeni fisi 'altin ornek' olarak kaydet
    4) PromptExample tablosunda varsa guncelle, yoksa ekle

Bu ornekler llm_extract.py:find_similar_examples tarafindan few-shot
RAG icin kullanilir — sonraki LLM cagrilarinda dogruluk artirir.
"""

import argparse
import json
import logging
import sys
from collections import defaultdict

from autotax.db import SessionLocal
from autotax.models import Invoice, PromptExample

logger = logging.getLogger("autotax.learn_from_corrections")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


def extract_pattern(vendor: str) -> str:
    """vendor adindan kisa eslestirme anahtari uret. learning._extract_keyword
    ile birebir uyumlu — apply_learning_rules + few-shot ayni pattern'i gorsun."""
    if not vendor:
        return ""
    if vendor in ("Unbekannt", ""):
        return ""
    words = vendor.lower().strip().split()
    for w in words:
        clean = "".join(c for c in w if c.isalpha())
        if len(clean) >= 3:
            return clean[:30]
    return vendor.lower().strip()[:30]


def invoice_to_expected_json(inv: Invoice) -> dict:
    """LLM prompt sablonundaki alanlarla bire bir esleyen JSON uret."""
    def _f(v):
        if v in (None, "", "0%"):
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    return {
        "vendor_name": inv.vendor or None,
        "total_amount": _f(inv.total_amount),
        "vat_rate": inv.vat_rate or None,
        "vat_amount": _f(inv.vat_amount),
        "date": inv.date or None,
        "invoice_number": inv.invoice_number or None,
        "payment_method": inv.payment_method or None,
        "category": inv.category or None,
        "vendor_iban": inv.vendor_iban or None,
        "vendor_email": inv.vendor_email or None,
        "vendor_phone": inv.vendor_phone or None,
        "vendor_address": inv.vendor_address or None,
    }


def run(dry_run: bool = False, limit: int = 50, min_text_len: int = 50) -> int:
    """confirmed fislerden ornek cikar. Donus: yazilan/guncellenen kayit sayisi."""
    db = SessionLocal()
    try:
        invoices = (
            db.query(Invoice)
            .filter(Invoice.status == "confirmed")
            .filter((Invoice.is_deleted == False) | (Invoice.is_deleted.is_(None)))  # noqa: E712
            .order_by(Invoice.id.desc())
            .all()
        )
        if not invoices:
            logger.info("confirmed durumda fis yok — hicbir sey yapilmadi")
            return 0

        groups: dict[str, list[Invoice]] = defaultdict(list)
        for inv in invoices:
            pat = extract_pattern(inv.vendor or "")
            if not pat:
                continue
            if not inv.raw_text or len(inv.raw_text) < min_text_len:
                continue
            groups[pat].append(inv)

        upserted = 0
        skipped = 0
        for pattern, invs in groups.items():
            invs.sort(key=lambda i: i.id, reverse=True)
            top = invs[0]
            expected = invoice_to_expected_json(top)
            expected_str = json.dumps(expected, ensure_ascii=False)
            ocr_text = top.raw_text or ""

            existing = (
                db.query(PromptExample)
                .filter(PromptExample.vendor_pattern == pattern)
                .first()
            )
            if existing:
                # Icerik aynidaysa atla
                same_json = (existing.expected_json or "") == expected_str
                same_ocr = (existing.ocr_text or "")[:500] == ocr_text[:500]
                if same_json and same_ocr:
                    skipped += 1
                    continue
                if not dry_run:
                    existing.ocr_text = ocr_text
                    existing.expected_json = expected_str
                upserted += 1
                logger.info("guncellendi: pattern=%s invoice_id=%s", pattern, top.id)
            else:
                if not dry_run:
                    db.add(PromptExample(
                        vendor_pattern=pattern,
                        ocr_text=ocr_text,
                        expected_json=expected_str,
                        quality_score=1.0,
                    ))
                upserted += 1
                logger.info("yeni: pattern=%s invoice_id=%s", pattern, top.id)

            if upserted >= limit:
                logger.info("limit (%d) doldu, durduruluyor", limit)
                break

        if dry_run:
            db.rollback()
            logger.info("[DRY-RUN] %d kayit yazilacakti, %d aynisi", upserted, skipped)
        else:
            db.commit()
            logger.info("yazildi: %d, atlandi: %d, toplam vendor: %d",
                        upserted, skipped, len(groups))
        return upserted
    except Exception:
        db.rollback()
        logger.exception("learn_from_corrections basarisiz")
        return -1
    finally:
        db.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true",
                    help="hicbir DB yazimi yapmaz, sadece ne yapacagini loglar")
    ap.add_argument("--limit", type=int, default=50,
                    help="Tek calistirmada en fazla yazilacak kayit (varsayilan 50)")
    ap.add_argument("--min-text-len", type=int, default=50,
                    help="Bu uzunluktan kisa raw_text'li fisler atlanir")
    args = ap.parse_args()
    code = run(args.dry_run, args.limit, args.min_text_len)
    sys.exit(0 if code >= 0 else 1)


if __name__ == "__main__":
    main()
