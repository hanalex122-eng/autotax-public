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

# Hangi alanlarda eslesme aranir, oncelik sirasiyla. 'name' en sonda — sadece
# diger kimlik anahtari hicbirinde eslesme yoksa fallback olarak kullanilir.
MATCH_KEYS_PRIORITY = ("ust_id", "iban", "hrb", "address", "email", "domain", "phone", "name")

# Eslestirme guven skorlari — match() bu degeri match.score olarak doner
MATCH_SCORE = {
    "ust_id": 1.00,    # USt-IdNr cok benzersiz, OCR'da bozulma riski az
    "iban": 0.95,
    "hrb": 0.90,
    "address": 0.85,   # Sokak + ev no + PLZ — sube'yi kesin tanimlar
    "email": 0.80,
    "domain": 0.80,
    "phone": 0.65,     # En zayif — degistirilmedi
    "name": 0.60,      # Sadece dier hicbiri eslemeyince fallback
}

# Manuel olarak girilmis (source='manual', confidence=1.0) kayitlar bir
# zayif anahtar uzerinden eslesirse skoru bu kadar artar — kullanicinin
# kendisi dogruladigi icin guvenlidir, vendor lock'a yetecek seviyeye cikar.
MANUAL_SOURCE_BOOST = 0.20

# Overwrite protection esigi — mevcut kayit bu skorun ustundeyse uzerine
# yazilmaz. Manuel kayitlar (confidence=1.0) korunur, auto_learned (0.7) update'lenebilir.
OVERWRITE_THRESHOLD = 0.9

# OCR'dan kimlik cikartmak icin regex'ler — parser.extract_entities ile uyumlu
_USTID_PAT = re.compile(r"(?i)\b(DE)\s?(\d{3}\s?\d{3}\s?\d{3})\b")
_IBAN_PAT = re.compile(r"\b([A-Z]{2}\s?\d{2}\s?(?:\d{4}\s?){2,7}\d{1,4})\b")
_HRB_PAT = re.compile(r"(?i)\b(HR[BA])\s+(?:[A-ZÄÖÜ][a-zäöüß]+\s+)?(\d{1,7})\b")
_EMAIL_PAT = re.compile(r"\b([a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})\b")
_DOMAIN_PAT = re.compile(r"(?i)\b(?:www\.)?([a-z0-9\-]{2,}\.(?:de|com|at|ch|eu|net|org|shop))\b")
_PHONE_PAT = re.compile(r"(?:\+\d{1,3}[\s\-]?)?(?:\(?\d{2,5}\)?[\s\-]?)?\d{3,4}[\s\-]?\d{2,6}")


