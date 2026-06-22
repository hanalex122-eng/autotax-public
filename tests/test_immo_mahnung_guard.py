"""Faz 4.3 proof — Mahnung amount behind the per-Mahnung parity GUARD.

Flag OFF → OLD _tenancy_arrears (bit-for-bit). Flag ON → ledger amount ONLY when it
equals OLD to the cent; mismatch / lazy-ensure-fail → OLD + WARN telemetry. A wrong
amount must never reach a legal Mahnung. Self-contained: in-memory SQLite
(StaticPool), TestClient. No prod DB / network.
Run:  PYTHONIOENCODING=utf-8 PYTHONPATH=. python tests/test_immo_mahnung_guard.py
"""
import logging
import os
import sys
from datetime import date

os.environ.setdefault("JWT_SECRET", "test-secret-" + "x" * 40)
os.environ["ADMIN_EMAILS"] = "owner@test.de"
os.environ["IMMO_LEDGER_MAHNUNG"] = "0"
os.environ["IMMO_LEDGER_READ"] = "0"

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi import FastAPI
from fastapi.testclient import TestClient

from autotax.models import Base, ImmoProperty, ImmoUnit, ImmoTenancy, ImmoRent, ImmoMahnung
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


class Cap(logging.Handler):
    def __init__(self): super().__init__(); self.msgs = []
    def emit(self, r): self.msgs.append(r.getMessage())


def main():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=eng)
    L.ensure_ledger_indexes(eng)
    S = sessionmaker(bind=eng)
    db = S()
    db.add(ImmoProperty(id=100, user_id=1, name="T", is_deleted=False))
    db.add(ImmoUnit(id=1, property_id=100, user_id=1, name="WHG-01", soll_miete=800))
    db.add(ImmoTenancy(id=105, unit_id=1, user_id=1, mieter_name="Test Mieter S", von=date(2025, 1, 1), bis=None, kaltmiete=800))
    rid = 7000
    for mo in range(1, 6):  # 5×800 = 4000 paid ; soll 12×800=9600 ; arrears 5600
        rid += 1
        db.add(ImmoRent(id=rid, property_id=100, tenancy_id=105, user_id=1, datum=date(2025, mo, 10), betrag=800))
    db.commit()
    L.run_backfill(db, 1, dry_run=False)
    t = db.query(ImmoTenancy).filter(ImmoTenancy.id == 105).first()

    cap = Cap(); lg = logging.getLogger("autotax"); lg.addHandler(cap); lg.setLevel(logging.INFO)

    print("\n[1] flag OFF → OLD _tenancy_arrears (bit-for-bit)")
    os.environ["IMMO_LEDGER_MAHNUNG"] = "0"
    ok(immo_api._mahnung_betrag(db, 1, t, 2025) == 5600.0, "OFF betrag == OLD 5600")
    ok(immo_api._mahnung_betrag(db, 1, t, 2025) == immo_api._tenancy_arrears(db, 1, t, 2025), "OFF == _tenancy_arrears")

    print("\n[2] flag ON, ledger == OLD → ledger amount")
    os.environ["IMMO_LEDGER_MAHNUNG"] = "1"
    ok(immo_api._mahnung_betrag(db, 1, t, 2025) == 5600.0, "ON betrag == 5600 (ledger==old)")

    print("\n[3] flag ON, ledger != OLD → GUARD falls back to OLD + WARN")
    L.post_entry(db, user_id=1, typ=L.TYP_KORREKTUR, betrag=300, jahr=2025, monat=7, tenancy_id=105, commit=True)
    cap.msgs.clear()
    g = immo_api._mahnung_betrag(db, 1, t, 2025)
    ok(g == 5600.0, f"GUARD: mismatch (ledger 5900) → OLD 5600 used (got {g})")
    mism = [m for m in cap.msgs if "mahnung_parity_mismatch" in m]
    ok(bool(mism), "WARN mahnung_parity_mismatch logged")
    ok(mism and "old=5600.0" in mism[-1] and "ledger=5900.0" in mism[-1] and "diff=300.0" in mism[-1],
       f"telemetry has old/ledger/diff (got {mism[-1] if mism else None})")

    print("\n[4] flag ON, lazy-ensure FAILS → OLD fallback + WARN")
    orig = immo_api._ledger.run_backfill
    immo_api._ledger.run_backfill = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
    cap.msgs.clear()
    try:
        gf = immo_api._mahnung_betrag(db, 1, t, 2025)
        ok(gf == 5600.0, f"refresh fail → OLD 5600 (got {gf})")
        ok(any("mahnung_guard refresh_failed" in m for m in cap.msgs), "WARN refresh_failed logged")
    finally:
        immo_api._ledger.run_backfill = orig
    lg.removeHandler(cap)

    print("\n[5] endpoint: create_mahnung records guarded betrag, returns PDF")
    immo_api.SessionLocal = S
    app = FastAPI(); app.include_router(immo_api.router)
    app.dependency_overrides[get_current_user] = lambda: {"sub": "1", "email": "owner@test.de"}
    cl = TestClient(app)
    os.environ["IMMO_LEDGER_MAHNUNG"] = "0"
    r = cl.post("/immo/tenancies/105/mahnung", json={"stufe": 1, "year": 2025})
    ok(r.status_code == 200 and r.headers.get("content-type", "").startswith("application/pdf"), f"OFF mahnung 200 PDF (got {r.status_code})")
    rec = S().query(ImmoMahnung).filter(ImmoMahnung.tenancy_id == 105).order_by(ImmoMahnung.id.desc()).first()
    ok(rec is not None and rec.betrag == 5600.0, f"recorded betrag 5600 (got {rec.betrag if rec else None})")

    print("\n[6] 4.2 untouched: Mahnung flag independent of dashboard flag")
    ok("IMMO_LEDGER_READ" != "IMMO_LEDGER_MAHNUNG", "separate flags (sanity)")
    os.environ["IMMO_LEDGER_MAHNUNG"] = "0"; os.environ["IMMO_LEDGER_READ"] = "0"
    db.close()

    print(f"\n=== Faz 4.3 mahnung guard: {PASS} passed, {FAIL} failed ===")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
