"""SINGLE SOURCE OF TRUTH — VANELLE: 470 Kaltmiete, 270 Zahlung → Rückstand 200.

Proves the SAME number (200) across all surfaces:
  Übersicht (_accounting) · Mietkonto (tenancy_mietkonto) · Mieter card (/mieter via
  _tenancy_arrears) · Mahnung (_mahnung_betrag) · Ledger (saldo_by_tenancy).
Partial payment MUST work (binary 'paid/unpaid' is rejected). today pinned 2026-06-23.
Run:  PYTHONIOENCODING=utf-8 PYTHONPATH=. python tests/test_immo_consistency.py
"""
import os
import sys
from datetime import date

os.environ.setdefault("JWT_SECRET", "x" * 44)

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from autotax.models import Base, ImmoProperty, ImmoUnit, ImmoTenancy, ImmoRent
from autotax import immo_api, immo_ledger as L, immo_ledger_read as R


class _FakeDate(date):
    @classmethod
    def today(cls):
        return date(2026, 6, 23)


immo_api.date = _FakeDate
R.date = _FakeDate

PASS = FAIL = 0


def ok(c, m):
    global PASS, FAIL
    if c:
        PASS += 1; print(f"  PASS  {m}")
    else:
        FAIL += 1; print(f"  FAIL  {m}")


def main():
    e = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=e)
    L.ensure_ledger_indexes(e)
    S = sessionmaker(bind=e)
    immo_api.SessionLocal = S
    db = S()
    db.add(ImmoProperty(id=10, user_id=1, name="Haus", adresse="Str 1"))
    db.add(ImmoUnit(id=1, property_id=10, user_id=1, name="EG", soll_miete=470))
    db.add(ImmoTenancy(id=101, unit_id=1, user_id=1, mieter_name="VANELLE", von=date(2026, 6, 15), kaltmiete=470, nk_voraus=70))
    db.add(ImmoRent(id=1, property_id=10, tenancy_id=101, user_id=1, betrag=270, datum=date(2026, 6, 10)))
    db.commit()
    # ledger: Sollbuchung (June 470) + Zahlung (270) → saldo 200
    L.ensure_sollbuchungen(db, 1, 2026)
    L.post_entry(db, user_id=1, typ="zahlung", betrag=-270, jahr=2026, monat=6, tenancy_id=101, commit=True)
    t = db.query(ImmoTenancy).get(101)

    print("\nVANELLE: Kaltmiete 470 · Zahlung 270 · 1 fälliger Monat (Juni) → erwartet Rückstand = 200\n")

    a = immo_api._accounting(db, 1, 10, 2026)
    uebersicht = a["tenancies"][0]["rueckstand"]
    print(f"  Übersicht (_accounting)      Rückstand = {uebersicht}")
    ok(uebersicht == 200, "Übersicht = 200")
    ok(a["tenancies"][0]["ist"] == 270 and a["summe"]["zahlungsausfall"] == 200, "Übersicht Ist=270, Zahlungsausfall=200")

    mk = immo_api.tenancy_mietkonto(101, 2026, {"sub": "1", "email": "o@test.de"})
    print(f"  Mietkonto (tenancy_mietkonto) offen     = {mk['summe']['offen']}")
    ok(mk["summe"]["offen"] == 200, "Mietkonto offen = 200")
    juni = next(r for r in mk["rows"] if r["monat"] == 6)
    ok(juni["status"] == "partial" and juni["bezahlt"] == 270, "Juni = partial, bezahlt 270")

    card = immo_api._tenancy_arrears(db, 1, t, 2026)
    print(f"  Mieter card (_tenancy_arrears)          = {card}")
    ok(card == 200, "Mieter card = 200")

    mahnung = immo_api._mahnung_betrag(db, 1, t, 2026)
    print(f"  Mahnung (_mahnung_betrag)               = {mahnung}")
    ok(mahnung == 200, "Mahnung = 200")

    ledger = R.saldo_by_tenancy(db, 1, 2026).get(101, {}).get("saldo")
    print(f"  Ledger (saldo_by_tenancy)               = {ledger}")
    ok(ledger == 200, "Ledger = 200")

    print("\n  → 5 Flächen, EIN Ergebnis:", uebersicht == mk["summe"]["offen"] == card == mahnung == ledger == 200)
    ok(uebersicht == mk["summe"]["offen"] == card == mahnung == ledger == 200, "TÜM EKRANLAR AYNI = 200")

    print(f"\n=== Consistency (single source Soll−Ist): {PASS} passed, {FAIL} failed ===")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
