"""Immobilien — PAYMENT SERVICE (the only writer of payment state).

Architecture law (CLAUDE.md — binding):
  1. Every payment enters the system exactly once.
  2. No UI is allowed to calculate debt independently.
  3. Debt is derived only from the Exception Engine.
  4. Every screen is read-only with respect to debt calculation.
  5. Only the Payment Service may modify payment state.

    "Bezahlt" button · partial · Mieteingang · (future) bank import
                              │
                              ▼
                      PAYMENT SERVICE          ← this module (orchestration only)
                              │
                      EXCEPTION ENGINE         ← the single debt truth
                              │
        Bu Ay · Mietkonto · Mahnung · Berichte · Nebenkosten (all read-only)

Layering — this file stays small on purpose (no God Object):
    immo_payment_models.py      domain vocabulary (PaymentRecord, Debt, …)
    immo_payment_repository.py  persistence ports + adapters (immo_rent | in-memory | later: ledger)
    immo_rules.py               pure derivation (Soll, proration, exception READ)
    immo_payments.py            ← workflow orchestration + exception WRITE (this file)

STATUS (Sprint 0, commit 1): infrastructure only. NOTHING calls this module yet —
no endpoint, no UI, no behaviour change. Endpoints are rewired in commit 2, and no
public method is used by an endpoint before it has unit tests.
"""
from __future__ import annotations

import json
from datetime import date
from typing import Optional

from autotax import immo_rules as rules
from autotax.immo_payment_models import (EPS, SOURCES, Debt, MonthDebt, PaymentError,
                                         PaymentRecord)
from autotax.immo_payment_repository import (ImmoRentRepository, PaymentRepository,
                                             SqlTenancyStore, TenancyStore)


