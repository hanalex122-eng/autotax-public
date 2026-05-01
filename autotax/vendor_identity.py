"""Vendor kimlik parmak izi servisi.

Beleg hinzufugen formundan manuel girilen vendor bilgileri (USt-IdNr, IBAN,
HRB, telefon, email, adres) VendorIdentity tablosuna saklanir. Yeni bir fis
yuklendiginde, OCR'dan ayni kimlik anahtarlari cikarilir ve burada eslesme
aranir; eslesme bulundugunda vendor adi OCR bozulmasindan bagimsiz olarak
dogru gelir.

Eslestirme onceligi (en guvenilirden en zayifa):
    1. ust_id   — DE143571783 (KDV no)
    2. iban     — DE89370400440532013000
    3. hrb      — HRB 23012
    4. email    — info@firma.de
    5. domain   — firma.de
    6. phone    — +49 681 123456

Phone en zayifi cunku OCR'da rakam bozulmasi en sik bunda olur ve cep/sabit
ayrim yapmiyoruz. Domain telefondan once cunku ASCII karakter dizisi.
"""

import logging
import re
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from autotax.db import SessionLocal
from autotax.models import VendorIdentity, Invoice

logger = logging.getLogger("autotax")

# Hangi alanlarda eslesme aranir, oncelik sirasiyla
MATCH_KEYS_PRIORITY = ("ust_id", "iban", "hrb", "email", "domain", "phone")

# Eslestirme guven skorlari — match() bu degeri match.score olarak doner
MATCH_SCORE = {
    "ust_id": 1.00,    # USt-IdNr cok benzersiz, OCR'da bozulma riski az
    "iban": 0.98,
    "hrb": 0.92,
    "email": 0.85,
    "domain": 0.75,
    "phone": 0.65,
}

# OCR'dan kimlik cikartmak icin regex'ler — parser.extract_entities ile uyumlu
_USTID_PAT = re.compile(r"(?i)\b(DE)\s?(\d{3}\s?\d{3}\s?\d{3})\b")
_IBAN_PAT = re.compile(r"\b([A-Z]{2}\s?\d{2}\s?(?:\d{4}\s?){2,7}\d{1,4})\b")
_HRB_PAT = re.compile(r"(?i)\b(HR[BA])\s+(?:[A-ZÄÖÜ][a-zäöüß]+\s+)?(\d{1,7})\b")
_EMAIL_PAT = re.compile(r"\b([a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})\b")
_DOMAIN_PAT = re.compile(r"(?i)\b(?:www\.)?([a-z0-9\-]{2,}\.(?:de|com|at|ch|eu|net|org|shop))\b")
_PHONE_PAT = re.compile(r"(?:\+\d{1,3}[\s\-]?)?(?:\(?\d{2,5}\)?[\s\-]?)?\d{3,4}[\s\-]?\d{2,6}")


def _normalize(value: Optional[str], kind: str) -> Optional[str]:
    """Kimlik anahtarlarini eslestirme icin standartlastirir."""
    if not value:
        return None
    v = str(value).strip()
    if kind == "iban":
        return v.replace(" ", "").upper()
    if kind == "ust_id":
        return v.replace(" ", "").upper()
    if kind == "hrb":
        # "HRB 12345" -> "HRB 12345" (tek bosluk)
        m = _HRB_PAT.search(v)
        if m:
            return f"{m.group(1).upper()} {m.group(2)}"
        return v.upper()
    if kind == "email":
        return v.lower()
    if kind == "domain":
        return v.lower().replace("www.", "")
    if kind == "phone":
        # Sadece rakam + + isareti
        return re.sub(r"[^\d+]", "", v)
    return v


