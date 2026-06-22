"""Faz 2.2 proof — day-based aging: _pay_alloc / konto_state / aging_report.

Self-contained in-memory SQLite. Deterministic as_of=2026-06-15. Posts
Sollbuchungen with explicit faellig_am for exact bucket boundaries, plus a FIFO
partial-payment case. No prod DB / network.
Run:  PYTHONIOENCODING=utf-8 PYTHONPATH=. python tests/test_immo_ledger_aging.py
"""
import sys
from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from autotax.models import Base, ImmoUnit, ImmoTenancy
from autotax import immo_ledger as L
from autotax import immo_ledger_read as R

PASS, FAIL = 0, 0
ASOF = date(2026, 6, 15)


def ok(cond, msg):
    global PASS, FAIL
    if cond:
        PASS += 1; print(f"  PASS  {msg}")
    else:
        FAIL += 1; print(f"  FAIL  {msg}")


def soll(db, tid, monat, betrag, faellig, ka="miete"):
    L.post_entry(db, user_id=1, typ=L.TYP_SOLLBUCHUNG, betrag=betrag, jahr=2026, monat=monat,
                 tenancy_id=tid, faellig_am=faellig, konto_art=ka, commit=False)


def main():
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=eng)
    L.ensure_ledger_indexes(eng)
    db = sessionmaker(bind=eng)()

    print("\n[1] _pay_alloc — FIFO, partial")
    rows = [{"monat": 1, "betrag": 800}, {"monat": 2, "betrag": 800}, {"monat": 3, "betrag": 800}]
    al = R._pay_alloc(rows, 1000)
    ok(al[0]["status"] == "paid" and al[0]["offen"] == 0.0, "month1 fully covered (paid)")
    ok(al[1]["status"] == "partial" and al[1]["gedeckt"] == 200.0 and al[1]["offen"] == 600.0, "month2 partial 200/600")
    ok(al[2]["status"] == "open" and al[2]["offen"] == 800.0, "month3 open 800")

    # seed DB
    db.add(ImmoUnit(id=1, property_id=10, user_id=1, name="WHG-01"))
    db.add(ImmoUnit(id=2, property_id=10, user_id=1, name="WHG-02"))
    db.add(ImmoTenancy(id=201, unit_id=1, user_id=1, mieter_name="Lang", kaltmiete=500))
    db.add(ImmoTenancy(id=202, unit_id=2, user_id=1, mieter_name="Berg", kaltmiete=800))
    db.commit()

    # T202: Jan/Feb/Mar 800 each, pay 1000 (FIFO) — konto_state
    soll(db, 202, 1, 800, date(2026, 1, 3))
    soll(db, 202, 2, 800, date(2026, 2, 3))
    soll(db, 202, 3, 800, date(2026, 3, 3))
    L.post_entry(db, user_id=1, typ=L.TYP_ZAHLUNG, betrag=-1000, jahr=2026, monat=1, tenancy_id=202, commit=False)
    # T201: aging buckets — explicit faellig relative to as_of 2026-06-15, NO payment
    soll(db, 201, 4, 500, date(2026, 4, 1))   # 75 days → critical
    soll(db, 201, 5, 500, date(2026, 5, 20))  # 26 days → high
    soll(db, 201, 6, 500, date(2026, 6, 10))  # 5 days  → warning
    soll(db, 201, 7, 500, date(2026, 7, 1))   # future  → excluded
    db.commit()

    print("\n[2] konto_state — FIFO month detail (T202)")
    ks = R.konto_state(db, 1, 202, 2026, as_of=ASOF)
    st = {r["monat"]: r for r in ks["rows"]}
    ok(st[1]["status"] == "paid" and st[1]["tage_ueberfaellig"] == 0, "Jan paid, tage 0")
    ok(st[2]["status"] == "partial" and st[2]["offen"] == 600.0, "Feb partial offen 600")
    ok(st[3]["status"] == "open" and st[3]["offen"] == 800.0, "Mar open offen 800")
    ok(st[3]["tage_ueberfaellig"] == (ASOF - date(2026, 3, 3)).days, f"Mar tage = {(ASOF-date(2026,3,3)).days}")
    ok(ks["summe"] == {"soll": 2400.0, "ist": 1000.0, "saldo": 1400.0, "offen": 1400.0}, f"summe (got {ks['summe']})")

    print("\n[3] aging_report — portfolio-wide buckets (T201 + T202 open)")
    ag = R.aging_report(db, 1, as_of=ASOF)
    # critical: T201 Apr(75d) + T202 Feb(132d) + T202 Mar(104d) = 3
    ok(ag["summary"]["critical"] == 3, f"3 critical (T201 Apr + T202 Feb/Mar) (got {ag['summary']['critical']})")
    ok(ag["summary"]["high"] == 1, f"1 high (T201 May 26d) (got {ag['summary']['high']})")
    ok(ag["summary"]["warning"] == 1, f"1 warning (T201 Jun 5d) (got {ag['summary']['warning']})")
    # offen_total: T201 3×500=1500 + T202 (600+800)=1400 = 2900
    ok(ag["summary"]["offen_total"] == 2900.0, f"offen_total 2900 (1500+1400, future excl) (got {ag['summary']['offen_total']})")
    months = {it["monat"]: it["bucket"] for it in ag["items"] if it["tenancy_id"] == 201}
    ok(months == {4: "critical", 5: "high", 6: "warning"}, f"buckets per month (got {months})")
    ok(all(it["monat"] != 7 for it in ag["items"]), "July (future) excluded — not yet due")
    ok(ag["items"][0]["tage"] >= ag["items"][-1]["tage"], "items sorted by tage desc")

    print("\n[4] aging — fully paid tenancy excluded")
    # T202 paid 1000 of 2400 → Feb partial(600 open) + Mar(800 open) ARE overdue too;
    # but their faellig (02-03, 03-03) are >30 days → critical. Confirm they appear.
    t202 = [it for it in ag["items"] if it["tenancy_id"] == 202]
    ok(len(t202) == 2 and all(it["bucket"] == "critical" for it in t202),
       f"T202 open Feb+Mar both critical (got {[(i['monat'],i['bucket']) for i in t202]})")

    db.close()
    print(f"\n=== Faz 2.2 aging: {PASS} passed, {FAIL} failed ===")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
