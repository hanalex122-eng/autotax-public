"""Immobilien — PURE domain rules (no DB, no HTTP, no ORM).

Extracted verbatim from immo_api.py so that BOTH the API layer and the Payment
Service can use the same month math without a circular import.

Architecture law (CLAUDE.md):
  * debt is derived ONLY from the Exception Engine,
  * every read surface derives — it never invents its own formula.

This module is the derivation. It is read-only by construction: nothing here
writes state. Mutating payment/exception state is the Payment Service's job
(autotax/immo_payments.py).

A "tenancy" here is any object exposing: von, bis, kaltmiete, nk_voraus,
erstmonat_betrag, miete_historie, offene_monate. That is duck-typing on purpose
— the rules must be testable without a database.
"""
from __future__ import annotations

import json
from calendar import monthrange
from datetime import date, datetime
from typing import Optional

# ── calendar / occupancy ──────────────────────────────────────────────


def tenancy_active_in_month(t, y: int, m: int) -> bool:
    mstart = date(y, m, 1)
    mend = date(y, m, monthrange(y, m)[1])
    von = t.von or date(1900, 1, 1)
    bis = t.bis or date(2999, 12, 31)
    return von <= mend and bis >= mstart


def months_active_in_year(t, y: int) -> int:
    return sum(1 for m in range(1, 13) if tenancy_active_in_month(t, y, m))


def months_due_to_date(t, y: int, as_of: Optional[date] = None) -> int:
    """Active months whose rent is ALREADY DUE — current year capped at the current
    month, past years full, future years 0. Used for arrears/Rückstand/Mahnung so
    future months (not yet owed) don't show up as debt."""
    as_of = as_of or date.today()
    last = 12 if y < as_of.year else (as_of.month if y == as_of.year else 0)
    return sum(1 for m in range(1, last + 1) if tenancy_active_in_month(t, y, m))


def month_proration(t, y: int, m: int) -> float:
    """Anteil (0..1) des Monats, den der Mieter bewohnt — für anteilige Miete bei
    Einzug/Auszug mitten im Monat (z.B. Einzug 15.06 → ~16/30). Voller Monat = 1.0."""
    dim = monthrange(y, m)[1]
    mstart = date(y, m, 1)
    mend = date(y, m, dim)
    von = t.von or date(1900, 1, 1)
    bis = t.bis or date(2999, 12, 31)
    occ_start = max(von, mstart)
    occ_end = min(bis, mend)
    if occ_end < occ_start:
        return 0.0
    days = (occ_end - occ_start).days + 1
    return max(0.0, min(1.0, days / dim))


# ── rent amounts ──────────────────────────────────────────────────────


def effective_kalt(t, y: int, m: int) -> float:
    """Effective Kaltmiete for month (y,m), honoring DATED Mieterhöhungen
    (t.miete_historie JSON [{ab, kalt}]). Base = t.kaltmiete; the latest change whose
    ab-date is on/before month-end wins → past months keep the old rent."""
    base = float(t.kaltmiete or 0)
    raw = getattr(t, "miete_historie", None)
    if not raw:
        return base
    try:
        hist = json.loads(raw) if isinstance(raw, str) else list(raw or [])
    except Exception:
        return base
    mend = date(y, m, monthrange(y, m)[1])
    best_ab, best = None, base
    for c in (hist or []):
        try:
            ab = datetime.strptime(str(c.get("ab"))[:10], "%Y-%m-%d").date()
            k = float(c.get("kalt"))
        except Exception:
            continue
        if ab <= mend and (best_ab is None or ab > best_ab):
            best_ab, best = ab, k
    return best


