"""USER-FACING DEBT CONSISTENCY (EXCEPTION ENGINE) — VANELLE moved in 15.06, Kalt 470.

June is ANTEILIG (16/30 of 470 ≈ 250.67). Debt comes ONLY from reported exceptions
('no problem reported' = paid). The 4 USER surfaces show the SAME number:
  Übersicht (_accounting) · Mietkonto · Mieter (_tenancy_arrears) · Mahnung.
(Ledger = separate AUDIT domain of real payments — covered by ledger_* tests.)
  • no problem reported            → 0 everywhere (zero data entry)
  • June partial (150.67 owed)     → 150.67 everywhere
today pinned 2026-06-23.
Run:  PYTHONIOENCODING=utf-8 PYTHONPATH=. python tests/test_immo_consistency.py
"""
import os
import sys
from datetime import date

os.environ.setdefault("JWT_SECRET", "x" * 44)

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from autotax.models import Base, ImmoProperty, ImmoUnit, ImmoTenancy
from autotax import immo_api
from autotax import immo_payments as _pay


class _FakeDate(date):
    @classmethod
    def today(cls):
        return date(2026, 6, 23)


immo_api.date = _FakeDate

PASS = FAIL = 0
JUNE_SOLL = round((470 + 70) * 16 / 30, 2)  # Warmmiete 540 × 16/30 = 288.00 (commit 2: NK is part of the Soll)


def ok(c, m):
    global PASS, FAIL
    if c:
        PASS += 1; print(f"  PASS  {m}")
    else:
        FAIL += 1; print(f"  FAIL  {m}")


def eq(a, b):
    return abs(float(a) - float(b)) < 0.02


def build(exc):
    """exc: None (no problem) | 'unpaid' | a number (partial 'offen' amount)."""
    e = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=e)
    S = sessionmaker(bind=e)
    immo_api.SessionLocal = S
    db = S()
    db.add(ImmoProperty(id=10, user_id=1, name="Haus", adresse="Str 1"))
    db.add(ImmoUnit(id=1, property_id=10, user_id=1, name="EG", soll_miete=470))
    db.add(ImmoTenancy(id=101, unit_id=1, user_id=1, mieter_name="VANELLE", von=date(2026, 6, 15), kaltmiete=470, nk_voraus=70))
    db.commit()
    t = db.query(ImmoTenancy).get(101)
    if exc == "unpaid":
        _pay.sql_service(db).report_problem(1, t.id, 2026, 6, "unpaid")
    elif exc is not None:
        _pay.sql_service(db).report_problem(1, t.id, 2026, 6, "partial", offen=exc)
    db.commit()
    return db


def four_surfaces(db):
    t = db.query(ImmoTenancy).get(101)
    a = immo_api._accounting(db, 1, 10, 2026)
    mk = immo_api.tenancy_mietkonto(101, 2026, {"sub": "1", "email": "o@test.de"})
    return {
        "Übersicht": a["tenancies"][0]["rueckstand"],
        "Mietkonto": mk["summe"]["offen"],
        "Mieter": immo_api._tenancy_arrears(db, 1, t, 2026),
        "Mahnung": immo_api._mahnung_betrag(db, 1, t, 2026),
        "_soll": a["tenancies"][0]["soll"],
    }


def main():
    print(f"\nVANELLE Einzug 15.06 → Juni anteilig {JUNE_SOLL}€ (nicht 470)\n")

    print("[A] Kein Problem gemeldet → Rückstand 0 überall (0 Eingaben)")
    s = four_surfaces(build(None))
    ok(eq(s["_soll"], JUNE_SOLL), f"Soll anteilig = {JUNE_SOLL} (Warmmiete, nicht 540) — got {s['_soll']}")
    for k in ("Übersicht", "Mietkonto", "Mieter", "Mahnung"):
        ok(eq(s[k], 0), f"{k} = 0 — got {s[k]}")

    print("\n[B] Juni Teilzahlung: 150.67 offen → gleich auf 4 Flächen")
    exp = round(JUNE_SOLL - 100, 2)  # zahlte 100 von 250.67 → 150.67 offen
    s2 = four_surfaces(build(exp))
    vals = [s2[k] for k in ("Übersicht", "Mietkonto", "Mieter", "Mahnung")]
    for k in ("Übersicht", "Mietkonto", "Mieter", "Mahnung"):
        ok(eq(s2[k], exp), f"{k} = {exp} — got {s2[k]}")
    ok(all(eq(v, vals[0]) for v in vals), "4 USER-Flächen IDENTISCH")

    print(f"\n=== Consistency (Exception Engine, 4 Flächen): {PASS} passed, {FAIL} failed ===")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
