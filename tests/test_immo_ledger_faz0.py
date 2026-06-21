"""Faz 0 proof — ImmoLedgerEntry posting service, sign enforcement, idempotency.

Self-contained: spins up an in-memory SQLite, create_all + ensure_ledger_indexes,
then asserts the sign rules, saldo math and the partial-unique guards. No prod DB,
no network. Run:  python tests/test_immo_ledger_faz0.py
"""
import sys
from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import IntegrityError

from autotax.models import Base, ImmoLedgerEntry
from autotax import immo_ledger as L

PASS, FAIL = 0, 0


def ok(cond, msg):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS  {msg}")
    else:
        FAIL += 1
        print(f"  FAIL  {msg}")


def expect_error(fn, msg):
    try:
        fn()
        ok(False, f"{msg} (expected LedgerError, none raised)")
    except L.LedgerError:
        ok(True, msg)
    except Exception as e:  # noqa: BLE001
        ok(False, f"{msg} (wrong exception: {type(e).__name__}: {e})")


def main():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    L.ensure_ledger_indexes(engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    UID, PID, TID = 1, 10, 100

    print("\n[1] Sign enforcement — accepted signs")
    e1 = L.post_entry(db, user_id=UID, typ=L.TYP_SOLLBUCHUNG, betrag=850, jahr=2026, monat=1,
                      property_id=PID, tenancy_id=TID, faellig_am=date(2026, 1, 3))
    ok(e1.id is not None and e1.betrag == 850.0, "sollbuchung +850 accepted")
    e2 = L.post_entry(db, user_id=UID, typ=L.TYP_ZAHLUNG, betrag=-850, jahr=2026, monat=1, tenancy_id=TID)
    ok(e2.betrag == -850.0, "zahlung -850 accepted")
    e3 = L.post_entry(db, user_id=UID, typ=L.TYP_TEILZAHLUNG, betrag=-400, jahr=2026, monat=2, tenancy_id=TID)
    ok(e3.betrag == -400.0, "teilzahlung -400 accepted")
    e4 = L.post_entry(db, user_id=UID, typ=L.TYP_MAHNGEBUEHR, betrag=15, jahr=2026, monat=2, tenancy_id=TID)
    ok(e4.betrag == 15.0, "mahngebuehr +15 accepted")
    e5 = L.post_entry(db, user_id=UID, typ=L.TYP_KORREKTUR, betrag=-50, jahr=2026, monat=3, tenancy_id=TID)
    ok(e5.betrag == -50.0, "korrektur -50 accepted (any sign)")
    e6 = L.post_entry(db, user_id=UID, typ=L.TYP_KORREKTUR, betrag=50, jahr=2026, monat=4, tenancy_id=TID)
    ok(e6.betrag == 50.0, "korrektur +50 accepted (any sign)")

    print("\n[2] Sign enforcement — wrong signs REJECTED (no row created)")
    expect_error(lambda: L.post_entry(db, user_id=UID, typ=L.TYP_SOLLBUCHUNG, betrag=-850, jahr=2026, monat=5, tenancy_id=TID),
                 "sollbuchung -850 rejected")
    expect_error(lambda: L.post_entry(db, user_id=UID, typ=L.TYP_MAHNGEBUEHR, betrag=-15, jahr=2026, monat=5, tenancy_id=TID),
                 "mahngebuehr -15 rejected")
    expect_error(lambda: L.post_entry(db, user_id=UID, typ=L.TYP_ZAHLUNG, betrag=850, jahr=2026, monat=5, tenancy_id=TID),
                 "zahlung +850 rejected")
    expect_error(lambda: L.post_entry(db, user_id=UID, typ=L.TYP_TEILZAHLUNG, betrag=400, jahr=2026, monat=5, tenancy_id=TID),
                 "teilzahlung +400 rejected")

    print("\n[3] Amount / type guards")
    expect_error(lambda: L.post_entry(db, user_id=UID, typ=L.TYP_KORREKTUR, betrag=0, jahr=2026, monat=5, tenancy_id=TID),
                 "betrag 0 rejected")
    expect_error(lambda: L.post_entry(db, user_id=UID, typ=L.TYP_SOLLBUCHUNG, betrag=float("inf"), jahr=2026, monat=5, tenancy_id=TID),
                 "betrag Inf rejected")
    expect_error(lambda: L.post_entry(db, user_id=UID, typ="bogus", betrag=10, jahr=2026, monat=5, tenancy_id=TID),
                 "unknown typ rejected")
    expect_error(lambda: L.post_entry(db, user_id=UID, typ=L.TYP_SOLLBUCHUNG, betrag=800, jahr=2026, tenancy_id=TID),
                 "sollbuchung without monat rejected")
    expect_error(lambda: L.post_entry(db, user_id=UID, typ=L.TYP_KORREKTUR, betrag=10, jahr=2026, monat=13, tenancy_id=TID),
                 "monat 13 rejected")
    expect_error(lambda: L.post_entry(db, user_id=UID, typ=L.TYP_ZAHLUNG, betrag=-10, jahr=2026, tenancy_id=TID, konto_art="bogus"),
                 "unknown konto_art rejected")

    print("\n[4] Saldo = SUM(betrag)  (user example: 850 -850 -400 +15 ... )")
    # accepted so far: +850 -850 -400 +15 -50 +50 = -385
    saldo = L.konto_saldo(db, UID, tenancy_id=TID, jahr=2026)
    ok(abs(saldo - (-385.0)) < 0.001, f"saldo == -385.00 (got {saldo})")
    # soft-delete must drop from saldo
    e6.is_deleted = True
    db.commit()
    saldo2 = L.konto_saldo(db, UID, tenancy_id=TID, jahr=2026)
    ok(abs(saldo2 - (-435.0)) < 0.001, f"soft-deleted korrektur excluded -> -435.00 (got {saldo2})")

    print("\n[5] Idempotency — partial-unique indexes")
    # one Sollbuchung per (user, tenancy, jahr, monat): jahr2026/monat1 already exists (e1)
    try:
        L.post_entry(db, user_id=UID, typ=L.TYP_SOLLBUCHUNG, betrag=850, jahr=2026, monat=1, tenancy_id=TID)
        ok(False, "duplicate Sollbuchung (same month) blocked")
    except IntegrityError:
        db.rollback()
        ok(True, "duplicate Sollbuchung (same month) blocked by uq_immo_ledger_soll")
    # one ledger row per source_rent_id
    L.post_entry(db, user_id=UID, typ=L.TYP_ZAHLUNG, betrag=-700, jahr=2026, monat=6, tenancy_id=TID,
                 source="import_rent", source_rent_id=5001)
    try:
        L.post_entry(db, user_id=UID, typ=L.TYP_ZAHLUNG, betrag=-700, jahr=2026, monat=6, tenancy_id=TID,
                     source="import_rent", source_rent_id=5001)
        ok(False, "duplicate import (same source_rent_id) blocked")
    except IntegrityError:
        db.rollback()
        ok(True, "duplicate import (same source_rent_id) blocked by uq_immo_ledger_rent")

    db.close()
    print(f"\n=== Faz 0 ledger: {PASS} passed, {FAIL} failed ===")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
