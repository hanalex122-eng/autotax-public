"""Faz 1.2 proof — run_backfill orchestrator + POST /immo/_ledger/backfill.

Covers: dry-run writes nothing, execute writes (single txn), idempotency, and the
HTTP endpoint (admin gate + JSON shape). Self-contained: in-memory SQLite via
StaticPool (shared across connections), FastAPI TestClient, get_current_user
overridden. No prod DB / network.
Run:  PYTHONIOENCODING=utf-8 PYTHONPATH=. python tests/test_immo_ledger_faz1_endpoint.py
"""
import os
import sys
from datetime import date

os.environ.setdefault("JWT_SECRET", "test-secret-" + "x" * 40)
os.environ["ADMIN_EMAILS"] = "owner@test.de"

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from autotax.models import Base, ImmoUnit, ImmoTenancy, ImmoRent, ImmoLedgerEntry
from autotax import immo_ledger as L

PASS, FAIL = 0, 0


def ok(cond, msg):
    global PASS, FAIL
    if cond:
        PASS += 1; print(f"  PASS  {msg}")
    else:
        FAIL += 1; print(f"  FAIL  {msg}")


def fresh_db():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=eng)
    L.ensure_ledger_indexes(eng)
    Session = sessionmaker(bind=eng)
    return eng, Session


def seed(db, uid=1, pid=10):
    db.add_all([
        ImmoUnit(id=1, property_id=pid, user_id=uid, name="WHG-01", soll_miete=850),
        ImmoUnit(id=2, property_id=pid, user_id=uid, name="WHG-02", soll_miete=800),
    ])
    db.add_all([
        ImmoTenancy(id=101, unit_id=1, user_id=uid, mieter_name="Müller", von=date(2026, 1, 1), bis=None, kaltmiete=850),
        ImmoTenancy(id=102, unit_id=2, user_id=uid, mieter_name="Schmidt", von=date(2026, 4, 1), bis=date(2026, 9, 30), kaltmiete=800),
    ])
    db.add_all([
        ImmoRent(id=5001, property_id=pid, tenancy_id=101, user_id=uid, datum=date(2026, 1, 15), betrag=850),
        ImmoRent(id=5002, property_id=pid, tenancy_id=101, user_id=uid, datum=date(2026, 2, 15), betrag=850),
    ])
    db.commit()


def ledger_count(Session):
    db = Session()
    try:
        return db.query(ImmoLedgerEntry).count()
    finally:
        db.close()


def main():
    # ── function-level: dry-run / execute / idempotency ──
    eng, Session = fresh_db()
    db = Session(); seed(db); db.close()

    print("\n[1] run_backfill dry-run — counts, writes NOTHING")
    db = Session()
    r = L.run_backfill(db, 1, dry_run=True)
    db.close()
    # 2026: T1 full-year 12 + T2 Apr-Sep 6 = 18 soll ; 2 rents imported ; 2 tenancies
    ok(r == {"dry_run": True, "soll_to_create": 18, "payments_to_import": 2, "tenancies": 2, "rents": 2},
       f"dry-run result shape+counts (got {r})")
    ok(ledger_count(Session) == 0, "dry-run wrote NOTHING (ledger empty)")

    print("\n[2] run_backfill execute — writes in one txn")
    db = Session()
    r2 = L.run_backfill(db, 1, dry_run=False)
    db.close()
    ok(r2["dry_run"] is False and r2["soll_to_create"] == 18 and r2["payments_to_import"] == 2,
       f"execute counts (got {r2})")
    ok(ledger_count(Session) == 20, f"ledger has 20 rows (18 soll + 2 zahlung) (got {ledger_count(Session)})")

    print("\n[3] run_backfill re-execute — idempotent")
    db = Session()
    r3 = L.run_backfill(db, 1, dry_run=False)
    db.close()
    ok(r3["soll_to_create"] == 0 and r3["payments_to_import"] == 0, f"re-execute 0 new (got {r3})")
    ok(ledger_count(Session) == 20, "ledger still 20 (no duplicates)")

    # ── HTTP endpoint via TestClient ──
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from autotax import immo_api
    from autotax.auth import get_current_user

    eng2, Session2 = fresh_db()
    db = Session2(); seed(db); db.close()
    immo_api.SessionLocal = Session2  # endpoint uses this

    app = FastAPI(); app.include_router(immo_api.router)
    state = {"user": {"sub": "1", "email": "owner@test.de"}}
    app.dependency_overrides[get_current_user] = lambda: state["user"]
    client = TestClient(app)

    print("\n[4] endpoint — non-admin → 403")
    state["user"] = {"sub": "1", "email": "intruder@test.de"}
    resp = client.post("/immo/_ledger/backfill?dry_run=true")
    ok(resp.status_code == 403, f"non-admin 403 (got {resp.status_code})")
    ok(ledger_count(Session2) == 0, "non-admin wrote nothing")

    print("\n[5] endpoint — admin dry-run → 200, shape, no write")
    state["user"] = {"sub": "1", "email": "owner@test.de"}
    resp = client.post("/immo/_ledger/backfill?dry_run=true")
    j = resp.json()
    ok(resp.status_code == 200, f"admin dry-run 200 (got {resp.status_code})")
    ok(set(j.keys()) == {"dry_run", "soll_to_create", "payments_to_import", "tenancies", "rents"},
       f"exact JSON shape (got {sorted(j.keys())})")
    ok(j["dry_run"] is True and j["soll_to_create"] == 18 and j["payments_to_import"] == 2, f"dry-run counts (got {j})")
    ok(ledger_count(Session2) == 0, "endpoint dry-run wrote nothing")

    print("\n[6] endpoint — admin execute → 200 writes; re-execute idempotent")
    resp = client.post("/immo/_ledger/backfill?dry_run=false")
    j = resp.json()
    ok(resp.status_code == 200 and j["dry_run"] is False and j["soll_to_create"] == 18, f"execute 200 (got {j})")
    ok(ledger_count(Session2) == 20, f"endpoint execute wrote 20 (got {ledger_count(Session2)})")
    resp = client.post("/immo/_ledger/backfill?dry_run=false")
    ok(resp.json()["soll_to_create"] == 0, "endpoint re-execute idempotent (0 new)")
    ok(ledger_count(Session2) == 20, "ledger still 20 after re-execute")

    print(f"\n=== Faz 1.2 backfill endpoint: {PASS} passed, {FAIL} failed ===")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
