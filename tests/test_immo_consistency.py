"""SINGLE SOURCE OF TRUTH + PRO-RATA — VANELLE moved in 15.06 (mid-month).

June is ANTEILIG (16/30 of 470 ≈ 250.67), NOT a full month. She paid 270 → covers
the half-month → Rückstand 0. Proves the SAME number across all surfaces:
  Übersicht (_accounting) · Mietkonto · Mieter card · Mahnung · Ledger.
Also a clear partial-debt case (pays 100 → 150.67 everywhere). today pinned 2026-06-23.
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
JUNE_SOLL = round(470 * 16 / 30, 2)  # 15.06 Einzug → 16/30 ≈ 250.67


def ok(c, m):
    global PASS, FAIL
    if c:
        PASS += 1; print(f"  PASS  {m}")
    else:
        FAIL += 1; print(f"  FAIL  {m}")


def eq(a, b):
    return abs(float(a) - float(b)) < 0.02


def build(payment):
    e = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=e)
    L.ensure_ledger_indexes(e)
    S = sessionmaker(bind=e)
    immo_api.SessionLocal = S
    db = S()
    db.add(ImmoProperty(id=10, user_id=1, name="Haus", adresse="Str 1"))
    db.add(ImmoUnit(id=1, property_id=10, user_id=1, name="EG", soll_miete=470))
    db.add(ImmoTenancy(id=101, unit_id=1, user_id=1, mieter_name="VANELLE", von=date(2026, 6, 15), kaltmiete=470, nk_voraus=70))
    db.add(ImmoRent(id=1, property_id=10, tenancy_id=101, user_id=1, betrag=payment, datum=date(2026, 6, 10)))
    db.commit()
    L.ensure_sollbuchungen(db, 1, 2026)
    L.post_entry(db, user_id=1, typ="zahlung", betrag=-payment, jahr=2026, monat=6, tenancy_id=101, commit=True)
    return db


def five_surfaces(db):
    t = db.query(ImmoTenancy).get(101)
    a = immo_api._accounting(db, 1, 10, 2026)
    mk = immo_api.tenancy_mietkonto(101, 2026, {"sub": "1", "email": "o@test.de"})
    return {
        "Übersicht": a["tenancies"][0]["rueckstand"],
        "Mietkonto": mk["summe"]["offen"],
        "Mieter": immo_api._tenancy_arrears(db, 1, t, 2026),
        "Mahnung": immo_api._mahnung_betrag(db, 1, t, 2026),
        "Ledger": R.offene_forderungen(db, 1, 2026)["total"],
        "_soll": a["tenancies"][0]["soll"],
    }


def main():
    print(f"\nVANELLE Einzug 15.06 → Juni anteilig {JUNE_SOLL}€ (nicht 470)\n")

    print("[A] Zahlung 270 → deckt Halbmonat → Rückstand 0 überall")
    s = five_surfaces(build(270))
    ok(eq(s["_soll"], JUNE_SOLL), f"Soll anteilig = {JUNE_SOLL} (nicht 470) — got {s['_soll']}")
    for k in ("Übersicht", "Mietkonto", "Mieter", "Mahnung", "Ledger"):
        ok(eq(s[k], 0), f"{k} = 0 — got {s[k]}")

    print("\n[B] Zahlung 100 → klarer Teilrückstand → gleich überall")
    exp = round(JUNE_SOLL - 100, 2)
    s2 = five_surfaces(build(100))
    vals = [s2[k] for k in ("Übersicht", "Mietkonto", "Mieter", "Mahnung", "Ledger")]
    for k in ("Übersicht", "Mietkonto", "Mieter", "Mahnung", "Ledger"):
        ok(eq(s2[k], exp), f"{k} = {exp} — got {s2[k]}")
    ok(all(eq(v, vals[0]) for v in vals), "5 Flächen IDENTISCH")

    print(f"\n=== Consistency + pro-rata: {PASS} passed, {FAIL} failed ===")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
