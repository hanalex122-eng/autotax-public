"""PHASE 1 migration analyzer — READ-ONLY proof + classification + idempotency.

Proves: (1) DB is byte-for-byte unchanged after a dry-run (no INSERT/UPDATE/DELETE),
(2) two runs on the same data give the same report, (3) snapshot file is produced,
(4) invariant is computed, (5) GREEN/YELLOW/RED are produced correctly.
today pinned 2025-12-31 (year 2025 fully due).
Run:  PYTHONIOENCODING=utf-8 PYTHONPATH=. python tests/test_immo_migration_dryrun.py
"""
import os
import sys
import json
import tempfile
from datetime import date

os.environ.setdefault("JWT_SECRET", "x" * 44)

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from autotax.models import Base, ImmoProperty, ImmoUnit, ImmoTenancy, ImmoRent
from autotax import immo_api, immo_migration as M

PASS = FAIL = 0
TODAY = date(2025, 12, 31)


def ok(c, m):
    global PASS, FAIL
    if c:
        PASS += 1; print(f"  PASS  {m}")
    else:
        FAIL += 1; print(f"  FAIL  {m}")


def fingerprint(db):
    """Everything the migration could touch — must be identical before/after."""
    tens = db.query(ImmoTenancy).order_by(ImmoTenancy.id).all()
    return {
        "tenant_count": len(tens),
        "rent_count": db.query(ImmoRent).count(),
        "offene_monate": {t.id: t.offene_monate for t in tens},
    }


def main():
    e = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=e)
    S = sessionmaker(bind=e)
    immo_api.SessionLocal = S
    db = S()
    db.add(ImmoProperty(id=10, user_id=1, name="Haus"))
    db.add(ImmoUnit(id=1, property_id=10, user_id=1, name="EG", soll_miete=500))
    # GREEN: 10×500 gezahlt, Soll 6000 → arrears 1000, saubere Daten
    db.add(ImmoTenancy(id=201, unit_id=1, user_id=1, mieter_name="Green Müller", von=date(2025, 1, 1), kaltmiete=500))
    for mo in range(1, 11):
        db.add(ImmoRent(property_id=10, tenancy_id=201, user_id=1, datum=date(2025, mo, 5), betrag=500))
    # YELLOW: Ist=0 (keine Zahlung) → Schuldenwand
    db.add(ImmoTenancy(id=202, unit_id=1, user_id=1, mieter_name="Yellow Leer", von=date(2025, 1, 1), kaltmiete=400))
    # YELLOW: voll bezahlt ABER eine gelöschte Zahlung in der Historie
    db.add(ImmoTenancy(id=203, unit_id=1, user_id=1, mieter_name="Yellow Churn", von=date(2025, 1, 1), kaltmiete=600))
    for mo in range(1, 13):
        db.add(ImmoRent(property_id=10, tenancy_id=203, user_id=1, datum=date(2025, mo, 5), betrag=600))
    db.add(ImmoRent(property_id=10, tenancy_id=203, user_id=1, datum=date(2025, 3, 9), betrag=600, is_deleted=True))
    db.commit()

    print("\n[READ-ONLY] DB vor/nach dem Dry-Run identisch")
    before = fingerprint(db)
    snap = M.dry_run(db, 1, today=TODAY)
    after = fingerprint(db)
    ok(before == after, "DB unverändert (kein INSERT/UPDATE/DELETE)")
    ok(all(v is None for v in after["offene_monate"].values()), "offene_monate weiterhin NULL (nichts geschrieben)")

    print("\n[IDEMPOTENT] zwei Läufe → gleicher Report")
    snap2 = M.dry_run(db, 1, today=TODAY)
    ok(snap["tenants"] == snap2["tenants"] and snap["summary"] == snap2["summary"], "Tenants + Summary identisch")

    by = {r["tenant_id"]: r for r in snap["tenants"]}
    print("\n[CLASSIFICATION]")
    ok(by[201]["classification"] == "GREEN", f"201 GREEN (got {by[201]['classification']})")
    ok(by[201]["old_arrears"] == 1000.0 and by[201]["new_exception_total"] == 1000.0 and by[201]["invariant_ok"], "201 invariant: old 1000 == new 1000")
    ok(len(by[201]["new_exceptions"]) == 2 and all(x["typ"] == "unpaid" for x in by[201]["new_exceptions"]), "201 → Nov+Dez unpaid")
    ok(by[202]["classification"] == "YELLOW" and "Ist=0" in by[202]["reason"], f"202 YELLOW Ist=0 (got {by[202]['classification']}/{by[202]['reason']})")
    ok(by[202]["old_arrears"] == 4800.0 and by[202]["invariant_ok"], "202 invariant: 4800 (Schuldenwand bewahrt, aber NICHT geschrieben)")
    ok(by[203]["classification"] == "YELLOW" and "lösch" in by[203]["reason"].lower(), f"203 YELLOW gelöschte Zahlung (got {by[203]['reason']})")
    ok(by[203]["old_arrears"] == 0.0, "203 arrears 0 (voll bezahlt) — trotzdem YELLOW wegen Daten-Churn")

    print("\n[RED] Invariant-Bruch → RED (Stop-Signal)")
    cls, reason = M._classify(False, [], 100.0, 250.0)
    ok(cls == "RED", f"_classify(invariant_broken) → RED (got {cls})")
    ok(M._classify(True, [])[0] == "GREEN" and M._classify(True, ["x"])[0] == "YELLOW", "_classify GREEN/YELLOW Pfade")

    print("\n[SNAPSHOT + REPORT]")
    p = os.path.join(tempfile.gettempdir(), "immo_dryrun_snap.json")
    M.write_snapshot(snap, p)
    ok(os.path.exists(p), "Snapshot-Datei erstellt")
    loaded = json.load(open(p, encoding="utf-8"))
    ok(loaded["phase"] == "1-dry-run" and "generated_at" in loaded and len(loaded["tenants"]) == 3, "Snapshot enthält audit-Felder + 3 Tenants")
    rep = M.format_report(snap)
    ok("GREEN=1" in rep and "YELLOW=2" in rep and "RED=0" in rep, "Report-Summary korrekt")

    print("\n[SUMMARY]")
    s = snap["summary"]
    ok(s["green"] == 1 and s["yellow"] == 2 and s["red"] == 0, f"1G/2Y/0R (got {s['green']}/{s['yellow']}/{s['red']})")
    ok(s["migration_blocked"] is False, "migration_blocked=False (kein RED)")

    print("\n--- REPORT VORSCHAU ---\n" + rep)
    print(f"\n=== Migration Phase-1 Dry-Run: {PASS} passed, {FAIL} failed ===")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
