"""Faz 4.2 Commit 2 proof — portfolio_view + lazy-ensure + endpoint wiring.

Flag OFF → dashboard/cockpit identical to today. Flag ON → debt metrics from the
ledger (lazy-ensured fresh). Error in refresh/read → OLD fallback, endpoint still
answers. Perf log (ledger_refresh_ms/created_entries/status) emitted per GET.
Self-contained: in-memory SQLite (StaticPool), TestClient. No prod DB / network.
Run:  PYTHONIOENCODING=utf-8 PYTHONPATH=. python tests/test_immo_portfolio_view.py
"""
import logging
import os
import sys
from datetime import date

os.environ.setdefault("JWT_SECRET", "test-secret-" + "x" * 40)
os.environ["ADMIN_EMAILS"] = "owner@test.de"
os.environ["IMMO_LEDGER_READ"] = "0"

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi import FastAPI
from fastapi.testclient import TestClient

from autotax.models import Base, ImmoProperty, ImmoUnit, ImmoTenancy, ImmoRent
from autotax import immo_ledger as L
from autotax import immo_api
from autotax.auth import get_current_user

PASS, FAIL = 0, 0


def ok(cond, msg):
    global PASS, FAIL
    if cond:
        PASS += 1; print(f"  PASS  {msg}")
    else:
        FAIL += 1; print(f"  FAIL  {msg}")


def seed(db, backfill=True):
    db.add(ImmoProperty(id=100, user_id=1, name="TEST Immobilie", is_deleted=False))
    for i in range(1, 7):
        db.add(ImmoUnit(id=i, property_id=100, user_id=1, name=f"WHG-0{i}", soll_miete=850))
    db.add_all([
        ImmoTenancy(id=101, unit_id=1, user_id=1, mieter_name="Test Mieter 1", von=date(2025, 1, 1), bis=None, kaltmiete=800),
        ImmoTenancy(id=102, unit_id=2, user_id=1, mieter_name="Test Mieter 2", von=date(2025, 1, 1), bis=None, kaltmiete=700),
        ImmoTenancy(id=103, unit_id=3, user_id=1, mieter_name="Test Mieter 3", von=date(2025, 1, 1), bis=None, kaltmiete=900),
        ImmoTenancy(id=104, unit_id=4, user_id=1, mieter_name="Test Mieter 4", von=date(2025, 1, 1), bis=date(2025, 6, 30), kaltmiete=600),
        ImmoTenancy(id=105, unit_id=5, user_id=1, mieter_name="Test Mieter 5", von=date(2025, 1, 1), bis=None, kaltmiete=500),
    ])
    rid = [6000]

    def pay(tid, betrag, mo):
        rid[0] += 1
        db.add(ImmoRent(id=rid[0], property_id=100, tenancy_id=tid, user_id=1, datum=date(2025, mo, 10), betrag=betrag))
    for mo, amt in [(1, 5000), (2, 5000)]:
        pay(101, amt, mo)
    for mo in range(1, 6):
        pay(102, 700, mo)
    for mo in (1, 2):
        pay(103, 900, mo)
    for mo in range(1, 5):
        pay(104, 600, mo)
    for mo in range(1, 7):
        pay(105, 500, mo)
    pay(105, -200, 7)
    db.commit()
    if backfill:
        L.run_backfill(db, 1, dry_run=False)


