"""Soft-delete query helpers + date helpers.

Mevcut kod 20+ yerde elle `(is_deleted == False) | (is_deleted == None)`
yazıyor; hata yapması kolay. Yeni endpoint'ler bu helper'ları kullanır;
mevcut yerler Sprint 3'te toplu refactor edilecek.

Date helpers Sprint 2C ile geldi — invoices.due_date string→Date
migration geçiş döneminde tek noktada normalize.

Kullanım:
    from autotax.queries import (
        active_invoices, active_cash_entries,
        parse_user_date, invoice_due_date, set_invoice_due_date,
    )
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional, Union

from sqlalchemy.orm import Query, Session

from autotax.models import CashEntry, Invoice


def active_invoices(db: Session, user_id: int) -> Query:
    """Belirli kullanıcının soft-delete edilmemiş faturalarını döndürür."""
    return db.query(Invoice).filter(
        Invoice.user_id == user_id,
        Invoice.is_deleted.isnot(True),   # FALSE veya NULL eşleşir
    )


def active_cash_entries(db: Session, user_id: int) -> Query:
    """Belirli kullanıcının soft-delete edilmemiş kasa girişlerini döndürür."""
    return db.query(CashEntry).filter(
        CashEntry.user_id == user_id,
        CashEntry.is_deleted.isnot(True),
    )


def parse_user_date(s: Union[str, date, datetime, None]) -> Optional[date]:
    """ISO (YYYY-MM-DD), DE (DD.MM.YYYY), date veya datetime — Date'e çevir.
    Tanımsız format → None."""
    if s is None or s == "":
        return None
    if isinstance(s, date) and not isinstance(s, datetime):
        return s
    if isinstance(s, datetime):
        return s.date()
    s = str(s).strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%Y/%m/%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(s[:10], fmt).date()
        except ValueError:
            continue
    return None


def invoice_due_date(inv: Invoice) -> Optional[date]:
    """Invoice.due_date'i Date olarak okur. Önce v2 (native), yoksa
    v1 (string) parse edilir."""
    if inv is None:
        return None
    v2 = getattr(inv, "due_date_v2", None)
    if v2:
        return v2 if isinstance(v2, date) and not isinstance(v2, datetime) else (
            v2.date() if isinstance(v2, datetime) else None
        )
    return parse_user_date(getattr(inv, "due_date", None))


def set_invoice_due_date(inv: Invoice, value: Union[str, date, datetime, None]) -> None:
    """Invoice.due_date'i ayarlar — her iki kolon da yazılır (dual write).
    String input ISO + DE format desteklenir; None → temizle."""
    if value is None:
        inv.due_date = None
        inv.due_date_v2 = None
        return
    parsed = parse_user_date(value)
    inv.due_date_v2 = parsed
    if isinstance(value, str):
        # ISO formatta normalize ederek string'i de güncelle
        inv.due_date = parsed.isoformat() if parsed else None
    else:
        inv.due_date = parsed.isoformat() if parsed else None
