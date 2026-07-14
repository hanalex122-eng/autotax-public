"""THE LAW, ENFORCED: no third book — not even behind a feature flag.

Found by the Sprint 0 production smoke test (2026-07-14), not by the unit tests:
IMMO_LEDGER_READ=1 was ON in production. portfolio_view() then OVERWROTE the debt fields
with numbers read from the immo_ledger, which computes a Kalt-only Soll and knows nothing
about the exception engine. Result on the live Berichte screen:

    Mieter card / Bu Ay / Mahnung : 940,00 €   (2 reported months × Warmmiete 470)
    Berichte (Rückstand KPI)      : 2.800,00 € (7 months × Kaltmiete 400, from the ledger)

Every unit test passed, because they all ran with the flag OFF — the default. That is the
hole this file closes: the flag is forced **ON** here, and the report must STILL agree with
the card. Debt is derived only from the Exception Engine (CLAUDE.md → Architecture law).

Run:  PYTHONIOENCODING=utf-8 PYTHONPATH=. python tests/test_immo_no_third_book.py
"""
import os
import sys
from datetime import date, datetime

os.environ["JWT_SECRET"] = "x" * 44
os.environ["IMMO_LEDGER_READ"] = "1"          # ← the production setting that caused the bug
os.environ["IMMO_LEDGER_WRITE"] = "1"

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi import FastAPI
from fastapi.testclient import TestClient

from autotax.models import Base, ImmoProperty, ImmoUnit, ImmoTenancy
from autotax import immo_api
from autotax.auth import get_current_user

TODAY = date(2026, 7, 14)


class _FakeDate(date):
    @classmethod
    def today(cls):
        return TODAY


class _FakeDT(datetime):
    @classmethod
    def now(cls, tz=None):
        return datetime(2026, 7, 14, tzinfo=tz)


immo_api.date = _FakeDate
immo_api.datetime = _FakeDT

PASS = FAIL = 0


def ok(c, m):
    global PASS, FAIL
    if c:
        PASS += 1
        print(f"  PASS  {m}")
    else:
        FAIL += 1
        print(f"  FAIL  {m}")


def main():
    from autotax.config import immo_ledger_read_enabled
    ok(immo_ledger_read_enabled(), "the ledger-read flag really is ON for this test")

    e = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=e)
    S = sessionmaker(bind=e)
    db = S()
    db.add(ImmoProperty(id=10, user_id=1, name="Haus", adresse="Teststr. 1, 10115 Berlin"))
    db.add(ImmoUnit(id=1, property_id=10, user_id=1, name="EG", soll_miete=470))
    db.add(ImmoTenancy(id=101, unit_id=1, user_id=1, mieter_name="Smoke Mieter",
                       von=date(2026, 1, 1), kaltmiete=400, nk_voraus=70))     # Warm 470
    db.commit()
    db.close()

    immo_api.SessionLocal = S
    app = FastAPI()
    app.include_router(immo_api.router)
    app.dependency_overrides[get_current_user] = lambda: {"sub": "1", "email": "o@test.de"}
    cl = TestClient(app)

    # exactly the production smoke-test scenario
    cl.delete("/immo/tenancies/101/monat-bezahlt?jahr=2026&monat=3")
    cl.delete("/immo/tenancies/101/monat-bezahlt?jahr=2026&monat=4")

    card = cl.get("/immo/mieter").json()
    debt = card["mieter"][0]["offene_forderung"]
    summe = card["summe"]["offen_gesamt"]
    ok(debt == 940.0, f"the Mieter card says 940,00 (2 × Warmmiete 470) — got {debt}")
    ok(summe == 940.0, f"Bu Ay's Σ says the same — got {summe}")

    ck = cl.get("/immo/cockpit?year=2026").json()
    rueck = ck["kpi"]["rueckstand"]["total"]
    ok(abs(rueck - 940.0) < 0.01,
       f"the REPORT says 940,00 too — NOT 2.800,00 from the ledger — got {rueck}")
    dash = cl.get("/immo/dashboard?year=2026").json()
    ok(abs(dash["financial"]["rueckstand"] - 940.0) < 0.01,
       f"/immo/dashboard agrees as well — NOT 2.800 — got {dash['financial']['rueckstand']}")
    ok(dash["warnings"]["debtors"] == 1, f"one debtor, counted the same way — got {dash['warnings']['debtors']}")
    top = dash["top_debtors"][0] if dash["top_debtors"] else {}
    ok(abs((top.get("debt") or 0) - 940.0) < 0.01, f"the debtor list agrees — got {top.get('debt')}")

    # a payment settles the month → every surface must move together
    cl.post("/immo/rent", json={"property_id": 10, "tenancy_id": 101, "betrag": 470,
                                "datum": "2026-07-05", "fuer_jahr": 2026, "fuer_monat": 3})
    card = cl.get("/immo/mieter").json()["mieter"][0]["offene_forderung"]
    rueck = cl.get("/immo/cockpit?year=2026").json()["kpi"]["rueckstand"]["total"]
    ok(card == 470.0 and abs(rueck - 470.0) < 0.01,
       f"after a Mieteingang payment: card {card} == report {rueck} (both 470)")

    src = open("autotax/immo_api.py", encoding="utf-8").read()
    ok("src_arrears_total" not in src.split("def portfolio_view")[1].split("def ")[0],
       "portfolio_view no longer reads any debt from the ledger — no env var can bring it back")

    print(f"\n=== NO THIRD BOOK: {PASS} passed, {FAIL} failed ===")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
