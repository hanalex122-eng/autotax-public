"""Faz 4.2 Commit 1 proof — parity is INDEPENDENT of IMMO_LEDGER_READ.

Guarantee for cutover: flipping the flag must NOT change parity_report, because
parity must always compare the TRUE OLD engine vs the ledger. _portfolio/_cockpit
stay pure OLD; the flag lives only in the consumer wrapper (Faz 4.2 Commit 2), so
parity is isolated by construction. This test locks that in. No prod DB / network.
Run:  PYTHONIOENCODING=utf-8 PYTHONPATH=. python tests/test_immo_parity_flag.py
"""
import os
import sys
from datetime import date

os.environ.setdefault("JWT_SECRET", "test-secret-" + "x" * 40)

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from autotax.models import Base, ImmoProperty, ImmoUnit, ImmoTenancy, ImmoRent
from autotax import immo_ledger as L
from autotax import immo_api

PASS, FAIL = 0, 0


def ok(cond, msg):
    global PASS, FAIL
    if cond:
        PASS += 1; print(f"  PASS  {msg}")
    else:
        FAIL += 1; print(f"  FAIL  {msg}")


def main():
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=eng)
    L.ensure_ledger_indexes(eng)
    db = sessionmaker(bind=eng)()
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
    rid = 6000

    def pay(tid, betrag, mo):
        nonlocal rid
        rid += 1
        db.add(ImmoRent(id=rid, property_id=100, tenancy_id=tid, user_id=1, datum=date(2025, mo, 10), betrag=betrag))
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
    L.run_backfill(db, 1, dry_run=False)

    print("\n[1] parity with flag OFF")
    os.environ["IMMO_LEDGER_READ"] = "0"
    rep_off = immo_api.parity_report(db, 1, 2025)
    ok(rep_off["passed"] is True, f"OFF passed=True (got {rep_off['passed']})")

    print("\n[2] parity with flag ON")
    os.environ["IMMO_LEDGER_READ"] = "1"
    rep_on = immo_api.parity_report(db, 1, 2025)
    ok(rep_on["passed"] is True, f"ON passed=True (got {rep_on['passed']})")

    print("\n[3] flag does NOT change parity (isolation guarantee)")
    ok(rep_off == rep_on, "parity_report identical OFF vs ON")
    om = {m["metric"]: (m["old"], m["ledger"]) for m in rep_off["metrics"]}
    nm = {m["metric"]: (m["old"], m["ledger"]) for m in rep_on["metrics"]}
    ok(om == nm, "every metric old/ledger identical regardless of flag")
    ok(om["offene_forderung"] == (18300.0, 18300.0), f"OLD side still real OLD numbers (got {om['offene_forderung']})")

    os.environ["IMMO_LEDGER_READ"] = "0"
    db.close()
    print(f"\n=== Faz 4.2 C1 parity-flag-independence: {PASS} passed, {FAIL} failed ===")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
