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

from datetime import date
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


# ══════════════════════════════════════════════════════════════════════
#  DAY-BASED aging engine (Faz 2.2). NEW capability — the OLD engine has no
#  equivalent, so this is NOT a parity metric and must never gate parity.
#  Nothing consumes it yet (no UI/cockpit) — read-model only.
# ══════════════════════════════════════════════════════════════════════
def _pay_alloc(soll_rows: list, total_paid: float) -> list:
    """FIFO: distribute `total_paid` across `soll_rows` (oldest first).

    Each row is a dict carrying at least 'betrag'. Returns the rows enriched with:
        gedeckt = amount covered, offen = remaining, status = paid|partial|open.
    Overpayment leftover is ignored (credit shows up in saldo, not here).
    """
    remaining = float(total_paid or 0)
    out = []
    for r in soll_rows:
        b = float(r.get("betrag") or 0)
        covered = min(remaining, b) if remaining > 0 else 0.0
        remaining -= covered
        offen = round(b - covered, 2)
        status = "paid" if offen <= 0.001 else ("partial" if covered > 0 else "open")
        out.append({**r, "gedeckt": round(covered, 2), "offen": offen, "status": status})
    return out


def _bucket(tage: int) -> Optional[str]:
    """Day-based overdue bucket. None if not yet due (tage<1)."""
    if tage < 1:
        return None
    return "warning" if tage <= 7 else ("high" if tage <= 30 else "critical")


def konto_state(db, uid: int, tenancy_id: int, year: int,
                konto_art: str = "miete", as_of=None) -> dict:
    """Month-by-month Mietkonto for one tenancy/year (UI base, not wired yet).

    {"tenancy_id", "year",
     "rows": [{monat, soll, gedeckt, offen, status, faellig_am, tage_ueberfaellig}],
     "summe": {soll, ist, saldo, offen}}
    Payments are allocated FIFO (oldest month first). saldo comes from
    saldo_by_tenancy (authoritative, incl. korrektur)."""
    as_of = as_of or date.today()
    solls = db.query(ImmoLedgerEntry).filter(
        ImmoLedgerEntry.user_id == uid, _notdel(ImmoLedgerEntry),
        ImmoLedgerEntry.tenancy_id == tenancy_id, ImmoLedgerEntry.konto_art == konto_art,
        ImmoLedgerEntry.typ == "sollbuchung", ImmoLedgerEntry.jahr == year,
    ).order_by(ImmoLedgerEntry.monat).all()
    pays = db.query(ImmoLedgerEntry.betrag).filter(
        ImmoLedgerEntry.user_id == uid, _notdel(ImmoLedgerEntry),
        ImmoLedgerEntry.tenancy_id == tenancy_id, ImmoLedgerEntry.konto_art == konto_art,
        ImmoLedgerEntry.typ.in_(_PAYMENT_TYPEN), ImmoLedgerEntry.jahr == year).all()
    ist = round(-sum(float(b or 0) for (b,) in pays), 2)
    rows_in = [{"monat": s.monat, "betrag": float(s.betrag or 0), "faellig_am": s.faellig_am} for s in solls]
    rows = []
    for a in _pay_alloc(rows_in, ist):
        tage = (as_of - a["faellig_am"]).days if a["faellig_am"] else None
        rows.append({
            "monat": a["monat"], "soll": round(a["betrag"], 2), "gedeckt": a["gedeckt"],
            "offen": a["offen"], "status": a["status"],
            "faellig_am": str(a["faellig_am"]) if a["faellig_am"] else None,
            "tage_ueberfaellig": (tage if (a["offen"] > 0.001 and tage and tage > 0) else 0),
        })
    saldo = saldo_by_tenancy(db, uid, year, konto_art).get(tenancy_id, {}).get("saldo", 0.0)
    return {"tenancy_id": tenancy_id, "year": year, "rows": rows,
            "summe": {"soll": round(sum(r["soll"] for r in rows), 2), "ist": ist,
                      "saldo": saldo, "offen": round(sum(r["offen"] for r in rows), 2)}}


def aging_report(db, uid: int, as_of=None, konto_art: str = "miete") -> dict:
    """Portfolio-wide day-based aging of OPEN Sollbuchungen (all years).

    Per tenancy, payments are FIFO-allocated across all its Sollbuchungen; each
    still-open one is aged by (as_of − faellig_am) and bucketed (1-7 warning /
    8-30 high / 30+ critical). Not-yet-due (tage<1) and fully-paid are excluded.
    {"summary": {warning, high, critical, offen_total},
     "items": [{tenancy_id, tenant_name, jahr, monat, offen, faellig_am, tage, bucket}]}"""
    as_of = as_of or date.today()
    solls = db.query(ImmoLedgerEntry).filter(
        ImmoLedgerEntry.user_id == uid, _notdel(ImmoLedgerEntry), ImmoLedgerEntry.konto_art == konto_art,
        ImmoLedgerEntry.typ == "sollbuchung", ImmoLedgerEntry.tenancy_id != None,  # noqa: E711
    ).order_by(ImmoLedgerEntry.tenancy_id, ImmoLedgerEntry.jahr, ImmoLedgerEntry.monat).all()
    pays = db.query(ImmoLedgerEntry.tenancy_id, ImmoLedgerEntry.betrag).filter(
        ImmoLedgerEntry.user_id == uid, _notdel(ImmoLedgerEntry), ImmoLedgerEntry.konto_art == konto_art,
        ImmoLedgerEntry.typ.in_(_PAYMENT_TYPEN), ImmoLedgerEntry.tenancy_id != None).all()  # noqa: E711
    ist_by = {}
    for tid, b in pays:
        ist_by[tid] = ist_by.get(tid, 0.0) + (-float(b or 0))
    by_t = {}
    for s in solls:
        by_t.setdefault(s.tenancy_id, []).append(s)
    tmap = _tenancy_map(db, uid)
    summary = {"warning": 0, "high": 0, "critical": 0, "offen_total": 0.0}
    items = []
    for tid, slist in by_t.items():
        rows_in = [{"jahr": s.jahr, "monat": s.monat, "betrag": float(s.betrag or 0), "faellig_am": s.faellig_am} for s in slist]
        for a in _pay_alloc(rows_in, ist_by.get(tid, 0.0)):
            if a["offen"] <= 0.001 or not a["faellig_am"]:
                continue
            tage = (as_of - a["faellig_am"]).days
            bucket = _bucket(tage)
            if bucket is None:
                continue
            summary[bucket] += 1
            summary["offen_total"] = round(summary["offen_total"] + a["offen"], 2)
            t = tmap.get(tid)
            items.append({"tenancy_id": tid, "tenant_name": (t.mieter_name if t else None),
                          "jahr": a["jahr"], "monat": a["monat"], "offen": a["offen"],
                          "faellig_am": str(a["faellig_am"]), "tage": tage, "bucket": bucket})
    items.sort(key=lambda x: -x["tage"])
    return {"summary": summary, "items": items}
