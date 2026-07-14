"""Mahnung amount = EXCEPTION ARREARS (audit-domain reframe).

The former Faz 4.3 ledger parity GUARD is RETIRED. Domains are now separated:
  • EXCEPTION engine = operational debt (reported problems) → drives the Mahnung
  • AUDIT ledger     = real payments / Soll−Ist → audit only (parity_report)
A Mahnung duns a tenant ONLY for a REPORTED problem (unpaid/partial). A tenant with
no flagged month is NEVER dunned (no payment record means 'no problem reported', not
'owes everything'). This proves _mahnung_betrag == exception arrears end-to-end.
Self-contained in-memory SQLite + TestClient. No prod DB / network.
Run:  PYTHONIOENCODING=utf-8 PYTHONPATH=. python tests/test_immo_mahnung_guard.py
"""
import os
import sys
from datetime import date

os.environ.setdefault("JWT_SECRET", "test-secret-" + "x" * 40)
os.environ["ADMIN_EMAILS"] = "owner@test.de"

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi import FastAPI
from fastapi.testclient import TestClient

from autotax.models import Base, ImmoProperty, ImmoUnit, ImmoTenancy, ImmoMahnung
from autotax import immo_api
from autotax import immo_payments as _pay
from autotax.auth import get_current_user

PASS, FAIL = 0, 0


def ok(cond, msg):
    global PASS, FAIL
    if cond:
        PASS += 1; print(f"  PASS  {msg}")
    else:
        FAIL += 1; print(f"  FAIL  {msg}")


def main():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=eng)
    S = sessionmaker(bind=eng)
    immo_api.SessionLocal = S
    db = S()
    db.add(ImmoProperty(id=100, user_id=1, name="T", is_deleted=False))
    db.add(ImmoUnit(id=1, property_id=100, user_id=1, name="WHG-01", soll_miete=800))
    db.add(ImmoTenancy(id=105, unit_id=1, user_id=1, mieter_name="Test Mieter S", von=date(2025, 1, 1), bis=None, kaltmiete=800))
    db.commit()
    t = lambda: db.query(ImmoTenancy).filter(ImmoTenancy.id == 105).first()

    print("\n[1] Kein Problem gemeldet → Mahnungsbetrag 0 (nie dunnen ohne Grund)")
    ok(immo_api._mahnung_betrag(db, 1, t(), 2025) == 0, f"betrag = 0 — got {immo_api._mahnung_betrag(db,1,t(),2025)}")

    print("\n[2] 7 Monate (Jun-Dez) als unbezahlt melden → 7×800 = 5600")
    for mo in range(6, 13):
        _pay.sql_service(db).report_problem(1, t().id, 2025, mo, "unpaid")
    db.commit()
    ok(immo_api._mahnung_betrag(db, 1, t(), 2025) == 5600.0, f"betrag = 5600 — got {immo_api._mahnung_betrag(db,1,t(),2025)}")
    ok(immo_api._mahnung_betrag(db, 1, t(), 2025) == immo_api._exception_arrears(t(), 2025), "betrag == exception arrears")

    print("\n[3] Juni auf Teilzahlung (300 offen) → 4800 + 300 = 5100")
    _pay.sql_service(db).report_problem(1, t().id, 2025, 6, "partial", offen=300)
    db.commit()
    ok(immo_api._mahnung_betrag(db, 1, t(), 2025) == 5100.0, f"betrag = 5100 — got {immo_api._mahnung_betrag(db,1,t(),2025)}")

    print("\n[4] Endpoint: Mahnung erzeugen → 200 PDF + erfasst exception-Betrag")
    app = FastAPI(); app.include_router(immo_api.router)
    app.dependency_overrides[get_current_user] = lambda: {"sub": "1", "email": "owner@test.de"}
    cl = TestClient(app)
    r = cl.post("/immo/tenancies/105/mahnung", json={"stufe": 1, "year": 2025})
    ok(r.status_code == 200 and r.headers.get("content-type", "").startswith("application/pdf"), f"Mahnung 200 PDF (got {r.status_code})")
    rec = S().query(ImmoMahnung).filter(ImmoMahnung.tenancy_id == 105).order_by(ImmoMahnung.id.desc()).first()
    ok(rec is not None and rec.betrag == 5100.0, f"recorded betrag = 5100 (exception arrears) — got {rec.betrag if rec else None}")

    print("\n[5] Alle Probleme gelöst → Mahnungsbetrag 0")
    for mo in range(6, 13):
        _pay.sql_service(db).mark_paid(1, t().id, 2025, mo)
    db.commit()
    ok(immo_api._mahnung_betrag(db, 1, t(), 2025) == 0, f"betrag = 0 (alle OK) — got {immo_api._mahnung_betrag(db,1,t(),2025)}")
    db.close()

    print(f"\n=== Mahnung = Exception Arrears: {PASS} passed, {FAIL} failed ===")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
