"""Immobilien Ledger — READ MODEL (Ledger-First Migration, Faz 2).

Pure, side-effect-free read helpers over immo_ledger_entry. This is the single
data source that Cockpit / Mahnung / Debtor / Risk will consume AFTER the parity
gate (Faz 3) passes and cutover happens (Faz 4). In Faz 2 NOTHING is wired — no
consumer, no endpoint, no read-path change.

Parity foundation (mirrors the OLD engine exactly):
  saldo = Σ betrag (signed). Every immo_rent maps to ledger entries summing to
  −rent.betrag, so ledger saldo === OLD (soll − ist) per tenancy, even with
  refunds (refund = korrektur). Therefore debt = max(0, saldo) is parity-exact.
"""
from __future__ import annotations

from typing import Optional

from autotax.models import ImmoLedgerEntry, ImmoTenancy

_PAYMENT_TYPEN = ("zahlung", "teilzahlung")


def _notdel(c):
    return (c.is_deleted == False) | (c.is_deleted == None)  # noqa: E712


def _tenancy_map(db, uid: int) -> dict:
    rows = db.query(ImmoTenancy).filter(ImmoTenancy.user_id == uid, _notdel(ImmoTenancy)).all()
    return {t.id: t for t in rows}


# ── saldo per tenancy ─────────────────────────────────────────────────
def saldo_by_tenancy(db, uid: int, year: Optional[int] = None, konto_art: str = "miete") -> dict:
    """{tenancy_id: {"soll", "ist", "saldo"}}.

    soll  = Σ betrag (typ=sollbuchung)
    ist   = −Σ betrag (typ in zahlung/teilzahlung)  → positive = collected
    saldo = Σ betrag (ALL typen incl. korrektur)    → positive = open arrears
    (saldo can differ from soll−ist when korrektur entries exist; saldo is the
     authoritative balance and equals OLD soll−ist_old.)
    """
    q = db.query(ImmoLedgerEntry.tenancy_id, ImmoLedgerEntry.typ, ImmoLedgerEntry.betrag).filter(
        ImmoLedgerEntry.user_id == uid, _notdel(ImmoLedgerEntry),
        ImmoLedgerEntry.konto_art == konto_art, ImmoLedgerEntry.tenancy_id != None)  # noqa: E711
    if year is not None:
        q = q.filter(ImmoLedgerEntry.jahr == year)
    out: dict = {}
    for tid, typ, betrag in q.all():
        d = out.setdefault(tid, {"soll": 0.0, "ist": 0.0, "saldo": 0.0})
        b = float(betrag or 0)
        d["saldo"] += b
        if typ == "sollbuchung":
            d["soll"] += b
        elif typ in _PAYMENT_TYPEN:
            d["ist"] += -b
    for d in out.values():
        d["soll"] = round(d["soll"], 2)
        d["ist"] = round(d["ist"], 2)
        d["saldo"] = round(d["saldo"], 2)
    return out


# ── open receivables (OLD: _portfolio.financial.rueckstand) ───────────
def offene_forderungen(db, uid: int, year: int, konto_art: str = "miete") -> dict:
    """{"total": €, "by_tenancy": {tid: open}}. open = max(0, saldo) per tenancy
    (OLD clamps arrears at 0; ledger saldo may be negative/credit)."""
    sal = saldo_by_tenancy(db, uid, year, konto_art)
    by = {tid: round(max(0.0, d["saldo"]), 2) for tid, d in sal.items() if d["saldo"] > 0}
    return {"total": round(sum(by.values()), 2), "by_tenancy": by}


# ── oldest still-open Sollbuchung (FIFO, minimal) ─────────────────────
def _oldest_open_faellig(db, uid: int, tid: int, year: int, konto_art: str, total_paid: float):
    """faellig_am of the oldest Sollbuchung not yet covered by payments (oldest
    first). None if every Sollbuchung is covered (e.g. debt comes only from a
    korrektur). Returns an ISO date string for JSON friendliness."""
    rows = db.query(ImmoLedgerEntry).filter(
        ImmoLedgerEntry.user_id == uid, _notdel(ImmoLedgerEntry),
        ImmoLedgerEntry.tenancy_id == tid, ImmoLedgerEntry.konto_art == konto_art,
        ImmoLedgerEntry.typ == "sollbuchung", ImmoLedgerEntry.jahr == year,
    ).order_by(ImmoLedgerEntry.jahr, ImmoLedgerEntry.monat).all()
    remaining = float(total_paid)
    for r in rows:
        b = float(r.betrag or 0)
        if remaining >= b:
            remaining -= b
        else:
            return str(r.faellig_am) if r.faellig_am else None
    return None


def _risk_level(months_overdue: Optional[int]) -> str:
    m = months_overdue or 0
    return "high" if m >= 2 else ("mid" if m >= 1 else "low")


# ── debtors (OLD: _portfolio.top_debtors) — UI-ready shape ────────────
def debtor_list(db, uid: int, year: int, konto_art: str = "miete") -> list:
    """[{tenancy_id, tenant_name, debt, months_overdue, oldest_due_date, risk_level}]
    for tenancies with debt>0, sorted by debt desc. Shape is UI-ready now even
    though no consumer is wired yet. months_overdue feeds OLD-parity (cockpit
    critical = months_overdue>=2)."""
    sal = saldo_by_tenancy(db, uid, year, konto_art)
    tmap = _tenancy_map(db, uid)
    out = []
    for tid, d in sal.items():
        debt = round(max(0.0, d["saldo"]), 2)
        if debt <= 0:
            continue
        t = tmap.get(tid)
        kalt = float(t.kaltmiete or 0) if t else 0.0
        months_overdue = round(debt / kalt) if kalt > 0 else None
        out.append({
            "tenancy_id": tid,
            "tenant_name": (t.mieter_name if t else None),
            "debt": debt,
            "months_overdue": months_overdue,
            "oldest_due_date": _oldest_open_faellig(db, uid, tid, year, konto_art, d["ist"]),
            "risk_level": _risk_level(months_overdue),
        })
    out.sort(key=lambda x: -x["debt"])
    return out