def calculate_confidence(data: dict) -> float:
    """Vendor identity verisi icin guven skoru hesaplar (0.0 - 1.0).

    - ust_id varsa  +0.5
    - iban varsa    +0.3
    - vendor_name   +0.2
    - max 1.0

    Asla raise etmez. data dict degilse 0.0 doner.
    """
    if not isinstance(data, dict):
        return 0.0
    score = 0.0
    if data.get("ust_id"):
        score += 0.5
    if data.get("iban"):
        score += 0.3
    if data.get("vendor_name"):
        score += 0.2
    return min(score, 1.0)


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

    VendorMatch.score = match_confidence (float, 0.6 - 1.0).
    """
    if identity_fields is None:
        identity_fields = extract_identity_from_text(ocr_text)
    if not any(identity_fields.values()):
        return None

    db = SessionLocal()
    try:
        def _final_score(base: float, source: Optional[str]) -> float:
            """Manuel girilmis (source='manual') kayit ise skoru artir — kullanici
            dogruladigi icin zayif anahtar bile lock'a yetsin. Cap 1.0."""
            if source == "manual":
                return min(base + MANUAL_SOURCE_BOOST, 1.0)
            return base

        # Mevcut anahtar bazli eslesme (ust_id, iban, hrb, email, domain, phone)
        for key in ("ust_id", "iban", "hrb", "email", "domain", "phone"):
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
                final = _final_score(MATCH_SCORE[key], row.source)
                logger.info(
                    "[VENDOR_MATCH] '%s' bulundu by=%s value=%s score=%.2f (source=%s)",
                    row.vendor_name, key, normalized, final, row.source,
                )
                return VendorMatch(
                    vendor_name=row.vendor_name,
                    matched_by=key,
                    score=final,
                    identity_id=row.id,
                    default_vat_rate=row.default_vat_rate,
                    default_category=row.default_category,
                    default_payment_method=row.default_payment_method,
                )

        # Adres bazli eslesme — IBAN'i olmayan market fislerinde tek anchor.
        # Kayitli adresi (normalize) OCR'da gecen adres icinde substring olarak
        # arariz. Esik: en az 8 karakter (random kelime cakismasini onler).
        addr_value = identity_fields.get("address")
        if addr_value and isinstance(addr_value, str) and len(addr_value.strip()) >= 8:
            ocr_addr_norm = re.sub(r"[^\w\s]", " ", addr_value.lower())
            ocr_addr_norm = re.sub(r"\s+", " ", ocr_addr_norm).strip()
            if len(ocr_addr_norm) >= 8:
                rows = (
                    db.query(VendorIdentity)
                    .filter(VendorIdentity.user_id == user_id)
                    .filter(VendorIdentity.address.isnot(None))
                    .order_by(VendorIdentity.confidence.desc(),
                              VendorIdentity.use_count.desc())
                    .all()
                )
                for row in rows:
                    if not row.address:
                        continue
                    stored_norm = re.sub(r"[^\w\s]", " ", row.address.lower())
                    stored_norm = re.sub(r"\s+", " ", stored_norm).strip()
                    if len(stored_norm) < 8:
                        continue
                    if stored_norm in ocr_addr_norm or ocr_addr_norm in stored_norm:
                        try:
                            row.use_count = (row.use_count or 0) + 1
                            row.last_used_at = datetime.now(timezone.utc)
                            db.commit()
                        except Exception:
                            db.rollback()
                        final = _final_score(MATCH_SCORE["address"], row.source)
                        logger.info(
                            "[VENDOR_MATCH] '%s' bulundu by=address score=%.2f (source=%s)",
                            row.vendor_name, final, row.source,
                        )
                        return VendorMatch(
                            vendor_name=row.vendor_name,
                            matched_by="address",
                            score=final,
                            identity_id=row.id,
                            default_vat_rate=row.default_vat_rate,
                            default_category=row.default_category,
                            default_payment_method=row.default_payment_method,
                        )

        # Name fallback — sadece kimlik anahtari hicbirinde eslesme yoksa.
        # vendor_name OCR'da bozuk gelmis olabilecegi icin en dusuk skor (0.60).
        name_value = identity_fields.get("name") or identity_fields.get("vendor_name")
        if name_value and isinstance(name_value, str) and len(name_value.strip()) >= 3:
            try:
                from sqlalchemy import func as _func
                norm_name = name_value.strip().lower()
                row = (
                    db.query(VendorIdentity)
                    .filter(VendorIdentity.user_id == user_id)
                    .filter(_func.lower(VendorIdentity.vendor_name) == norm_name)
                    .order_by(VendorIdentity.confidence.desc(),
                              VendorIdentity.use_count.desc())
                    .first()
                )
                if row:
                    try:
                        row.use_count = (row.use_count or 0) + 1
                        row.last_used_at = datetime.now(timezone.utc)
                        db.commit()
                    except Exception:
                        db.rollback()
                    logger.info(
                        "[VENDOR_MATCH] '%s' bulundu by=name (fallback) score=%.2f",
                        row.vendor_name, MATCH_SCORE["name"],
                    )
                    return VendorMatch(
                        vendor_name=row.vendor_name,
                        matched_by="name",
                        score=MATCH_SCORE["name"],
                        identity_id=row.id,
                        default_vat_rate=row.default_vat_rate,
                        default_category=row.default_category,
                        default_payment_method=row.default_payment_method,
                    )
            except Exception as e:
                logger.warning("[VENDOR_MATCH] name fallback hatasi: %s", e)

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
            # Overwrite protection — mevcut kayit yuksek guvenli ise (manuel
            # girilmis veya admin tarafindan onaylanmis) auto kaynaklar uzerine yazmaz.
            existing_conf = float(existing.confidence or 0)
            if source != "manual" and existing_conf > OVERWRITE_THRESHOLD:
                logger.info(
                    "[VENDOR_IDENTITY] overwrite atlandi id=%s vendor=%s "
                    "(mevcut confidence=%.2f > %.2f, source=%s)",
                    existing.id, existing.vendor_name, existing_conf,
                    OVERWRITE_THRESHOLD, source,
                )
                return existing.id

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


