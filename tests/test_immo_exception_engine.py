"""EXCEPTION ENGINE — default-paid model. The landlord enters NOTHING; debt surfaces
ONLY from reported problems ('no problem reported', not 'money received').

Scenario: tenant von 01.01.2026, Kalt 400 + NK 70. today pinned 30.06 (Jan-Jun due).
  • new tenant, no action       → debt 0, this-month 'paid'   (THE point: zero entry)
  • report June unpaid          → debt 400
  • mark June paid (clear)      → debt 0
  • report June partial (280)   → debt 120 (offen)
Run:  PYTHONIOENCODING=utf-8 PYTHONPATH=. python tests/test_immo_exception_engine.py
"""
import os
import sys
from datetime import date, datetime

os.environ.setdefault("JWT_SECRET", "x" * 44)

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi import FastAPI
from fastapi.testclient import TestClient

from autotax.models import Base, ImmoProperty, ImmoUnit, ImmoTenancy
from autotax import immo_api
from autotax.auth import get_current_user


class _FakeDate(date):
    @classmethod
    def today(cls):
        return date(2026, 6, 30)


class _FakeDT(datetime):
    @classmethod
    def now(cls, tz=None):
        return datetime(2026, 6, 30, tzinfo=tz)


immo_api.date = _FakeDate
immo_api.datetime = _FakeDT

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
    S = sessionmaker(bind=e)
    immo_api.SessionLocal = S
    db = S()
    db.add(ImmoProperty(id=10, user_id=1, name="Haus"))
    db.add(ImmoUnit(id=1, property_id=10, user_id=1, name="EG", soll_miete=400))
    db.add(ImmoTenancy(id=101, unit_id=1, user_id=1, mieter_name="Test", von=date(2026, 1, 1), kaltmiete=400, nk_voraus=70))
    db.commit()

    app = FastAPI(); app.include_router(immo_api.router)
    app.dependency_overrides[get_current_user] = lambda: {"sub": "1", "email": "o@test.de"}
    cl = TestClient(app)
    t = lambda: db.query(ImmoTenancy).get(101)

    print("\n[1] Neuer Mieter, KEINE Aktion → kein Problem → Schuld 0]")
    ok(immo_api._exception_arrears(t(), 2026) == 0, f"Schuld = 0 (default OK, 0 Eingaben) — got {immo_api._exception_arrears(t(),2026)}")
    m = cl.get("/immo/mieter").json()["mieter"][0]
    ok(m["offene_forderung"] == 0, "/mieter offen = 0")
    ok(m["this_month_status"] == "paid", f"diesen Monat = paid (kein Problem) — got {m['this_month_status']}")
    acc = cl.get("/immo/properties/10/accounting?year=2026").json()
    ok(acc["tenancies"][0]["rueckstand"] == 0, "accounting Rückstand = 0")

    print("\n[2] Juni als UNBEZAHLT melden → Schuld = 400]")
    cl.delete("/immo/tenancies/101/monat-bezahlt", params={"jahr": 2026, "monat": 6})
    db.refresh(t())
    ok(immo_api._exception_arrears(t(), 2026) == 400, f"Schuld = 400 (volle Monatsmiete) — got {immo_api._exception_arrears(t(),2026)}")
    mk = cl.get("/immo/tenancies/101/mietkonto?year=2026").json()
    jun = [r for r in mk["rows"] if r["monat"] == 6][0]
    ok(jun["status"] == "open", f"Mietkonto Juni status=open — got {jun['status']}")
    ok(mk["summe"]["offen"] == 400, f"Mietkonto offen=400 — got {mk['summe']['offen']}")

    print("\n[3] Juni als BEZAHLT markieren (Problem löschen) → Schuld 0]")
    cl.post("/immo/tenancies/101/monat-bezahlt", json={"jahr": 2026, "monat": 6})
    db.refresh(t())
    ok(immo_api._exception_arrears(t(), 2026) == 0, f"Schuld = 0 (Problem gelöst) — got {immo_api._exception_arrears(t(),2026)}")

    print("\n[4] Juni TEILZAHLUNG: 280 von 400 → Schuld 120]")
    cl.post("/immo/tenancies/101/monat-bezahlt", json={"jahr": 2026, "monat": 6, "betrag": 280})
    db.refresh(t())
    ok(immo_api._exception_arrears(t(), 2026) == 120, f"Schuld = 120 (offen) — got {immo_api._exception_arrears(t(),2026)}")
    mk = cl.get("/immo/tenancies/101/mietkonto?year=2026").json()
    jun = [r for r in mk["rows"] if r["monat"] == 6][0]
    ok(jun["status"] == "partial", f"Mietkonto Juni status=partial — got {jun['status']}")

    print("\n[5] Zukunft (Juli) zählt nie als Schuld]")
    ok(immo_api._exc_for(t(), 2026, 7) is None, "Juli keine Ausnahme")
    ok(immo_api._exception_arrears(t(), 2026) == 120, "nur Juni-Teil (120), Juli nicht fällig")

    print(f"\n=== EXCEPTION ENGINE: {PASS} passed, {FAIL} failed ===")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