def monat_soll(t, y: int, m: int) -> float:
    """Soll für EINEN Monat = WARMMIETE: (Kaltmiete + NK-Voraus. + Heizkosten-Voraus.) × Tagesanteil.

    Commit 2 (defect A3): the NK-Vorauszahlung is part of what the tenant owes every
    month. Before, the Soll was Kalt-only, so the debt — and the Mahnung amount — were
    short by the NK every single month (tenant card said "Gesamt 470", Bu Ay said
    "offen 400", the Mahnung dunned for 400). It is also the precondition for the
    Nebenkostenabrechnung (Masterplan #8): you cannot settle Vorauszahlungen you never
    tracked as owed.

    Flexible Mietmodelle Faz 1 (Sprint 1.1): + heizkosten_voraus (separate Heizkosten
    prepayment). heizkosten_voraus = None -> 0 -> BYTE-IDENTICAL to the pre-Faz-1 Soll.
    Single-Ledger split (invariant): monat_soll == monat_kalt_soll + monat_nk_soll + monat_heiz_soll.

    Exception: `erstmonat_betrag` (vereinbarte Erstmiete) is a GROSS agreed amount for
    the move-in month — NK/Heiz are not added on top of it.
    """
    em = getattr(t, "erstmonat_betrag", None)
    if em is not None and t.von and t.von.year == y and t.von.month == m:
        return round(float(em), 2)
    warm = (effective_kalt(t, y, m)
            + float(getattr(t, "nk_voraus", 0) or 0)
            + float(getattr(t, "heizkosten_voraus", 0) or 0))
    return round(warm * month_proration(t, y, m), 2)


def monat_kalt_soll(t, y: int, m: int) -> float:
    """Kalt-only Soll — for reports that must split Kaltmiete from Nebenkosten
    (Anlage V, Nebenkostenabrechnung). NOT a debt figure: debt is always monat_soll."""
    em = getattr(t, "erstmonat_betrag", None)
    if em is not None and t.von and t.von.year == y and t.von.month == m:
        # Erstmiete is gross: subtract the NK + Heiz prepayment parts to get the Kalt part.
        # heiz=0 -> byte-identical to the pre-Faz-1 `em - nk`.
        vor = (float(getattr(t, "nk_voraus", 0) or 0)
               + float(getattr(t, "heizkosten_voraus", 0) or 0)) * month_proration(t, y, m)
        return round(max(0.0, float(em) - vor), 2)
    return round(effective_kalt(t, y, m) * month_proration(t, y, m), 2)


def monat_heiz_soll(t, y: int, m: int) -> float:
    """Heizkostenvorauszahlung owed for one month (pro-rated). Flexible Mietmodelle Faz 1:
    part of the Warmmiete/monat_soll, but deliberately NOT read by the Nebenkostenabrechnung
    yet (Faz 4 = NK-Heiz-Mahsub). heizkosten_voraus = None -> 0 -> byte-identical to pre-Faz-1."""
    return round(float(getattr(t, "heizkosten_voraus", 0) or 0) * month_proration(t, y, m), 2)


def monat_nk_soll(t, y: int, m: int) -> float:
    """NK-Vorauszahlung owed for one month (pro-rated) — the basis of the future
    Nebenkostenabrechnung (Masterplan #8). EXCLUDES Heiz (NK isolation, Faz 1):
    = monat_soll - monat_kalt_soll - monat_heiz_soll. For heiz=0 this is byte-identical
    to the pre-Faz-1 `monat_soll - monat_kalt_soll`."""
    return round(monat_soll(t, y, m) - monat_kalt_soll(t, y, m) - monat_heiz_soll(t, y, m), 2)


def soll_faellig(t, y: int, as_of: Optional[date] = None) -> float:
    """Fälliges Soll bis heute (ein Jahr): pro Monat monat_soll."""
    as_of = as_of or date.today()
    last = 12 if y < as_of.year else (as_of.month if y == as_of.year else 0)
    total = 0.0
    for m in range(1, last + 1):
        if tenancy_active_in_month(t, y, m):
            total += monat_soll(t, y, m)
    return round(total, 2)


def due_months(t, as_of: Optional[date] = None) -> list:
    """EVERY active month whose rent is already due, ACROSS YEAR BOUNDARIES —
    from the Einzug month up to (and including) the current month.

    This is what "who owes me money" must be built from. The per-year view
    (exception_arrears) is a screen, not the truth: an unpaid December must not
    disappear on 1 January (defect A2).
    """
    as_of = as_of or date.today()
    start = t.von or date(as_of.year, 1, 1)
    y, m = start.year, start.month
    out = []
    while (y, m) <= (as_of.year, as_of.month):
        if tenancy_active_in_month(t, y, m):
            out.append((y, m))
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return out


