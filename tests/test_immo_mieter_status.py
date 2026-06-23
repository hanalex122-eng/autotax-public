"""Step 2 — status columns (anmeldung_done, wgb_erstellt_am) + display in /immo/mieter.

Additive nullable columns; verifies defaults, PATCH sets anmeldung_done, and the
WGB PDF endpoint stamps wgb_erstellt_am → both surface in /immo/mieter.
Run:  PYTHONIOENCODING=utf-8 PYTHONPATH=. python tests/test_immo_mieter_status.py
"""
import os
import sys
from datetime import date

os.environ.setdefault("JWT_SECRET", "x" * 44)

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi import FastAPI
from fastapi.testclient import TestClient

from autotax.models import Base, ImmoProperty, ImmoUnit, ImmoTenancy, UserCompany
from autotax import immo_api
from autotax.auth import get_current_user

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

    cols = [c["name"] for c in inspect(e).get_columns("immo_tenancy")]
    ok("anmeldung_done" in cols and "wgb_erstellt_am" in cols, "columns exist (anmeldung_done, wgb_erstellt_am)")

    db = S()
    db.add(ImmoProperty(id=10, user_id=1, name="Haus", adresse="Str 1, 10115 Berlin"))
    db.add(ImmoUnit(id=1, property_id=10, user_id=1, name="EG", wohnflaeche=50, soll_miete=400))
    db.add(ImmoTenancy(id=101, unit_id=1, user_id=1, mieter_name="Test", von=date(2026, 1, 1), kaltmiete=400, nk_voraus=60))
    db.add(UserCompany(user_id=1, company_name="Vermieter", address="V-Str 1", is_default=True))
    db.commit(); db.close()

    immo_api.SessionLocal = S
    app = FastAPI(); app.include_router(immo_api.router)
    app.dependency_overrides[get_current_user] = lambda: {"sub": "1", "email": "o@test.de"}
    cl = TestClient(app)

    print("\n[defaults]")
    m = cl.get("/immo/mieter").json()["mieter"][0]
    ok(m["anmeldung_done"] is False, "anmeldung_done default False")
    ok(m["wgb_done"] is False and m["wgb_erstellt_am"] is None, "wgb_done default False")

    print("\n[PATCH anmeldung_done=true]")
    r = cl.patch("/immo/tenancies/101", json={"anmeldung_done": True})
    ok(r.status_code == 200 and r.json().get("anmeldung_done") is True, "PATCH returns anmeldung_done True")
    m2 = cl.get("/immo/mieter").json()["mieter"][0]
    ok(m2["anmeldung_done"] is True, "/mieter reflects anmeldung_done True")

    print("\n[WGB PDF stamps wgb_erstellt_am]")
    rp = cl.get("/immo/tenancies/101/wohnungsgeberbestaetigung/pdf?art=einzug")
    ok(rp.status_code == 200 and rp.content[:4] == b"%PDF", "WGB PDF 200")
    m3 = cl.get("/immo/mieter").json()["mieter"][0]
    ok(m3["wgb_done"] is True and m3["wgb_erstellt_am"] is not None, "/mieter reflects wgb_done True after PDF")

    print(f"\n=== Step 2 status columns: {PASS} passed, {FAIL} failed ===")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
