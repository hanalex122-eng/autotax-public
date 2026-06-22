"""Faz 3 proof — parity_report (OLD engine vs LEDGER) + endpoint gate.

Seeds property/unit/tenancy/rent, runs the Faz 1 backfill so ledger == OLD, then
asserts parity_report passes all 6 metrics. A second case corrupts the ledger
(soft-deletes one Sollbuchung) and proves the gate FAILS the right metrics.
Finally checks the admin endpoint (403 + passed=True). No prod DB / network.
Run:  PYTHONIOENCODING=utf-8 PYTHONPATH=. python tests/test_immo_ledger_parity.py
"""
import os
import sys
from datetime import date

os.environ.setdefault("JWT_SECRET", "test-secret-" + "x" * 40)
os.environ["ADMIN_EMAILS"] = "owner@test.de"

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from autotax.models import Base, ImmoProperty, ImmoUnit, ImmoTenancy, ImmoRent, ImmoLedgerEntry
from autotax import immo_ledger as L
from autotax import immo_api

PASS, FAIL = 0, 0


def ok(cond, msg):
    global PASS, FAIL
    if cond:
        PASS += 1; print(f"  PASS  {msg}")
    else:
        FAIL += 1; print(f"  FAIL  {msg}")


def fresh():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=eng)
    L.ensure_ledger_indexes(eng)
    return eng, sessionmaker(bind=eng)


def seed_and_backfill(db):
    db.add(ImmoProperty(id=10, user_id=1, name="Haus A", einheiten=1))
    db.add(ImmoUnit(id=1, property_id=10, user_id=1, name="WHG-01", soll_miete=850))
    db.add(ImmoTenancy(id=101, unit_id=1, user_id=1, mieter_name="Müller", von=date(2026, 1, 1), bis=None, kaltmiete=850))
    db.add(ImmoRent(id=5001, property_id=10, tenancy_id=101, user_id=1, datum=date(2026, 1, 15), betrag=850))
    db.commit()
    L.ensure_sollbuchungen(db, 1, 2026)
    L.import_rents_to_ledger(db, 1)
    db.commit()


def by_metric(rep):
    return {m["metric"]: m for m in rep["metrics"]}


def main():
    # ── [1] perfect parity ──
    eng, S = fresh()
    db = S(); seed_and_backfill(db)
    rep = immo_api.parity_report(db, 1, 2026)
    m = by_metric(rep)
    print("\n[1] perfect parity — all metrics OK")
    ok(rep["passed"] is True, f"passed=True (got {rep['passed']})")
    ok(m["offene_forderung"]["old"] == 9350.0 and m["offene_forderung"]["ledger"] == 9350.0 and m["offene_forderung"]["ok"],
       f"offene_forderung 9350==9350 (got {m['offene_forderung']})")
    ok(m["debtor_count"]["old"] == 1 and m["debtor_count"]["ledger"] == 1 and m["debtor_count"]["ok"], "debtor_count 1==1")
    ok(m["mahnung_candidates"]["ok"], "mahnung_candidates ok")
    ok(m["cockpit_critical"]["old"] == m["cockpit_critical"]["ledger"] and m["cockpit_critical"]["ok"],
       f"cockpit_critical match (got {m['cockpit_critical']})")
    ok(m["collected_rent"]["old"] == 850.0 and m["collected_rent"]["ledger"] == 850.0 and m["collected_rent"]["ok"],
       f"collected_rent 850==850 (got {m['collected_rent']})")
    ok(m["tenancy_saldo"]["old"] == 9350.0 and m["tenancy_saldo"]["ledger"] == 9350.0 and m["tenancy_saldo"]["ok"],
       f"tenancy_saldo 9350==9350 (got {m['tenancy_saldo']})")
    db.close()

    # ── [2] corrupted ledger → gate FAILS ──
    eng2, S2 = fresh()
    db = S2(); seed_and_backfill(db)
    victim = db.query(ImmoLedgerEntry).filter(ImmoLedgerEntry.typ == "sollbuchung").first()
    victim.is_deleted = True
    db.commit()
    rep2 = immo_api.parity_report(db, 1, 2026)
    m2 = by_metric(rep2)
    print("\n[2] corrupted ledger (1 Sollbuchung soft-deleted) — gate FAILS")
    ok(rep2["passed"] is False, f"passed=False (got {rep2['passed']})")
    ok(m2["offene_forderung"]["ok"] is False, f"offene_forderung FAIL (old {m2['offene_forderung']['old']} vs ledger {m2['offene_forderung']['ledger']})")
    ok(m2["tenancy_saldo"]["ok"] is False and m2["tenancy_saldo"]["mismatches"], "tenancy_saldo FAIL + mismatch listed")
    ok(m2["collected_rent"]["ok"] is True, "collected_rent still OK (payments untouched)")
    db.close()

    # ── [3] admin endpoint ──
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from autotax.auth import get_current_user
    eng3, S3 = fresh()
    db = S3(); seed_and_backfill(db); db.close()
    immo_api.SessionLocal = S3
    app = FastAPI(); app.include_router(immo_api.router)
    st = {"u": {"sub": "1", "email": "owner@test.de"}}
    app.dependency_overrides[get_current_user] = lambda: st["u"]
    client = TestClient(app)
    print("\n[3] endpoint — admin gate + report")
    st["u"] = {"sub": "1", "email": "intruder@test.de"}
    ok(client.get("/immo/_ledger/parity?year=2026").status_code == 403, "non-admin → 403")
    st["u"] = {"sub": "1", "email": "owner@test.de"}
    r = client.get("/immo/_ledger/parity?year=2026")
    ok(r.status_code == 200 and r.json()["passed"] is True, f"admin 200 + passed=True (got {r.status_code})")

    print(f"\n=== Faz 3 parity: {PASS} passed, {FAIL} failed ===")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
