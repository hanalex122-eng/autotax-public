"""Recurring invoice spawner.

is_recurring=True olan fatura'lar 'template'. Her tick'te:
  - recurring_next_at <= today ise yeni kayit olustur (template'in kopyasi)
  - Yeni kayit: yeni date, yeni due_date (+14 gun), recurring_parent_id=template.id
  - Template'in recurring_next_at'i ileri al (sonraki periyot)
  - Yeni kayit reminder akisina otomatik girer (due_date var)

Frekans:
  monthly   = +1 ay
  quarterly = +3 ay
  yearly    = +1 yil
"""

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from autotax.db import SessionLocal
from autotax.models import Invoice
from autotax.reminders import send_telegram

logger = logging.getLogger("autotax.recurring")


def _add_months(d: date, months: int) -> date:
    """date + N ay. Ay sonu (Jan 31 + 1 ay = Feb 28/29) korunur."""
    new_month = d.month - 1 + months
    new_year = d.year + new_month // 12
    new_month = new_month % 12 + 1
    # Gun: hedef ayda gecerli son gune kadar
    from calendar import monthrange
    max_day = monthrange(new_year, new_month)[1]
    new_day = min(d.day, max_day)
    return date(new_year, new_month, new_day)


def compute_next_spawn(current_date: date, freq: str) -> date:
    """Frekansa gore sonraki spawn tarihi."""
    if freq == "monthly":
        return _add_months(current_date, 1)
    if freq == "quarterly":
        return _add_months(current_date, 3)
    if freq == "yearly":
        return _add_months(current_date, 12)
    return _add_months(current_date, 1)  # default monthly


async def process_recurring_spawns() -> dict:
    """Her template kontrol et: recurring_next_at <= today ise yeni kayit
    olustur. Bir kez tetiklenmesi yeterli — sonraki gun de kontrol edilir."""
    today = datetime.now(timezone.utc).date()
    db = SessionLocal()
    stats = {"checked": 0, "spawned": 0}
    try:
        templates = (
            db.query(Invoice)
            .filter(Invoice.is_recurring == True)
            .filter((Invoice.is_deleted == False) | (Invoice.is_deleted == None))
            .all()
        )
        stats["checked"] = len(templates)

        for tmpl in templates:
            try:
                if not tmpl.recurring_next_at:
                    # Template'e next_at set edilmemis — atla, kullanicidan
                    # aktivasyon zamani manuel set olmali
                    continue
                try:
                    next_d = datetime.strptime(tmpl.recurring_next_at, "%Y-%m-%d").date()
                except ValueError:
                    logger.warning("[RECURRING] invalid next_at for tmpl %s: %s",
                                   tmpl.id, tmpl.recurring_next_at)
                    continue
                if next_d > today:
                    continue  # henuz vakit yok

                # Yeni kayit olustur — template'i kopyala, yeni due_date hesapla
                new_due = next_d + timedelta(days=14)  # 14 gun odeme vadesi
                copy = Invoice(
                    user_id=tmpl.user_id,
                    filename=f"recurring-{tmpl.id}-{next_d.isoformat()}.pdf",
                    vendor=tmpl.vendor,
                    invoice_number=f"{tmpl.invoice_number or 'AUTO'}-{next_d.strftime('%Y%m')}",
                    invoice_type=tmpl.invoice_type or "expense",
                    total_amount=tmpl.total_amount or 0,
                    vat_amount=tmpl.vat_amount or 0,
                    vat_rate=tmpl.vat_rate or "0%",
                    date=next_d.isoformat(),
                    payment_method=tmpl.payment_method or "",
                    raw_text=f"[Recurring auto-generated from template #{tmpl.id}]\n\n{(tmpl.raw_text or '')[:500]}",
                    category=tmpl.category or "other",
                    processed=False,
                    status="needs_review",
                    vendor_iban=tmpl.vendor_iban or "",
                    vendor_email=tmpl.vendor_email or "",
                    vendor_phone=tmpl.vendor_phone or "",
                    vendor_fax=getattr(tmpl, "vendor_fax", None) or "",
                    vendor_address=tmpl.vendor_address or "",
                    vendor_website=getattr(tmpl, "vendor_website", None) or "",
                    vendor_ust_id=tmpl.vendor_ust_id,
                    vendor_hrb=tmpl.vendor_hrb,
                    vendor_steuernr=getattr(tmpl, "vendor_steuernr", None),
                    due_date=new_due.isoformat(),
                    payment_status="unpaid",
                    is_recurring=False,  # kopya degil template
                    recurring_parent_id=tmpl.id,
                )
                db.add(copy)

                # Template'in next_at'ini ileri al
                tmpl.recurring_next_at = compute_next_spawn(next_d, tmpl.recurring_freq or "monthly").isoformat()
                stats["spawned"] += 1

                logger.info("[RECURRING] spawned invoice from tmpl %s (%s) for %s",
                            tmpl.id, tmpl.vendor, next_d.isoformat())

                # Telegram alert (admin'e — sen)
                try:
                    await send_telegram(
                        f"🔁 <b>Recurring Rechnung erstellt</b>\n"
                        f"Vendor: {tmpl.vendor}\n"
                        f"Datum: {next_d.isoformat()}\n"
                        f"Fällig: {new_due.isoformat()}\n"
                        f"Betrag: €{tmpl.total_amount or 0:.2f}\n"
                        f"<i>Frequenz: {tmpl.recurring_freq or 'monthly'}</i>"
                    )
                except Exception:
                    pass

            except Exception:
                logger.exception("[RECURRING] error processing tmpl %s", tmpl.id)

        db.commit()
        if stats["spawned"]:
            logger.info("[RECURRING] cycle: %s", stats)
    except Exception:
        db.rollback()
        logger.exception("[RECURRING] fatal")
    finally:
        db.close()
    return stats
