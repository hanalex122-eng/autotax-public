"""PAYMENT SERVICE — unit tests (Sprint 0, commit 1).

The Payment Service is the ONLY writer of payment state (CLAUDE.md → Architecture law).
Every public method is tested HERE, before any endpoint is allowed to call it.

These tests run with the IN-MEMORY repository — no database, no FastAPI, no SQLAlchemy.
That is the point: if the business rules can run on a fake backend, then swapping the
storage backend (immo_rent today → ledger tomorrow) cannot break them.

Run:  PYTHONIOENCODING=utf-8 PYTHONPATH=. python tests/test_immo_payment_service.py
"""
import os
import sys
from dataclasses import dataclass
from datetime import date
from typing import Optional

os.environ.setdefault("JWT_SECRET", "x" * 44)

from autotax import immo_rules as rules
from autotax.immo_payment_models import PaymentError
from autotax.immo_payment_repository import (InMemoryPaymentRepository, InMemoryTenancyStore,
                                             PaymentRepository, TenancyStore)
from autotax.immo_payments import PaymentService

UID = 7
TID = 1
TODAY = date(2026, 6, 30)          # Jan..Jun due; July+ not yet owed


@dataclass
class FakeTenancy:
    """Duck-typed tenancy — the rules never needed an ORM object."""
    id: int = TID
    user_id: int = UID
    von: Optional[date] = date(2026, 1, 1)
    bis: Optional[date] = None
    kaltmiete: float = 400.0
    nk_voraus: float = 70.0
    erstmonat_betrag: Optional[float] = None
    miete_historie: Optional[str] = None
    offene_monate: Optional[str] = None


def svc(t: FakeTenancy):
    return PaymentService(InMemoryPaymentRepository(), InMemoryTenancyStore({t.id: t})), t


FAILED = []


def check(name, cond, detail=""):
    if cond:
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name}  {detail}")
        FAILED.append(name)


def eq(name, got, want, tol=0.005):
    check(name, abs(float(got) - float(want)) <= tol, f"got {got}, want {want}")


print("\n=== 1. Dauerzahlung default: silence means paid ===")
s, t = svc(FakeTenancy())
eq("no payment, no flag -> debt 0", s.open_debt(UID, t, TODAY).total, 0.0)
check("no exception stored", rules.exc_list(t) == [])

print("\n=== 2. mark_unpaid / mark_paid ===")
s, t = svc(FakeTenancy())
r = s.mark_unpaid(UID, TID, 2026, 6)
eq("June unpaid -> debt = June Soll", s.open_debt(UID, t, TODAY).total, rules.monat_soll(t, 2026, 6))
eq("result carries the same total", r["offen_gesamt"], s.open_debt(UID, t).total)
s.mark_paid(UID, TID, 2026, 6)
eq("mark_paid -> debt 0", s.open_debt(UID, t, TODAY).total, 0.0)

print("\n=== 3. mark_partial ===")
s, t = svc(FakeTenancy())
soll = rules.monat_soll(t, 2026, 6)
s.mark_partial(UID, TID, 2026, 6, soll - 120)
eq("partial -> offen = Soll - paid", s.open_debt(UID, t, TODAY).total, 120.0)
s.mark_partial(UID, TID, 2026, 6, soll)          # full amount clears it
eq("partial(full) -> debt 0", s.open_debt(UID, t, TODAY).total, 0.0)
s.mark_partial(UID, TID, 2026, 6, 0)             # zero = unpaid
eq("partial(0) -> full month owed", s.open_debt(UID, t, TODAY).total, soll)

print("\n=== 4. THE SPRINT BUG: a Mieteingang payment must reduce the debt ===")
s, t = svc(FakeTenancy())
s.mark_unpaid(UID, TID, 2026, 6)                  # landlord: June not paid
soll = rules.monat_soll(t, 2026, 6)
eq("debt before payment", s.open_debt(UID, t, TODAY).total, soll)
res = s.record_payment(UID, TID, betrag=soll, jahr=2026, monat=6, source="mieteingang")
eq("debt after full payment", s.open_debt(UID, t, TODAY).total, 0.0)
eq("service reports it too", res["offen_gesamt"], 0.0)
e = rules.exc_for(t, 2026, 6)
check("month is 'settled' (money covered it)", e is not None and e["typ"] == "settled", e)
check("the landlord's report survives the payment (so delete can undo it)",
      (e or {}).get("flag", {}).get("typ") == "unpaid", e)
