"""Step 1 — GET /immo/mieter (tenant-centric card feed).

Self-contained in-memory SQLite + TestClient, today pinned to 2026-06-23.
Asserts the aggregated card fields for two tenancies: one paid (no debt) and one
unpaid (debtor). READ-ONLY endpoint — no ledger/Soll/Ist logic touched.
Run:  PYTHONIOENCODING=utf-8 PYTHONPATH=. python tests/test_immo_mieter.py
"""
import os
import sys
from datetime import date, datetime, timezone

os.environ.setdefault("JWT_SECRET", "x" * 44)

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi import FastAPI
from fastapi.testclient import TestClient

from autotax.models import Base, ImmoProperty, ImmoUnit, ImmoTenancy, ImmoRent
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


def main():
    e = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=e)
    S = sessionmaker(bind=e)
    db = S()
    db.add(ImmoProperty(id=10, user_id=1, name="Musterstr. 12", adresse="Musterstr. 12, 10115 Berlin"))
    db.add(ImmoUnit(id=1, property_id=10, user_id=1, name="EG Links", wohnflaeche=57, soll_miete=330))
    db.add(ImmoUnit(id=2, property_id=10, user_id=1, name="OG Rechts", wohnflaeche=72, soll_miete=500))
    # TEN 101: moved in this month, paid → no debt
    db.add(ImmoTenancy(id=101, unit_id=1, user_id=1, mieter_name="Ahmet Yilmaz",
                       von=date(2026, 6, 1), bis=None, kaltmiete=330, nk_voraus=70))
    db.add(ImmoRent(id=1, property_id=10, tenancy_id=101, user_id=1, betrag=330, datum=date(2026, 6, 10)))
    # TEN 102: moved in this month, NOT paid → debtor
    db.add(ImmoTenancy(id=102, unit_id=2, user_id=1, mieter_name="Maria Mueller",
                       von=date(2026, 6, 1), bis=None, kaltmiete=500, nk_voraus=40))
    db.commit(); db.close()

    immo_api.SessionLocal = S
    app = FastAPI(); app.include_router(immo_api.router)
    app.dependency_overrides[get_current_user] = lambda: {"sub": "1", "email": "o@test.de"}
    cl = TestClient(app)

    r = cl.get("/immo/mieter")
    ok(r.status_code == 200, f"200 (got {r.status_code})")
    data = r.json()["mieter"]
    ok(len(data) == 2, f"2 tenancies (got {len(data)})")
    # sorted by offene_forderung desc → debtor first
    m = {x["tenancy_id"]: x for x in data}
    a, b = m[101], m[102]

    print("\n[TEN 101 — paid, no debt]")
    ok(a["mieter_name"] == "Ahmet Yilmaz", "mieter_name")
    ok(a["property_name"] == "Musterstr. 12" and "Berlin" in (a["property_address"] or ""), "property name+address")
    ok(a["unit_name"] == "EG Links" and a["wohnflaeche"] == 57, "unit_name + wohnflaeche 57")
    ok(a["kaltmiete"] == 330 and a["nk_vorauszahlung"] == 70, "kaltmiete 330 + nk 70")
    ok(a["gesamtmiete"] == 400, "gesamtmiete = 400 (330+70)")
    ok(a["einzug"] == "2026-06-01" and a["auszug"] is None, "einzug + auszug")
    ok(a["offene_forderung"] == 0 and a["debtor"] is False, "offene_forderung 0 + debtor False")
    ok(a["this_month_status"] == "paid", f"this_month_status paid (got {a['this_month_status']})")
    ok(a["last_payment_date"] == "2026-06-10", "last_payment_date 2026-06-10")

    print("\n[TEN 102 — unpaid, debtor]")
    ok(b["gesamtmiete"] == 540, "gesamtmiete = 540 (500+40)")
    ok(b["offene_forderung"] == 500 and b["debtor"] is True, f"offene 500 + debtor True (got {b['offene_forderung']})")
    ok(b["this_month_status"] == "open", f"this_month_status open (got {b['this_month_status']})")
    ok(b["last_payment_date"] is None, "last_payment_date None")

    print("\n[sort] debtor first")
    ok(data[0]["tenancy_id"] == 102, "highest offene first")

    print(f"\n=== Step 1 /immo/mieter: {PASS} passed, {FAIL} failed ===")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
