"""immo_source adapter under the EXCEPTION ENGINE — flag toggles two DISTINCT domains.

MODEL CHANGE: user-facing debt is now exception-based ('no problem reported' = paid),
NOT Soll−Ist over immo_rent. The old "OFF==ON cutover is safe" parity premise is
therefore RETIRED: the two sources now mean different things and are EXPECTED to
differ.

  • IMMO_LEDGER_READ OFF (default, the live consumer path)
        src_arrears_total / src_tenancy_arrears  →  OLD engine = EXCEPTION debt
        (reported exceptions only; immo_rent rows do NOT drive it).
  • IMMO_LEDGER_READ ON
        →  the LEDGER read model, a SEPARATE audit domain over real immo_rent
        payments (Soll−Ist), kept for reconciliation — not the user surface.

This test seeds the realistic fixture (immo_rent → 18300 audit debt) AND reports a
DIFFERENT set of exceptions (→ 13900 user debt, 2 debtors) precisely to prove the
flag selects two independent domains. No prod DB / network.
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
from autotax import immo_api
from autotax import immo_payments as _pay

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
    t102 = db.query(ImmoTenancy).filter(ImmoTenancy.id == 102).first()
    t103 = db.query(ImmoTenancy).filter(ImmoTenancy.id == 103).first()

    # EXCEPTION ENGINE user-facing debt: report ONLY T102 (4900) and T103 (9000) as
    # problems → user total 13900, 2 debtors. T105/T101 have NO problem reported →
    # user debt 0 EVEN THOUGH immo_rent (the audit domain) shows 3200 / overpaid.
    _pay.sql_service(db).report_problem(1, t102.id, 2025, 1, "partial", offen=4900.0)
    _pay.sql_service(db).report_problem(1, t103.id, 2025, 1, "partial", offen=9000.0)
    db.commit()

    print("\n[1] flag OFF (live path) → EXCEPTION debt (reported problems only)")
    os.environ["IMMO_LEDGER_READ"] = "0"
    off_total = S.src_arrears_total(db, 1, 2025)
    ok(off_total == 13900.0, f"OFF arrears_total = 13900 (reported exceptions) (got {off_total})")
    ok(S.src_tenancy_arrears(db, 1, t103, 2025) == 9000.0, f"OFF T103 = 9000 (reported) (got {S.src_tenancy_arrears(db,1,t103,2025)})")
    ok(S.src_tenancy_arrears(db, 1, t102, 2025) == 4900.0, f"OFF T102 = 4900 (reported) (got {S.src_tenancy_arrears(db,1,t102,2025)})")
    ok(S.src_tenancy_arrears(db, 1, t105, 2025) == 0.0,
       f"OFF T105 = 0 (no problem reported, even though immo_rent underpaid) (got {S.src_tenancy_arrears(db,1,t105,2025)})")
    ok(S.src_tenancy_arrears(db, 1, t101, 2025) == 0.0, f"OFF T101 = 0 (no problem) (got {S.src_tenancy_arrears(db,1,t101,2025)})")

    print("\n[2] flag ON → LEDGER audit domain (Soll−Ist over immo_rent, independent)")
    os.environ["IMMO_LEDGER_READ"] = "1"
    on_total = S.src_arrears_total(db, 1, 2025)
    ok(on_total == 18300.0, f"ON arrears_total = 18300 (immo_rent audit domain) (got {on_total})")
    ok(S.src_tenancy_arrears(db, 1, t105, 2025) == 3200.0, f"ON T105 = 3200 (immo_rent Soll−Ist) (got {S.src_tenancy_arrears(db,1,t105,2025)})")

    print("\n[3] the two domains are INDEPENDENT (parity premise retired)")
    ok(off_total != on_total, f"OFF (exceptions {off_total}) != ON (audit {on_total}) — distinct domains")
    ok(S.src_tenancy_arrears(db, 1, t105, 2025) != 0.0, "T105: audit domain (ON) shows debt where user domain (OFF) shows 0")

    os.environ["IMMO_LEDGER_READ"] = "0"
    db.close()
    print(f"\n=== immo_source (exception engine vs audit domain): {PASS} passed, {FAIL} failed ===")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