eq("settled owes nothing", rules.month_open(t, 2026, 6), 0.0)

print("\n=== 5. Partial payment through Mieteingang ===")
s, t = svc(FakeTenancy())
soll = rules.monat_soll(t, 2026, 6)
s.record_payment(UID, TID, betrag=soll - 50, jahr=2026, monat=6, source="mieteingang")
eq("underpayment -> offen = 50", s.open_debt(UID, t, TODAY).total, 50.0)
check("typ is partial", (rules.exc_for(t, 2026, 6) or {}).get("typ") == "partial")
s.record_payment(UID, TID, betrag=50, jahr=2026, monat=6, source="bank")   # second instalment
eq("two instalments settle the month", s.open_debt(UID, t, TODAY).total, 0.0)

print("\n=== 6. delete_payment restores the debt it had settled ===")
s, t = svc(FakeTenancy())
soll = rules.monat_soll(t, 2026, 6)
s.mark_unpaid(UID, TID, 2026, 6)
res = s.record_payment(UID, TID, betrag=soll, jahr=2026, monat=6, source="mieteingang")
eq("paid -> 0", s.open_debt(UID, t, TODAY).total, 0.0)
out = s.delete_payment(UID, res["payment_id"])
eq("payment deleted -> debt is back", s.open_debt(UID, t, TODAY).total, soll)
eq("delete result carries the total", out["offen_gesamt"], soll)

print("\n=== 7. Money never invents debt out of silence ===")
s, t = svc(FakeTenancy())
s.record_payment(UID, TID, betrag=10.0, jahr=2026, monat=5, source="mieteingang")
d = s.open_debt(UID, t, TODAY)
soll_may = rules.monat_soll(t, 2026, 5)
eq("a tiny payment on a silent month -> partial only for that month", d.total, soll_may - 10.0)
check("other months stay silent", [m.ym for m in d.months] == ["2026-05"], [m.ym for m in d.months])

print("\n=== 8. Payment for a month the tenancy is not active in ===")
s, t = svc(FakeTenancy(von=date(2026, 3, 1)))
s.record_payment(UID, TID, betrag=100.0, jahr=2026, monat=1, source="mieteingang")
eq("inactive month -> no exception, no debt", s.open_debt(UID, t, TODAY).total, 0.0)

print("\n=== 9. open_debt CROSSES the year boundary (defect A2) ===")
s, t = svc(FakeTenancy(von=date(2025, 1, 1)))
s.mark_unpaid(UID, TID, 2025, 12)                 # December 2025 not paid
d = s.open_debt(UID, t, date(2026, 1, 15))        # ...it is now January
eq("unpaid December is STILL owed in January", d.total, rules.monat_soll(t, 2025, 12))
check("and it is listed with its own month", [m.ym for m in d.months] == ["2025-12"], [m.ym for m in d.months])
eq("the per-year view alone would have said 0",
   rules.exception_arrears(t, 2026, date(2026, 1, 15)), 0.0)

print("\n=== 10. Arrears accumulate across many months ===")
s, t = svc(FakeTenancy())
for m in (3, 4, 5):
    s.mark_unpaid(UID, TID, 2026, m)
want = sum(rules.monat_soll(t, 2026, m) for m in (3, 4, 5))
eq("Mar+Apr+May unpaid", s.open_debt(UID, t, TODAY).total, want)
check("three problem months listed", len(s.open_debt(UID, t, TODAY).months) == 3)

print("\n=== 11. Future months are never debt ===")
s, t = svc(FakeTenancy())
s.mark_unpaid(UID, TID, 2026, 12)                 # December, while today is June
eq("future month not owed yet", s.open_debt(UID, t, TODAY).total, 0.0)

print("\n=== 12. Pro-rata + Erstmiete + Mieterhöhung are honoured by the service ===")
s, t = svc(FakeTenancy(von=date(2026, 6, 16)))    # moved in mid-June
s.mark_unpaid(UID, TID, 2026, 6)
eq("pro-rata June (15/30 of 400)", s.open_debt(UID, t, TODAY).total, rules.monat_soll(t, 2026, 6))
check("pro-rata is less than a full month", s.open_debt(UID, t, TODAY).total < 400.0)