def extract_identity_from_text(ocr_text: str) -> dict:
    """OCR metninden kimlik anahtarlarini cikarir. parser.extract_entities'den
    bagimsiz calisir — vendor_identity modulu standalone kullanilabilsin diye."""
    if not ocr_text:
        return {}
    raw_ust = _USTID_PAT.findall(ocr_text)
    ust_ids = ["DE" + n.replace(" ", "") for _, n in raw_ust]

    raw_iban = _IBAN_PAT.findall(ocr_text.upper())
    ibans = [i.replace(" ", "") for i in raw_iban if len(i.replace(" ", "")) >= 15]

    raw_hrb = _HRB_PAT.findall(ocr_text)
    hrbs = [f"{p.upper()} {n}" for p, n in raw_hrb]

    emails = [e.lower() for e in _EMAIL_PAT.findall(ocr_text)]
    domains = [d.lower() for d in _DOMAIN_PAT.findall(ocr_text)]

    raw_phones = _PHONE_PAT.findall(ocr_text)
    phones = [_normalize(p, "phone") for p in raw_phones
              if len(re.sub(r"[^\d]", "", p)) >= 8]

    return {
        "ust_id": ust_ids[0] if ust_ids else None,
        "iban": ibans[0] if ibans else None,
        "hrb": hrbs[0] if hrbs else None,
        "email": emails[0] if emails else None,
        "domain": domains[0] if domains else None,
        "phone": phones[0] if phones else None,
    }


class VendorMatch:
    """match_vendor() sonucu. Tek alan iceren basit veri sinifi."""
    __slots__ = ("vendor_name", "matched_by", "score", "identity_id",
                 "default_vat_rate", "default_category", "default_payment_method")

    def __init__(self, vendor_name, matched_by, score, identity_id,
                 default_vat_rate=None, default_category=None,
                 default_payment_method=None):
        self.vendor_name = vendor_name
        self.matched_by = matched_by    # "ust_id" | "iban" | ...
        self.score = score              # MATCH_SCORE'tan
        self.identity_id = identity_id
        self.default_vat_rate = default_vat_rate
        self.default_category = default_category
        self.default_payment_method = default_payment_method

    def __repr__(self):
        return (f"VendorMatch(vendor={self.vendor_name!r}, "
                f"by={self.matched_by}, score={self.score:.2f})")


def match_vendor(user_id: int, ocr_text: str = "",
                 identity_fields: Optional[dict] = None) -> Optional[VendorMatch]:
    """OCR text'inden veya verilen kimlik field'larindan vendor'i bulur.

    identity_fields oncelikli — verilirse OCR extraction yapilmaz.
    Donus: VendorMatch veya None (eslesme yoksa). Hata olursa None — asla raise etmez.
    """
    if identity_fields is None:
        identity_fields = extract_identity_from_text(ocr_text)
    if not any(identity_fields.values()):
        return None

    db = SessionLocal()
    try:
        for key in MATCH_KEYS_PRIORITY:
            value = identity_fields.get(key)
            if not value:
                continue
            normalized = _normalize(value, key)
            if not normalized:
                continue

            col = getattr(VendorIdentity, key, None)
            if col is None:
                continue
            row = (
                db.query(VendorIdentity)
                .filter(VendorIdentity.user_id == user_id)
                .filter(col == normalized)
                .order_by(VendorIdentity.confidence.desc(),
                          VendorIdentity.use_count.desc())
                .first()
            )
            if row:
                # Kullanim sayaci + son kullanim guncelle (best-effort)
                try:
                    row.use_count = (row.use_count or 0) + 1
                    row.last_used_at = datetime.now(timezone.utc)
                    db.commit()
                except Exception:
                    db.rollback()
                logger.info(
                    "[VENDOR_MATCH] '%s' bulundu by=%s value=%s score=%.2f",
                    row.vendor_name, key, normalized, MATCH_SCORE[key],
                )
                return VendorMatch(
                    vendor_name=row.vendor_name,
                    matched_by=key,
                    score=MATCH_SCORE[key],
                    identity_id=row.id,
                    default_vat_rate=row.default_vat_rate,
                    default_category=row.default_category,
                    default_payment_method=row.default_payment_method,
                )
        return None
    except Exception as e:
        logger.warning("[VENDOR_MATCH] sorgu hatasi: %s", e)
        return None
    finally:
        db.close()


