"""Faz 4.0 proof — delete-cascade (property/unit/tenancy → ledger) + reconcile.

Keeps ledger scope identical to property/unit/tenancy scope so the orphan drift
parity caught can never recur. Pure data consistency — no flag, no read-path.
Self-contained: in-memory SQLite (StaticPool), FastAPI TestClient, admin override.
Run:  PYTHONIOENCODING=utf-8 PYTHONPATH=. python tests/test_immo_ledger_cascade.py
"""
import os
import sys
from datetime import date

os.environ.setdefault("JWT_SECRET", "test-secret-" + "x" * 40)
os.environ["ADMIN_EMAILS"] = "owner@test.de"

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi import FastAPI
from fastapi.testclient import TestClient

from autotax.models import Base, ImmoProperty, ImmoUnit, ImmoTenancy, ImmoRent, ImmoLedgerEntry
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


def fresh():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=eng)
    L.ensure_ledger_indexes(eng)
    return eng, sessionmaker(bind=eng)


def active(S):
    db = S()
    try:
        return db.query(ImmoLedgerEntry).filter(
            (ImmoLedgerEntry.is_deleted == False) | (ImmoLedgerEntry.is_deleted == None)).count()  # noqa: E712
    finally:
        db.close()


def active_for(S, **f):
    db = S()
    try:
        q = db.query(ImmoLedgerEntry).filter(
            (ImmoLedgerEntry.is_deleted == False) | (ImmoLedgerEntry.is_deleted == None))  # noqa: E712
        for k, v in f.items():
            q = q.filter(getattr(ImmoLedgerEntry, k) == v)
        return q.count()
    finally:
        db.close()


def client_for(S):
    immo_api.SessionLocal = S
    app = FastAPI(); app.include_router(immo_api.router)
    app.dependency_overrides[get_current_user] = lambda: {"sub": "1", "email": "owner@test.de"}
    return TestClient(app)