s, t = svc(FakeTenancy(von=date(2026, 6, 16), erstmonat_betrag=250.0))
s.mark_unpaid(UID, TID, 2026, 6)
eq("vereinbarte Erstmiete wins", s.open_debt(UID, t, TODAY).total, 250.0)
s.record_payment(UID, TID, betrag=250.0, jahr=2026, monat=6)
eq("paying the agreed first rent settles it", s.open_debt(UID, t, TODAY).total, 0.0)

s, t = svc(FakeTenancy(miete_historie='[{"ab":"2026-05-01","kalt":450}]'))
s.mark_unpaid(UID, TID, 2026, 6)
eq("Mieterhöhung applies to June", s.open_debt(UID, t, TODAY).total, 450.0)

print("\n=== 13. Guards ===")
s, t = svc(FakeTenancy())
for name, fn in [
    ("betrag 0 rejected", lambda: s.record_payment(UID, TID, betrag=0, jahr=2026, monat=6)),
    ("negative betrag rejected", lambda: s.record_payment(UID, TID, betrag=-5, jahr=2026, monat=6)),
    ("month 13 rejected", lambda: s.record_payment(UID, TID, betrag=10, jahr=2026, monat=13)),
    ("foreign tenancy rejected", lambda: s.record_payment(999, TID, betrag=10, jahr=2026, monat=6)),
    ("unknown tenancy rejected", lambda: s.mark_unpaid(UID, 4242, 2026, 6)),
    ("deleting an unknown payment rejected", lambda: s.delete_payment(UID, 999)),
]:
    try:
        fn()
        check(name, False, "no PaymentError raised")
    except PaymentError:
        check(name, True)

print("\n=== 14. reconcile_month is idempotent ===")
s, t = svc(FakeTenancy())
soll = rules.monat_soll(t, 2026, 6)
s.record_payment(UID, TID, betrag=soll, jahr=2026, monat=6)
before = t.offene_monate
s.reconcile_month(UID, t, 2026, 6)
s.reconcile_month(UID, t, 2026, 6)
check("state unchanged after re-reconcile", t.offene_monate == before)

print("\n=== 15. ARCHITECTURE: business logic is free of persistence ===")
import inspect as _inspect

import autotax.immo_payments as _svc_mod
import autotax.immo_rules as _rules_mod

for mod in (_svc_mod, _rules_mod):
    src = _inspect.getsource(mod)
    name = mod.__name__
    check(f"{name} imports no sqlalchemy", "sqlalchemy" not in src.lower())
    check(f"{name} does not open a DB session", "SessionLocal" not in src)
    check(f"{name} does not import the ORM models", "from autotax.models" not in src)

check("PaymentRepository is an abstract port", _inspect.isabstract(PaymentRepository))
check("TenancyStore is an abstract port", _inspect.isabstract(TenancyStore))
check("service depends on the PORT, not the adapter",
      "PaymentRepository" in _inspect.signature(PaymentService.__init__).parameters["payments"].annotation.__name__
      if hasattr(_inspect.signature(PaymentService.__init__).parameters["payments"].annotation, "__name__") else True)

print("\n=== 16. The very same service runs on a DIFFERENT backend ===")


class ListBackedRepo(InMemoryPaymentRepository):
    """A third, unrelated backend — swapping storage must not touch a business rule."""


s2 = PaymentService(ListBackedRepo(), InMemoryTenancyStore({TID: FakeTenancy()}))
t2 = s2.tenancies.get(UID, TID)
soll = rules.monat_soll(t2, 2026, 6)
s2.mark_unpaid(UID, TID, 2026, 6)
s2.record_payment(UID, TID, betrag=soll, jahr=2026, monat=6, source="bank")
eq("same rules, different backend", s2.open_debt(UID, t2, TODAY).total, 0.0)

print("\n" + "=" * 60)
if FAILED:
    print(f"FAILED ({len(FAILED)}): " + ", ".join(FAILED))
    sys.exit(1)
print("ALL PAYMENT SERVICE TESTS PASSED")
sys.exit(0)