def save_or_update(
    user_id: int,
    vendor_name: str,
    *,
    ust_id: Optional[str] = None,
    iban: Optional[str] = None,
    hrb: Optional[str] = None,
    phone: Optional[str] = None,
    email: Optional[str] = None,
    domain: Optional[str] = None,
    address: Optional[str] = None,
    default_vat_rate: Optional[str] = None,
    default_category: Optional[str] = None,
    default_payment_method: Optional[str] = None,
    source: str = "manual",
) -> Optional[int]:
    """VendorIdentity tablosuna upsert. En az bir kimlik anahtari (ust_id/iban/
    hrb/email/domain) olmali — yoksa None doner.

    Eslesme stratejisi: oncelikli anahtarlardan biri zaten ayni user icin
    kayitliysa, mevcut kaydi guncelle (eksik alanlari doldur). Aksi halde
    yeni kayit olustur.

    Donus: kaydedilen VendorIdentity.id veya None.
    """
    if not vendor_name or not vendor_name.strip():
        return None

    fields_norm = {
        "ust_id": _normalize(ust_id, "ust_id"),
        "iban": _normalize(iban, "iban"),
        "hrb": _normalize(hrb, "hrb"),
        "email": _normalize(email, "email"),
        "domain": _normalize(domain, "domain"),
        "phone": _normalize(phone, "phone"),
    }
    if not any(fields_norm.values()):
        logger.info("[VENDOR_IDENTITY] kimlik anahtari yok, kayit atlandi: %s", vendor_name)
        return None

    db = SessionLocal()
    try:
        existing = None
        for key in MATCH_KEYS_PRIORITY:
            val = fields_norm.get(key)
            if not val:
                continue
            col = getattr(VendorIdentity, key)
            existing = (
                db.query(VendorIdentity)
                .filter(VendorIdentity.user_id == user_id)
                .filter(col == val)
                .first()
            )
            if existing:
                break

        if existing:
            # Eksik alanlari doldur, vendor adini manuel veya yuksek-guven kayit ezsin
            for key, val in fields_norm.items():
                if val and not getattr(existing, key, None):
                    setattr(existing, key, val)
            if address and not existing.address:
                existing.address = address[:300]
            if default_vat_rate and not existing.default_vat_rate:
                existing.default_vat_rate = default_vat_rate
            if default_category and not existing.default_category:
                existing.default_category = default_category
            if default_payment_method and not existing.default_payment_method:
                existing.default_payment_method = default_payment_method
            if source == "manual":
                existing.vendor_name = vendor_name.strip()
                existing.source = "manual"
                existing.confidence = 1.0
            db.commit()
            logger.info("[VENDOR_IDENTITY] guncellendi id=%s vendor=%s",
                        existing.id, vendor_name)
            return existing.id

        # Yeni kayit
        record = VendorIdentity(
            user_id=user_id,
            vendor_name=vendor_name.strip()[:200],
            ust_id=fields_norm["ust_id"],
            iban=fields_norm["iban"],
            hrb=fields_norm["hrb"],
            phone=fields_norm["phone"],
            email=fields_norm["email"],
            domain=fields_norm["domain"],
            address=(address or "")[:300] or None,
            default_vat_rate=default_vat_rate,
            default_category=default_category,
            default_payment_method=default_payment_method,
            source=source,
            confidence=1.0 if source == "manual" else 0.7,
        )
        db.add(record)
        db.commit()
        db.refresh(record)
        logger.info("[VENDOR_IDENTITY] yeni kayit id=%s vendor=%s source=%s",
                    record.id, vendor_name, source)
        return record.id
    except Exception as e:
        db.rollback()
        logger.warning("[VENDOR_IDENTITY] save hatasi: %s", e)
        return None
    finally:
        db.close()


def learn_from_invoice(invoice: Invoice) -> Optional[int]:
    """Confirmed Invoice'dan otomatik VendorIdentity ogrenir. _do_update_invoice
    PATCH sonunda cagirir (status='confirmed' + bilgi varsa). Manual kayit
    dururken auto_learned'i ezmez."""
    if not invoice or not invoice.vendor or invoice.vendor in ("", "Unbekannt"):
        return None
    return save_or_update(
        user_id=invoice.user_id,
        vendor_name=invoice.vendor,
        ust_id=invoice.vendor_ust_id,
        iban=invoice.vendor_iban,
        hrb=invoice.vendor_hrb,
        phone=invoice.vendor_phone,
        email=invoice.vendor_email,
        address=invoice.vendor_address,
        default_vat_rate=invoice.vat_rate,
        default_category=invoice.category,
        default_payment_method=invoice.payment_method,
        source="auto_learned",
    )
