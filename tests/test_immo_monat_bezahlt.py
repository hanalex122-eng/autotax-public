"""Step 4 — Ödendi/Ödenmedi quick-action UX layer (EXCEPTION ENGINE).

today pinned to 2026-06-23. Under the exception engine a new tenant defaults to OK
(paid, offene 0) with NO data entry; debt surfaces ONLY from reported problems.
Verifies the two quick actions:
  • Ödenmedi (DELETE) → sets an UNPAID exception → open + offene = full Monatsmiete.
  • Ödendi  (POST)   → clears the exception → paid + offene 0; idempotent.
  • Ödendi with betrag < Soll → records a PARTIAL exception → partial + offene rest.
No immo_rent payment row is created (model = 'no problem reported', not 'money
received'); the endpoints return the resulting exception, not a betrag/removed.
Run:  PYTHONIOENCODING=utf-8 PYTHONPATH=. python tests/test_immo_monat_bezahlt.py
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

from autotax.models import Base, ImmoProperty, ImmoUnit, ImmoTenancy, ImmoRent  # noqa: F401
from autotax import immo_api
from autotax.auth import get_current_user

TODAY = date(2026, 6, 23)


class _FakeDate(date):
    @classmethod
    def today(cls):
        return TODAY


class _FakeDT(datetime):
    @classmethod
    def now(cls, tz=None):
        return datetime(2026, 6, 23, tzinfo=tz)


immo_api.date = _FakeDate
immo_api.datetime = _FakeDT

PASS = FAIL = 0


def ok(c, m):
    global PASS, FAIL
    if c:
        PASS += 1; print(f"  PASS  {m}")
    else:
        FAIL += 1; print(f"  FAIL  {m}")


def card(cl):
    return cl.get("/immo/mieter").json()["mieter"][0]


def main():
    e = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=e)
    S = sessionmaker(bind=e)
    db = S()
    db.add(ImmoProperty(id=10, user_id=1, name="Haus", adresse="Str 1"))
    db.add(ImmoUnit(id=1, property_id=10, user_id=1, name="EG", wohnflaeche=50, soll_miete=500))
    db.add(ImmoTenancy(id=101, unit_id=1, user_id=1, mieter_name="Test", von=date(2026, 6, 1), kaltmiete=500, nk_voraus=40))
    db.commit(); db.close()

    immo_api.SessionLocal = S
    app = FastAPI(); app.include_router(immo_api.router)
    app.dependency_overrides[get_current_user] = lambda: {"sub": "1", "email": "o@test.de"}
    cl = TestClient(app)

    print("\n[before] new tenant, no problem reported → default OK (paid, offene 0)")
    c0 = card(cl)
    ok(c0["this_month_status"] == "paid" and c0["offene_forderung"] == 0,
       f"paid + offene 0 (got {c0['this_month_status']}/{c0['offene_forderung']})")

    print("\n[Ödenmedi] DELETE → report June UNBEZAHLT → open + offene = full 500")
    rd = cl.delete("/immo/tenancies/101/monat-bezahlt?jahr=2026&monat=6")
    ok(rd.status_code == 200 and rd.json()["exception"]["typ"] == "unpaid",
       f"200 + unpaid exception (got {rd.status_code}/{rd.json().get('exception')})")
    c1 = card(cl)
    ok(c1["this_month_status"] == "open" and c1["offene_forderung"] == 500 and c1["debtor"] is True,
       f"open + offene 500 + debtor (got {c1['this_month_status']}/{c1['offene_forderung']})")

    print("\n[Ödendi] POST → clear the exception → paid + offene 0")
    r = cl.post("/immo/tenancies/101/monat-bezahlt", json={"jahr": 2026, "monat": 6})
    ok(r.status_code == 200 and r.json()["exception"] is None, f"200 + no exception (got {r.status_code})")
    c2 = card(cl)
    ok(c2["this_month_status"] == "paid", f"this_month paid (got {c2['this_month_status']})")
    ok(c2["offene_forderung"] == 0 and c2["debtor"] is False, f"offene 0 + not debtor (got {c2['offene_forderung']})")

    print("\n[idempotent] second Ödendi → still no exception, no immo_rent created")
    cl.post("/immo/tenancies/101/monat-bezahlt", json={"jahr": 2026, "monat": 6})
    t = S().query(ImmoTenancy).get(101)
    ok(immo_api._exc_for(t, 2026, 6) is None, "no exception after repeated Ödendi")
    n = S().query(ImmoRent).filter(ImmoRent.tenancy_id == 101).count()
    ok(n == 0, f"no immo_rent payment row created by Ödendi (got {n})")

    print("\n[custom amount] Ödendi betrag 200 < Soll 500 → PARTIAL exception, offene 300")
    cl.post("/immo/tenancies/101/monat-bezahlt", json={"jahr": 2026, "monat": 6, "betrag": 200})
    c3 = card(cl)
    ok(c3["this_month_status"] == "partial", f"partial (got {c3['this_month_status']})")
    ok(c3["offene_forderung"] == 300, f"offene 300 (got {c3['offene_forderung']})")

    print(f"\n=== Step 4 Ödendi/Ödenmedi: {PASS} passed, {FAIL} failed ===")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
