"""Kasa MVP — system category seeder (Sprint 1).

Idempotent: inserts the global (user_id = NULL, is_system = True) default
categories only if missing. Safe to run on every startup. Because the
(user_id, name) unique constraint treats NULL user_id as distinct, idempotency
is enforced explicitly here (check-then-insert), not by the constraint.
"""
from __future__ import annotations

import logging

from autotax.models import CashCategory

logger = logging.getLogger("autotax.kasse")

# name, kind, datev_konto (SKR03), euer_line (forms.json anlage_euer key), vat
_SYSTEM_CATEGORIES = [
    ("Umsatz 19%",            "income",  "8400", "umsatzerloese", "19"),
    ("Umsatz 7%",             "income",  "8300", "umsatzerloese", "7"),
    ("Sonstige Einnahmen",    "income",  "8200", "umsatzerloese", "0"),
    ("Wareneinkauf",          "expense", "3400", "wareneinkauf",  "19"),
    ("Miete & Nebenkosten",   "expense", "4210", "raumkosten",    "19"),
    ("Personalkosten",        "expense", "4100", "personalkosten","0"),
    ("Fahrzeugkosten",        "expense", "4500", "kfz_kosten",    "19"),
    ("Bürobedarf",            "expense", "4930", "betriebsausgaben","19"),
    ("Versicherungen",        "expense", "4360", "betriebsausgaben","0"),
    ("Gebühren & Beiträge",   "expense", "4380", "betriebsausgaben","0"),
    ("Abschreibungen (AfA)",  "expense", "4830", "afa",           "0"),
    ("Sonstige Ausgaben",     "expense", "4900", "betriebsausgaben","19"),
]


def seed_system_categories(db) -> int:
    """Insert missing system categories. Returns number inserted."""
    inserted = 0
    for i, (name, kind, konto, euer, vat) in enumerate(_SYSTEM_CATEGORIES):
        exists = db.query(CashCategory.id).filter(
            CashCategory.user_id.is_(None),
            CashCategory.name == name,
        ).first()
        if exists:
            continue
        db.add(CashCategory(
            user_id=None, name=name, kind=kind, datev_konto=konto, euer_line=euer,
            default_vat_rate=vat, sort_order=i, is_system=True, is_active=True,
        ))
        inserted += 1
    if inserted:
        db.commit()
        logger.info("kasse: seeded %d system categories", inserted)
    return inserted
