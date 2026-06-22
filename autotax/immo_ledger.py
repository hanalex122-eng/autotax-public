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

from calendar import monthrange
from datetime import date
from typing import Optional

from sqlalchemy import func

from autotax.models import ImmoLedgerEntry, ImmoProperty, ImmoUnit, ImmoTenancy, ImmoRent


def _notdel(c):
    return (c.is_deleted == False) | (c.is_deleted == None)  # noqa: E712


# ── scoping helpers — MUST match OLD _portfolio (non-deleted property →
#    non-deleted unit → tenancy/rent). A tenancy/rent under a SOFT-DELETED
#    property is an orphan and must be excluded (orphan-leak fix b03c292).
def _active_pids(db, uid: int) -> list:
    return [pid for (pid,) in db.query(ImmoProperty.id).filter(
        ImmoProperty.user_id == uid, _notdel(ImmoProperty)).all()]


def _active_units(db, uid: int, pids: list) -> dict:
    if not pids:
        return {}
    return {u.id: u for u in db.query(ImmoUnit).filter(
        ImmoUnit.user_id == uid, _notdel(ImmoUnit), ImmoUnit.property_id.in_(pids)).all()}


def _active_tenancies(db, uid: int, units: dict) -> list:
    if not units:
        return []
    return db.query(ImmoTenancy).filter(
        ImmoTenancy.user_id == uid, _notdel(ImmoTenancy),
        ImmoTenancy.unit_id.in_(list(units.keys()))).all()

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


# ══════════════════════════════════════════════════════════════════════
#  BACKFILL (Faz 1) — tenancy -> Sollbuchung, immo_rent -> ledger payment
#  Idempotent (set-difference), non-destructive (immo_rent untouched),
#  commit=False (caller owns the transaction → all-or-nothing).
# ══════════════════════════════════════════════════════════════════════
def _active_in_month(t, y, m) -> bool:
    """MUST stay identical to immo_api._tenancy_active_in_month so the Faz 3
    parity gate matches OLD vs LEDGER. von<=Monatsende und bis>=Monatsanfang."""
    mstart = date(y, m, 1)
    mend = date(y, m, monthrange(y, m)[1])
    von = t.von or date(1900, 1, 1)
    bis = t.bis or date(2999, 12, 31)
    return von <= mend and bis >= mstart


def ensure_sollbuchungen(db, uid: int, year: int, *, faellig_tag: int = 3) -> int:
    """Idempotently post one konto_art=miete Sollbuchung per ACTIVE month for
    every tenancy of the user in `year`.

    Replicates the existing engine's active-month logic EXACTLY — including the
    full-year current-year quirk (_months_active_in_year counts all 12 months,
    not capped at today) — so parity (Faz 3) matches. The quirk is preserved as
    a MIGRATION decision only; a tech-debt review follows after parity.

    Set-difference idempotent: a re-run inserts nothing (also guarded by
    uq_immo_ledger_soll_cat). Tenancies without a positive Kaltmiete are skipped
    (engine soll = months*0 = 0; a 0-Betrag entry is illegal anyway). commit=False
    — the caller commits. Returns the number of Sollbuchungen inserted.
    """
    units = _active_units(db, uid, _active_pids(db, uid))
    tenancies = _active_tenancies(db, uid, units)
    existing = set(db.query(ImmoLedgerEntry.tenancy_id, ImmoLedgerEntry.monat).filter(
        ImmoLedgerEntry.user_id == uid, ImmoLedgerEntry.jahr == year,
        ImmoLedgerEntry.typ == TYP_SOLLBUCHUNG, ImmoLedgerEntry.konto_art == "miete",
        _notdel(ImmoLedgerEntry)).all())
    inserted = 0
    for t in tenancies:
        kalt = float(t.kaltmiete or 0)
        if kalt <= 0:
            continue
        u = units.get(t.unit_id)
        pid = u.property_id if u else None
        for m in range(1, 13):
            if not _active_in_month(t, year, m):
                continue
            if (t.id, m) in existing:
                continue
            post_entry(db, user_id=uid, typ=TYP_SOLLBUCHUNG, betrag=kalt, jahr=year, monat=m,
                       property_id=pid, unit_id=t.unit_id, tenancy_id=t.id,
                       faellig_am=date(year, m, min(faellig_tag, monthrange(year, m)[1])),
                       source="auto", konto_art="miete", commit=False)
            existing.add((t.id, m))
            inserted += 1
    return inserted


