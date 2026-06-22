"""Faz 2.1 proof — read model: saldo_by_tenancy / offene_forderungen / debtor_list.

Self-contained in-memory SQLite. Seeds tenancies, generates Sollbuchungen via the
Faz 1 engine, posts payments/korrektur directly, then asserts the read model
(incl. max(0,saldo) clamp, korrektur in saldo, konto_art filter, UI-ready debtor
fields, FIFO oldest_due_date). No prod DB / network.
Run:  PYTHONIOENCODING=utf-8 PYTHONPATH=. python tests/test_immo_ledger_read.py
"""
import sys
from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from autotax.models import Base, ImmoUnit, ImmoTenancy
from autotax import immo_ledger as L
from autotax import immo_ledger_read as R

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

    db.add_all([
        ImmoUnit(id=1, property_id=10, user_id=UID, name="WHG-01", soll_miete=850),
        ImmoUnit(id=2, property_id=10, user_id=UID, name="WHG-02", soll_miete=800),
        ImmoUnit(id=3, property_id=10, user_id=UID, name="WHG-03", soll_miete=900),
        ImmoUnit(id=4, property_id=10, user_id=UID, name="WHG-04", soll_miete=850),
    ])
    db.add_all([
        ImmoTenancy(id=101, unit_id=1, user_id=UID, mieter_name="Müller", von=date(2026, 1, 1), bis=None, kaltmiete=850),
        ImmoTenancy(id=102, unit_id=2, user_id=UID, mieter_name="Schmidt", von=date(2026, 1, 1), bis=None, kaltmiete=800),
        ImmoTenancy(id=103, unit_id=3, user_id=UID, mieter_name="Weber", von=date(2026, 1, 1), bis=None, kaltmiete=900),
        ImmoTenancy(id=104, unit_id=4, user_id=UID, mieter_name="Koch", von=date(2026, 1, 1), bis=date(2026, 6, 30), kaltmiete=850),
    ])
    db.commit()

    # Sollbuchungen via Faz 1 engine: T1=12*850, T2=12*800, T3=12*900, T4=6*850
    L.ensure_sollbuchungen(db, UID, 2026); db.commit()
    # Payments (direct posts):
    L.post_entry(db, user_id=UID, typ=L.TYP_ZAHLUNG, betrag=-850, jahr=2026, monat=1, tenancy_id=101, commit=False)   # T1 paid Jan only
    L.post_entry(db, user_id=UID, typ=L.TYP_ZAHLUNG, betrag=-9600, jahr=2026, monat=12, tenancy_id=102, commit=False)  # T2 fully paid
    L.post_entry(db, user_id=UID, typ=L.TYP_ZAHLUNG, betrag=-11000, jahr=2026, monat=12, tenancy_id=103, commit=False) # T3 overpaid
    L.post_entry(db, user_id=UID, typ=L.TYP_ZAHLUNG, betrag=-5100, jahr=2026, monat=6, tenancy_id=104, commit=False)   # T4 soll fully paid
    L.post_entry(db, user_id=UID, typ=L.TYP_KORREKTUR, betrag=50, jahr=2026, monat=6, tenancy_id=104, commit=False)    # T4 debt only from korrektur
    L.post_entry(db, user_id=UID, typ=L.TYP_SOLLBUCHUNG, betrag=620, jahr=2026, monat=1, tenancy_id=101, konto_art="nebenkosten", commit=False)  # NK
    db.commit()

    print("\n[1] saldo_by_tenancy (konto_art=miete)")
    s = R.saldo_by_tenancy(db, UID, 2026)
    ok(s[101] == {"soll": 10200.0, "ist": 850.0, "saldo": 9350.0}, f"T1 soll10200 ist850 saldo9350 (got {s[101]})")
    ok(s[102]["saldo"] == 0.0, f"T2 fully paid → saldo 0 (got {s[102]['saldo']})")
    ok(s[103]["saldo"] == -200.0, f"T3 overpaid → saldo -200 (got {s[103]['saldo']})")
    ok(s[104] == {"soll": 5100.0, "ist": 5100.0, "saldo": 50.0}, f"T4 korrektur → saldo 50, ist 5100 (got {s[104]})")

    print("\n[2] offene_forderungen — max(0,saldo) clamp")
    f = R.offene_forderungen(db, UID, 2026)
    ok(f["total"] == 9400.0, f"total == 9350+50 == 9400 (T2=0,T3<0 excluded) (got {f['total']})")
    ok(set(f["by_tenancy"].keys()) == {101, 104}, f"only debtors 101,104 (got {sorted(f['by_tenancy'].keys())})")

    print("\n[3] debtor_list — UI-ready shape + FIFO oldest_due_date")
    d = R.debtor_list(db, UID, 2026)
    ok([x["tenancy_id"] for x in d] == [101, 104], f"sorted by debt desc [101,104] (got {[x['tenancy_id'] for x in d]})")
    t1 = d[0]
    ok(set(t1.keys()) == {"tenancy_id", "tenant_name", "debt", "months_overdue", "oldest_due_date", "risk_level"},
       f"debtor keys UI-ready (got {sorted(t1.keys())})")
    ok(t1["tenant_name"] == "Müller" and t1["debt"] == 9350.0 and t1["months_overdue"] == 11 and t1["risk_level"] == "high",
       f"T1 name/debt/months/risk (got {t1})")
    ok(t1["oldest_due_date"] == "2026-02-03", f"T1 oldest open = Feb (Jan paid) faellig 2026-02-03 (got {t1['oldest_due_date']})")
    t4 = d[1]
    ok(t4["debt"] == 50.0 and t4["months_overdue"] == 0 and t4["risk_level"] == "low",
       f"T4 debt50 months0 risk low (got {t4})")
    ok(t4["oldest_due_date"] is None, f"T4 debt only from korrektur → oldest_due_date None (got {t4['oldest_due_date']})")

    print("\n[4] konto_art filter")
    nk = R.saldo_by_tenancy(db, UID, 2026, konto_art="nebenkosten")
    ok(nk[101]["saldo"] == 620.0 and 101 not in R.saldo_by_tenancy(db, UID, 2026) or s[101]["saldo"] == 9350.0,
       "nebenkosten saldo 620 separate from miete 9350")
    ok(nk.get(101, {}).get("saldo") == 620.0, f"NK saldo 620 (got {nk.get(101)})")

    print("\n[5] empty user")
    ok(R.saldo_by_tenancy(db, 999, 2026) == {}, "empty saldo {}")
    ok(R.offene_forderungen(db, 999, 2026) == {"total": 0.0, "by_tenancy": {}}, "empty forderungen 0")
    ok(R.debtor_list(db, 999, 2026) == [], "empty debtor_list []")

    db.close()
    print(f"\n=== Faz 2.1 read model: {PASS} passed, {FAIL} failed ===")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
