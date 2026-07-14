"""Immobilien Payment — DOMAIN MODELS (no DB, no HTTP, no framework).

The vocabulary the Payment Service speaks. Deliberately free of SQLAlchemy so the
storage backend (immo_rent today, ledger tomorrow) can change without touching a
single business rule. See CLAUDE.md → "Architecture law".
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import List, Optional

# Money comparison tolerance (cents).
EPS = 0.01

# Which UI door the payment came through. Bookkeeping metadata only — it must never
# influence the debt calculation (law #2: no UI calculates debt).
SOURCES = {"manual", "quick", "mieteingang", "bank", "import"}


class PaymentError(ValueError):
    """Business-rule violation (invalid amount, unknown month, foreign tenancy…)."""


@dataclass
class PaymentRecord:
    """A payment FACT: money the landlord asserts he received, for ONE rent month.

    `fuer_jahr`/`fuer_monat` = the month this payment settles. Deliberately separate
    from `datum` (when the money arrived): March rent may be paid in April. Debt is
    per rent-month, so the attribution — not the value date — is what the Exception
    Engine reconciles against.
    """
    tenancy_id: int
    user_id: int
    betrag: float
    fuer_jahr: int
    fuer_monat: int
    datum: Optional[date] = None
    property_id: Optional[int] = None
    source: str = "manual"
    notiz: Optional[str] = None
    id: Optional[int] = None


@dataclass
class MonthDebt:
    """One month's contribution to the debt — derived, never stored."""
    jahr: int
    monat: int
    soll: float
    bezahlt: float
    offen: float
    typ: Optional[str]          # None (ok) | "unpaid" | "partial"

    @property
    def ym(self) -> str:
        return "%04d-%02d" % (self.jahr, self.monat)


@dataclass
class Debt:
    """What a tenant owes — the ONLY debt answer in the system (law #3)."""
    tenancy_id: int
    total: float = 0.0
    months: List[MonthDebt] = field(default_factory=list)

    @property
    def is_debtor(self) -> bool:
        return self.total > EPS

    def to_dict(self) -> dict:
        return {
            "tenancy_id": self.tenancy_id,
            "offen_gesamt": round(self.total, 2),
            "debtor": self.is_debtor,
            "monate": [{"ym": m.ym, "jahr": m.jahr, "monat": m.monat, "soll": m.soll,
                        "bezahlt": m.bezahlt, "offen": m.offen, "typ": m.typ} for m in self.months],
        }
