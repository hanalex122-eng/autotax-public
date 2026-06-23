"""Wohnungsgeberbestätigung (§19 BMG) PDF endpoint test.

Self-contained: in-memory SQLite (StaticPool), FastAPI TestClient, admin override.
Verifies: PDF 200 (einzug+auszug) with %PDF body, 400 when no UserCompany, 404 for
unknown tenancy. Additive — does not touch ledger/Mahnung.
Run:  PYTHONIOENCODING=utf-8 PYTHONPATH=. python tests/test_immo_wohnungsgeber.py
"""
import os
import sys
from datetime import date

os.environ.setdefault("JWT_SECRET", "test-secret-" + "x" * 40)

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi import FastAPI
from fastapi.testclient import TestClient

from autotax.models import Base, ImmoProperty, ImmoUnit, ImmoTenancy, UserCompany
from autotax import immo_api
from autotax.auth import get_current_user

PASS, FAIL = 0, 0


def ok(c, m):
    global PASS, FAIL
    if c:
        PASS += 1; print(f"  PASS  {m}")
    else:
        FAIL += 1; print(f"  FAIL  {m}")


def fresh():
    e = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=e)
    return e, sessionmaker(bind=e)


def seed(db, company=True):
    db.add(ImmoProperty(id=10, user_id=1, name="Musterstr. 12", adresse="Musterstr. 12, 10115 Berlin"))
    db.add(ImmoUnit(id=1, property_id=10, user_id=1, name="WHG-01 EG links"))
    db.add(ImmoTenancy(id=101, unit_id=1, user_id=1, mieter_name="Max Müller", von=date(2025, 3, 1), bis=date(2026, 2, 28), kaltmiete=850))
    if company:
        db.add(UserCompany(user_id=1, company_name="Vermieter Schmidt", address="Vermieterstr. 1, 10117 Berlin", is_default=True))
    db.commit()


def client(S):
    immo_api.SessionLocal = S
    app = FastAPI(); app.include_router(immo_api.router)
    app.dependency_overrides[get_current_user] = lambda: {"sub": "1", "email": "o@test.de"}
    return TestClient(app)


def main():
    # with company
    e, S = fresh(); db = S(); seed(db, company=True); db.close()
    cl = client(S)
    print("\n[1] Einzug PDF")
    r = cl.get("/immo/tenancies/101/wohnungsgeberbestaetigung/pdf?art=einzug")
    ok(r.status_code == 200 and r.headers.get("content-type", "").startswith("application/pdf"), f"einzug 200 PDF (got {r.status_code})")
    ok(r.content[:4] == b"%PDF", "body is a real PDF (%PDF)")
    ok(b"wohnungsgeberbestaetigung_101.pdf" in r.headers.get("content-disposition", "").encode(), "filename header")

    print("\n[2] Auszug PDF (uses bis)")
    r2 = cl.get("/immo/tenancies/101/wohnungsgeberbestaetigung/pdf?art=auszug")
    ok(r2.status_code == 200 and r2.content[:4] == b"%PDF", f"auszug 200 PDF (got {r2.status_code})")

    print("\n[3] unknown tenancy → 404")
    ok(cl.get("/immo/tenancies/9999/wohnungsgeberbestaetigung/pdf").status_code == 404, "404 for unknown tenancy")

    # without company → 400 guard
    print("\n[4] no UserCompany → 400 guard")
    e2, S2 = fresh(); db = S2(); seed(db, company=False); db.close()
    cl2 = client(S2)
    r4 = cl2.get("/immo/tenancies/101/wohnungsgeberbestaetigung/pdf")
    ok(r4.status_code == 400 and "Firmendaten" in r4.text, f"400 + Firmendaten hint (got {r4.status_code})")

    print(f"\n=== Wohnungsgeberbestätigung: {PASS} passed, {FAIL} failed ===")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