def main():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=eng)
    L.ensure_ledger_indexes(eng)
    S = sessionmaker(bind=eng)
    db = S(); seed(db); db.close()
    immo_api.SessionLocal = S
    app = FastAPI(); app.include_router(immo_api.router)
    app.dependency_overrides[get_current_user] = lambda: {"sub": "1", "email": "owner@test.de"}
    cl = TestClient(app)

    print("\n[1] flag OFF → portfolio_view == _portfolio, cockpit identical")
    os.environ["IMMO_LEDGER_READ"] = "0"
    db = S()
    pv = immo_api.portfolio_view(db, 1, 2025)
    old = immo_api._portfolio(db, 1, 2025)
    ok(pv == old, "OFF portfolio_view == _portfolio")
    ck = immo_api._cockpit(db, 1, 2025)
    cv = immo_api._cockpit(db, 1, 2025, base=immo_api.portfolio_view(db, 1, 2025))
    ok(cv == ck, "OFF cockpit(base=view) == cockpit()")
    ok(old["financial"]["rueckstand"] == 18300.0, f"OLD rueckstand 18300 (got {old['financial']['rueckstand']})")
    db.close()

    print("\n[2] flag ON → debt from LEDGER (proven by a ledger-only divergence)")
    os.environ["IMMO_LEDGER_READ"] = "1"
    db = S()
    # ledger-only korrektur (+500 on tenancy 105) — OLD doesn't know it
    L.post_entry(db, user_id=1, typ=L.TYP_KORREKTUR, betrag=500, jahr=2025, monat=7, tenancy_id=105, commit=True)
    pv_on = immo_api.portfolio_view(db, 1, 2025)
    ok(pv_on["financial"]["rueckstand"] == 18800.0, f"ON rueckstand 18800 = ledger incl. korrektur (got {pv_on['financial']['rueckstand']})")
    ok(pv_on["financial"]["rueckstand"] != old["financial"]["rueckstand"], "ON value differs from OLD → reads LEDGER not OLD")
    ok(pv_on["warnings"]["debtors"] == 4, f"ON debtor warning from ledger (got {pv_on['warnings']['debtors']})")
    ok(immo_api.parity_report(db, 1, 2025)["passed"] in (True, False), "parity_report still runs (pure OLD vs ledger)")
    db.close()

    print("\n[3] lazy-ensure POPULATES an empty ledger on ON read")
    eng2 = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=eng2); L.ensure_ledger_indexes(eng2)
    S2 = sessionmaker(bind=eng2)
    db = S2(); seed(db, backfill=False)  # NO backfill → ledger empty
    from autotax.models import ImmoLedgerEntry
    before = db.query(ImmoLedgerEntry).count()
    pv2 = immo_api.portfolio_view(db, 1, 2025)  # flag ON → lazy ensure fills ledger
    after = db.query(ImmoLedgerEntry).count()
    ok(before == 0 and after > 0, f"lazy-ensure created ledger rows ({before}→{after})")
    ok(pv2["financial"]["rueckstand"] == 18300.0, f"ON rueckstand from freshly-ensured ledger 18300 (got {pv2['financial']['rueckstand']})")
    db.close()

    print("\n[4] perf log fields emitted per GET")
    recs = []
    h = logging.Handler(); h.emit = lambda r: recs.append(r.getMessage())
    lg = logging.getLogger("autotax"); lg.addHandler(h); lg.setLevel(logging.INFO)
    db = S(); immo_api.portfolio_view(db, 1, 2025); db.close()
    lg.removeHandler(h)
    perf = [m for m in recs if "ledger_refresh_status" in m]
    ok(perf and "ledger_refresh_ms" in perf[-1] and "ledger_created_entries" in perf[-1],
       f"perf log has ms/created/status (got {perf[-1] if perf else None})")

    print("\n[5] error → OLD fallback, endpoint still responds")
    orig = immo_api._ledger.run_backfill
    immo_api._ledger.run_backfill = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
    try:
        db = S()
        pv_err = immo_api.portfolio_view(db, 1, 2025)
        ok(pv_err["financial"]["rueckstand"] == 18300.0, f"refresh error → OLD fallback 18300 (got {pv_err['financial']['rueckstand']})")
        db.close()
        r = cl.get("/immo/dashboard?year=2025")
        ok(r.status_code == 200 and r.json()["financial"]["rueckstand"] == 18300.0, f"endpoint still 200 + OLD numbers (got {r.status_code})")
    finally:
        immo_api._ledger.run_backfill = orig

    print("\n[6] endpoints respond (OFF + ON)")
    os.environ["IMMO_LEDGER_READ"] = "0"
    ok(cl.get("/immo/dashboard?year=2025").status_code == 200, "OFF /dashboard 200")
    ok(cl.get("/immo/cockpit?year=2025").status_code == 200, "OFF /cockpit 200")
    os.environ["IMMO_LEDGER_READ"] = "1"
    ok(cl.get("/immo/dashboard?year=2025").status_code == 200, "ON /dashboard 200")
    ok(cl.get("/immo/cockpit?year=2025").status_code == 200, "ON /cockpit 200")
    os.environ["IMMO_LEDGER_READ"] = "0"

    print(f"\n=== Faz 4.2 C2 portfolio_view: {PASS} passed, {FAIL} failed ===")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
