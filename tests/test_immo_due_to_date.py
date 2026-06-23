"""Due-to-date arrears fix — FUTURE months must NOT count as debt.

Live case: tenancy von=15.06.2026, Kaltmiete 500 €, one payment 500 €, today pinned
to 23.06.2026.
  OLD bug:  Soll 3500 € (Jun–Dec = 7 mo), Rückstand 3000 €
  FIXED:    Soll-bis-heute 500 € (only June due), Rückstand 0 €

Verifies OLD engine (_accounting / _tenancy_arrears / _old_debtors / _portfolio)
AND ledger read (saldo_by_tenancy / offene_forderungen / debtor_list) AND parity
(OLD == ledger). The ledger still STORES all 7 Sollbuchungen (forecast intact);
only the READ is capped to due months.

Run:  PYTHONIOENCODING=utf-8 PYTHONPATH=. python tests/test_immo_due_to_date.py
"""
import os
import sys
from datetime import date

os.environ.setdefault("JWT_SECRET", "x" * 44)

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from autotax.models import Base, ImmoProperty, ImmoUnit, ImmoTenancy, ImmoRent, ImmoLedgerEntry
from autotax import immo_api, immo_ledger, immo_ledger_read

TODAY = date(2026, 6, 23)


class FakeDate(date):
    @classmethod
    def today(cls):
        return TODAY


# pin date.today() in both engines so the test is deterministic
immo_api.date = FakeDate
immo_ledger_read.date = FakeDate

PASS = FAIL = 0


def ok(c, m):
    global PASS, FAIL
    if c:
        PASS += 1; print(f"  PASS  {m}")
    else:
        FAIL += 1; print(f"  FAIL  {m}")


def main():
    e = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=e)
    S = sessionmaker(bind=e)
    db = S()
    db.add(ImmoProperty(id=10, user_id=1, name="Haus", adresse="Str 1, 10115 Berlin"))
    db.add(ImmoUnit(id=1, property_id=10, user_id=1, name="WHG-01", soll_miete=500))
    db.add(ImmoTenancy(id=101, unit_id=1, user_id=1, mieter_name="Neuer Mieter",
                       von=date(2026, 6, 15), bis=None, kaltmiete=500))
    db.add(ImmoRent(id=1, property_id=10, tenancy_id=101, user_id=1, betrag=500, datum=date(2026, 6, 5)))
    db.commit()
    t = db.query(ImmoTenancy).get(101)

    print("\n[0] Quirk magnitude")
    ok(immo_api._months_active_in_year(t, 2026) == 7, "full-year active months = 7 (Jun–Dec) → would be Soll 3500")
    ok(immo_api._months_due_to_date(t, 2026) == 1, "due-to-date months = 1 (only June)")

    print("\n[OLD] _accounting (Mietkonto row)")
    acc = immo_api._accounting(db, 1, 10, 2026)
    tr = acc["tenancies"][0]
    print(f"       soll={tr['soll']} ist={tr['ist']} rueckstand={tr['rueckstand']}")
    ok(tr["soll"] == 500, "OLD Soll-bis-heute = 500 (was 3500)")
    ok(tr["ist"] == 500, "OLD Ist = 500")
    ok(tr["rueckstand"] == 0, "OLD Rueckstand = 0 (was 3000)")
    ok(acc["summe"]["zahlungsausfall"] == 0, "OLD summe.zahlungsausfall = 0")

    print("\n[OLD] arrears / debtors / Mahnung")
    ok(immo_api._tenancy_arrears(db, 1, t, 2026) == 0, "OLD _tenancy_arrears (Mahnung amount) = 0")
    ok(len(immo_api._old_debtors(db, 1, 2026)) == 0, "OLD _old_debtors empty (no false debtor)")
    port = immo_api._portfolio(db, 1, 2026)
    ok(port["financial"]["rueckstand"] == 0, "OLD _portfolio.financial.rueckstand = 0")

    print("\n[LEDGER] backfill then read")
    immo_ledger.run_backfill(db, 1, dry_run=False); db.commit()
    nsoll = db.query(ImmoLedgerEntry).filter(ImmoLedgerEntry.tenancy_id == 101,
                                             ImmoLedgerEntry.typ == "sollbuchung").count()
    ok(nsoll == 7, "ledger STORES 7 Sollbuchungen (forecast intact)")
    d = immo_ledger_read.saldo_by_tenancy(db, 1, 2026).get(101, {})
    print(f"       saldo_by_tenancy={d}")
    ok(d.get("soll") == 500, "LEDGER soll due-to-date = 500 (Jul–Dec excluded from read)")
    ok(d.get("ist") == 500, "LEDGER ist = 500")
    ok(d.get("saldo") == 0, "LEDGER saldo = 0")
    of = immo_ledger_read.offene_forderungen(db, 1, 2026)
    ok(of["total"] == 0, "LEDGER offene_forderungen total = 0")
    ok(len(immo_ledger_read.debtor_list(db, 1, 2026)) == 0, "LEDGER debtor_list empty")

    print("\n[PARITY] OLD == Ledger (current year)")
    ok(port["financial"]["rueckstand"] == of["total"], "rueckstand: OLD == ledger (0 == 0)")
    ok(len(immo_api._old_debtors(db, 1, 2026)) == len(immo_ledger_read.debtor_list(db, 1, 2026)),
       "debtor_count: OLD == ledger (0 == 0)")

    print(f"\n=== Due-to-date: {PASS} passed, {FAIL} failed ===")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