# ── exception engine (READ side — the single debt truth) ──────────────


def exc_list(t) -> list:
    """Parsed exception list of the tenancy.

    Each entry: {ym, typ, offen?, flag?}

      typ   — the DERIVED state of the month: 'unpaid' | 'partial' | 'settled'
              ('settled' = money covered it; the entry survives only to remember `flag`)
      flag  — what the LANDLORD reported, independent of any money:
              {"typ": "unpaid"} or {"typ": "partial", "offen": 120.0} or None.
              The flag is what makes "delete a payment" undoable — the report outlives
              the payment that settled it.

    Legacy entries (bare "2026-06" strings, dicts without `flag`) stay valid.
    """
    raw = getattr(t, "offene_monate", None)
    if not raw:
        return []
    try:
        lst = json.loads(raw) if isinstance(raw, str) else list(raw or [])
    except Exception:
        return []
    out = []
    for e in (lst or []):
        if isinstance(e, dict) and e.get("ym"):
            out.append({"ym": str(e["ym"])[:7], "typ": e.get("typ") or "unpaid",
                        "offen": e.get("offen"), "flag": _norm_flag(e.get("flag"))})
        elif isinstance(e, str) and len(e) >= 7:          # legacy bare "2026-06" = unpaid
            out.append({"ym": e[:7], "typ": "unpaid", "offen": None, "flag": {"typ": "unpaid"}})
    return out


def _norm_flag(f):
    """Landlord report, normalised. Legacy string 'unpaid' → {"typ": "unpaid"}."""
    if not f:
        return None
    if isinstance(f, str):
        return {"typ": f}
    if isinstance(f, dict) and f.get("typ"):
        out = {"typ": f["typ"]}
        if f.get("offen") is not None:
            out["offen"] = round(float(f["offen"]), 2)
        return out
    return None


def exc_for(t, year: int, m: int) -> Optional[dict]:
    ym = "%04d-%02d" % (year, m)
    for e in exc_list(t):
        if e["ym"] == ym:
            return e
    return None


def month_open(t, y: int, m: int) -> float:
    """Open (owed) amount for ONE month, derived ONLY from the exception engine.
    no entry / 'settled' → 0 (Dauerzahlung default: silence means paid)
    'partial'            → the stored open amount
    'unpaid'             → the full month Soll"""
    if not tenancy_active_in_month(t, y, m):
        return 0.0
    e = exc_for(t, y, m)
    if not e:
        return 0.0
    if e["typ"] == "partial":
        return round(float(e.get("offen") or 0), 2)
    if e["typ"] == "settled":
        return 0.0
    return monat_soll(t, y, m)


def exception_arrears(t, year: int, as_of: Optional[date] = None) -> float:
    """Debt of ONE calendar year (Mietkonto tab view). Due-to-date, active months only."""
    as_of = as_of or date.today()
    last = 12 if year < as_of.year else (as_of.month if year == as_of.year else 0)
    total = sum(month_open(t, year, m) for m in range(1, last + 1))
    return round(max(0.0, total), 2)


# ── income (Ist) — DERIVED, never summed from payment rows ────────────
#
# Commit 2 (defect B2): the reports used to sum immo_rent rows, which the Exception
# Engine never creates → income was always 0, Gewinn was negative, the income chart was
# a flat line and the portfolio score was red. Income is not a second book: it is what
# was owed minus what is still open.


def month_ist(t, y: int, m: int, as_of: Optional[date] = None) -> float:
    """Rent effectively received in ONE month = Soll − offen. Future/inactive → 0."""
    as_of = as_of or date.today()
    if not tenancy_active_in_month(t, y, m):
        return 0.0
    if (y, m) > (as_of.year, as_of.month):          # not due yet → no income claimed
        return 0.0
    return round(max(0.0, monat_soll(t, y, m) - month_open(t, y, m)), 2)


def year_ist(t, y: int, as_of: Optional[date] = None) -> float:
    return round(sum(month_ist(t, y, m, as_of) for m in range(1, 13)), 2)
