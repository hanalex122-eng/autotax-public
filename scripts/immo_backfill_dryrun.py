"""IMMO PAYMENT BACKFILL — DRY-RUN REPORT (READ-ONLY. NO WRITES. NO MIGRATION.)

Sprint 0 added immo_rent.fuer_jahr / fuer_monat = WHICH RENT MONTH a payment settles.
Old rows have them empty, so today they are invisible to the debt calculation (exactly as
before the sprint — nothing regressed). This script asks ONE question, without changing
anything:

    IF we filled those columns from each payment's `datum`, what would happen?

Every candidate row gets a confidence class:

  🟢 HIGH    the month can be inferred safely
  🟡 MEDIUM  probably right, needs a human look
  🔴 LOW     cannot be inferred reliably — never migrate automatically

Only HIGH rows would ever be migrated automatically. MEDIUM/LOW stay untouched.

Run (read-only, against production):
    railway run python scripts/immo_backfill_dryrun.py
"""
from __future__ import annotations

import os
import sys
from collections import defaultdict
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("JWT_SECRET", "x" * 44)

from sqlalchemy import inspect, text                      # noqa: E402

from autotax.db import SessionLocal, engine               # noqa: E402
from autotax.models import (ImmoTenancy, ImmoUnit, ImmoProperty)   # noqa: E402
from autotax import immo_rules as R                        # noqa: E402
from autotax.immo_payments import PaymentService           # noqa: E402
from autotax.immo_payment_repository import (InMemoryPaymentRepository,      # noqa: E402
                                             InMemoryTenancyStore)
from autotax.immo_payment_models import PaymentRecord      # noqa: E402

TODAY = date.today()
HIGH, MED, LOW = "🟢 HIGH", "🟡 MEDIUM", "🔴 LOW"


def notdel(c):
    return (c.is_deleted == False) | (c.is_deleted == None)  # noqa: E712


class Row:
    """A payment row read with RAW SQL — production does not have fuer_jahr/fuer_monat yet
    (they are created on the next boot), so the ORM model must not be used here."""

    def __init__(self, id, tenancy_id, property_id, user_id, datum, betrag, fuer_jahr, fuer_monat):
        self.id = id
        self.tenancy_id = tenancy_id
        self.property_id = property_id
        self.user_id = user_id
        self.datum = datum
        self.betrag = betrag
        self.fuer_jahr = fuer_jahr
        self.fuer_monat = fuer_monat


def read_rents(db):
    cols = {c["name"] for c in inspect(engine).get_columns("immo_rent")}
    has_new = {"fuer_jahr", "fuer_monat"} <= cols
    sel = ("id, tenancy_id, property_id, user_id, datum, betrag, "
           + ("fuer_jahr, fuer_monat" if has_new else "NULL AS fuer_jahr, NULL AS fuer_monat"))
    sql = f"SELECT {sel} FROM immo_rent WHERE is_deleted IS NOT TRUE ORDER BY user_id, tenancy_id, datum"
    rows = [Row(*r) for r in db.execute(text(sql)).fetchall()]
    return rows, has_new


class Shadow:
    """A throw-away copy of a tenancy — so we can simulate the backfill in memory
    WITHOUT touching the database row."""

    def __init__(self, t):
        self.id = t.id
        self.user_id = t.user_id
        self.von = t.von
        self.bis = t.bis
        self.kaltmiete = t.kaltmiete
        self.nk_voraus = t.nk_voraus
        self.erstmonat_betrag = getattr(t, "erstmonat_betrag", None)
        self.miete_historie = getattr(t, "miete_historie", None)
        self.offene_monate = getattr(t, "offene_monate", None)     # copied, not shared