def learn_from_invoice(data, source: str = "auto_learned") -> Optional[int]:
    """Confirmed fisten otomatik VendorIdentity ogrenir.

    `data` parametresi iki tipte olabilir (geriye uyumlu):
      - autotax.models.Invoice ORM objesi   — mevcut imza
      - dict — yeni: vendor_name + (ust_id OR iban) anahtarlari beklenir

    `source`:
      - "auto_learned" (default): KATI kural, ust_id veya iban gerekli
        (kucuk veriden saglam fingerprint).
      - "manual": kullanici PATCH'i — adres/telefon/email yeterli, cunku
        kullanici dogruladigi vendor adini her ne olursa olsun kaydetmek
        istiyor. Market fislerinde IBAN yok, eskiden ogrenmeyi atliyorduk.

    Asla raise etmez. Donus: yeni veya guncellenen VendorIdentity.id veya None.
    """
    if data is None:
        return None

    def _have_any_identity_key(*vals) -> bool:
        return any(v and str(v).strip() for v in vals)

    # --- dict yolu (yeni) ---
    if isinstance(data, dict):
        vendor_name = (data.get("vendor_name") or data.get("vendor") or "").strip()
        if not vendor_name or vendor_name in ("Unbekannt", "Manual Entry"):
            return None
        ust_id = data.get("ust_id") or data.get("vendor_ust_id")
        iban = data.get("iban") or data.get("vendor_iban")
        phone = data.get("phone") or data.get("vendor_phone")
        email = data.get("email") or data.get("vendor_email")
        address = data.get("address") or data.get("vendor_address")
        domain = data.get("domain") or data.get("vendor_domain")
        # auto_learned: ust_id/iban zorunlu. manual: phone/email/address da kabul.
        if source == "manual":
            if not _have_any_identity_key(ust_id, iban, phone, email, address, domain):
                return None
        else:
            if not (ust_id or iban):
                return None
        user_id = data.get("user_id")
        if not user_id:
            return None
        return save_or_update(
            user_id=user_id,
            vendor_name=vendor_name,
            ust_id=ust_id,
            iban=iban,
            hrb=data.get("hrb") or data.get("vendor_hrb"),
            phone=phone,
            email=email,
            domain=domain,
            address=address,
            default_vat_rate=data.get("default_vat_rate") or data.get("vat_rate"),
            default_category=data.get("default_category") or data.get("category"),
            default_payment_method=(
                data.get("default_payment_method") or data.get("payment_method")
            ),
            source=source,
        )

    # --- Invoice ORM yolu (mevcut imza, geriye uyumlu) ---
    invoice = data
    vendor_name = (getattr(invoice, "vendor", "") or "").strip()
    if not vendor_name or vendor_name in ("Unbekannt", "Manual Entry"):
        return None
    ust_id = getattr(invoice, "vendor_ust_id", None)
    iban = getattr(invoice, "vendor_iban", None)
    phone = getattr(invoice, "vendor_phone", None)
    email = getattr(invoice, "vendor_email", None)
    address = getattr(invoice, "vendor_address", None)
    if source == "manual":
        if not _have_any_identity_key(ust_id, iban, phone, email, address):
            return None
    else:
        if not (ust_id or iban):
            return None
    return save_or_update(
        user_id=invoice.user_id,
        vendor_name=vendor_name,
        ust_id=ust_id,
        iban=iban,
        hrb=getattr(invoice, "vendor_hrb", None),
        phone=phone,
        email=email,
        address=address,
        default_vat_rate=getattr(invoice, "vat_rate", None),
        default_category=getattr(invoice, "category", None),
        default_payment_method=getattr(invoice, "payment_method", None),
        source=source,
    )
