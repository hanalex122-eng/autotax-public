"""Faz 4.1 proof — source adapter (IMMO_LEDGER_READ flag) OFF==OLD, ON==ledger.

Seeds the realistic landlord fixture (year 2025), backfills, then verifies each
adapter returns the OLD value with the flag OFF, the ledger value with it ON, and
that OFF==ON (cutover is safe). Adapters are INERT (no consumer wired) — this
only exercises them directly. No prod DB / network.
Run:  PYTHONIOENCODING=utf-8 PYTHONPATH=. python tests/test_immo_source.py
"""
import os
import sys
from datetime import date

os.environ.setdefault("JWT_SECRET", "test-secret-" + "x" * 40)
os.environ["IMMO_LEDGER_READ"] = "0"

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from autotax.models import Base, ImmoProperty, ImmoUnit, ImmoTenancy, ImmoRent
from autotax import immo_ledger as L
from autotax import immo_source as S

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
    t105 = db.query(ImmoTenancy).filter(ImmoTenancy.id == 105).first()
    t101 = db.query(ImmoTenancy).filter(ImmoTenancy.id == 101).first()

    def measure():
        return {
            "arrears_total": S.src_arrears_total(db, 1, 2025),
            "debtors": S.src_debtors(db, 1, 2025),
            "arr_105": S.src_tenancy_arrears(db, 1, t105, 2025),
            "arr_101": S.src_tenancy_arrears(db, 1, t101, 2025),
        }

    print("\n[1] flag OFF → OLD engine values")
    os.environ["IMMO_LEDGER_READ"] = "0"
    off = measure()
    ok(off["arrears_total"] == 18300.0, f"OFF arrears_total 18300 (got {off['arrears_total']})")
    ok(len(off["debtors"]) == 4, f"OFF 4 debtors (got {len(off['debtors'])})")
    ok([d["tenant"] for d in off["debtors"]] == ["Test Mieter 3", "Test Mieter 2", "Test Mieter 5", "Test Mieter 4"],
       f"OFF debtors sorted by debt desc (got {[d['tenant'] for d in off['debtors']]})")
    ok(off["arr_105"] == 3200.0, f"OFF tenancy 105 arrears 3200 (got {off['arr_105']})")
    ok(off["arr_101"] == 0.0, f"OFF tenancy 101 (overpaid) arrears 0 (got {off['arr_101']})")

    print("\n[2] flag ON → ledger values")
    os.environ["IMMO_LEDGER_READ"] = "1"
    on = measure()
    ok(on["arrears_total"] == 18300.0, f"ON arrears_total 18300 (got {on['arrears_total']})")
    ok(len(on["debtors"]) == 4, f"ON 4 debtors (got {len(on['debtors'])})")
    ok(on["arr_105"] == 3200.0, f"ON tenancy 105 arrears 3200 (got {on['arr_105']})")

    print("\n[3] OFF == ON (cutover safe)")
    ok(off["arrears_total"] == on["arrears_total"], "arrears_total OFF==ON")
    ok(off["debtors"] == on["debtors"], "debtors OFF==ON (same shape+values+order)")
    ok(off["arr_105"] == on["arr_105"] and off["arr_101"] == on["arr_101"], "tenancy_arrears OFF==ON")

    os.environ["IMMO_LEDGER_READ"] = "0"
    db.close()
    print(f"\n=== Faz 4.1 source adapter: {PASS} passed, {FAIL} failed ===")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