def classify(r, t, same_month_rows):
    """Confidence that `datum`'s month is the rent month this payment settles."""
    reasons = []
    if not r.tenancy_id or t is None:
        return LOW, ["no tenancy — the payment belongs to no rent account"]
    if r.datum is None:
        return LOW, ["no date — nothing to infer the month from"]
    if r.betrag is None or float(r.betrag or 0) <= 0:
        return LOW, ["amount missing or <= 0"]
    y, m = r.datum.year, r.datum.month
    if not R.tenancy_active_in_month(t, y, m):
        return LOW, [f"tenancy not active in {y}-{m:02d} (Einzug {t.von}, Auszug {t.bis or '—'})"]
    if r.datum > TODAY:
        return LOW, [f"payment date {r.datum} is in the FUTURE"]

    soll = R.monat_soll(t, y, m)
    amt = round(float(r.betrag), 2)

    # A payment booked in the first days of a month very often settles the PREVIOUS month
    # (rent paid late). We cannot know — that is exactly what MEDIUM is for.
    if r.datum.day <= 3:
        reasons.append(f"booked on day {r.datum.day} — may well be {y}-{m:02d} rent paid late for the previous month")
    if len(same_month_rows) > 1:
        reasons.append(f"{len(same_month_rows)} payments for the same tenant in {y}-{m:02d} (instalments? duplicate?)")
    if soll > 0 and abs(amt - soll) > 0.01:
        if amt > soll + 0.01:
            reasons.append(f"amount {amt:.2f} EXCEEDS the month's Soll {soll:.2f} — may cover several months")
        else:
            reasons.append(f"amount {amt:.2f} is below the month's Soll {soll:.2f} (partial?)")
    if soll <= 0:
        reasons.append("the month's Soll is 0 (no rent configured) — cannot cross-check the amount")

    if not reasons:
        return HIGH, [f"amount matches the month's Soll ({soll:.2f}) and the tenancy is active"]
    return MED, reasons


