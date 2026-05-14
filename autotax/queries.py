"""Soft-delete query helpers — tek noktada filter mantığı.

Mevcut kod 20+ yerde elle `(is_deleted == False) | (is_deleted == None)`
yazıyor; hata yapması kolay. Yeni endpoint'ler bu helper'ları kullanır;
mevcut yerler Sprint 3'te toplu refactor edilecek.

Kullanım:
    from autotax.queries import active_invoices, active_cash_entries

    invs = active_invoices(db, user_id).order_by(Invoice.date.desc()).all()
    entries = active_cash_entries(db, user_id).filter(
        CashEntry.date.between(d1, d2)
    ).all()
"""

from __future__ import annotations

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