class PaymentService:
    """The ONLY component allowed to modify payment state.

    Every payment UI is a door into this one room:
        mark_paid / mark_unpaid / mark_partial → "Bezahlt" button, Mietkonto row
        record_payment                         → Mieteingang, bank import (future)
        delete_payment                         → payment correction

    All of them end in `reconcile_month`, which derives the month's exception from
    (Soll ↔ money actually recorded). Debt is then read — by everyone — via
    `open_debt`. No caller may compute a debt figure of its own.
    """

    def __init__(self, payments: PaymentRepository, tenancies: TenancyStore):
        self.payments = payments
        self.tenancies = tenancies

    # ── exception engine — WRITE side (private; the read side is immo_rules) ──

    @staticmethod
    def _save_exc(t, lst) -> None:
        t.offene_monate = json.dumps([{k: v for k, v in e.items() if v is not None} for e in lst]) if lst else None

    KEEP = "__keep__"

    def _write_exception(self, t, y: int, m: int, typ: str, offen: Optional[float] = None,
                         flag=KEEP) -> None:
        """Write the month's entry.

        `typ`  = derived state ('unpaid' | 'partial' | 'settled').
        `flag` = the landlord's own report ({"typ":"unpaid"} | {"typ":"partial","offen":x}
                 | None); KEEP preserves whatever is stored. The flag is why deleting a
                 payment can restore the debt it settled — the report outlives the money.
        """
        ym = "%04d-%02d" % (y, m)
        old = rules.exc_for(t, y, m) or {}
        lst = [e for e in rules.exc_list(t) if e["ym"] != ym]
        e = {"ym": ym, "typ": typ}
        if typ == "partial":
            e["offen"] = round(float(offen or 0), 2)
        e["flag"] = old.get("flag") if flag == self.KEEP else flag
        if typ == "settled" and not e["flag"]:
            self._save_exc(t, lst)                      # settled and nothing to remember
            return
        lst.append(e)
        self._save_exc(t, lst)

    def _clear_exception(self, t, y: int, m: int) -> None:
        """Remove the month entirely — the landlord says there is no problem at all."""
        ym = "%04d-%02d" % (y, m)
        self._save_exc(t, [e for e in rules.exc_list(t) if e["ym"] != ym])

    # ── THE single rule ──────────────────────────────────────────────

    def reconcile_month(self, user_id: int, t, jahr: int, monat: int) -> Optional[dict]:
        """Derive the month's exception from Soll ↔ recorded payments.

            paid >= soll     → no exception              (settled)
            0 < paid < soll  → partial(offen = soll − paid)
            paid == 0        → the landlord's explicit flag stands; if there is none,
                               no exception (Dauerzahlung default: silence = paid)

        A recorded payment can only ever move a month TOWARD settled — money never
        invents debt out of silence.
        """
        if not rules.tenancy_active_in_month(t, jahr, monat):
            return rules.exc_for(t, jahr, monat)
        soll = rules.monat_soll(t, jahr, monat)
        paid = round(sum(p.betrag for p in self.payments.list_for_month(user_id, t.id, jahr, monat)), 2)
        flag = (rules.exc_for(t, jahr, monat) or {}).get("flag")
        if paid <= 0:
            # No money on record → the landlord's report decides, and silence means paid.
            if not flag:
                self._clear_exception(t, jahr, monat)
            elif flag.get("typ") == "partial":
                self._write_exception(t, jahr, monat, "partial", offen=flag.get("offen") or soll)
            else:
                self._write_exception(t, jahr, monat, "unpaid")
        elif paid >= soll - EPS:
            self._write_exception(t, jahr, monat, "settled")     # keeps the flag, owes nothing
        else:
            self._write_exception(t, jahr, monat, "partial", offen=round(soll - paid, 2))
        self.tenancies.save(t)
        return rules.exc_for(t, jahr, monat)

    # ── write paths (the only ones in the system) ────────────────────

    def record_payment(self, user_id: int, tenancy_id: int, *, betrag: float, jahr: int, monat: int,
                       datum: Optional[date] = None, source: str = "manual",
                       notiz: Optional[str] = None, property_id: Optional[int] = None) -> dict:
        """Mieteingang / bank import / any "money arrived" UI. Enters the system ONCE."""
        t = self._require_tenancy(user_id, tenancy_id)
        self._require_month(jahr, monat)
        betrag = self._money(betrag)
        if betrag <= 0:
            raise PaymentError("Betrag muss größer als 0 sein")
        rec = self.payments.add(PaymentRecord(
            tenancy_id=tenancy_id, user_id=user_id, betrag=betrag, fuer_jahr=jahr, fuer_monat=monat,
            datum=datum or date(jahr, monat, 1), property_id=property_id,
            source=(source if source in SOURCES else "manual"), notiz=notiz,
        ))
        exc = self.reconcile_month(user_id, t, jahr, monat)
        return self._result(user_id, t, jahr, monat, exc, payment_id=rec.id, betrag=betrag)

    def delete_payment(self, user_id: int, payment_id: int) -> dict:
        """Payment correction — removing money must restore the debt it had settled."""
        rec = self.payments.soft_delete(user_id, payment_id)
        if not rec:
            raise PaymentError("Zahlung nicht gefunden")
        t = self.tenancies.get(user_id, rec.tenancy_id) if rec.tenancy_id else None
        if t is None or not rec.fuer_jahr or not rec.fuer_monat:
            return {"deleted": payment_id, "exception": None, "offen_gesamt": 0.0}
        exc = self.reconcile_month(user_id, t, rec.fuer_jahr, rec.fuer_monat)
        out = self._result(user_id, t, rec.fuer_jahr, rec.fuer_monat, exc)
        out["deleted"] = payment_id
        return out

    def update_payment(self, user_id: int, payment_id: int, *, betrag: Optional[float] = None,
                       datum: Optional[date] = None, jahr: Optional[int] = None,
                       monat: Optional[int] = None, notiz: Optional[str] = None) -> dict:
        """Correct a payment = replace it (remove + re-enter), then reconcile BOTH the
        old and the new rent month. A correction must never leave the old month settled
        by money that no longer exists."""
        old = self.payments.get(user_id, payment_id)
        if not old:
            raise PaymentError("Zahlung nicht gefunden")
        new_jahr = int(jahr) if jahr else old.fuer_jahr
        new_monat = int(monat) if monat else old.fuer_monat
        self._require_month(new_jahr, new_monat)
        new_betrag = self._money(betrag) if betrag is not None else old.betrag
        if new_betrag <= 0:
            raise PaymentError("Betrag muss größer als 0 sein")
        self.payments.soft_delete(user_id, payment_id)
        rec = self.payments.add(PaymentRecord(
            tenancy_id=old.tenancy_id, user_id=user_id, betrag=new_betrag,
            fuer_jahr=new_jahr, fuer_monat=new_monat,
            datum=datum or old.datum, property_id=old.property_id, source=old.source,
            notiz=notiz if notiz is not None else old.notiz,
        ))
        t = self.tenancies.get(user_id, old.tenancy_id) if old.tenancy_id else None
        if t is None:
            return {"success": True, "payment_id": rec.id}
        if old.fuer_jahr and old.fuer_monat and (old.fuer_jahr, old.fuer_monat) != (new_jahr, new_monat):
            self.reconcile_month(user_id, t, old.fuer_jahr, old.fuer_monat)   # the month it left
        exc = self.reconcile_month(user_id, t, new_jahr, new_monat)           # the month it landed in
        return self._result(user_id, t, new_jahr, new_monat, exc, payment_id=rec.id, betrag=new_betrag)

    def mark_paid(self, user_id: int, tenancy_id: int, jahr: int, monat: int) -> dict:
        """"Bezahlt" button — the landlord reports: no problem in this month."""
        t = self._require_tenancy(user_id, tenancy_id)
        self._require_month(jahr, monat)
        self._clear_exception(t, jahr, monat)
        self.tenancies.save(t)
        return self._result(user_id, t, jahr, monat, None)

    def mark_unpaid(self, user_id: int, tenancy_id: int, jahr: int, monat: int) -> dict:
        """"Nicht bezahlt" button — the landlord reports a problem: the full month is owed."""
        t = self._require_tenancy(user_id, tenancy_id)
        self._require_month(jahr, monat)
        self._write_exception(t, jahr, monat, "unpaid", flag={"typ": "unpaid"})
        self.tenancies.save(t)
        return self._result(user_id, t, jahr, monat, rules.exc_for(t, jahr, monat))

    def report_problem(self, user_id: int, tenancy_id: int, jahr: int, monat: int,
                       typ: str, offen: Optional[float] = None) -> dict:
        """The landlord reports a problem directly: 'unpaid', or 'partial' with a known
        open amount (e.g. imported from an old system). Same law — the service writes,
        nobody else. mark_unpaid/mark_partial are the friendly UI wrappers around it."""
        t = self._require_tenancy(user_id, tenancy_id)
        self._require_month(jahr, monat)
        if typ == "partial":
            # NOT clamped to the month's Soll on purpose: an imported/carried-over open
            # amount may legitimately exceed one month's rent. Silently shrinking a debt
            # is worse than showing an unusual one.
            off = self._money(offen or 0)
            if off <= 0:
                self._clear_exception(t, jahr, monat)
            else:
                self._write_exception(t, jahr, monat, "partial", offen=off,
                                      flag={"typ": "partial", "offen": off})
        else:
            self._write_exception(t, jahr, monat, "unpaid", flag={"typ": "unpaid"})
        self.tenancies.save(t)
        return self._result(user_id, t, jahr, monat, rules.exc_for(t, jahr, monat))

    def mark_partial(self, user_id: int, tenancy_id: int, jahr: int, monat: int, betrag: float) -> dict:
        """Partial payment reported through the quick UI (no payment row booked)."""
        t = self._require_tenancy(user_id, tenancy_id)
        self._require_month(jahr, monat)
        betrag = self._money(betrag)
        if betrag < 0:
            raise PaymentError("Betrag muss 0 oder größer sein")
        soll = rules.monat_soll(t, jahr, monat)
        if betrag >= soll - EPS:
            self._clear_exception(t, jahr, monat)                     # landlord: all good
        elif betrag <= 0:
            self._write_exception(t, jahr, monat, "unpaid", flag={"typ": "unpaid"})
        else:
            offen = round(soll - betrag, 2)
            self._write_exception(t, jahr, monat, "partial", offen=offen,
                                  flag={"typ": "partial", "offen": offen})
        self.tenancies.save(t)
        return self._result(user_id, t, jahr, monat, rules.exc_for(t, jahr, monat))

    # ── read path (every screen derives from here — law #2/#3/#4) ────

    def open_debt(self, user_id: int, t, as_of: Optional[date] = None) -> Debt:
        """THE debt answer — across months AND across years, so an unpaid December does
        not vanish on 1 January. Every screen must use this and compute nothing itself."""
        d = Debt(tenancy_id=t.id)
        for (y, m) in rules.due_months(t, as_of):
            offen = rules.month_open(t, y, m)
            if offen <= 0:
                continue
            soll = rules.monat_soll(t, y, m)
            e = rules.exc_for(t, y, m) or {}
            d.months.append(MonthDebt(jahr=y, monat=m, soll=soll,
                                      bezahlt=round(max(0.0, soll - offen), 2),
                                      offen=offen, typ=e.get("typ")))
            d.total = round(d.total + offen, 2)
        return d

    # ── helpers / guards ─────────────────────────────────────────────

    def _result(self, user_id: int, t, jahr: int, monat: int, exc, **extra) -> dict:
        out = {"success": True, "jahr": jahr, "monat": monat, "exception": exc,
               "offen_gesamt": self.open_debt(user_id, t).total}
        out.update(extra)
        return out

    @staticmethod
    def _money(v) -> float:
        try:
            return round(float(v), 2)
        except (TypeError, ValueError):
            raise PaymentError("Betrag ungültig")

    def _require_tenancy(self, user_id: int, tenancy_id: int):
        t = self.tenancies.get(user_id, tenancy_id)
        if t is None:
            raise PaymentError("Mietverhältnis nicht gefunden")
        return t

    @staticmethod
    def _require_month(jahr: int, monat: int) -> None:
        if not (1 <= int(monat) <= 12):
            raise PaymentError("monat 1-12")
        if not (2000 <= int(jahr) <= 2100):
            raise PaymentError("jahr ungültig")


def sql_service(db) -> PaymentService:
    """Factory for the API layer (commit 2): the service wired to today's SQL backend."""
    return PaymentService(ImmoRentRepository(db), SqlTenancyStore(db))
