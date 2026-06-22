"""Immobilien source-selector adapter (Ledger-First Migration, Faz 4.1).

The safe ON/OFF switch for cutover. Each function returns the SAME shape as the
OLD engine, choosing the data source by the IMMO_LEDGER_READ flag:

    flag OFF (default) → OLD engine (immo_api._portfolio / _old_debtors /
                         _tenancy_arrears) — 100% today's behavior.
    flag ON            → ledger read model (immo_ledger_read) — parity-proven
                         to equal OLD (Faz 3 gate, incl. refund/korrektur).

Scope = the DEBT/arrears numbers that drift and for which the ledger is the new
source. Raw "collected" (ist) keeps coming from immo_rent (payment source of
truth) — never routed here, so it can't diverge.

Faz 4.1 is INERT: nothing calls these adapters yet (wiring = Faz 4.2/4.3). The
OLD functions are NOT removed (strangler fallback). immo_api is imported lazily
inside each function to avoid an import cycle when consumers later call this.
"""
from __future__ import annotations

from autotax import immo_ledger_read as _read
from autotax.config import immo_ledger_read_enabled


def src_arrears_total(db, uid: int, year: int) -> float:
    """Total open receivables (OLD: _portfolio.financial.rueckstand)."""
    if immo_ledger_read_enabled():
        return _read.offene_forderungen(db, uid, year)["total"]
    from autotax import immo_api as _api
    return _api._portfolio(db, uid, year)["financial"]["rueckstand"]


def src_tenancy_arrears(db, uid: int, t, year: int) -> float:
    """Open amount for one tenancy (OLD: _tenancy_arrears) — feeds Mahnung.
    Ledger path = max(0, saldo), parity-equal incl. korrektur."""
    if immo_ledger_read_enabled():
        sal = _read.saldo_by_tenancy(db, uid, year).get(t.id, {})
        return round(max(0.0, sal.get("saldo", 0.0)), 2)
    from autotax import immo_api as _api
    return _api._tenancy_arrears(db, uid, t, year)


def src_debtors(db, uid: int, year: int) -> list:
    """Full debtor list in OLD top_debtors shape [{tenant, debt, months_overdue}],
    sorted by debt desc. Callers cap (e.g. [:5]) for display as before."""
    if immo_ledger_read_enabled():
        return [{"tenant": d["tenant_name"], "debt": d["debt"], "months_overdue": d["months_overdue"]}
                for d in _read.debtor_list(db, uid, year)]
    from autotax import immo_api as _api
    return _api._old_debtors(db, uid, year)
