"""END-TO-END: a landlord adds a NEW property → unit → tenant (mid-month) → payment.

Answers the fear 'adding a new property will error again'. Exercises the real create
endpoints + the (structurally fixed) accounting. today pinned 2026-06-23.
Run:  PYTHONIOENCODING=utf-8 PYTHONPATH=. python tests/test_immo_create_flow.py
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

from autotax.models import Base
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
    immo_api.SessionLocal = sessionmaker(bind=e)
    app = FastAPI(); app.include_router(immo_api.router)
    app.dependency_overrides[get_current_user] = lambda: {"sub": "1", "email": "o@test.de"}
    cl = TestClient(app)

    print("\n[1] Neue Immobilie")
    rp = cl.post("/immo/properties", json={"name": "Neue Str. 5", "adresse": "Neue Str. 5, 66115 SB"})
    ok(rp.status_code == 200, f"property created (got {rp.status_code})")
    pid = rp.json().get("id")

    print("[2] Neue Einheit")
    ru = cl.post("/immo/units", json={"property_id": pid, "name": "EG", "wohnflaeche": 57, "soll_miete": 470})
    ok(ru.status_code == 200, f"unit created (got {ru.status_code})")
    uid_ = ru.json().get("id")

    print("[3] Neuer Mieter (Einzug 15.06 — Teilmonat)")
    rt = cl.post("/immo/tenancies", json={"unit_id": uid_, "mieter_name": "Neuer Mieter",
                                          "von": "2026-06-15", "kaltmiete": 470, "nk_voraus": 70})
    ok(rt.status_code == 200, f"tenancy created (got {rt.status_code})")
    tid = rt.json().get("id")

    print("[4] /immo/mieter — neuer Mieter, KEINE Aktion → Schuld 0 (EXCEPTION ENGINE default OK)")
    rm = cl.get("/immo/mieter")
    ok(rm.status_code == 200, f"/mieter 200 (got {rm.status_code})")
    m = next((x for x in rm.json()["mieter"] if x["tenancy_id"] == tid), None)
    ok(m is not None and m["gesamtmiete"] == 540, "Gesamt = 540 (470+70)")
    ok(m["offene_forderung"] == 0, f"offen = 0 (kein Problem gemeldet, 0 Eingaben) — got {m['offene_forderung']}")

    print("[5] Juni als UNBEZAHLT melden → Rückstand = anteilig Warmmiete ~288.00")
    cl.delete(f"/immo/tenancies/{tid}/monat-bezahlt", params={"jahr": 2026, "monat": 6})
    acc = cl.get(f"/immo/properties/{pid}/accounting?year=2026").json()
    tr = acc["tenancies"][0]
    ok(abs(tr["rueckstand"] - round((470 + 70) * 16 / 30, 2)) < 0.02, f"Rückstand = anteilig Juni Warmmiete ~288.00 — got {tr['rueckstand']}")

    print("[6] Juni als BEZAHLT markieren → Rückstand 0")
    cl.post(f"/immo/tenancies/{tid}/monat-bezahlt", json={"jahr": 2026, "monat": 6})
    acc = cl.get(f"/immo/properties/{pid}/accounting?year=2026").json()
    ok(acc["tenancies"][0]["rueckstand"] == 0, f"Rückstand = 0 — got {acc['tenancies'][0]['rueckstand']}")
    ok(rm.status_code == 200, "kein Fehler im gesamten Flow")

    print(f"\n=== Create-Flow (neue Immobilie ohne Fehler): {PASS} passed, {FAIL} failed ===")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
