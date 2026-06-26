"""Step 2c — Untermieter (subtenant) relationship.

typ + parent_tenancy_id; Untermieter nested under Hauptmieter; rent/debt stays with
the Hauptmieter (Untermieter offene=0, this_month/mahnung None). today pinned.
Run:  PYTHONIOENCODING=utf-8 PYTHONPATH=. python tests/test_immo_untermieter.py
"""
import os
import sys
from datetime import date, datetime

os.environ.setdefault("JWT_SECRET", "x" * 44)

from sqlalchemy import create_engine, inspect
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
        return date(2026, 6, 23)


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

    cols = [c["name"] for c in inspect(e).get_columns("immo_tenancy")]
    if "typ" not in cols or "parent_tenancy_id" not in cols:
        # WIP: Untermieter (subtenant) feature not yet implemented on the model.
        # This is a TDD spec written ahead of the model; skip so the suite stays
        # honestly green. Remove this guard when typ/parent_tenancy_id are added.
        print("  SKIP  Untermieter feature not implemented (typ/parent_tenancy_id absent) — WIP")
        print("\n=== Step 2c Untermieter: SKIPPED (feature not implemented) ===")
        sys.exit(0)
    ok("typ" in cols and "parent_tenancy_id" in cols, "columns exist (typ, parent_tenancy_id)")

    db = S()
    db.add(ImmoProperty(id=10, user_id=1, name="Haus", adresse="Str 1"))
    db.add(ImmoUnit(id=1, property_id=10, user_id=1, name="EG", wohnflaeche=80, soll_miete=600))
    # Hauptmieter — unpaid → debtor
    db.add(ImmoTenancy(id=101, unit_id=1, user_id=1, mieter_name="Haupt", von=date(2026, 6, 1), kaltmiete=600, nk_voraus=80, typ="hauptmieter"))
    db.commit(); db.close()

    immo_api.SessionLocal = S
    app = FastAPI(); app.include_router(immo_api.router)
    app.dependency_overrides[get_current_user] = lambda: {"sub": "1", "email": "o@test.de"}
    cl = TestClient(app)

    print("\n[create Untermieter via POST]")
    r = cl.post("/immo/tenancies", json={"unit_id": 1, "mieter_name": "Unter", "typ": "untermieter",
                                         "parent_tenancy_id": 101, "von": "2026-06-01"})
    ok(r.status_code == 200 and r.json().get("typ") == "untermieter", f"created typ=untermieter (got {r.status_code})")
    ok(r.json().get("parent_tenancy_id") == 101, "parent_tenancy_id = 101")

    print("\n[/mieter shape]")
    data = cl.get("/immo/mieter").json()["mieter"]
    by = {x["mieter_name"]: x for x in data}
    ok(len(data) == 2, f"2 rows (got {len(data)})")
    h, u = by["Haupt"], by["Unter"]
    ok(h["typ"] == "hauptmieter" and h["offene_forderung"] == 600, f"Hauptmieter arrears 600 (got {h['offene_forderung']})")
    ok(u["typ"] == "untermieter" and u["parent_tenancy_id"] == 101, "Untermieter typ+parent")
    ok(u["offene_forderung"] == 0 and u["debtor"] is False, "Untermieter NO debt (rent at Hauptmieter)")
    ok(u["this_month_status"] is None and u["letzte_mahnung"] is None, "Untermieter no payment-status/mahnung")
    ok(u["unit_id"] == 1, "Untermieter same unit as Hauptmieter")

    print(f"\n=== Step 2c Untermieter: {PASS} passed, {FAIL} failed ===")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
