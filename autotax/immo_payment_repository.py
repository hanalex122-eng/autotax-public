"""Immobilien Payment — PERSISTENCE PORTS + ADAPTERS.

The Payment Service talks ONLY to these two ports and never to SQLAlchemy:

    PaymentRepository   — where payment facts live
    TenancyStore        — where the tenancy + its exception state (offene_monate) live

Today the payment backend is the `immo_rent` table (`ImmoRentRepository`).
Tomorrow it can be the ledger (`ImmoLedgerRepository`) — swapping the backend must
NOT require changing a business rule. The in-memory adapters are the proof: the very
same service runs with no database at all (see tests/test_immo_payment_service.py).

See CLAUDE.md → "Architecture law — ONE accounting model, many UIs".
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import List, Optional

from autotax.immo_payment_models import PaymentRecord


# ══ PORTS ═════════════════════════════════════════════════════════════


class PaymentRepository(ABC):
    """Persistence port for payment facts."""

    @abstractmethod
    def add(self, p: PaymentRecord) -> PaymentRecord: ...

    @abstractmethod
    def get(self, user_id: int, payment_id: int) -> Optional[PaymentRecord]: ...

    @abstractmethod
    def list_for_month(self, user_id: int, tenancy_id: int, jahr: int, monat: int) -> List[PaymentRecord]: ...

    @abstractmethod
    def list_for_tenancy(self, user_id: int, tenancy_id: int, jahr: Optional[int] = None) -> List[PaymentRecord]: ...

    @abstractmethod
    def soft_delete(self, user_id: int, payment_id: int) -> Optional[PaymentRecord]: ...


class TenancyStore(ABC):
    """Persistence port for the tenancy and its exception state."""

    @abstractmethod
    def get(self, user_id: int, tenancy_id: int): ...

    @abstractmethod
    def save(self, t) -> None: ...


# ══ SQL ADAPTERS (today's backend) ════════════════════════════════════


def _notdel(c):
    return (c.is_deleted == False) | (c.is_deleted == None)  # noqa: E712


class ImmoRentRepository(PaymentRepository):
    """TODAY's backend: the `immo_rent` table."""

    def __init__(self, db):
        self.db = db

    @staticmethod
    def _to_record(r) -> PaymentRecord:
        return PaymentRecord(
            id=r.id, tenancy_id=r.tenancy_id, user_id=r.user_id,
            betrag=float(r.betrag or 0), datum=r.datum,
            fuer_jahr=getattr(r, "fuer_jahr", None), fuer_monat=getattr(r, "fuer_monat", None),
            property_id=r.property_id, source=r.source or "manual", notiz=r.notiz,
        )

    def add(self, p: PaymentRecord) -> PaymentRecord:
        from autotax.models import ImmoRent
        row = ImmoRent(
            property_id=p.property_id, tenancy_id=p.tenancy_id, user_id=p.user_id,
            datum=p.datum, betrag=round(float(p.betrag), 2), notiz=p.notiz,
            source=p.source, fuer_jahr=p.fuer_jahr, fuer_monat=p.fuer_monat,
        )
        self.db.add(row)
        self.db.flush()
        p.id = row.id
        return p

    def get(self, user_id: int, payment_id: int) -> Optional[PaymentRecord]:
        from autotax.models import ImmoRent
        r = (self.db.query(ImmoRent)
             .filter(ImmoRent.id == payment_id, ImmoRent.user_id == user_id, _notdel(ImmoRent))
             .first())
        return self._to_record(r) if r else None

    def list_for_month(self, user_id: int, tenancy_id: int, jahr: int, monat: int) -> List[PaymentRecord]:
        from autotax.models import ImmoRent
        rows = (self.db.query(ImmoRent)
                .filter(ImmoRent.user_id == user_id, ImmoRent.tenancy_id == tenancy_id,
                        ImmoRent.fuer_jahr == jahr, ImmoRent.fuer_monat == monat, _notdel(ImmoRent))
                .all())
        return [self._to_record(r) for r in rows]

    def list_for_tenancy(self, user_id: int, tenancy_id: int, jahr: Optional[int] = None) -> List[PaymentRecord]:
        from autotax.models import ImmoRent
        q = (self.db.query(ImmoRent)
             .filter(ImmoRent.user_id == user_id, ImmoRent.tenancy_id == tenancy_id, _notdel(ImmoRent)))
        if jahr is not None:
            q = q.filter(ImmoRent.fuer_jahr == jahr)
        return [self._to_record(r) for r in q.all()]

    def soft_delete(self, user_id: int, payment_id: int) -> Optional[PaymentRecord]:
        from autotax.models import ImmoRent
        r = (self.db.query(ImmoRent)
             .filter(ImmoRent.id == payment_id, ImmoRent.user_id == user_id, _notdel(ImmoRent))
             .first())
        if not r:
            return None
        rec = self._to_record(r)
        r.is_deleted = True
        r.deleted_at = datetime.now(timezone.utc)
        self.db.flush()
        return rec


class SqlTenancyStore(TenancyStore):
    def __init__(self, db):
        self.db = db

    def get(self, user_id: int, tenancy_id: int):
        from autotax.models import ImmoTenancy
        return (self.db.query(ImmoTenancy)
                .filter(ImmoTenancy.id == tenancy_id, ImmoTenancy.user_id == user_id, _notdel(ImmoTenancy))
                .first())

    def save(self, t) -> None:
        self.db.flush()          # the request-level transaction commits


# ══ IN-MEMORY ADAPTERS (tests — and proof the service is storage-agnostic) ══


class InMemoryPaymentRepository(PaymentRepository):
    def __init__(self):
        self.rows: List[PaymentRecord] = []
        self._deleted: set = set()
        self._seq = 0

    def _alive(self) -> List[PaymentRecord]:
        return [r for r in self.rows if r.id not in self._deleted]

    def add(self, p: PaymentRecord) -> PaymentRecord:
        self._seq += 1
        p.id = self._seq
        p.betrag = round(float(p.betrag), 2)
        self.rows.append(p)
        return p

    def get(self, user_id: int, payment_id: int) -> Optional[PaymentRecord]:
        return next((r for r in self._alive() if r.id == payment_id and r.user_id == user_id), None)

    def list_for_month(self, user_id, tenancy_id, jahr, monat) -> List[PaymentRecord]:
        return [r for r in self._alive()
                if r.user_id == user_id and r.tenancy_id == tenancy_id
                and r.fuer_jahr == jahr and r.fuer_monat == monat]

    def list_for_tenancy(self, user_id, tenancy_id, jahr=None) -> List[PaymentRecord]:
        return [r for r in self._alive()
                if r.user_id == user_id and r.tenancy_id == tenancy_id
                and (jahr is None or r.fuer_jahr == jahr)]

    def soft_delete(self, user_id: int, payment_id: int) -> Optional[PaymentRecord]:
        r = self.get(user_id, payment_id)
        if not r:
            return None
        self._deleted.add(payment_id)
        return r


class InMemoryTenancyStore(TenancyStore):
    def __init__(self, tenancies: dict):
        self.tenancies = tenancies          # {tenancy_id: tenancy-like object}
        self.saves = 0

    def get(self, user_id: int, tenancy_id: int):
        t = self.tenancies.get(tenancy_id)
        if t is not None and getattr(t, "user_id", user_id) != user_id:
            return None
        return t

    def save(self, t) -> None:
        self.saves += 1
