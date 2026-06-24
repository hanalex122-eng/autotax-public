"""Mieterhöhung (dated rent change) + Mieter-Info (Telefon/E-Mail/Kaution).

Tenant von 01.01.2026, Kaltmiete 400 → Mieterhöhung ab 01.07.2026 auf 450.
Soll 2026 (today pinned 31.12) = Jan-Jun 6×400 + Jul-Dez 6×450 = 5100. Past months
keep 400. Same number on OLD engine AND ledger (parity). today pinned year-end.
Run:  PYTHONIOENCODING=utf-8 PYTHONPATH=. python tests/test_immo_mieterhoehung.py
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
from autotax import immo_api, immo_ledger as L, immo_ledger_read as R
from autotax.auth import get_current_user


class _FakeDate(date):
    @classmethod
    def today(cls):
        return date(2026, 12, 31)


class _FakeDT(datetime):
    @classmethod
    def now(cls, tz=None):
        return datetime(2026, 12, 31, tzinfo=tz)


immo_api.date = _FakeDate
immo_api.datetime = _FakeDT
R.date = _FakeDate

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
    L.ensure_ledger_indexes(e)
    S = sessionmaker(bind=e)
    immo_api.SessionLocal = S
    db = S()
    db.add(ImmoProperty(id=10, user_id=1, name="Haus"))
    db.add(ImmoUnit(id=1, property_id=10, user_id=1, name="EG", soll_miete=400))
    db.add(ImmoTenancy(id=101, unit_id=1, user_id=1, mieter_name="Test", von=date(2026, 1, 1), kaltmiete=400))
    db.commit()

    app = FastAPI(); app.include_router(immo_api.router)
    app.dependency_overrides[get_current_user] = lambda: {"sub": "1", "email": "o@test.de"}
    cl = TestClient(app)

    print("\n[Mieterhöhung ab 01.07.2026 → 450]")
    r = cl.post("/immo/tenancies/101/mieterhoehung", json={"ab": "2026-07-01", "kalt": 450})
    ok(r.status_code == 200, f"200 (got {r.status_code})")
    t = db.query(ImmoTenancy).get(101); db.refresh(t)
    ok(immo_api._effective_kalt(t, 2026, 6) == 400, "Juni effektiv = 400 (alt)")
    ok(immo_api._effective_kalt(t, 2026, 7) == 450, "Juli effektiv = 450 (neu)")
    ok(immo_api._soll_faellig(t, 2026) == 5100, f"Soll 2026 = 5100 (6×400+6×450) — got {immo_api._soll_faellig(t,2026)}")

    print("\n[Ledger = OLD (parity)]")
    L.ensure_sollbuchungen(db, 1, 2026); db.commit()
    sal = R.saldo_by_tenancy(db, 1, 2026).get(101, {})
    ok(sal.get("soll") == 5100, f"Ledger soll = 5100 (Mieterhöhung im Ledger) — got {sal.get('soll')}")

    print("\n[Mieter-Info: Telefon/E-Mail/Kaution]")
    cl.patch("/immo/tenancies/101", json={"telefon": "0176 123", "email": "a@b.de", "kaution": 900})
    m = cl.get("/immo/mieter").json()["mieter"][0]
    ok(m["telefon"] == "0176 123" and m["email"] == "a@b.de", "Telefon + E-Mail im /mieter")
    ok(m["kaution"] == 900, "Kaution im /mieter")
    ok(m["kaltmiete"] == 450, f"aktuelle Kaltmiete = 450 (nach Erhöhung) — got {m['kaltmiete']}")

    print(f"\n=== Mieterhöhung + Info: {PASS} passed, {FAIL} failed ===")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
