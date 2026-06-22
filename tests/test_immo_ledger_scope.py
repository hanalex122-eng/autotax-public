"""Faz 3-fix proof — backfill scoping honors property soft-deletion (OLD parity).

A tenancy/rent under a SOFT-DELETED property is an orphan and must be EXCLUDED
from the backfill, exactly like OLD _portfolio (orphan-leak fix b03c292). Seeds
one active property (with data) and one deleted property (with orphan data) and
asserts only the active one is backfilled. No prod DB / network.
Run:  PYTHONIOENCODING=utf-8 PYTHONPATH=. python tests/test_immo_ledger_scope.py
"""
import sys
from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from autotax.models import Base, ImmoProperty, ImmoUnit, ImmoTenancy, ImmoRent, ImmoLedgerEntry
from autotax import immo_ledger as L

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
    UID = 1

    # P10 ACTIVE, P20 SOFT-DELETED (orphan)
    db.add(ImmoProperty(id=10, user_id=UID, name="Aktiv", is_deleted=False))
    db.add(ImmoProperty(id=20, user_id=UID, name="Gelöscht", is_deleted=True))
    db.add(ImmoUnit(id=1, property_id=10, user_id=UID, name="WHG-01", soll_miete=850))
    db.add(ImmoUnit(id=2, property_id=20, user_id=UID, name="WHG-OLD", soll_miete=800))
    db.add(ImmoTenancy(id=101, unit_id=1, user_id=UID, mieter_name="Aktiv-Mieter", von=date(2026, 1, 1), bis=None, kaltmiete=850))
    db.add(ImmoTenancy(id=201, unit_id=2, user_id=UID, mieter_name="Orphan-Mieter", von=date(2026, 1, 1), bis=None, kaltmiete=800))
    db.add(ImmoRent(id=5001, property_id=10, tenancy_id=101, user_id=UID, datum=date(2026, 1, 15), betrag=850))
    db.add(ImmoRent(id=5002, property_id=20, tenancy_id=201, user_id=UID, datum=date(2026, 1, 15), betrag=800))
    db.commit()

    print("\n[1] run_backfill dry-run — orphan (deleted property) EXCLUDED")
    r = L.run_backfill(db, UID, dry_run=True)
    ok(r == {"dry_run": True, "soll_to_create": 12, "payments_to_import": 1, "tenancies": 1, "rents": 1},
       f"only active property counted: 12 soll / 1 payment / 1 tenancy / 1 rent (got {r})")

    print("\n[2] execute — ledger contains ONLY active-property data")
    L.run_backfill(db, UID, dry_run=False)
    all_e = db.query(ImmoLedgerEntry).all()
    ok(len(all_e) == 13, f"13 ledger rows (12 soll + 1 zahlung) (got {len(all_e)})")
    ok(all(e.tenancy_id == 101 for e in all_e), "every entry belongs to active tenancy 101")
    ok(all(e.property_id == 10 for e in all_e), "every entry under active property 10")
    ok(db.query(ImmoLedgerEntry).filter(ImmoLedgerEntry.tenancy_id == 201).count() == 0, "orphan tenancy 201 → 0 entries")
    ok(db.query(ImmoLedgerEntry).filter(ImmoLedgerEntry.source_rent_id == 5002).count() == 0, "orphan rent 5002 NOT imported")

    print("\n[3] idempotent after fix")
    r2 = L.run_backfill(db, UID, dry_run=False)
    ok(r2["soll_to_create"] == 0 and r2["payments_to_import"] == 0, f"re-run 0 new (got {r2})")
    ok(db.query(ImmoLedgerEntry).count() == 13, "still 13 rows")

    db.close()
    print(f"\n=== Faz 3-fix scope: {PASS} passed, {FAIL} failed ===")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
