"""Step 5a — GET /immo/tenancies/{tid}/mietkonto (monthly Mietkonto), EXCEPTION ENGINE.

today pinned 2026-06-23. Tenancy von=2026-04-01, kalt 500. April has no reported
problem (default OK → paid, bezahlt=soll). May and June are reported UNBEZAHLT
exceptions (full month owed). Expect: Jan-Mar inactive, Apr paid, May/Jun open,
Jul-Dec future; summe due=1500 (Apr+May+Jun), bezahlt 500 (only Apr), offen 1000
(= the two reported exceptions). immo_rent rows no longer drive these numbers.
Run:  PYTHONIOENCODING=utf-8 PYTHONPATH=. python tests/test_immo_mietkonto.py
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

from autotax.models import Base, ImmoProperty, ImmoUnit, ImmoTenancy, ImmoRent
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
    db = S()
    db.add(ImmoProperty(id=10, user_id=1, name="Haus"))
    db.add(ImmoUnit(id=1, property_id=10, user_id=1, name="EG", soll_miete=500))
    db.add(ImmoTenancy(id=101, unit_id=1, user_id=1, mieter_name="Test", von=date(2026, 4, 1), kaltmiete=500))
    db.commit()
    t = db.query(ImmoTenancy).get(101)
    # April: no problem reported → default OK (paid). May+June reported UNBEZAHLT.
    immo_api._set_problem(t, 2026, 5, "unpaid")
    immo_api._set_problem(t, 2026, 6, "unpaid")
    db.commit(); db.close()

    immo_api.SessionLocal = S
    app = FastAPI(); app.include_router(immo_api.router)
    app.dependency_overrides[get_current_user] = lambda: {"sub": "1", "email": "o@test.de"}
    cl = TestClient(app)

    r = cl.get("/immo/tenancies/101/mietkonto?year=2026")
    ok(r.status_code == 200, f"200 (got {r.status_code})")
    d = r.json()
    rows = {x["monat"]: x for x in d["rows"]}
    ok(len(d["rows"]) == 12, "12 month rows")
    ok(rows[2]["status"] == "inactive", "Feb inactive (vor Einzug)")
    ok(rows[4]["status"] == "paid" and rows[4]["bezahlt"] == 500, "Apr paid 500")
    ok(rows[5]["status"] == "open" and rows[5]["soll"] == 500, "May open (soll 500)")
    ok(rows[6]["status"] == "open", "Jun (current) open")
    ok(rows[7]["status"] == "future", "Jul future (noch nicht fällig)")
    ok(rows[12]["status"] == "future", "Dec future")
    s = d["summe"]
    ok(s["soll_faellig"] == 1500, f"soll_faellig 1500 (Apr+May+Jun) (got {s['soll_faellig']})")
    ok(s["bezahlt"] == 500, f"bezahlt 500 (got {s['bezahlt']})")
    ok(s["offen"] == 1000, f"offen 1000 (got {s['offen']})")

    print(f"\n=== Step 5a mietkonto: {PASS} passed, {FAIL} failed ===")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
