"""Immobilien Ledger — posting service (Ledger-First Migration, Faz 0).

The single write-path for Mietkonto movements. It ENFORCES the sign rules so a
wrong-signed entry can never be persisted:

    sollbuchung  ->  betrag > 0     (Forderung)
    mahngebuehr  ->  betrag > 0     (Mahngebühr erhöht die Forderung)
    zahlung      ->  betrag < 0     (Tilgung)
    teilzahlung  ->  betrag < 0     (Teil-Tilgung)
    korrektur    ->  betrag != 0    (any sign — manuelle Korrektur)

Konto-Saldo = SUM(betrag). Positive saldo = open arrears (Rückstand),
zero/negative = paid / credit.

ADDITIVE & ISOLATED: never touches immo_rent, OCR, VAT, Kassenbuch or
Rechnungen. This is Faz 0 — table + posting service + validation only. Backfill
(Faz 1), read models (Faz 2) and consumer cutover (Faz 4) build on top of this.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import func

from autotax.models import ImmoLedgerEntry

# ── Buchungsarten ─────────────────────────────────────────────────────
TYP_SOLLBUCHUNG = "sollbuchung"
TYP_ZAHLUNG = "zahlung"
TYP_TEILZAHLUNG = "teilzahlung"
TYP_KORREKTUR = "korrektur"
TYP_MAHNGEBUEHR = "mahngebuehr"

ALL_TYPEN = {TYP_SOLLBUCHUNG, TYP_ZAHLUNG, TYP_TEILZAHLUNG, TYP_KORREKTUR, TYP_MAHNGEBUEHR}
POSITIVE_TYPEN = {TYP_SOLLBUCHUNG, TYP_MAHNGEBUEHR}   # must be > 0
NEGATIVE_TYPEN = {TYP_ZAHLUNG, TYP_TEILZAHLUNG}       # must be < 0
# korrektur: any non-zero sign

KONTO_ARTEN = {"miete", "leerstand", "nebenkosten", "anlage_v"}


class LedgerError(ValueError):
    """Raised when a Buchung violates a sign / type / amount rule.

    Callers (API endpoints) should map this to HTTP 400 — it is a client/data
    error, never a server fault.
    """


# ── validation ────────────────────────────────────────────────────────
def validate_entry(typ: str, betrag) -> float:
    """Validate a single Buchung and return the rounded, sign-checked amount.

    Rejects (raises LedgerError) — never silently coerces the sign, so a
    wrong-signed record can never be created (per the enforcement requirement).
    """
    if typ not in ALL_TYPEN:
        raise LedgerError(f"Unbekannter Buchungstyp: {typ!r}")
    try:
        b = float(betrag)
    except (TypeError, ValueError):
        raise LedgerError(f"Betrag ist keine Zahl: {betrag!r}")
    if b != b or b in (float("inf"), float("-inf")):       # NaN / Inf
        raise LedgerError("Betrag ist NaN/Inf")
    b = round(b, 2)
    if b == 0:
        raise LedgerError(f"Betrag 0 ist nicht erlaubt (typ={typ})")
    if typ in POSITIVE_TYPEN and b < 0:
        raise LedgerError(f"{typ} muss positiv sein (Forderung), war {b}")
    if typ in NEGATIVE_TYPEN and b > 0:
        raise LedgerError(f"{typ} muss negativ sein (Tilgung), war {b}")
    return b


# ── posting ───────────────────────────────────────────────────────────
def post_entry(db, *, user_id: int, typ: str, betrag, jahr: int,
               property_id: Optional[int] = None, unit_id: Optional[int] = None,
               tenancy_id: Optional[int] = None, monat: Optional[int] = None,
               buchungsdatum=None, faellig_am=None, beleg: Optional[str] = None,
               source: str = "manual", source_rent_id: Optional[int] = None,
               mahnung_id: Optional[int] = None, konto_art: str = "miete",
               commit: bool = True) -> ImmoLedgerEntry:
    """Create one validated, sign-checked ledger entry.

    Raises LedgerError on any rule violation BEFORE touching the DB. The caller
    owns the session; pass commit=False to batch many posts in one transaction
    (used by the Faz 1 backfill).
    """
    betrag = validate_entry(typ, betrag)
    if konto_art not in KONTO_ARTEN:
        raise LedgerError(f"Unbekannte Konto-Art: {konto_art!r}")
    if typ == TYP_SOLLBUCHUNG and not monat:
        raise LedgerError("sollbuchung benötigt monat (1-12)")
    if monat is not None and not (1 <= int(monat) <= 12):
        raise LedgerError(f"monat muss 1-12 sein, war {monat}")
    e = ImmoLedgerEntry(
        user_id=user_id, konto_art=konto_art, property_id=property_id,
        unit_id=unit_id, tenancy_id=tenancy_id, typ=typ, betrag=betrag,
        jahr=jahr, monat=(int(monat) if monat is not None else None),
        buchungsdatum=buchungsdatum, faellig_am=faellig_am, beleg=beleg,
        source=source, source_rent_id=source_rent_id, mahnung_id=mahnung_id,
    )
    db.add(e)
    if commit:
        db.commit()
        db.refresh(e)
    return e


# ── minimal read helper (full read models arrive in Faz 2) ────────────
def konto_saldo(db, user_id: int, *, tenancy_id: Optional[int] = None,
                property_id: Optional[int] = None, jahr: Optional[int] = None,
                konto_art: str = "miete") -> float:
    """SUM(betrag) over the (soft-delete-filtered) ledger. Positive = arrears."""
    notdel = (ImmoLedgerEntry.is_deleted == False) | (ImmoLedgerEntry.is_deleted == None)  # noqa: E712
    q = db.query(func.coalesce(func.sum(ImmoLedgerEntry.betrag), 0.0)).filter(
        ImmoLedgerEntry.user_id == user_id, notdel)
    if konto_art:
        q = q.filter(ImmoLedgerEntry.konto_art == konto_art)
    if tenancy_id is not None:
        q = q.filter(ImmoLedgerEntry.tenancy_id == tenancy_id)
    if property_id is not None:
        q = q.filter(ImmoLedgerEntry.property_id == property_id)
    if jahr is not None:
        q = q.filter(ImmoLedgerEntry.jahr == jahr)
    return round(float(q.scalar() or 0.0), 2)


# ── idempotency indexes (called from db.init_db AND tests) ────────────
def ensure_ledger_indexes(engine) -> None:
    """Create the partial-unique indexes that guarantee backfill idempotency.

    create_all builds the table but cannot express partial (WHERE) unique
    indexes, so they are ensured here. Portable across SQLite and PostgreSQL
    (both support partial indexes). Best-effort — caller wraps in try/except.

      uq_immo_ledger_soll_cat : one Sollbuchung per
          (user, tenancy, konto_art, jahr, monat)
      uq_immo_ledger_rent     : one ledger row per imported immo_rent

    The Sollbuchung key includes konto_art so a tenant can carry SEPARATE
    Forderungsarten (miete / nebenkosten / heizkosten / hausgeld / nachzahlung)
    in the SAME month. The original 4-column index (uq_immo_ledger_soll, without
    konto_art) is dropped first — done while immo_ledger_entry is still empty
    (pre-Faz-1), so there is zero data-migration cost.
    """
    from sqlalchemy import text, inspect
    insp = inspect(engine)
    if "immo_ledger_entry" not in insp.get_table_names():
        return
    with engine.begin() as conn:
        # retire the old konto_art-less Sollbuchung index (idempotent no-op once gone)
        conn.execute(text("DROP INDEX IF EXISTS uq_immo_ledger_soll"))
        conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_immo_ledger_soll_cat "
            "ON immo_ledger_entry(user_id, tenancy_id, konto_art, jahr, monat) "
            "WHERE typ = 'sollbuchung'"))
        conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_immo_ledger_rent "
            "ON immo_ledger_entry(source_rent_id) "
            "WHERE source_rent_id IS NOT NULL"))