def import_rents_to_ledger(db, uid: int) -> dict:
    """Idempotently import every immo_rent of the user into the ledger as a
    konto_art=miete payment. Sign-preserving so parity (ist) is exact:
        r.betrag > 0  -> zahlung    (betrag = -r.betrag)
        r.betrag < 0  -> korrektur  (betrag = -r.betrag > 0; a refund/clawback)
        r.betrag == 0 -> skipped    (illegal 0-Betrag; engine ist unaffected)
        r.datum is None -> skipped  (engine's year filter ignores undated rows;
                                     importing them would break parity)
    Set-difference on source_rent_id => a re-run imports nothing (also guarded by
    uq_immo_ledger_rent). immo_rent is NOT modified. commit=False. Returns counts.
    """
    already = set(rid for (rid,) in db.query(ImmoLedgerEntry.source_rent_id).filter(
        ImmoLedgerEntry.user_id == uid, ImmoLedgerEntry.source_rent_id != None,  # noqa: E711
        _notdel(ImmoLedgerEntry)).all())
    pids = _active_pids(db, uid)
    rents = db.query(ImmoRent).filter(
        ImmoRent.user_id == uid, _notdel(ImmoRent), ImmoRent.property_id.in_(pids)).all() if pids else []
    imported = skipped_zero = skipped_nodate = skipped_dup = 0
    for r in rents:
        if r.id in already:
            skipped_dup += 1
            continue
        if not r.datum:
            skipped_nodate += 1
            continue
        amt = round(float(r.betrag or 0), 2)
        if amt == 0:
            skipped_zero += 1
            continue
        typ = TYP_ZAHLUNG if amt > 0 else TYP_KORREKTUR
        post_entry(db, user_id=uid, typ=typ, betrag=-amt, jahr=r.datum.year, monat=r.datum.month,
                   property_id=r.property_id, tenancy_id=r.tenancy_id, buchungsdatum=r.datum,
                   source="import_rent", source_rent_id=r.id, konto_art="miete", commit=False)
        already.add(r.id)
        imported += 1
    return {"imported": imported, "skipped_zero": skipped_zero,
            "skipped_nodate": skipped_nodate, "skipped_dup": skipped_dup}


def _backfill_years(db, uid: int) -> list:
    """Year range to backfill: from the earliest tenancy.von / rent.datum up to
    the CURRENT year (an ongoing tenancy is active now, so the engine counts the
    current year → ledger must too). Scoped to non-deleted properties (OLD
    parity). Empty if the user has no active immo data."""
    pids = _active_pids(db, uid)
    if not pids:
        return []
    units = _active_units(db, uid, pids)
    yrs = set()
    for t in _active_tenancies(db, uid, units):
        if t.von:
            yrs.add(t.von.year)
    for (d,) in db.query(ImmoRent.datum).filter(
            ImmoRent.user_id == uid, _notdel(ImmoRent), ImmoRent.property_id.in_(pids)).all():
        if d:
            yrs.add(d.year)
    if not yrs:
        return []
    return list(range(min(yrs), max(max(yrs), date.today().year) + 1))


def _scope_tenancy_count(db, uid: int, years: list) -> int:
    """Distinct tenancies in scope (Kaltmiete>0 and ≥1 active month in range),
    under non-deleted properties (OLD parity). Independent of ledger/session
    state → stable in both dry-run and execute."""
    if not years:
        return 0
    tens = _active_tenancies(db, uid, _active_units(db, uid, _active_pids(db, uid)))
    cnt = 0
    for t in tens:
        if float(t.kaltmiete or 0) <= 0:
            continue
        if any(_active_in_month(t, y, m) for y in years for m in range(1, 13)):
            cnt += 1
    return cnt


def run_backfill(db, uid: int, *, dry_run: bool = True) -> dict:
    """Orchestrate the Faz 1 backfill in ONE transaction with rollback safety.

    dry_run=True  → run the same code path, count, then ROLLBACK (writes nothing).
    dry_run=False → COMMIT (idempotent: a re-run writes 0 because the engine
                    functions are set-difference + partial-unique guarded).

    Returns the exact requested shape:
        {dry_run, soll_to_create, payments_to_import, tenancies, rents}
    Touches ONLY immo_ledger_entry — no cockpit/mahnung/debtor/dashboard/risk,
    no immo_rent mutation. Any error → rollback + re-raise.
    """
    try:
        years = _backfill_years(db, uid)
        soll = sum(ensure_sollbuchungen(db, uid, y) for y in years)
        pay = import_rents_to_ledger(db, uid)
        result = {
            "dry_run": dry_run,
            "soll_to_create": soll,
            "payments_to_import": pay["imported"],
            "tenancies": _scope_tenancy_count(db, uid, years),
            "rents": pay["imported"] + pay["skipped_dup"],
        }
        if dry_run:
            db.rollback()
        else:
            db.commit()
        return result
    except Exception:
        db.rollback()
        raise


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