def main():
    # ── cascade ──
    eng, S = fresh()
    db = S()
    db.add(ImmoProperty(id=10, user_id=1, name="Haus", is_deleted=False))
    for i in (1, 2, 3):
        db.add(ImmoUnit(id=i, property_id=10, user_id=1, name=f"WHG-0{i}", soll_miete=800))
        db.add(ImmoTenancy(id=100 + i, unit_id=i, user_id=1, mieter_name=f"Test Mieter {i}", von=date(2026, 1, 1), bis=None, kaltmiete=800))
        db.add(ImmoRent(id=5000 + i, property_id=10, tenancy_id=100 + i, user_id=1, datum=date(2026, 1, 15), betrag=800))
    db.commit()
    L.run_backfill(db, 1, dry_run=False)
    db.close()
    cl = client_for(S)
    ok(active(S) == 39, f"backfill → 39 active ledger rows (3×13) (got {active(S)})")

    print("\n[1] DELETE tenancy → its ledger rows cascade soft-delete")
    r = cl.delete("/immo/tenancies/101")
    ok(r.status_code == 200, "delete tenancy 200")
    ok(active_for(S, tenancy_id=101) == 0, "tenancy 101 ledger → 0 active")
    ok(active(S) == 26, f"others intact → 26 active (got {active(S)})")

    print("\n[2] DELETE unit → its ledger rows cascade")
    cl.delete("/immo/units/2")
    ok(active_for(S, unit_id=2) == 0, "unit 2 ledger → 0 active")
    ok(active(S) == 13, f"only tenancy 103 left → 13 (got {active(S)})")

    print("\n[3] DELETE property → all remaining ledger rows cascade")
    cl.delete("/immo/properties/10")
    ok(active(S) == 0, f"property delete → 0 active ledger (got {active(S)})")

    # ── reconcile (simulated drift) ──
    eng2, S2 = fresh()
    db = S2()
    db.add(ImmoProperty(id=20, user_id=1, name="Drift", is_deleted=False))
    db.add(ImmoUnit(id=1, property_id=20, user_id=1, name="WHG-01", soll_miete=850))
    db.add(ImmoTenancy(id=201, unit_id=1, user_id=1, mieter_name="Test Mieter X", von=date(2026, 1, 1), bis=None, kaltmiete=850))
    db.add(ImmoRent(id=6001, property_id=20, tenancy_id=201, user_id=1, datum=date(2026, 1, 15), betrag=850))
    db.commit()
    L.run_backfill(db, 1, dry_run=False)
    # simulate OLD drift: property soft-deleted WITHOUT cascade (pre-fix data)
    db.query(ImmoProperty).filter(ImmoProperty.id == 20).update({ImmoProperty.is_deleted: True})
    db.commit(); db.close()
    cl2 = client_for(S2)

    print("\n[4] reconcile dry-run — detects orphans, writes nothing")
    j = cl2.post("/immo/_ledger/reconcile?dry_run=true").json()
    ok(j == {"dry_run": True, "orphan_by_property": 13, "orphan_by_unit": 0,
             "orphan_by_tenancy": 0, "total_orphan": 13, "cleaned": 0},
       f"dry-run reports 13 orphan-by-property, cleaned 0 (got {j})")
    ok(active(S2) == 13, "dry-run wrote nothing (still 13 active)")

    print("\n[5] reconcile execute — cleans orphans, idempotent")
    j2 = cl2.post("/immo/_ledger/reconcile?dry_run=false").json()
    ok(j2["cleaned"] == 13 and j2["total_orphan"] == 13, f"execute cleaned 13 (got {j2})")
    ok(active(S2) == 0, "after reconcile → 0 active ledger")
    j3 = cl2.post("/immo/_ledger/reconcile?dry_run=false").json()
    ok(j3["total_orphan"] == 0 and j3["cleaned"] == 0, "re-run → 0 orphan (idempotent)")

    print("\n[6] admin gate")
    immo_api.SessionLocal = S2
    app = FastAPI(); app.include_router(immo_api.router)
    st = {"u": {"sub": "1", "email": "intruder@test.de"}}
    app.dependency_overrides[get_current_user] = lambda: st["u"]
    ok(TestClient(app).post("/immo/_ledger/reconcile").status_code == 403, "non-admin reconcile → 403")

    # ── [7] ROOT-CAUSE proof: scope-based reconcile catches the NULL-unit_id
    #         payment under a unit-only deletion (a unit_id filter would miss it) ──
    eng3, S3 = fresh()
    db = S3()
    db.add(ImmoProperty(id=30, user_id=1, name="Aktiv", is_deleted=False))
    db.add(ImmoUnit(id=1, property_id=30, user_id=1, name="WHG-01", soll_miete=850))
    db.add(ImmoTenancy(id=301, unit_id=1, user_id=1, mieter_name="Test Mieter U", von=date(2026, 1, 1), bis=None, kaltmiete=850))
    db.add(ImmoRent(id=7001, property_id=30, tenancy_id=301, user_id=1, datum=date(2026, 1, 15), betrag=850))
    db.commit()
    L.run_backfill(db, 1, dry_run=False)  # 12 soll (unit_id=1) + 1 payment (unit_id=NULL)
    # simulate drift: UNIT soft-deleted WITHOUT cascade; property + tenancy stay active
    db.query(ImmoUnit).filter(ImmoUnit.id == 1).update({ImmoUnit.is_deleted: True})
    db.commit(); db.close()
    cl3 = client_for(S3)
    print("\n[7] reconcile — unit-only deletion: catches payment with NULL unit_id (scope-based)")
    j = cl3.post("/immo/_ledger/reconcile?dry_run=true").json()
    ok(j["total_orphan"] == 13, f"total_orphan 13 incl. NULL-unit_id payment (a unit_id filter → 12) (got {j['total_orphan']})")
    ok(j["orphan_by_unit"] == 13 and j["orphan_by_property"] == 0 and j["orphan_by_tenancy"] == 0,
       f"all 13 attributed by_unit (got {j})")
    cl3.post("/immo/_ledger/reconcile?dry_run=false")
    ok(active(S3) == 0, "after execute → 0 active (payment cleaned too)")

    print(f"\n=== Faz 4.0 cascade+reconcile: {PASS} passed, {FAIL} failed ===")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
