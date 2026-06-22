"""Faz 1 proof — backfill: ensure_sollbuchungen + import_rents_to_ledger.

Self-contained in-memory SQLite. Creates real ImmoUnit/ImmoTenancy/ImmoRent rows,
runs the backfill, and asserts: full-year quirk replication, partial-year span,
Kaltmiete=0 skip, multi-year, idempotency (2x = 0 new), rent import sign/edge
handling, and per-tenancy saldo. No prod DB / network.
Run:  PYTHONPATH=. python tests/test_immo_ledger_faz1.py
"""
import sys
from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from autotax.models import Base, ImmoUnit, ImmoTenancy, ImmoRent, ImmoLedgerEntry
from autotax import immo_ledger as L

PASS, FAIL = 0, 0


def ok(cond, msg):
    global PASS, FAIL
    if cond:
        PASS += 1; print(f"  PASS  {msg}")
    else:
        FAIL += 1; print(f"  FAIL  {msg}")


def soll_count(db, uid, tid, year):
    return db.query(ImmoLedgerEntry).filter(
        ImmoLedgerEntry.user_id == uid, ImmoLedgerEntry.tenancy_id == tid,
        ImmoLedgerEntry.jahr == year, ImmoLedgerEntry.typ == L.TYP_SOLLBUCHUNG).count()


def main():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    L.ensure_ledger_indexes(engine)
    db = sessionmaker(bind=engine)()
    UID, PID = 1, 10

    # units + tenancies
    u1 = ImmoUnit(id=1, property_id=PID, user_id=UID, name="WHG-01", soll_miete=850)
    u2 = ImmoUnit(id=2, property_id=PID, user_id=UID, name="WHG-02", soll_miete=800)
    u3 = ImmoUnit(id=3, property_id=PID, user_id=UID, name="WHG-03", soll_miete=900)
    db.add_all([u1, u2, u3]); db.commit()
    # T1: ongoing from 2026-01-01 (full-year quirk → 12 in 2026)
    t1 = ImmoTenancy(id=101, unit_id=1, user_id=UID, mieter_name="Müller", von=date(2026, 1, 1), bis=None, kaltmiete=850)
    # T2: partial 2026-04-01 .. 2026-09-30 (6 months)
    t2 = ImmoTenancy(id=102, unit_id=2, user_id=UID, mieter_name="Schmidt", von=date(2026, 4, 1), bis=date(2026, 9, 30), kaltmiete=800)
    # T3: kaltmiete 0 → skip
    t3 = ImmoTenancy(id=103, unit_id=3, user_id=UID, mieter_name="NullMiete", von=date(2026, 1, 1), bis=None, kaltmiete=0)
    # T4: spans 2025-2026 (ongoing) on unit 1 historically — test multi-year
    t4 = ImmoTenancy(id=104, unit_id=1, user_id=UID, mieter_name="AltMieter", von=date(2025, 6, 1), bis=date(2025, 12, 31), kaltmiete=700)
    db.add_all([t1, t2, t3, t4]); db.commit()

    print("\n[1] ensure_sollbuchungen — full-year quirk + partial + skip")
    n2026 = L.ensure_sollbuchungen(db, UID, 2026); db.commit()
    ok(soll_count(db, UID, 101, 2026) == 12, f"T1 ongoing → 12 Sollbuchungen 2026 (quirk) (got {soll_count(db, UID, 101, 2026)})")
    ok(soll_count(db, UID, 102, 2026) == 6, f"T2 partial Apr-Sep → 6 (got {soll_count(db, UID, 102, 2026)})")
    ok(soll_count(db, UID, 103, 2026) == 0, "T3 Kaltmiete=0 → 0 (skipped)")
    ok(soll_count(db, UID, 104, 2026) == 0, "T4 (2025-only) → 0 in 2026")
    ok(n2026 == 18, f"2026 inserted total == 18 (12+6) (got {n2026})")
    # amounts/konto_art correct
    e = db.query(ImmoLedgerEntry).filter(ImmoLedgerEntry.tenancy_id == 101, ImmoLedgerEntry.monat == 5).first()
    ok(e and e.betrag == 850.0 and e.konto_art == "miete" and e.faellig_am == date(2026, 5, 3),
       "Sollbuchung betrag=850, konto_art=miete, faellig=2026-05-03")

    print("\n[2] multi-year — call for 2025")
    n2025 = L.ensure_sollbuchungen(db, UID, 2025); db.commit()
    ok(soll_count(db, UID, 104, 2025) == 7, f"T4 Jun-Dec 2025 → 7 (got {soll_count(db, UID, 104, 2025)})")
    ok(soll_count(db, UID, 101, 2025) == 0, "T1 (von 2026) → 0 in 2025")

    print("\n[3] idempotency — re-run inserts nothing")
    again = L.ensure_sollbuchungen(db, UID, 2026); db.commit()
    ok(again == 0, f"2nd ensure(2026) == 0 new (got {again})")
    ok(soll_count(db, UID, 101, 2026) == 12, "T1 still 12 (no duplicates)")

    print("\n[4] import_rents_to_ledger — sign + edge handling")
    db.add_all([
        ImmoRent(id=5001, property_id=PID, tenancy_id=101, user_id=UID, datum=date(2026, 1, 15), betrag=850),   # zahlung -850
        ImmoRent(id=5002, property_id=PID, tenancy_id=101, user_id=UID, datum=date(2026, 2, 15), betrag=500),   # teil/zahlung -500
        ImmoRent(id=5003, property_id=PID, tenancy_id=101, user_id=UID, datum=date(2026, 3, 10), betrag=-100),  # refund → korrektur +100
        ImmoRent(id=5004, property_id=PID, tenancy_id=101, user_id=UID, datum=date(2026, 4, 1), betrag=0),      # zero → skip
        ImmoRent(id=5005, property_id=PID, tenancy_id=101, user_id=UID, datum=None, betrag=300),                # no date → skip
    ]); db.commit()
    res = L.import_rents_to_ledger(db, UID); db.commit()
    ok(res["imported"] == 3, f"imported == 3 (got {res['imported']})")
    ok(res["skipped_zero"] == 1, f"skipped_zero == 1 (got {res['skipped_zero']})")
    ok(res["skipped_nodate"] == 1, f"skipped_nodate == 1 (got {res['skipped_nodate']})")
    z = db.query(ImmoLedgerEntry).filter(ImmoLedgerEntry.source_rent_id == 5001).first()
    ok(z and z.typ == L.TYP_ZAHLUNG and z.betrag == -850.0, "rent 850 → zahlung -850")
    k = db.query(ImmoLedgerEntry).filter(ImmoLedgerEntry.source_rent_id == 5003).first()
    ok(k and k.typ == L.TYP_KORREKTUR and k.betrag == 100.0, "rent -100 (refund) → korrektur +100")

    print("\n[5] import idempotency — re-run imports nothing")
    res2 = L.import_rents_to_ledger(db, UID); db.commit()
    ok(res2["imported"] == 0 and res2["skipped_dup"] == 3, f"2nd import 0 new, 3 dup (got {res2})")

    print("\n[6] saldo sanity (T1, konto_art=miete)")
    # soll 12*850=10200 ; payments: -850 -500 +100(refund) = -1250 ; saldo = 8950
    s = L.konto_saldo(db, UID, tenancy_id=101, konto_art="miete")
    ok(abs(s - 8950.0) < 0.001, f"T1 saldo == 8950.00 (10200 soll -1250 zahlung+korrektur) (got {s})")

    db.close()
    print(f"\n=== Faz 1 backfill: {PASS} passed, {FAIL} failed ===")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