def main():
    db = SessionLocal()
    try:
        rents, has_new = read_rents(db)
        todo = [r for r in rents if r.fuer_jahr is None or r.fuer_monat is None]
        tens = {t.id: t for t in db.query(ImmoTenancy).filter(notdel(ImmoTenancy)).all()}
        units = {u.id: u for u in db.query(ImmoUnit).all()}
        props = {p.id: p for p in db.query(ImmoProperty).all()}

        print("=" * 78)
        print("IMMO PAYMENT BACKFILL — DRY-RUN  (READ-ONLY — nothing is written)")
        print(f"today: {TODAY}   database rows are NOT modified by this script")
        print(f"immo_rent.fuer_jahr/fuer_monat exist in this DB: {has_new}"
              + ("" if has_new else "   (they are added on the next deploy — that is fine, this is a simulation)"))
        print("=" * 78)

        # ── 1 / 2 — scope ────────────────────────────────────────────
        aff_ten = sorted({r.tenancy_id for r in todo if r.tenancy_id})
        print(f"\n1. Payment records in immo_rent (not deleted) : {len(rents)}")
        print(f"   …of them WITHOUT fuer_jahr/fuer_monat        : {len(todo)}   ← the backfill candidates")
        print(f"2. Tenancies affected                            : {len(aff_ten)}")
        print(f"   Payments with NO tenancy at all               : {sum(1 for r in todo if not r.tenancy_id)}")
        if not todo:
            print("\nNothing to backfill. Old payments are already attributed, or there are none.")
            return

        # group by tenancy, and by (tenancy, ym) to spot duplicates
        by_ten = defaultdict(list)
        for r in todo:
            by_ten[r.tenancy_id].append(r)
        by_ten_ym = defaultdict(list)
        for r in todo:
            if r.tenancy_id and r.datum:
                by_ten_ym[(r.tenancy_id, r.datum.year, r.datum.month)].append(r)

        # ── 3 — row by row ───────────────────────────────────────────
        print("\n3. ROW BY ROW")
        print("-" * 78)
        counts = defaultdict(int)
        rows_by_conf = defaultdict(list)
        for tid in sorted(by_ten, key=lambda x: (x is None, x)):
            t = tens.get(tid)
            if t:
                u = units.get(t.unit_id)
                p = props.get(u.property_id) if u else None
                where = " · ".join(x for x in [(p.adresse or p.name) if p else None, u.name if u else None] if x)
                print(f"\n  Mieter: {t.mieter_name}   (tenancy {tid})   {where}")
                print(f"    Einzug {t.von} · Auszug {t.bis or '—'} · Kalt {t.kaltmiete} + NK {t.nk_voraus} "
                      f"= Warm {round(float(t.kaltmiete or 0) + float(t.nk_voraus or 0), 2)}")
            else:
                print(f"\n  ⚠ payments WITHOUT a tenancy (tenancy_id={tid})")
            for r in by_ten[tid]:
                same = by_ten_ym.get((r.tenancy_id, r.datum.year, r.datum.month), []) if (r.tenancy_id and r.datum) else []
                conf, why = classify(r, t, same)
                counts[conf] += 1
                rows_by_conf[conf].append((r, t, why))
                fy = r.datum.year if r.datum else "—"
                fm = f"{r.datum.month:02d}" if r.datum else "—"
                amt = f"{float(r.betrag or 0):8.2f}" if r.betrag is not None else "    none"
                print(f"    id {r.id:<5} datum {str(r.datum or '—'):<10} betrag {amt}  "
                      f"→ fuer_jahr {fy} fuer_monat {fm}   {conf}")
                for w in why:
                    print(f"          · {w}")

        # ── 4 — ambiguity summary ────────────────────────────────────
        print("\n" + "-" * 78)
        print("4. AMBIGUOUS / PROBLEM ROWS")
        no_ten = [r for r in todo if not r.tenancy_id]
        no_date = [r for r in todo if r.datum is None]
        no_amt = [r for r in todo if r.betrag is None or float(r.betrag or 0) <= 0]
        future = [r for r in todo if r.datum and r.datum > TODAY]
        dups = {k: v for k, v in by_ten_ym.items() if len(v) > 1}
        print(f"   missing tenancy   : {len(no_ten)}   {[r.id for r in no_ten][:12]}")
        print(f"   missing date      : {len(no_date)}  {[r.id for r in no_date][:12]}")
        print(f"   missing/0 amount  : {len(no_amt)}   {[r.id for r in no_amt][:12]}")
        print(f"   impossible (future): {len(future)}  {[r.id for r in future][:12]}")
        print(f"   several payments in the same month (instalment or duplicate): {len(dups)} groups")
        for (tid, y, m), rs in list(dups.items())[:10]:
            nm = tens[tid].mieter_name if tid in tens else "?"
            print(f"      {nm}  {y}-{m:02d}: ids {[r.id for r in rs]} amounts {[float(r.betrag or 0) for r in rs]}")

        # ── 5 — BEFORE / AFTER, simulated in memory ──────────────────
        print("\n" + "-" * 78)
        print("5. BEFORE / AFTER — would any DEBT change?")
        print("   (simulated on shadow copies; the database is untouched)")
        print("   Rule applied: ONLY 🟢 HIGH rows are migrated. MEDIUM/LOW are left empty.")
        print()
        changed = []
        for tid, t in tens.items():
            if tid not in by_ten:
                continue
            shadow = Shadow(t)
            repo = InMemoryPaymentRepository()
            svc = PaymentService(repo, InMemoryTenancyStore({shadow.id: shadow}))
            before = svc.open_debt(t.user_id, shadow, TODAY).total     # exception state as it is today

            high_rows = [r for (r, tt, _w) in rows_by_conf[HIGH] if r.tenancy_id == tid]
            for r in high_rows:
                repo.add(PaymentRecord(tenancy_id=tid, user_id=t.user_id, betrag=float(r.betrag),
                                       fuer_jahr=r.datum.year, fuer_monat=r.datum.month,
                                       datum=r.datum, source="mieteingang"))
                svc.reconcile_month(t.user_id, shadow, r.datum.year, r.datum.month)
            after = svc.open_debt(t.user_id, shadow, TODAY).total
            if abs(after - before) > 0.005:
                changed.append((t, before, after, high_rows))
            print(f"   {t.mieter_name:<24} debt BEFORE {before:9.2f}  →  AFTER {after:9.2f}"
                  f"   {'CHANGED' if abs(after-before) > 0.005 else 'unchanged'}   "
                  f"({len(high_rows)} HIGH rows applied)")

        print("\n   WHY a debt would change:")
        if not changed:
            print("     — no tenant's debt would change. The HIGH rows all land on months that")
            print("       carry no reported problem (Dauerzahlung: already counted as paid), so")
            print("       reconciling them settles nothing that was not already settled.")
        for t, b, a, rows in changed:
            print(f"     {t.mieter_name}: {b:.2f} → {a:.2f}")
            for r in rows:
                soll = R.monat_soll(t, r.datum.year, r.datum.month)
                print(f"        payment id {r.id} ({float(r.betrag):.2f}) is attributed to "
                      f"{r.datum.year}-{r.datum.month:02d} (Soll {soll:.2f}) → that month's "
                      f"reported problem is settled by the money")

        # ── verdict ──────────────────────────────────────────────────
        print("\n" + "=" * 78)
        print("SUMMARY")
        print(f"   {HIGH}   : {counts[HIGH]:>3}  rows — safe to migrate automatically")
        print(f"   {MED} : {counts[MED]:>3}  rows — NOT migrated; need a human decision")
        print(f"   {LOW}    : {counts[LOW]:>3}  rows — NOT migrated; cannot be inferred")
        print(f"   tenants whose debt would change: {len(changed)}")
        print("\n   NOTHING WAS WRITTEN. No migration, no deployment.")
        print("=" * 78)
    finally:
        db.close()


if __name__ == "__main__":
    main()
