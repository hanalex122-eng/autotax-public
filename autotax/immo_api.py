"""Immobilien PRO MVP — landlord module API router.

ADDITIVE & ISOLATED: brand-new router, own tables (immo_*), own prefix /immo.
Does NOT touch OCR / Vision / Parser / VAT / Kassenbuch / Rechnungen.
Every endpoint: JWT auth + user_id isolation + soft-delete.

Resources: properties, tenants, rent (payments), expenses, documents.
Plus per-property dashboard (year) and a one-click annual PDF report.
"""
from __future__ import annotations

import io
import logging
import os
import time
from calendar import monthrange
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import or_

from autotax import storage
from autotax import immo_rules as _rules
from autotax import immo_payments as _pay
from autotax import immo_ledger as _ledger
from autotax import immo_ledger_read as _read
from autotax import immo_source as _src
from autotax.auth import get_current_user

logger = logging.getLogger("autotax")
from autotax.db import SessionLocal
from autotax.models import (ImmoProperty, ImmoTenant, ImmoRent, ImmoExpense, ImmoDocument,
                            ImmoUnit, ImmoTenancy, ImmoMahnung, ImmoEvent, ImmoLedgerEntry, UserCompany)

router = APIRouter(prefix="/immo", tags=["immobilien"])

EXPENSE_KATEGORIEN = {"nebenkosten", "strom", "gas", "heizung", "reparaturen",
                      "schoenheitsrep", "garten", "versicherung", "grundsteuer",
                      "finanzierung", "sonstige"}
DOC_TYPEN = {"contract", "utility", "insurance", "tax", "repair", "other"}


# ── helpers ───────────────────────────────────────────────────────────
def _uid(user: dict) -> int:
    return int(user["sub"])


def _pdate(s):
    if not s:
        return None
    try:
        return datetime.strptime(str(s)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _own_property(db, uid: int, pid: int) -> ImmoProperty:
    p = db.query(ImmoProperty).filter(
        ImmoProperty.id == pid, ImmoProperty.user_id == uid,
        (ImmoProperty.is_deleted == False) | (ImmoProperty.is_deleted == None),  # noqa: E712
    ).first()
    if not p:
        raise HTTPException(status_code=404, detail="Immobilie nicht gefunden")
    return p


def _prop_dict(p):
    return {"id": p.id, "name": p.name, "adresse": p.adresse, "einheiten": p.einheiten,
            "kaufdatum": str(p.kaufdatum) if p.kaufdatum else "", "kaufpreis": p.kaufpreis,
            "notiz": p.notiz or ""}


def _tenant_dict(t):
    return {"id": t.id, "property_id": t.property_id, "name": t.name,
            "einzug_datum": str(t.einzug_datum) if t.einzug_datum else "",
            "auszug_datum": str(t.auszug_datum) if t.auszug_datum else "",
            "kaltmiete": t.kaltmiete, "kaution": t.kaution, "status": t.status}


def _rent_dict(r):
    return {"id": r.id, "property_id": r.property_id, "tenant_id": r.tenant_id, "tenancy_id": r.tenancy_id,
            "datum": str(r.datum) if r.datum else "", "betrag": r.betrag, "notiz": r.notiz or ""}


def _exp_dict(e):
    return {"id": e.id, "property_id": e.property_id, "datum": str(e.datum) if e.datum else "",
            "kategorie": e.kategorie, "betrag": e.betrag, "beschreibung": e.beschreibung or "",
            "document_id": e.document_id}


def _doc_dict(d):
    return {"id": d.id, "property_id": d.property_id, "typ": d.typ or "", "filename": d.filename or "",
            "uploaded_at": str(d.uploaded_at)[:19] if d.uploaded_at else ""}


# ── request models ────────────────────────────────────────────────────
class PropertyIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    adresse: Optional[str] = None
    einheiten: Optional[int] = 1
    kaufdatum: Optional[str] = None
    kaufpreis: Optional[float] = None
    notiz: Optional[str] = None


class PropertyPatch(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    adresse: Optional[str] = None
    einheiten: Optional[int] = None
    kaufdatum: Optional[str] = None
    kaufpreis: Optional[float] = None
    notiz: Optional[str] = None


class TenantIn(BaseModel):
    property_id: int
    name: str = Field(..., min_length=1, max_length=200)
    einzug_datum: Optional[str] = None
    auszug_datum: Optional[str] = None
    kaltmiete: Optional[float] = None
    kaution: Optional[float] = None
    status: Optional[str] = "active"


class TenantPatch(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    einzug_datum: Optional[str] = None
    auszug_datum: Optional[str] = None
    kaltmiete: Optional[float] = None
    kaution: Optional[float] = None
    status: Optional[str] = None


class RentIn(BaseModel):
    property_id: int
    tenant_id: Optional[int] = None
    tenancy_id: Optional[int] = None
    datum: Optional[str] = None              # Wertstellung (when the money arrived)
    betrag: float = 0.0
    notiz: Optional[str] = None
    fuer_jahr: Optional[int] = None          # WHICH rent month this settles;
    fuer_monat: Optional[int] = None         # defaults to the month of `datum`


class RentPatch(BaseModel):
    tenant_id: Optional[int] = None
    tenancy_id: Optional[int] = None
    datum: Optional[str] = None
    betrag: Optional[float] = None
    notiz: Optional[str] = None
    fuer_jahr: Optional[int] = None
    fuer_monat: Optional[int] = None


class ExpenseIn(BaseModel):
    property_id: int
    datum: Optional[str] = None
    kategorie: str = "sonstige"
    betrag: float = 0.0
    beschreibung: Optional[str] = None
    document_id: Optional[int] = None


class ExpensePatch(BaseModel):
    datum: Optional[str] = None
    kategorie: Optional[str] = None
    betrag: Optional[float] = None
    beschreibung: Optional[str] = None
    document_id: Optional[int] = None


def _mahnung_status(db, uid, tid):
    """Last Mahnung for a tenancy (stufe + datum) for the Mieter card; None if none."""
    m = db.query(ImmoMahnung).filter(ImmoMahnung.tenancy_id == tid, ImmoMahnung.user_id == uid,
                                     _notdel(ImmoMahnung)).order_by(ImmoMahnung.datum.desc(), ImmoMahnung.id.desc()).first()
    if not m:
        return None
    return {"stufe": m.stufe, "stufe_text": _STUFE_TXT.get(m.stufe, "Mahnung"),
            "datum": str(m.datum) if m.datum else None}


# ── MIETER (tenant-centric card data) ─────────────────────────────────
@router.get("/mieter")
def list_mieter(year: Optional[int] = None, user: dict = Depends(get_current_user)):
    """Tenant-centric card feed — one row per active tenancy across all properties.
    Aggregates tenancy + unit + property + derived gesamtmiete + arrears (source
    adapter → due-to-date) + this-month payment status + last payment date.
    READ-ONLY: no ledger / Soll / Ist / Rückstand / Mahnung logic touched.
    Arrears come from the OLD immo_rent path (due-to-date) so the card reflects
    quick Ödendi/Ödenmedi payments immediately (immo_rent = payment source of truth)."""
    uid = _uid(user)
    now = datetime.now(timezone.utc).date()
    y = year or now.year
    db = SessionLocal()
    try:
        units = {u.id: u for u in db.query(ImmoUnit).filter(ImmoUnit.user_id == uid, _notdel(ImmoUnit)).all()}
        props = {p.id: p for p in db.query(ImmoProperty).filter(ImmoProperty.user_id == uid, _notdel(ImmoProperty)).all()}
        # A4 belt-and-braces: even if an old row survived a pre-cascade delete, a tenancy
        # whose unit or property is gone is NOT shown (it used to appear with a blank
        # address, accrue debt and offer a Mahnung).
        tncs = [t for t in db.query(ImmoTenancy).filter(ImmoTenancy.user_id == uid, _notdel(ImmoTenancy)).all()
                if t.unit_id in units and units[t.unit_id].property_id in props]
        svc = _pay.sql_service(db)
        out = []
        for t in tncs:
            u = units.get(t.unit_id)
            p = props.get(u.property_id) if u else None
            kalt = _effective_kalt(t, now.year, now.month)   # güncel kira (Mieterhöhung sonrası)
            nk = float(t.nk_voraus or 0)
            debt = svc.open_debt(uid, t, now)                # ALL open months, ALL years
            offen = debt.total
            # last payment (immo_rent = payment source of truth)
            lp_row = db.query(ImmoRent.datum).filter(ImmoRent.tenancy_id == t.id, ImmoRent.user_id == uid,
                                                     ImmoRent.datum != None).order_by(ImmoRent.datum.desc()).first()  # noqa: E711
            last_payment = str(lp_row[0]) if lp_row and lp_row[0] else None
            # this-month status + open amount (current calendar month) — EXCEPTION ENGINE
            tm = None; tm_offen = 0.0
            if y == now.year and _tenancy_active_in_month(t, now.year, now.month):
                tm_offen = _rules.month_open(t, now.year, now.month)   # single derivation
                soll_m = _monat_soll(t, now.year, now.month)
                if tm_offen <= 0:
                    tm = "paid"
                elif tm_offen < soll_m - 0.01:
                    tm = "partial"
                else:
                    tm = "open"
            out.append({
                "tenancy_id": t.id, "mieter_name": t.mieter_name,
                "property_name": (p.name if p else None), "property_address": (p.adresse if p else None),
                "unit_name": (u.name if u else None), "wohnflaeche": (u.wohnflaeche if u else None),
                "kaltmiete": round(kalt, 2), "nk_vorauszahlung": round(nk, 2),
                "gesamtmiete": round(kalt + nk, 2),
                "einzug": str(t.von) if t.von else None, "auszug": str(t.bis) if t.bis else None,
                "offene_forderung": offen, "debtor": offen > 0,
                # every open month, oldest first — so "Bu Ay" can stop lying with
                # "✅ alles bezahlt" while March/April/last December are still unpaid
                "rueckstand_monate": [{"ym": m.ym, "offen": m.offen, "typ": m.typ} for m in debt.months],
                "this_month_status": tm, "this_month_offen": round(tm_offen, 2), "last_payment_date": last_payment,
                "telefon": getattr(t, "telefon", None), "email": getattr(t, "email", None),
                "kaution": (round(float(t.kaution), 2) if t.kaution is not None else None),
                "miete_historie": (getattr(t, "miete_historie", None) or None),
                "erstmonat_betrag": getattr(t, "erstmonat_betrag", None),
                "anmeldung_done": bool(t.anmeldung_done),
                "wgb_done": t.wgb_erstellt_am is not None,
                "wgb_erstellt_am": str(t.wgb_erstellt_am) if t.wgb_erstellt_am else None,
                "letzte_mahnung": _mahnung_status(db, uid, t.id),
            })
        out.sort(key=lambda x: (-(x["offene_forderung"] or 0), (x["mieter_name"] or "")))
        # SUMMARY — computed HERE, not in the browser. The frontend may not calculate
        # debt (CLAUDE.md → Architecture law #2/#4); it only displays these numbers.
        akt = [x for x in out if x["this_month_status"]]
        summe = {
            "aktiv": len(akt),
            "sorgenfrei": sum(1 for x in akt if not x["debtor"]),
            "schuldner": sum(1 for x in akt if x["debtor"]),
            "teilzahlung": sum(1 for x in akt if any(m["typ"] == "partial" for m in x["rueckstand_monate"])),
            "nicht_bezahlt": sum(1 for x in akt if any(m["typ"] != "partial" for m in x["rueckstand_monate"])),
            "monate_offen": sum(len(x["rueckstand_monate"]) for x in akt),
            "offen_gesamt": round(sum(x["offene_forderung"] or 0 for x in akt), 2),
        }
        return {"mieter": out, "year": y, "summe": summe}
    finally:
        db.close()


class MonatBezahltIn(BaseModel):
    jahr: int
    monat: int = Field(..., ge=1, le=12)
    datum: Optional[str] = None
    betrag: Optional[float] = None


@router.post("/tenancies/{tid}/monat-bezahlt")
def mark_monat_bezahlt(tid: int, body: MonatBezahltIn, user: dict = Depends(get_current_user)):
    """'Bezahlt / kein Problem' — Payment Service. A partial amount below the month's
    Soll is reported as a PARTIAL problem (offen = Soll − betrag)."""
    uid = _uid(user)
    db = SessionLocal()
    try:
        svc = _pay.sql_service(db)
        if body.betrag is not None:
            out = svc.mark_partial(uid, tid, body.jahr, body.monat, body.betrag)
        else:
            out = svc.mark_paid(uid, tid, body.jahr, body.monat)
        db.commit()
        return out
    except _pay.PaymentError as e:
        db.rollback()
        raise HTTPException(status_code=404 if "nicht gefunden" in str(e) else 400, detail=str(e))
    finally:
        db.close()


@router.delete("/tenancies/{tid}/monat-bezahlt")
def unmark_monat_bezahlt(tid: int, jahr: int, monat: int, user: dict = Depends(get_current_user)):
    """'Nicht bezahlt' — Payment Service: report the month as a problem (full month owed)."""
    uid = _uid(user)
    db = SessionLocal()
    try:
        out = _pay.sql_service(db).mark_unpaid(uid, tid, jahr, monat)
        db.commit()
        return out
    except _pay.PaymentError as e:
        db.rollback()
        raise HTTPException(status_code=404 if "nicht gefunden" in str(e) else 400, detail=str(e))
    finally:
        db.close()


@router.get("/tenancies/{tid}/mietkonto")
def tenancy_mietkonto(tid: int, year: Optional[int] = None, user: dict = Depends(get_current_user)):
    """Month-by-month Mietkonto for one tenancy (Tenancy Detail screen). Per month:
    soll (Kaltmiete if active), bezahlt (immo_rent in that month), status
    (paid|partial|open|future|inactive). immo_rent = payment source of truth, so it
    matches the Mieter card and reflects Ödendi/Ödenmedi instantly. READ-ONLY."""
    uid = _uid(user)
    now = datetime.now(timezone.utc).date()
    y = year or now.year
    db = SessionLocal()
    try:
        t = db.query(ImmoTenancy).filter(ImmoTenancy.id == tid, ImmoTenancy.user_id == uid, _notdel(ImmoTenancy)).first()
        if not t:
            raise HTTPException(status_code=404, detail="Mietverhältnis nicht gefunden")
        rows = []
        soll_due = 0.0
        for m in range(1, 13):
            active = _tenancy_active_in_month(t, y, m)
            soll = _monat_soll(t, y, m) if active else 0.0  # Erstmiete / anteilig / Mieterhöhung
            is_future = (y > now.year) or (y == now.year and m > now.month)
            exc = _exc_for(t, y, m)
            if not active:
                status, paid = "inactive", 0.0
            elif is_future:
                status, paid = "future", 0.0
            elif not exc:                                   # EXCEPTION ENGINE: default = OK
                status, paid = "paid", soll
            elif exc.get("typ") == "partial":
                status, paid = "partial", round(max(0.0, soll - float(exc.get("offen") or 0)), 2)
            else:
                status, paid = "open", 0.0                  # unpaid exception
            if active and not is_future:
                soll_due += soll
            rows.append({"monat": m, "soll": soll, "bezahlt": paid, "status": status})
        offen = _exception_arrears(t, y)
        ist_due = round(max(0.0, soll_due - offen), 2)
        return {"tenancy_id": tid, "year": y, "rows": rows,
                "summe": {"soll_faellig": round(soll_due, 2), "bezahlt": ist_due, "offen": offen}}
    finally:
        db.close()


# ── PROPERTIES ────────────────────────────────────────────────────────
@router.get("/properties")
def list_properties(user: dict = Depends(get_current_user)):
    db = SessionLocal()
    try:
        rows = db.query(ImmoProperty).filter(
            ImmoProperty.user_id == _uid(user),
            (ImmoProperty.is_deleted == False) | (ImmoProperty.is_deleted == None),  # noqa: E712
        ).order_by(ImmoProperty.name).all()
        return {"properties": [_prop_dict(p) for p in rows]}
    finally:
        db.close()


@router.post("/properties")
def create_property(body: PropertyIn, user: dict = Depends(get_current_user)):
    db = SessionLocal()
    try:
        p = ImmoProperty(user_id=_uid(user), name=body.name.strip(), adresse=body.adresse,
                         einheiten=body.einheiten or 1, kaufdatum=_pdate(body.kaufdatum),
                         kaufpreis=body.kaufpreis, notiz=body.notiz)
        db.add(p); db.commit(); db.refresh(p)
        return {"success": True, **_prop_dict(p)}
    finally:
        db.close()


@router.patch("/properties/{pid}")
def update_property(pid: int, body: PropertyPatch, user: dict = Depends(get_current_user)):
    db = SessionLocal()
    try:
        p = _own_property(db, _uid(user), pid)
        if body.name is not None: p.name = body.name.strip()
        if body.adresse is not None: p.adresse = body.adresse
        if body.einheiten is not None: p.einheiten = body.einheiten
        if body.kaufdatum is not None: p.kaufdatum = _pdate(body.kaufdatum)
        if body.kaufpreis is not None: p.kaufpreis = body.kaufpreis
        if body.notiz is not None: p.notiz = body.notiz
        db.commit(); db.refresh(p)
        return {"success": True, **_prop_dict(p)}
    finally:
        db.close()


def _soft_delete_tenancies(db, uid: int, tids: list) -> int:
    """A4: a tenancy cannot outlive its unit. Before, deleting a property/unit left the
    tenants alive: they kept showing up on Mieter and Bu Ay with a blank address, kept
    accruing debt and still offered a Mahnung button. Soft-delete, so nothing is lost."""
    if not tids:
        return 0
    now = datetime.now(timezone.utc)
    n = 0
    for t in db.query(ImmoTenancy).filter(ImmoTenancy.user_id == uid, ImmoTenancy.id.in_(tids),
                                          _notdel(ImmoTenancy)).all():
        t.is_deleted = True
        t.deleted_at = now
        n += 1
    return n


@router.delete("/properties/{pid}")
def delete_property(pid: int, user: dict = Depends(get_current_user)):
    """Deletes the property AND everything that hangs off it (units, tenancies) — the UI
    warns about exactly this before asking."""
    uid = _uid(user)
    db = SessionLocal()
    try:
        p = _own_property(db, uid, pid)
        p.is_deleted = True; p.deleted_at = datetime.now(timezone.utc)
        now = datetime.now(timezone.utc)
        units = db.query(ImmoUnit).filter(ImmoUnit.property_id == pid, ImmoUnit.user_id == uid,
                                          _notdel(ImmoUnit)).all()
        uids = [u.id for u in units]
        tids = [t for (t,) in db.query(ImmoTenancy.id).filter(ImmoTenancy.user_id == uid,
                                                              ImmoTenancy.unit_id.in_(uids)).all()] if uids else []
        for u in units:
            u.is_deleted = True; u.deleted_at = now
        n_ten = _soft_delete_tenancies(db, uid, tids)
        _cascade_ledger_delete(db, uid, property_id=pid)  # Faz 4.0: keep ledger scope in sync
        db.commit()
        return {"success": True, "einheiten_geloescht": len(units), "mieter_geloescht": n_ten}
    finally:
        db.close()


# ── TENANTS ───────────────────────────────────────────────────────────
@router.get("/properties/{pid}/tenants")
def list_tenants(pid: int, user: dict = Depends(get_current_user)):
    db = SessionLocal()
    try:
        _own_property(db, _uid(user), pid)
        rows = db.query(ImmoTenant).filter(
            ImmoTenant.property_id == pid, ImmoTenant.user_id == _uid(user),
            (ImmoTenant.is_deleted == False) | (ImmoTenant.is_deleted == None),  # noqa: E712
        ).order_by(ImmoTenant.status, ImmoTenant.name).all()
        return {"tenants": [_tenant_dict(t) for t in rows]}
    finally:
        db.close()


@router.post("/tenants")
def create_tenant(body: TenantIn, user: dict = Depends(get_current_user)):
    db = SessionLocal()
    try:
        _own_property(db, _uid(user), body.property_id)
        t = ImmoTenant(property_id=body.property_id, user_id=_uid(user), name=body.name.strip(),
                       einzug_datum=_pdate(body.einzug_datum), auszug_datum=_pdate(body.auszug_datum),
                       kaltmiete=body.kaltmiete, kaution=body.kaution,
                       status=(body.status if body.status in ("active", "inactive") else "active"))
        db.add(t); db.commit(); db.refresh(t)
        return {"success": True, **_tenant_dict(t)}
    finally:
        db.close()


@router.patch("/tenants/{tid}")
def update_tenant(tid: int, body: TenantPatch, user: dict = Depends(get_current_user)):
    db = SessionLocal()
    try:
        t = db.query(ImmoTenant).filter(ImmoTenant.id == tid, ImmoTenant.user_id == _uid(user)).first()
        if not t:
            raise HTTPException(status_code=404, detail="Mieter nicht gefunden")
        if body.name is not None: t.name = body.name.strip()
        if body.einzug_datum is not None: t.einzug_datum = _pdate(body.einzug_datum)
        if body.auszug_datum is not None: t.auszug_datum = _pdate(body.auszug_datum)
        if body.kaltmiete is not None: t.kaltmiete = body.kaltmiete
        if body.kaution is not None: t.kaution = body.kaution
        if body.status in ("active", "inactive"): t.status = body.status
        db.commit(); db.refresh(t)
        return {"success": True, **_tenant_dict(t)}
    finally:
        db.close()


@router.delete("/tenants/{tid}")
def delete_tenant(tid: int, user: dict = Depends(get_current_user)):
    db = SessionLocal()
    try:
        t = db.query(ImmoTenant).filter(ImmoTenant.id == tid, ImmoTenant.user_id == _uid(user)).first()
        if not t:
            raise HTTPException(status_code=404, detail="Mieter nicht gefunden")
        t.is_deleted = True; t.deleted_at = datetime.now(timezone.utc)
        db.commit()
        return {"success": True}
    finally:
        db.close()


# ── RENT PAYMENTS ─────────────────────────────────────────────────────
@router.get("/properties/{pid}/rent")
def list_rent(pid: int, year: Optional[int] = Query(None), user: dict = Depends(get_current_user)):
    db = SessionLocal()
    try:
        _own_property(db, _uid(user), pid)
        q = db.query(ImmoRent).filter(
            ImmoRent.property_id == pid, ImmoRent.user_id == _uid(user),
            (ImmoRent.is_deleted == False) | (ImmoRent.is_deleted == None),  # noqa: E712
        )
        if year:
            q = q.filter(ImmoRent.datum >= date(year, 1, 1), ImmoRent.datum <= date(year, 12, 31))
        rows = q.order_by(ImmoRent.datum.desc()).all()
        return {"rent": [_rent_dict(r) for r in rows]}
    finally:
        db.close()


@router.post("/rent")
def create_rent(body: RentIn, user: dict = Depends(get_current_user)):
    """MIETEINGANG — a door into the Payment Service, not a second book.

    Commit 2 (defect B1): this used to INSERT an immo_rent row that changed no debt
    figure — the landlord recorded a payment, got a green toast, and the Rückstand
    stayed exactly the same. Now the payment goes through the service, which reconciles
    the rent month's exception → Bu Ay, Mietkonto, Mahnung and Berichte all move.

    `fuer_jahr`/`fuer_monat` = which rent month is settled; defaults to the month of
    `datum` (so the existing UI keeps working until it gets its "Für Monat" selector).
    """
    uid = _uid(user)
    db = SessionLocal()
    try:
        _own_property(db, uid, body.property_id)
        if not body.tenancy_id:
            raise HTTPException(status_code=400, detail="Bitte den Mieter wählen (tenancy_id fehlt)")
        d = _pdate(body.datum) or date.today()
        out = _pay.sql_service(db).record_payment(
            uid, body.tenancy_id, betrag=body.betrag,
            jahr=body.fuer_jahr or d.year, monat=body.fuer_monat or d.month,
            datum=d, source="mieteingang", notiz=body.notiz, property_id=body.property_id)
        db.commit()
        return {"success": True, **out}
    except _pay.PaymentError as e:
        db.rollback()
        raise HTTPException(status_code=404 if "nicht gefunden" in str(e) else 400, detail=str(e))
    finally:
        db.close()


@router.patch("/rent/{rid}")
def update_rent(rid: int, body: RentPatch, user: dict = Depends(get_current_user)):
    """Correct a payment — through the service (law #5), so both the old and the new
    rent month are reconciled."""
    db = SessionLocal()
    try:
        d = _pdate(body.datum) if body.datum is not None else None
        out = _pay.sql_service(db).update_payment(
            _uid(user), rid, betrag=body.betrag, datum=d,
            jahr=body.fuer_jahr or (d.year if d else None),
            monat=body.fuer_monat or (d.month if d else None), notiz=body.notiz)
        db.commit()
        return {"success": True, **out}
    except _pay.PaymentError as e:
        db.rollback()
        raise HTTPException(status_code=404 if "nicht gefunden" in str(e) else 400, detail=str(e))
    finally:
        db.close()


@router.delete("/rent/{rid}")
def delete_rent(rid: int, user: dict = Depends(get_current_user)):
    """Remove a payment — through the service, so the debt it had settled comes back."""
    db = SessionLocal()
    try:
        out = _pay.sql_service(db).delete_payment(_uid(user), rid)
        db.commit()
        return {"success": True, **out}
    except _pay.PaymentError as e:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(e))
    finally:
        db.close()


# ── EXPENSES ──────────────────────────────────────────────────────────
@router.get("/properties/{pid}/expenses")
def list_expenses(pid: int, year: Optional[int] = Query(None), user: dict = Depends(get_current_user)):
    db = SessionLocal()
    try:
        _own_property(db, _uid(user), pid)
        q = db.query(ImmoExpense).filter(
            ImmoExpense.property_id == pid, ImmoExpense.user_id == _uid(user),
            (ImmoExpense.is_deleted == False) | (ImmoExpense.is_deleted == None),  # noqa: E712
        )
        if year:
            q = q.filter(ImmoExpense.datum >= date(year, 1, 1), ImmoExpense.datum <= date(year, 12, 31))
        rows = q.order_by(ImmoExpense.datum.desc()).all()
        return {"expenses": [_exp_dict(e) for e in rows]}
    finally:
        db.close()


@router.post("/expenses")
def create_expense(body: ExpenseIn, user: dict = Depends(get_current_user)):
    db = SessionLocal()
    try:
        _own_property(db, _uid(user), body.property_id)
        kat = body.kategorie if body.kategorie in EXPENSE_KATEGORIEN else "sonstige"
        e = ImmoExpense(property_id=body.property_id, user_id=_uid(user), datum=_pdate(body.datum) or date.today(),
                        kategorie=kat, betrag=body.betrag, beschreibung=body.beschreibung, document_id=body.document_id)
        db.add(e); db.commit(); db.refresh(e)
        return {"success": True, **_exp_dict(e)}
    finally:
        db.close()


@router.patch("/expenses/{eid}")
def update_expense(eid: int, body: ExpensePatch, user: dict = Depends(get_current_user)):
    db = SessionLocal()
    try:
        e = db.query(ImmoExpense).filter(ImmoExpense.id == eid, ImmoExpense.user_id == _uid(user)).first()
        if not e:
            raise HTTPException(status_code=404, detail="Ausgabe nicht gefunden")
        if body.datum is not None: e.datum = _pdate(body.datum)
        if body.kategorie is not None and body.kategorie in EXPENSE_KATEGORIEN: e.kategorie = body.kategorie
        if body.betrag is not None: e.betrag = body.betrag
        if body.beschreibung is not None: e.beschreibung = body.beschreibung
        if body.document_id is not None: e.document_id = body.document_id
        db.commit(); db.refresh(e)
        return {"success": True, **_exp_dict(e)}
    finally:
        db.close()


@router.delete("/expenses/{eid}")
def delete_expense(eid: int, user: dict = Depends(get_current_user)):
    db = SessionLocal()
    try:
        e = db.query(ImmoExpense).filter(ImmoExpense.id == eid, ImmoExpense.user_id == _uid(user)).first()
        if not e:
            raise HTTPException(status_code=404, detail="Ausgabe nicht gefunden")
        e.is_deleted = True; e.deleted_at = datetime.now(timezone.utc)
        db.commit()
        return {"success": True}
    finally:
        db.close()


# ── DOCUMENTS ─────────────────────────────────────────────────────────
@router.get("/properties/{pid}/documents")
def list_documents(pid: int, user: dict = Depends(get_current_user)):
    db = SessionLocal()
    try:
        _own_property(db, _uid(user), pid)
        rows = db.query(ImmoDocument).filter(
            ImmoDocument.property_id == pid, ImmoDocument.user_id == _uid(user),
            (ImmoDocument.is_deleted == False) | (ImmoDocument.is_deleted == None),  # noqa: E712
        ).order_by(ImmoDocument.uploaded_at.desc()).all()
        return {"documents": [_doc_dict(d) for d in rows]}
    finally:
        db.close()


@router.post("/documents")
async def upload_document(property_id: int = Form(...), typ: str = Form("other"),
                          file: UploadFile = File(...), user: dict = Depends(get_current_user)):
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Datei leer")
    db = SessionLocal()
    try:
        _own_property(db, _uid(user), property_id)
        rel = storage.save_file(_uid(user), content, file.filename)
        d = ImmoDocument(property_id=property_id, user_id=_uid(user),
                         typ=(typ if typ in DOC_TYPEN else "other"),
                         filename=file.filename or "dokument", file_path=rel,
                         file_content_type=file.content_type or "application/octet-stream")
        db.add(d); db.commit(); db.refresh(d)
        return {"success": True, **_doc_dict(d)}
    finally:
        db.close()


@router.get("/documents/{did}/download")
def download_document(did: int, user: dict = Depends(get_current_user)):
    db = SessionLocal()
    try:
        d = db.query(ImmoDocument).filter(ImmoDocument.id == did, ImmoDocument.user_id == _uid(user)).first()
        if not d or not d.file_path:
            raise HTTPException(status_code=404, detail="Dokument nicht gefunden")
        try:
            data = storage.read_file(d.file_path)
        except Exception:
            raise HTTPException(status_code=404, detail="Datei nicht gefunden")
        return StreamingResponse(io.BytesIO(data), media_type=d.file_content_type or "application/octet-stream",
                                 headers={"Content-Disposition": f'inline; filename="{d.filename or "dok"}"'})
    finally:
        db.close()


@router.delete("/documents/{did}")
def delete_document(did: int, user: dict = Depends(get_current_user)):
    db = SessionLocal()
    try:
        d = db.query(ImmoDocument).filter(ImmoDocument.id == did, ImmoDocument.user_id == _uid(user)).first()
        if not d:
            raise HTTPException(status_code=404, detail="Dokument nicht gefunden")
        d.is_deleted = True; d.deleted_at = datetime.now(timezone.utc)
        db.commit()
        return {"success": True}
    finally:
        db.close()


# ── DASHBOARD (per property, per year) ────────────────────────────────
def _year_totals(db, uid, pid, year):
    notdel = lambda col: (col.is_deleted == False) | (col.is_deleted == None)  # noqa: E731, E712
    rents = db.query(ImmoRent).filter(
        ImmoRent.property_id == pid, ImmoRent.user_id == uid, notdel(ImmoRent),
        ImmoRent.datum >= date(year, 1, 1), ImmoRent.datum <= date(year, 12, 31)).all()
    exps = db.query(ImmoExpense).filter(
        ImmoExpense.property_id == pid, ImmoExpense.user_id == uid, notdel(ImmoExpense),
        ImmoExpense.datum >= date(year, 1, 1), ImmoExpense.datum <= date(year, 12, 31)).all()
    einnahmen = round(sum(float(r.betrag or 0) for r in rents), 2)
    by_kat = {}
    for e in exps:
        by_kat[e.kategorie] = round(by_kat.get(e.kategorie, 0) + float(e.betrag or 0), 2)
    ausgaben = round(sum(by_kat.values()), 2)
    return einnahmen, ausgaben, by_kat, rents


@router.get("/properties/{pid}/dashboard")
def property_dashboard(pid: int, year: Optional[int] = Query(None), user: dict = Depends(get_current_user)):
    uid = _uid(user)
    db = SessionLocal()
    try:
        p = _own_property(db, uid, pid)
        y = year or datetime.now(timezone.utc).year
        notdel = (ImmoTenant.is_deleted == False) | (ImmoTenant.is_deleted == None)  # noqa: E712
        tenants = db.query(ImmoTenant).filter(ImmoTenant.property_id == pid, ImmoTenant.user_id == uid, notdel).all()
        aktiv = [t for t in tenants if t.status == "active"]
        belegt = len(aktiv)
        leer = max(0, (p.einheiten or 0) - belegt)
        einnahmen, ausgaben, by_kat, rents = _year_totals(db, uid, pid, y)
        # fehlende Miete: aktive Mieter × Soll-Monatsmiete vs erhaltene Miete (grob, Jahr)
        soll = round(sum(float(t.kaltmiete or 0) for t in aktiv) * 12, 2)
        fehlend = round(max(0, soll - einnahmen), 2) if soll > 0 else 0
        return {
            "property": _prop_dict(p), "year": y,
            "einheiten": p.einheiten or 0, "belegt": belegt, "leer": leer,
            "einnahmen": einnahmen, "ausgaben": ausgaben, "gewinn": round(einnahmen - ausgaben, 2),
            "ausgaben_by_kategorie": by_kat,
            "soll_miete_jahr": soll, "fehlende_miete": fehlend,
        }
    finally:
        db.close()


# ── ANNUAL PDF REPORT ─────────────────────────────────────────────────
@router.get("/properties/{pid}/report/pdf")
def property_report_pdf(pid: int, year: Optional[int] = Query(None), user: dict = Depends(get_current_user)):
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet
    uid = _uid(user)
    db = SessionLocal()
    try:
        p = _own_property(db, uid, pid)
        y = year or datetime.now(timezone.utc).year
        einnahmen, ausgaben, by_kat, rents = _year_totals(db, uid, pid, y)
        notdel = (ImmoExpense.is_deleted == False) | (ImmoExpense.is_deleted == None)  # noqa: E712
        exps = db.query(ImmoExpense).filter(
            ImmoExpense.property_id == pid, ImmoExpense.user_id == uid, notdel,
            ImmoExpense.datum >= date(y, 1, 1), ImmoExpense.datum <= date(y, 12, 31)).order_by(ImmoExpense.datum).all()
        ss = getSampleStyleSheet(); title = ss["Title"]; title.fontSize = 15; h = ss["Heading2"]
        buf = io.BytesIO()
        doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=14 * mm, bottomMargin=14 * mm, leftMargin=14 * mm, rightMargin=14 * mm)
        el = [Paragraph(f"Immobilie: {p.name}", title),
              Paragraph(f"{p.adresse or ''} — Jahresbericht {y}", ss["Normal"]), Spacer(1, 8 * mm)]
        # Summary
        summ = [["", str(y)], ["Einnahmen (Miete)", f"{einnahmen:.2f} EUR"],
                ["Ausgaben gesamt", f"{ausgaben:.2f} EUR"], ["GEWINN / VERLUST", f"{einnahmen - ausgaben:.2f} EUR"]]
        ts = Table(summ, colWidths=[80 * mm, 60 * mm])
        ts.setStyle(TableStyle([("FONTSIZE", (0, 0), (-1, -1), 11), ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
                                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e293b")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                                ("FONTNAME", (0, 3), (-1, 3), "Helvetica-Bold"), ("BACKGROUND", (0, 3), (-1, 3), colors.HexColor("#e2e8f0"))]))
        el += [ts, Spacer(1, 6 * mm), Paragraph("Ausgaben nach Kategorie", h)]
        if by_kat:
            kt = [["Kategorie", "Betrag"]] + [[k, f"{v:.2f} EUR"] for k, v in sorted(by_kat.items())]
            t2 = Table(kt, colWidths=[80 * mm, 60 * mm])
            t2.setStyle(TableStyle([("FONTSIZE", (0, 0), (-1, -1), 10), ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
                                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e2e8f0"))]))
            el.append(t2)
        el += [Spacer(1, 6 * mm), Paragraph("Ausgaben — Einzelbelege", h)]
        det = [["Datum", "Kategorie", "Beschreibung", "Betrag"]]
        for e in exps:
            det.append([str(e.datum) if e.datum else "", e.kategorie, (e.beschreibung or "")[:50], f"{float(e.betrag or 0):.2f}"])
        t3 = Table(det, colWidths=[24 * mm, 30 * mm, 80 * mm, 26 * mm], repeatRows=1)
        t3.setStyle(TableStyle([("FONTSIZE", (0, 0), (-1, -1), 9), ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
                                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e293b")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white)]))
        el.append(t3)
        doc.build(el)
        buf.seek(0)
        return StreamingResponse(buf, media_type="application/pdf",
                                 headers={"Content-Disposition": f'attachment; filename="immobilie_{pid}_{y}.pdf"'})
    finally:
        db.close()


# ══════════════════════════════════════════════════════════════════════
#  PRO ACCOUNTING ENGINE — units + tenancies (period-based, per-tenant)
# ══════════════════════════════════════════════════════════════════════
def _notdel(c):
    return (c.is_deleted == False) | (c.is_deleted == None)  # noqa: E712


def _own_unit(db, uid, uid_):
    u = db.query(ImmoUnit).filter(ImmoUnit.id == uid_, ImmoUnit.user_id == uid, _notdel(ImmoUnit)).first()
    if not u:
        raise HTTPException(status_code=404, detail="Einheit nicht gefunden")
    return u


def _unit_dict(u):
    return {"id": u.id, "property_id": u.property_id, "name": u.name or "", "wohnflaeche": u.wohnflaeche,
            "soll_miete": u.soll_miete}


def _tenancy_dict(t):
    return {"id": t.id, "unit_id": t.unit_id, "mieter_name": t.mieter_name,
            "von": str(t.von) if t.von else "", "bis": str(t.bis) if t.bis else "",
            "kaltmiete": t.kaltmiete, "kaution": t.kaution, "nk_voraus": t.nk_voraus,
            "anmeldung_done": bool(getattr(t, "anmeldung_done", False)),
            "wgb_erstellt_am": str(t.wgb_erstellt_am) if getattr(t, "wgb_erstellt_am", None) else None,
            "telefon": getattr(t, "telefon", None), "email": getattr(t, "email", None),
            "notiz": getattr(t, "notiz", None), "erstmonat_betrag": getattr(t, "erstmonat_betrag", None)}


# Month math lives in autotax/immo_rules.py (pure, DB-free) so that the API layer and
# the Payment Service share ONE formula — see CLAUDE.md → Architecture law. These names
# are kept as aliases; behaviour is identical.
_tenancy_active_in_month = _rules.tenancy_active_in_month
_months_active_in_year = _rules.months_active_in_year
_month_proration = _rules.month_proration


# "Today"-dependent helpers stay thin wrappers so that `immo_api.date` remains the one
# clock the API layer reads (the test-suite pins it: immo_api.date = FakeDate).
def _months_due_to_date(t, y, as_of=None):
    return _rules.months_due_to_date(t, y, as_of or date.today())


_effective_kalt = _rules.effective_kalt
_monat_soll = _rules.monat_soll


def _soll_faellig(t, y, as_of=None):
    return _rules.soll_faellig(t, y, as_of or date.today())


class UnitIn(BaseModel):
    property_id: int
    name: Optional[str] = None
    wohnflaeche: Optional[float] = None
    soll_miete: Optional[float] = None


class UnitPatch(BaseModel):
    name: Optional[str] = None
    wohnflaeche: Optional[float] = None
    soll_miete: Optional[float] = None


class TenancyIn(BaseModel):
    unit_id: int
    mieter_name: str = Field(..., min_length=1, max_length=200)
    von: Optional[str] = None
    bis: Optional[str] = None
    kaltmiete: Optional[float] = None
    kaution: Optional[float] = None
    nk_voraus: Optional[float] = None


class TenancyPatch(BaseModel):
    mieter_name: Optional[str] = Field(None, min_length=1, max_length=200)
    von: Optional[str] = None
    bis: Optional[str] = None
    kaltmiete: Optional[float] = None
    kaution: Optional[float] = None
    nk_voraus: Optional[float] = None
    anmeldung_done: Optional[bool] = None
    telefon: Optional[str] = Field(None, max_length=50)
    email: Optional[str] = Field(None, max_length=200)
    notiz: Optional[str] = None
    erstmonat_betrag: Optional[float] = None    # vereinbarte Erstmiete; -1 = löschen (zurück zu Tagesanteil)


# ── UNITS ─────────────────────────────────────────────────────────────
@router.get("/properties/{pid}/units")
def list_units(pid: int, user: dict = Depends(get_current_user)):
    db = SessionLocal()
    try:
        _own_property(db, _uid(user), pid)
        rows = db.query(ImmoUnit).filter(ImmoUnit.property_id == pid, ImmoUnit.user_id == _uid(user),
                                         _notdel(ImmoUnit)).order_by(ImmoUnit.id).all()
        return {"units": [_unit_dict(u) for u in rows]}
    finally:
        db.close()


@router.post("/units")
def create_unit(body: UnitIn, user: dict = Depends(get_current_user)):
    db = SessionLocal()
    try:
        _own_property(db, _uid(user), body.property_id)
        u = ImmoUnit(property_id=body.property_id, user_id=_uid(user), name=body.name,
                     wohnflaeche=body.wohnflaeche, soll_miete=body.soll_miete)
        db.add(u); db.commit(); db.refresh(u)
        return {"success": True, **_unit_dict(u)}
    finally:
        db.close()


@router.patch("/units/{uid_}")
def update_unit(uid_: int, body: UnitPatch, user: dict = Depends(get_current_user)):
    db = SessionLocal()
    try:
        u = _own_unit(db, _uid(user), uid_)
        if body.name is not None: u.name = body.name
        if body.wohnflaeche is not None: u.wohnflaeche = body.wohnflaeche
        if body.soll_miete is not None: u.soll_miete = body.soll_miete
        db.commit(); db.refresh(u)
        return {"success": True, **_unit_dict(u)}
    finally:
        db.close()


@router.delete("/units/{uid_}")
def delete_unit(uid_: int, user: dict = Depends(get_current_user)):
    """Deletes the unit AND its tenancies (A4 — no orphaned tenants)."""
    uid = _uid(user)
    db = SessionLocal()
    try:
        u = _own_unit(db, uid, uid_)
        u.is_deleted = True; u.deleted_at = datetime.now(timezone.utc)
        _tids = [t for (t,) in db.query(ImmoTenancy.id).filter(ImmoTenancy.unit_id == uid_).all()]
        n_ten = _soft_delete_tenancies(db, uid, _tids)
        _cascade_ledger_delete(db, uid, unit_id=uid_, tenancy_ids=_tids)  # Faz 4.0: incl. payments (no unit_id)
        db.commit()
        return {"success": True, "mieter_geloescht": n_ten}
    finally:
        db.close()


# ── TENANCIES (Mietverhältnisse) ──────────────────────────────────────
@router.get("/units/{uid_}/tenancies")
def list_tenancies(uid_: int, user: dict = Depends(get_current_user)):
    db = SessionLocal()
    try:
        _own_unit(db, _uid(user), uid_)
        rows = db.query(ImmoTenancy).filter(ImmoTenancy.unit_id == uid_, ImmoTenancy.user_id == _uid(user),
                                            _notdel(ImmoTenancy)).order_by(ImmoTenancy.von).all()
        return {"tenancies": [_tenancy_dict(t) for t in rows]}
    finally:
        db.close()


@router.post("/tenancies")
def create_tenancy(body: TenancyIn, user: dict = Depends(get_current_user)):
    db = SessionLocal()
    try:
        _own_unit(db, _uid(user), body.unit_id)
        t = ImmoTenancy(unit_id=body.unit_id, user_id=_uid(user), mieter_name=body.mieter_name.strip(),
                        von=_pdate(body.von), bis=_pdate(body.bis), kaltmiete=body.kaltmiete,
                        kaution=body.kaution, nk_voraus=body.nk_voraus)
        db.add(t); db.commit(); db.refresh(t)
        return {"success": True, **_tenancy_dict(t)}
    finally:
        db.close()


@router.patch("/tenancies/{tid}")
def update_tenancy(tid: int, body: TenancyPatch, user: dict = Depends(get_current_user)):
    db = SessionLocal()
    try:
        t = db.query(ImmoTenancy).filter(ImmoTenancy.id == tid, ImmoTenancy.user_id == _uid(user)).first()
        if not t:
            raise HTTPException(status_code=404, detail="Mietverhältnis nicht gefunden")
        if body.mieter_name is not None: t.mieter_name = body.mieter_name.strip()
        if body.von is not None: t.von = _pdate(body.von)
        if body.bis is not None: t.bis = _pdate(body.bis)
        if body.kaltmiete is not None: t.kaltmiete = body.kaltmiete
        if body.kaution is not None: t.kaution = body.kaution
        if body.nk_voraus is not None: t.nk_voraus = body.nk_voraus
        if body.anmeldung_done is not None: t.anmeldung_done = body.anmeldung_done
        if body.telefon is not None: t.telefon = body.telefon.strip() or None
        if body.email is not None: t.email = body.email.strip() or None
        if body.notiz is not None: t.notiz = body.notiz
        if body.erstmonat_betrag is not None:
            t.erstmonat_betrag = None if body.erstmonat_betrag < 0 else body.erstmonat_betrag
        db.commit(); db.refresh(t)
        return {"success": True, **_tenancy_dict(t)}
    finally:
        db.close()


class MieterhoehungIn(BaseModel):
    ab: str                      # ab-Datum, z.B. "2026-07-01"
    kalt: float                  # neue Kaltmiete


@router.post("/tenancies/{tid}/mieterhoehung")
def add_mieterhoehung(tid: int, body: MieterhoehungIn, user: dict = Depends(get_current_user)):
    """Dated rent change (Mieterhöhung): append {ab, kalt} to miete_historie. Past
    months keep the old rent; from `ab`'s month the new rent applies (Soll per month
    via _effective_kalt). Does NOT change t.kaltmiete (= initial rent)."""
    import json
    uid = _uid(user)
    db = SessionLocal()
    try:
        t = db.query(ImmoTenancy).filter(ImmoTenancy.id == tid, ImmoTenancy.user_id == uid, _notdel(ImmoTenancy)).first()
        if not t:
            raise HTTPException(status_code=404, detail="Mietverhältnis nicht gefunden")
        d = _pdate(body.ab)
        if not d:
            raise HTTPException(status_code=400, detail="Ungültiges ab-Datum (JJJJ-MM-TT)")
        if not body.kalt or body.kalt <= 0:
            raise HTTPException(status_code=400, detail="Neue Kaltmiete muss > 0 sein")
        try:
            hist = json.loads(t.miete_historie) if t.miete_historie else []
        except Exception:
            hist = []
        hist = [c for c in hist if str(c.get("ab", ""))[:10] != str(d)]  # gleiche ab-Datum überschreiben
        hist.append({"ab": str(d), "kalt": round(float(body.kalt), 2)})
        hist.sort(key=lambda c: str(c.get("ab", "")))
        t.miete_historie = json.dumps(hist)
        db.commit()
        return {"success": True, "miete_historie": hist}
    finally:
        db.close()


@router.delete("/tenancies/{tid}")
def delete_tenancy(tid: int, user: dict = Depends(get_current_user)):
    db = SessionLocal()
    try:
        t = db.query(ImmoTenancy).filter(ImmoTenancy.id == tid, ImmoTenancy.user_id == _uid(user)).first()
        if not t:
            raise HTTPException(status_code=404, detail="Mietverhältnis nicht gefunden")
        t.is_deleted = True; t.deleted_at = datetime.now(timezone.utc)
        _cascade_ledger_delete(db, _uid(user), tenancy_id=tid)  # Faz 4.0: keep ledger scope in sync
        db.commit()
        return {"success": True}
    finally:
        db.close()


# ── THE ENGINE: period-based accounting per property/year ──────────────
def _accounting(db, uid, pid, year):
    p = db.query(ImmoProperty).filter(ImmoProperty.id == pid, ImmoProperty.user_id == uid).first()
    units = db.query(ImmoUnit).filter(ImmoUnit.property_id == pid, ImmoUnit.user_id == uid,
                                      _notdel(ImmoUnit)).order_by(ImmoUnit.id).all()
    uids = [u.id for u in units]
    if uids:
        tenancies = db.query(ImmoTenancy).filter(ImmoTenancy.user_id == uid, _notdel(ImmoTenancy),
                                                 ImmoTenancy.unit_id.in_(uids)).all()
    else:
        tenancies = []
    # Income is DERIVED (Soll − offen), never summed from payment rows — see immo_rules.
    unit_results = []
    tenancy_results = []
    total_soll = total_occ = total_vac = total_leer = 0.0
    for u in units:
        u_ten = [t for t in tenancies if t.unit_id == u.id]
        occ = vac = 0
        soll_u = 0.0
        for m in range(1, 13):
            act = [t for t in u_ten if _tenancy_active_in_month(t, year, m)]
            if act:
                occ += 1
                soll_u += _monat_soll(act[0], year, m)   # Warmmiete, anteilig — same Soll as the debt
            else:
                vac += 1
        leer = vac * float(u.soll_miete or 0)
        unit_results.append({"unit_id": u.id, "name": u.name or ("Whg " + str(u.id)),
                             "soll_miete": u.soll_miete, "occupied_months": occ, "vacant_months": vac,
                             "belegungsquote": round(occ / 12 * 100, 1), "soll": round(soll_u, 2),
                             "leerstandsverlust": round(leer, 2)})
        total_soll += soll_u; total_occ += occ; total_vac += vac; total_leer += leer
        for t in u_ten:
            ma = _months_due_to_date(t, year)
            soll_t = _soll_faellig(t, year)                 # Warmmiete, anteilig (Teilmonat pro-rata)
            rueck_t = _exception_arrears(t, year)           # this YEAR's open months (year report)
            ist_t = _rules.year_ist(t, year, date.today())  # derived: Soll − offen, month by month
            tenancy_results.append({"tenancy_id": t.id, "unit_id": u.id, "mieter_name": t.mieter_name,
                                    "von": str(t.von) if t.von else "", "bis": str(t.bis) if t.bis else "",
                                    "kaltmiete": t.kaltmiete, "monate": ma, "soll": round(soll_t, 2),
                                    "ist": ist_t, "rueckstand": round(rueck_t, 2),
                                    "kaution": t.kaution})
    exps = db.query(ImmoExpense).filter(ImmoExpense.property_id == pid, ImmoExpense.user_id == uid, _notdel(ImmoExpense),
                                        ImmoExpense.datum >= date(year, 1, 1), ImmoExpense.datum <= date(year, 12, 31)).all()
    by_kat = {}
    for e in exps:
        by_kat[e.kategorie] = round(by_kat.get(e.kategorie, 0) + float(e.betrag or 0), 2)
    ausgaben = round(sum(by_kat.values()), 2)
    soll_sum = round(sum(t["soll"] for t in tenancy_results), 2)
    ist_sum = round(sum(t["ist"] for t in tenancy_results), 2)
    ist_total = ist_sum                                     # EXCEPTION ENGINE: erhalten = Soll − Ausnahmen
    zahlungsausfall = round(sum(t["rueckstand"] for t in tenancy_results), 2)  # = gemeldete Ausnahmen
    gewinn = round(ist_total - ausgaben, 2)
    rendite = round(gewinn / float(p.kaufpreis) * 100, 2) if (p and p.kaufpreis) else None
    total_unit_months = (len(units) * 12) or 1
    return {
        "year": year, "property": _prop_dict(p) if p else None,
        "summe": {"soll_miete": round(total_soll, 2), "ist_miete": round(ist_total, 2),
                  "leerstandsverlust": round(total_leer, 2), "zahlungsausfall": zahlungsausfall,
                  "ausgaben": ausgaben, "gewinn": gewinn, "rendite_prozent": rendite,
                  "belegungsquote": round(total_occ / total_unit_months * 100, 1),
                  "leerstand_monate": int(total_vac), "einheiten": len(units)},
        "ausgaben_by_kategorie": by_kat, "units": unit_results, "tenancies": tenancy_results,
    }


@router.get("/properties/{pid}/accounting")
def property_accounting(pid: int, year: Optional[int] = Query(None), user: dict = Depends(get_current_user)):
    db = SessionLocal()
    try:
        _own_property(db, _uid(user), pid)
        y = year or datetime.now(timezone.utc).year
        return _accounting(db, _uid(user), pid, y)
    finally:
        db.close()


# ══════════════════════════════════════════════════════════════════════
#  EXECUTIVE DASHBOARD — portfolio-wide KPIs (all properties, one year)
# ══════════════════════════════════════════════════════════════════════
def _portfolio(db, uid, year):
    today = date.today()
    ref_month = today.month if year == today.year else 12
    props = db.query(ImmoProperty).filter(ImmoProperty.user_id == uid, _notdel(ImmoProperty)).all()
    pids = [p.id for p in props]
    prop_name = {p.id: p.name for p in props}
    kaufpreis_total = sum(float(p.kaufpreis or 0) for p in props)
    units = db.query(ImmoUnit).filter(ImmoUnit.user_id == uid, _notdel(ImmoUnit),
                                      ImmoUnit.property_id.in_(pids)).all() if pids else []
    uids = [u.id for u in units]
    tenancies = db.query(ImmoTenancy).filter(ImmoTenancy.user_id == uid, _notdel(ImmoTenancy),
                                             ImmoTenancy.unit_id.in_(uids)).all() if uids else []
    exps = db.query(ImmoExpense).filter(ImmoExpense.user_id == uid, _notdel(ImmoExpense), ImmoExpense.property_id.in_(pids),
                                        ImmoExpense.datum >= date(year, 1, 1), ImmoExpense.datum <= date(year, 12, 31)).all() if pids else []
    ten_by_unit = {}
    for t in tenancies:
        ten_by_unit.setdefault(t.unit_id, []).append(t)
    unit_by_id = {u.id: u for u in units}
    # Monthly income — DERIVED from the exception engine (Soll − offen), NOT summed from
    # immo_rent rows. Commit 2 (defect B2): the old sum was structurally always 0 under
    # the exception model, which made Gewinn negative, the income chart a flat zero line
    # and the "inkasso" score red, while the same page's detail list showed real profits.
    monthly_income = [0.0] * 12
    monthly_expenses = [0.0] * 12
    ist_by_ten = {}
    for t in tenancies:
        for m in range(1, 13):
            im = _rules.month_ist(t, year, m, today)
            if im:
                monthly_income[m - 1] += im
                ist_by_ten[t.id] = round(ist_by_ten.get(t.id, 0) + im, 2)
    monthly_income = [round(x, 2) for x in monthly_income]
    ist_total = round(sum(monthly_income), 2)
    expense_by_cat = {}
    for e in exps:
        if e.datum:
            monthly_expenses[e.datum.month - 1] += float(e.betrag or 0)
        expense_by_cat[e.kategorie] = round(expense_by_cat.get(e.kategorie, 0) + float(e.betrag or 0), 2)
    ausgaben_total = round(sum(monthly_expenses), 2)
    # per unit: occupancy, vacancy, soll
    vacancy_trend = [0] * 12
    occupied_now = 0
    soll_total = leer_total = 0.0
    top_vacancies = []
    for u in units:
        ut = ten_by_unit.get(u.id, [])
        vac_months = 0
        for m in range(1, 13):
            act = [t for t in ut if _tenancy_active_in_month(t, year, m)]
            if act:
                soll_total += _monat_soll(act[0], year, m)   # same Soll the debt uses
            else:
                vac_months += 1
                vacancy_trend[m - 1] += 1
        ref_act = [t for t in ut if _tenancy_active_in_month(t, year, ref_month)]
        if ref_act:
            occupied_now += 1
        loss = vac_months * float(u.soll_miete or 0)
        leer_total += loss
        if not ref_act and vac_months > 0:
            last_bis = max([t.bis for t in ut if t.bis], default=None)
            top_vacancies.append({"unit": u.name or ("Whg " + str(u.id)), "property": prop_name.get(u.property_id, ""),
                                  "empty_since": str(last_bis) if last_bis else "", "loss": round(loss, 2)})
    vacant_now = len(units) - occupied_now
    # debtors
    top_debtors = []
    ausfall_total = 0.0
    svc = _pay.sql_service(db)
    for t in tenancies:
        d = svc.open_debt(uid, t, today)          # the SAME number Bu Ay and the Mahnung show
        arr = d.total
        if arr > 0:
            ausfall_total += arr
            top_debtors.append({"tenant": t.mieter_name, "debt": arr,
                                "months_overdue": len(d.months),
                                "monate": [m.ym for m in d.months]})
    ausfall_total = round(ausfall_total, 2)
    # contracts ending within 60 days
    contracts_ending = []
    for t in tenancies:
        if t.bis and today <= t.bis <= today + timedelta(days=60):
            uu = unit_by_id.get(t.unit_id)
            contracts_ending.append({"tenant": t.mieter_name, "unit": (uu.name if uu else ""), "bis": str(t.bis)})
    soll_total = round(soll_total, 2)
    leer_total = round(leer_total, 2)
    gewinn = round(ist_total - ausgaben_total, 2)
    rendite = round(gewinn / kaufpreis_total * 100, 2) if kaufpreis_total else None
    occ_rate = round(occupied_now / len(units) * 100, 1) if units else 0
    top_vacancies.sort(key=lambda x: -x["loss"])
    top_debtors.sort(key=lambda x: -x["debt"])
    return {
        "year": year,
        "portfolio": {"properties": len(props), "units": len(units), "occupied": occupied_now,
                      "vacant": vacant_now, "occupancy_rate": occ_rate},
        "financial": {"soll": soll_total, "ist": ist_total, "leerstandsverlust": leer_total,
                      "rueckstand": ausfall_total, "ausgaben": ausgaben_total, "gewinn": gewinn, "rendite": rendite},
        "warnings": {"vacant_units": vacant_now, "debtors": len(top_debtors), "contracts_ending": len(contracts_ending)},
        "top_vacancies": top_vacancies[:5],
        "top_debtors": top_debtors[:5],
        "top_expenses": dict(sorted(expense_by_cat.items(), key=lambda x: -x[1])[:6]),
        "charts": {"monthly_income": [round(x, 2) for x in monthly_income],
                   "monthly_expenses": [round(x, 2) for x in monthly_expenses],
                   "vacancy_trend": vacancy_trend, "expense_by_cat": expense_by_cat},
        "contracts_ending": contracts_ending,
    }


# ── Faz 4.2: consumer-facing portfolio view (flag-gated debt source) ──
def _lazy_ledger_refresh(db, uid: int, year: int) -> dict:
    """Flag-ON only: bring the ledger current (idempotent backfill) before a read.
    Replaces dual-write for now. On ANY error → rollback + status='fallback' so the
    caller serves OLD numbers. Logs cost on every call (per-GET visibility)."""
    t0 = time.monotonic()
    try:
        res = _ledger.run_backfill(db, uid, dry_run=False)
        created = int(res.get("soll_to_create", 0)) + int(res.get("payments_to_import", 0))
        out = {"ledger_refresh_ms": round((time.monotonic() - t0) * 1000, 1),
               "ledger_created_entries": created, "ledger_refresh_status": "ok"}
    except Exception as e:
        db.rollback()
        out = {"ledger_refresh_ms": round((time.monotonic() - t0) * 1000, 1),
               "ledger_created_entries": 0, "ledger_refresh_status": "fallback"}
        logger.warning("immo ledger refresh failed (OLD fallback) uid=%s year=%s: %s", uid, year, e)
    logger.info("ledger_refresh_ms=%s ledger_created_entries=%s ledger_refresh_status=%s",
                out["ledger_refresh_ms"], out["ledger_created_entries"], out["ledger_refresh_status"])
    return out


def portfolio_view(db, uid: int, year: int) -> dict:
    """THE portfolio view. Debt comes from the Exception Engine — like everywhere else.

    HOTFIX (Sprint 0 smoke test, 2026-07-14): this function used to OVERWRITE the debt
    fields (rueckstand / top_debtors / warnings.debtors) with numbers read from the
    immo_ledger whenever IMMO_LEDGER_READ was on — and that flag IS on in production.
    The ledger computes a Kalt-only Soll and knows nothing about the exception engine, so
    Berichte showed a landlord "2.800 €" (7 months × Kaltmiete 400) while his Mieter card,
    Bu Ay and the Mahnung all said "940 €" (2 reported months × Warmmiete 470). A third
    book, live, contradicting the other two.

    That override is GONE. The ledger stays a shadow/audit domain (/immo/_ledger/*), it is
    never a debt source for a user-facing screen. No environment variable can resurrect it.
    See CLAUDE.md → "Architecture law": debt is derived ONLY from the Exception Engine.
    """
    return _portfolio(db, uid, year)


@router.get("/dashboard")
def immo_dashboard(year: Optional[int] = Query(None), user: dict = Depends(get_current_user)):
    db = SessionLocal()
    try:
        return portfolio_view(db, _uid(user), year or datetime.now(timezone.utc).year)
    finally:
        db.close()


# ══════════════════════════════════════════════════════════════════════
#  COCKPIT — decision-support layer (score, actions, ranking, risk).
#  Pure derivation on top of the engine; NO accounting formula changes.
# ══════════════════════════════════════════════════════════════════════
_MON_DE = ["", "Jan", "Feb", "März", "Apr", "Mai", "Juni", "Juli", "Aug", "Sep", "Okt", "Nov", "Dez"]


def _risk_from_months(m):
    m = m or 0
    return "high" if m >= 2 else ("mid" if m >= 1 else "low")


def _days_since(s, today):
    if not s:
        return None
    try:
        return (today - datetime.strptime(s, "%Y-%m-%d").date()).days
    except ValueError:
        return None


def _cockpit(db, uid, year, base=None):
    # base injectable so the consumer path (Faz 4.2) can feed a ledger-sourced
    # portfolio_view, while parity keeps calling _cockpit() → pure OLD _portfolio.
    if base is None:
        base = _portfolio(db, uid, year)
    P, F = base["portfolio"], base["financial"]
    today = date.today()
    soll = F["soll"] or 0
    # ── Portfolio score (0-100) — derived from existing engine numbers ──
    belegung = P["occupancy_rate"]
    inkasso = min(100.0, (F["ist"] / soll * 100) if soll else 100.0)
    leer_den = soll + F["leerstandsverlust"]
    leerstand_sc = 100.0 - min(100.0, (F["leerstandsverlust"] / leer_den * 100) if leer_den else 0.0)
    schulden_sc = 100.0 - min(100.0, (F["rueckstand"] / soll * 100) if soll else 0.0)
    rend = F["rendite"]
    rendite_sc = 50.0 if rend is None else min(100.0, max(0.0, rend * 15))
    total = round(0.30 * belegung + 0.25 * inkasso + 0.15 * leerstand_sc + 0.10 * schulden_sc + 0.20 * rendite_sc)
    score = {"total": total, "color": "green" if total >= 80 else ("orange" if total >= 60 else "red"),
             "components": {"belegung": round(belegung), "inkasso": round(inkasso), "leerstand": round(leerstand_sc),
                            "schulden": round(schulden_sc), "rendite": round(rendite_sc)}}
    # ── Vacancy enriched (days + risk) ──
    vacancy = []
    for v in base["top_vacancies"]:
        dv = _days_since(v.get("empty_since"), today)
        risk = "high" if ((dv or 0) >= 60 or v["loss"] >= 3000) else ("mid" if (dv or 0) >= 20 else "low")
        vacancy.append({**v, "days_vacant": dv, "risk": risk})
    # ── Tenant risk ──
    tenant_risk = [{**d, "risk": _risk_from_months(d.get("months_overdue"))} for d in base["top_debtors"]]
    # ── Property ranking + trend (year vs year-1) ──
    props = db.query(ImmoProperty).filter(ImmoProperty.user_id == uid, _notdel(ImmoProperty)).all()
    ranking = []
    gewinn_items = []
    for p in props:
        a = _accounting(db, uid, p.id, year)["summe"]
        a0 = _accounting(db, uid, p.id, year - 1)["summe"]
        g, g0 = a["gewinn"], a0["gewinn"]
        trend = "up" if g > g0 + 1 else ("down" if g < g0 - 1 else "flat")
        col = "green" if (g > 0 and a["belegungsquote"] >= 80) else ("red" if (a["belegungsquote"] < 60 or g < 0) else "orange")
        ranking.append({"property_id": p.id, "name": p.name, "gewinn": g, "trend": trend,
                        "color": col, "belegung": a["belegungsquote"]})
        gewinn_items.append({"name": p.name, "value": g})
    ranking.sort(key=lambda x: -x["gewinn"])
    gewinn_items.sort(key=lambda x: -x["value"])
    # ── Actions (Heute wichtig) ──
    actions = []
    for v in vacancy:
        actions.append({"severity": "red" if v["risk"] == "high" else "orange", "typ": "vacancy",
                        "text": "%s · %s Tage leer · −%.0f€" % (v["unit"], v["days_vacant"] if v["days_vacant"] is not None else "?", v["loss"]),
                        "unit": v["unit"], "property": v.get("property", "")})
    for d in tenant_risk:
        actions.append({"severity": "red" if d["risk"] == "high" else "orange", "typ": "debt",
                        "text": "%s schuldet %.0f€ · %s Mon" % (d["tenant"], d["debt"], d.get("months_overdue") if d.get("months_overdue") is not None else "?"),
                        "tenant": d["tenant"]})
    for c in base["contracts_ending"]:
        dleft = None
        try:
            dleft = (datetime.strptime(c["bis"], "%Y-%m-%d").date() - today).days
        except ValueError:
            pass
        actions.append({"severity": "orange", "typ": "contract_ending",
                        "text": "Vertrag %s (%s) endet in %s Tagen" % (c.get("unit", ""), c["tenant"], dleft if dleft is not None else "?"),
                        "tenant": c["tenant"]})
    # Rent missing THIS month — from the exception engine, not from "no immo_rent row".
    # Commit 2 (defect B2): the old check fired for EVERY active tenant every month
    # (the exception model creates no payment rows), so the cockpit permanently warned
    # "Miete Jun fehlt · Ahmet" about tenants that Bu Ay showed as ✓ sorgenfrei.
    if year == today.year:
        cm = today.month
        pids = [p.id for p in props]
        units = db.query(ImmoUnit).filter(ImmoUnit.user_id == uid, _notdel(ImmoUnit), ImmoUnit.property_id.in_(pids)).all() if pids else []
        uids2 = [u.id for u in units]
        tens = db.query(ImmoTenancy).filter(ImmoTenancy.user_id == uid, _notdel(ImmoTenancy), ImmoTenancy.unit_id.in_(uids2)).all() if uids2 else []
        for t in tens:
            if _rules.month_open(t, year, cm) > 0:
                actions.append({"severity": "orange", "typ": "missing_rent",
                                "text": "Miete %s fehlt · %s" % (_MON_DE[cm], t.mieter_name), "tenant": t.mieter_name})
    actions.sort(key=lambda a: 0 if a["severity"] == "red" else 1)
    kpi = {
        "gewinn": {"total": F["gewinn"], "items": gewinn_items},
        "leerstand": {"total": F["leerstandsverlust"], "items": vacancy},
        "rueckstand": {"total": F["rueckstand"], "items": tenant_risk},
        "belegung": {"occupied": P["occupied"], "vacant": P["vacant"], "rate": P["occupancy_rate"]},
    }
    # timeline: contracts ending + manual events, next 90 days
    timeline = []
    for c in base["contracts_ending"]:
        dl = None
        try:
            dl = (datetime.strptime(c["bis"], "%Y-%m-%d").date() - today).days
        except ValueError:
            pass
        timeline.append({"datum": c["bis"], "typ": "contract_ending", "days_left": dl,
                         "titel": "Vertrag endet · %s (%s)" % (c.get("unit", ""), c["tenant"])})
    ev = db.query(ImmoEvent).filter(ImmoEvent.user_id == uid, _notdel(ImmoEvent), ImmoEvent.done == False,  # noqa: E712
                                    ImmoEvent.datum >= today, ImmoEvent.datum <= today + timedelta(days=90)).all()
    for e in ev:
        timeline.append({"datum": str(e.datum) if e.datum else "", "typ": e.typ or "sonstige",
                         "days_left": (e.datum - today).days if e.datum else None, "titel": e.titel, "event_id": e.id})
    timeline.sort(key=lambda x: x["datum"] or "9999")
    return {"year": year, "score": score, "portfolio": P, "financial": F, "actions": actions,
            "ranking": ranking, "kpi": kpi, "vacancy": vacancy, "tenant_risk": tenant_risk,
            "charts": base["charts"], "contracts_ending": base["contracts_ending"], "timeline": timeline}


@router.get("/cockpit")
def immo_cockpit(year: Optional[int] = Query(None), user: dict = Depends(get_current_user)):
    db = SessionLocal()
    try:
        y = year or datetime.now(timezone.utc).year
        return _cockpit(db, _uid(user), y, base=portfolio_view(db, _uid(user), y))
    finally:
        db.close()


# ══════════════════════════════════════════════════════════════════════
#  P2 — Mahnung (dunning) PDF + history, Erinnerungen/Events, Timeline
# ══════════════════════════════════════════════════════════════════════
_STUFE_TXT = {1: "Zahlungserinnerung", 2: "1. Mahnung", 3: "2. Mahnung"}
EVENT_TYPEN = {"wartung", "versicherung", "grundsteuer", "mieterhoehung", "sonstige"}


# ── EXCEPTION ENGINE ────────────────────────────────────────────────────────
# The product generates Soll for every due month and assumes each month is OK
# unless a PROBLEM is reported. Debt surfaces ONLY from reported exceptions — this
# is NOT an assertion that money arrived, just "no problem reported". One foundation
# for delays, bank-matching, reminders, reporting. Stored per tenancy in
# offene_monate (JSON): [{"ym":"2026-06","typ":"unpaid"},
#                        {"ym":"2026-07","typ":"partial","offen":120.0}]
# Exception-engine READ side lives in immo_rules (shared with the Payment Service).
_exc_list = _rules.exc_list
_exc_for = _rules.exc_for


# LAW #5 — only the Payment Service may modify payment state.
# The former _save_exc / _set_problem / _clear_problem helpers lived here and were the
# second writer of the exception engine. They are GONE (commit 2): this module now only
# READS (immo_rules) and delegates every write to autotax.immo_payments.PaymentService.


# EXCEPTION ENGINE debt for ONE year (Mietkonto tab view) — shared formula, see immo_rules.
# Commit 2 replaces the callers with PaymentService.open_debt(), which spans years (defect A2).
def _exception_arrears(t, year, as_of=None):
    return _rules.exception_arrears(t, year, as_of or date.today())


def _debt(db, uid, t):
    """THE debt answer for one tenancy — Payment Service, across ALL months and years.
    Every surface that shows "what does he owe me" must use this and compute nothing
    itself (law #2/#3/#4)."""
    return _pay.sql_service(db).open_debt(uid, t, date.today())


def _tenancy_arrears(db, uid, t, year=None):
    """Commit 2 (defects A1/A2): the debt is no longer clipped to one calendar year.
    BEFORE: a tenant unpaid in March showed 0 in June's view, and an unpaid December
    disappeared on 1 January. AFTER: every due, unsettled month counts, whatever year
    it sits in. `year` is accepted and ignored — kept so callers need no rewrite."""
    return _debt(db, uid, t).total


def _mahnung_betrag(db, uid, t, year=None) -> float:
    """Mahnung amount = the same debt every screen shows (incl. Nebenkosten, incl.
    previous years). Before commit 2 it dunned Kalt-only, current-year-only."""
    return _debt(db, uid, t).total


class MahnungIn(BaseModel):
    stufe: int = 1
    year: Optional[int] = None
    notiz: Optional[str] = None


@router.get("/tenancies/{tid}/mahnungen")
def list_mahnungen(tid: int, user: dict = Depends(get_current_user)):
    db = SessionLocal()
    try:
        t = db.query(ImmoTenancy).filter(ImmoTenancy.id == tid, ImmoTenancy.user_id == _uid(user)).first()
        if not t:
            raise HTTPException(status_code=404, detail="Mietverhältnis nicht gefunden")
        rows = db.query(ImmoMahnung).filter(ImmoMahnung.tenancy_id == tid, ImmoMahnung.user_id == _uid(user),
                                            _notdel(ImmoMahnung)).order_by(ImmoMahnung.datum.desc()).all()
        # C4: the ESCALATION is decided here, not in the browser. Before, the UI hardcoded
        # stufe:1 at both call sites — clicking Mahnung five times produced five identical
        # "Zahlungserinnerung" letters and the 2./3. Mahnung the backend supports were
        # unreachable. The next step is one above the highest one already sent (max 3).
        hoechste = max([m.stufe or 1 for m in rows], default=0)
        naechste = min(hoechste + 1, 3) if rows else 1
        return {"mahnungen": [{"id": m.id, "datum": str(m.datum) if m.datum else "", "betrag": m.betrag,
                               "stufe": m.stufe, "stufe_text": _STUFE_TXT.get(m.stufe, "Mahnung"),
                               "notiz": m.notiz or ""} for m in rows],
                "naechste_stufe": naechste,
                "naechste_stufe_text": _STUFE_TXT.get(naechste, "Mahnung"),
                "gesendet": len(rows)}
    finally:
        db.close()


@router.get("/tenancies/{tid}/wohnungsgeberbestaetigung/pdf")
def wohnungsgeber_pdf(tid: int, art: str = Query("einzug"), user: dict = Depends(get_current_user)):
    """Wohnungsgeberbestätigung (§19 BMG) PDF for a tenancy. art=einzug|auszug.
    Single meldepflichtige Person (tenancy.mieter_name). Wohnungsgeber = the user's
    default UserCompany; 400 if none is set. Additive — does not touch ledger/Mahnung."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet
    uid = _uid(user)
    db = SessionLocal()
    try:
        t = db.query(ImmoTenancy).filter(ImmoTenancy.id == tid, ImmoTenancy.user_id == uid).first()
        if not t:
            raise HTTPException(status_code=404, detail="Mietverhältnis nicht gefunden")
        u = db.query(ImmoUnit).filter(ImmoUnit.id == t.unit_id).first()
        p = db.query(ImmoProperty).filter(ImmoProperty.id == u.property_id).first() if u else None
        comp = (db.query(UserCompany).filter(UserCompany.user_id == uid, UserCompany.is_default == True).first()  # noqa: E712
                or db.query(UserCompany).filter(UserCompany.user_id == uid).order_by(UserCompany.id.desc()).first())
        if not comp:
            raise HTTPException(status_code=400, detail="Bitte zuerst Firmendaten (Wohnungsgeber) unter 'Firmen' hinterlegen.")
        art = "auszug" if str(art).lower() == "auszug" else "einzug"
        art_lbl = "Auszug" if art == "auszug" else "Einzug"
        dat = (t.bis if art == "auszug" else t.von)
        dat_s = dat.strftime("%d.%m.%Y") if dat else "—"
        wohnung = (p.adresse if (p and p.adresse) else (p.name if p else "")) or "—"
        lage = u.name if u else ""
        wg_addr = (comp.address or "").replace("\n", "<br/>")
        ss = getSampleStyleSheet()
        buf = io.BytesIO()
        doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=22 * mm, bottomMargin=18 * mm, leftMargin=22 * mm, rightMargin=22 * mm)
        heute = date.today().strftime("%d.%m.%Y")
        body_txt = (
            "<b>Wohnungsgeberbestätigung</b> (§ 19 Bundesmeldegesetz)<br/><br/>"
            f"<b>Wohnungsgeber:</b><br/>{comp.company_name}<br/>{wg_addr}<br/><br/>"
            f"<b>Anschrift der Wohnung:</b><br/>{wohnung}" + (f"<br/>Lage: {lage}" if lage else "") + "<br/><br/>"
            f"<b>Art des meldepflichtigen Vorgangs:</b> {art_lbl}<br/>"
            f"<b>Datum des {art_lbl}s:</b> {dat_s}<br/><br/>"
            f"<b>Meldepflichtige Person:</b><br/>{t.mieter_name}<br/><br/>"
            f"Hiermit wird der {art_lbl} der oben genannten Person in die bzw. aus der "
            "genannten Wohnung bestätigt.<br/><br/><br/>"
            f"________________________________<br/>Ort, Datum: {heute}<br/><br/><br/>"
            "________________________________<br/>Unterschrift Wohnungsgeber"
        )
        doc.build([Paragraph(body_txt, ss["Normal"]), Spacer(1, 4 * mm)])
        try:
            t.wgb_erstellt_am = datetime.now(timezone.utc); db.commit()  # UI status: WGB erzeugt
        except Exception:
            db.rollback()
        buf.seek(0)
        return StreamingResponse(buf, media_type="application/pdf",
                                 headers={"Content-Disposition": f'attachment; filename="wohnungsgeberbestaetigung_{tid}.pdf"'})
    finally:
        db.close()


@router.post("/tenancies/{tid}/mahnung")
def create_mahnung(tid: int, body: MahnungIn, user: dict = Depends(get_current_user)):
    """Record a Mahnung (computes current arrears) and return the PDF letter."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet
    uid = _uid(user)
    db = SessionLocal()
    try:
        t = db.query(ImmoTenancy).filter(ImmoTenancy.id == tid, ImmoTenancy.user_id == uid).first()
        if not t:
            raise HTTPException(status_code=404, detail="Mietverhältnis nicht gefunden")
        u = db.query(ImmoUnit).filter(ImmoUnit.id == t.unit_id).first()
        p = db.query(ImmoProperty).filter(ImmoProperty.id == u.property_id).first() if u else None
        y = body.year or datetime.now(timezone.utc).year
        debt = _debt(db, uid, t)                       # the same number Bu Ay / Mieter show
        betrag = debt.total
        stufe = body.stufe if body.stufe in (1, 2, 3) else 1
        m = ImmoMahnung(tenancy_id=tid, user_id=uid, datum=date.today(), betrag=betrag, stufe=stufe, notiz=body.notiz)
        db.add(m); db.commit(); db.refresh(m)
        # A5: the letter must come FROM the landlord, not from an anonymous "Hausverwaltung".
        comp = (db.query(UserCompany).filter(UserCompany.user_id == uid, UserCompany.is_default == True).first()  # noqa: E712
                or db.query(UserCompany).filter(UserCompany.user_id == uid).order_by(UserCompany.id.desc()).first())
        absender = (comp.company_name if comp else "")
        abs_addr = ((comp.address or "").replace("\n", ", ") if comp else "")
        iban = (comp.iban if (comp and comp.iban) else None)
        ss = getSampleStyleSheet()
        buf = io.BytesIO()
        doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=22 * mm, bottomMargin=18 * mm, leftMargin=22 * mm, rightMargin=22 * mm)
        objekt = (p.name if p else "") + (" · " + p.adresse if (p and p.adresse) else "")
        whg = u.name if u else ""
        heute = date.today().strftime("%d.%m.%Y")
        frist = (date.today() + timedelta(days=14)).strftime("%d.%m.%Y")   # A5: a real deadline DATE
        # A5: the recipient block — the tenant is addressed at the flat he rents
        empf = "<br/>".join(x for x in [f"<b>{t.mieter_name}</b>",
                                        (p.adresse if (p and p.adresse) else None),
                                        (f"Wohnung: {whg}" if whg else None)] if x)
        # the open months, itemised — a dunning letter must say WHAT is being dunned
        _MN = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August",
               "September", "Oktober", "November", "Dezember"]
        posten = "<br/>".join(f"{_MN[mo.monat - 1]} {mo.jahr}: {mo.offen:.2f} EUR" for mo in debt.months) or "—"
        konto = (f"auf das Konto <b>{iban}</b>" if iban else "auf das bekannte Konto")
        body_txt = (
            f"<b>{_STUFE_TXT.get(stufe, 'Mahnung')}</b><br/><br/>"
            f"Sehr geehrte/r {t.mieter_name},<br/><br/>"
            f"für die von Ihnen gemietete Einheit <b>{whg}</b> ({objekt}) sind zum heutigen Tag "
            f"folgende Mietzahlungen offen:<br/><br/>"
            f"{posten}<br/><br/>"
            f"<b>Offener Gesamtbetrag: {betrag:.2f} EUR</b><br/><br/>"
            f"Wir bitten Sie, den offenen Betrag bis zum <b>{frist}</b> {konto} zu überweisen. "
            f"Sollte sich Ihre Zahlung mit diesem Schreiben überschnitten haben, "
            f"betrachten Sie es bitte als gegenstandslos.<br/><br/>"
            f"Mit freundlichen Grüßen<br/>{absender or 'Der Vermieter'}"
        )
        el = []
        if absender:
            el.append(Paragraph(f"<font size=8>{absender}{' · ' + abs_addr if abs_addr else ''}</font>", ss["Normal"]))
            el.append(Spacer(1, 6 * mm))
        el += [Paragraph(empf, ss["Normal"]), Spacer(1, 10 * mm),
               Paragraph(heute, ss["Normal"]), Spacer(1, 8 * mm),
               Paragraph(body_txt, ss["Normal"])]
        doc.build(el)
        buf.seek(0)
        return StreamingResponse(buf, media_type="application/pdf",
                                 headers={"Content-Disposition": f'attachment; filename="mahnung_{tid}_{m.id}.pdf"'})
    finally:
        db.close()


# ── Events / Erinnerungen ─────────────────────────────────────────────
class EventIn(BaseModel):
    property_id: Optional[int] = None
    datum: Optional[str] = None
    typ: Optional[str] = None
    titel: str = Field(..., min_length=1, max_length=200)


class EventPatch(BaseModel):
    datum: Optional[str] = None
    typ: Optional[str] = None
    titel: Optional[str] = None
    done: Optional[bool] = None


def _event_dict(e):
    return {"id": e.id, "property_id": e.property_id, "datum": str(e.datum) if e.datum else "",
            "typ": e.typ or "sonstige", "titel": e.titel, "done": bool(e.done)}


@router.get("/events")
def list_events(user: dict = Depends(get_current_user)):
    db = SessionLocal()
    try:
        rows = db.query(ImmoEvent).filter(ImmoEvent.user_id == _uid(user), _notdel(ImmoEvent)).order_by(ImmoEvent.datum).all()
        return {"events": [_event_dict(e) for e in rows]}
    finally:
        db.close()


@router.post("/events")
def create_event(body: EventIn, user: dict = Depends(get_current_user)):
    db = SessionLocal()
    try:
        e = ImmoEvent(user_id=_uid(user), property_id=body.property_id, datum=_pdate(body.datum),
                      typ=(body.typ if body.typ in EVENT_TYPEN else "sonstige"), titel=body.titel.strip())
        db.add(e); db.commit(); db.refresh(e)
        return {"success": True, **_event_dict(e)}
    finally:
        db.close()


@router.patch("/events/{eid}")
def update_event(eid: int, body: EventPatch, user: dict = Depends(get_current_user)):
    db = SessionLocal()
    try:
        e = db.query(ImmoEvent).filter(ImmoEvent.id == eid, ImmoEvent.user_id == _uid(user)).first()
        if not e:
            raise HTTPException(status_code=404, detail="Termin nicht gefunden")
        if body.datum is not None: e.datum = _pdate(body.datum)
        if body.typ is not None and body.typ in EVENT_TYPEN: e.typ = body.typ
        if body.titel is not None: e.titel = body.titel.strip()
        if body.done is not None: e.done = body.done
        db.commit(); db.refresh(e)
        return {"success": True, **_event_dict(e)}
    finally:
        db.close()


@router.delete("/events/{eid}")
def delete_event(eid: int, user: dict = Depends(get_current_user)):
    db = SessionLocal()
    try:
        e = db.query(ImmoEvent).filter(ImmoEvent.id == eid, ImmoEvent.user_id == _uid(user)).first()
        if not e:
            raise HTTPException(status_code=404, detail="Termin nicht gefunden")
        e.is_deleted = True; e.deleted_at = datetime.now(timezone.utc)
        db.commit()
        return {"success": True}
    finally:
        db.close()


# ══════════════════════════════════════════════════════════════════════
#  LEDGER BACKFILL (Faz 1.2) — admin-gated, dry-run/execute.
#  Writes ONLY immo_ledger_entry. Does NOT change cockpit/mahnung/debtor/
#  dashboard/risk — the ledger is NOT yet a read source (that is Faz 4,
#  gated by parity). This endpoint only moves existing data into the ledger.
# ══════════════════════════════════════════════════════════════════════
def _is_admin(user: dict) -> bool:
    """Owner/admin gate — token email vs ADMIN_EMAILS (same basis as the
    /admin/* middleware). Signed JWT, so the email is trustworthy."""
    admins = {e.strip().lower() for e in (os.getenv("ADMIN_EMAILS") or "").split(",") if e.strip()}
    return bool(admins) and (user.get("email") or "").strip().lower() in admins


@router.post("/_ledger/backfill")
def ledger_backfill(dry_run: bool = Query(True), user: dict = Depends(get_current_user)):
    """Run the Faz 1 backfill for the calling admin's own data.

    dry_run=true (default) counts and writes NOTHING; dry_run=false executes in a
    single transaction (rollback-safe, idempotent). Returns:
        {dry_run, soll_to_create, payments_to_import, tenancies, rents}
    """
    if not _is_admin(user):
        raise HTTPException(status_code=403, detail="Admin only")
    db = SessionLocal()
    try:
        return _ledger.run_backfill(db, _uid(user), dry_run=dry_run)
    finally:
        db.close()


# ══════════════════════════════════════════════════════════════════════
#  PARITY COMPARATOR (Faz 3) — proves LEDGER == OLD engine before cutover.
#  GATE: no read-path is switched to the ledger (Faz 4) until passed=True.
#  Read-only; changes NOTHING. Money tol ±0.01, counts exact.
# ══════════════════════════════════════════════════════════════════════
def _old_scope(db, uid: int):
    """OLD _portfolio scoping: non-deleted property → unit → tenancy + year rents."""
    props = db.query(ImmoProperty).filter(ImmoProperty.user_id == uid, _notdel(ImmoProperty)).all()
    pids = [p.id for p in props]
    units = db.query(ImmoUnit).filter(ImmoUnit.user_id == uid, _notdel(ImmoUnit),
                                      ImmoUnit.property_id.in_(pids)).all() if pids else []
    uids = [u.id for u in units]
    tens = db.query(ImmoTenancy).filter(ImmoTenancy.user_id == uid, _notdel(ImmoTenancy),
                                        ImmoTenancy.unit_id.in_(uids)).all() if uids else []
    return pids, tens


def _old_ist_by_tenancy(db, uid: int, pids: list, year: int) -> dict:
    rents = db.query(ImmoRent).filter(ImmoRent.user_id == uid, _notdel(ImmoRent), ImmoRent.property_id.in_(pids),
                                      ImmoRent.datum >= date(year, 1, 1), ImmoRent.datum <= date(year, 12, 31)).all() if pids else []
    ist_by = {}
    for r in rents:
        if r.tenancy_id:
            ist_by[r.tenancy_id] = ist_by.get(r.tenancy_id, 0) + float(r.betrag or 0)
    return ist_by


def _old_debtors(db, uid: int, year: int) -> list:
    """Full OLD-engine debtor list (uncapped) in top_debtors shape:
    [{tenant, debt, months_overdue}], sorted by debt desc. Single source for the
    parity comparator AND the source adapter so they never drift apart."""
    pids, tens = _old_scope(db, uid)
    ist_by = _old_ist_by_tenancy(db, uid, pids, year)
    out = []
    for t in tens:
        soll_t = _months_due_to_date(t, year) * float(t.kaltmiete or 0)
        ist_t = round(ist_by.get(t.id, 0), 2)
        arr = round(max(0, soll_t - ist_t), 2)
        if arr > 0:
            mo = round(arr / float(t.kaltmiete)) if t.kaltmiete else None
            out.append({"tenant": t.mieter_name, "debt": arr, "months_overdue": mo})
    out.sort(key=lambda x: -x["debt"])
    return out


def _parity_old(db, uid: int, year: int) -> dict:
    """AUDIT TRUTH — Soll (ledger posting basis = _soll_faellig: anteilig / Mieterhöhung
    / Erstmiete, due-to-date) minus REAL immo_rent payments. Independent of the
    operational EXCEPTION engine. parity_report verifies the audit LEDGER against THIS
    direct recomputation (audit-truth ↔ ledger), NOT against user-facing exception debt
    (a separate domain — see _mahnung_betrag / _exception_arrears)."""
    pids, tens = _old_scope(db, uid)
    ist_by = _old_ist_by_tenancy(db, uid, pids, year)
    per_saldo, rueckstand, ist_total, debtor_count = {}, 0.0, 0.0, 0
    for t in tens:
        soll_t = _soll_faellig(t, year)
        ist_t = round(ist_by.get(t.id, 0), 2)
        bal = round(soll_t - ist_t, 2)
        per_saldo[t.id] = bal
        ist_total += ist_t
        if bal > 0.01:
            rueckstand += bal; debtor_count += 1
    return {"rueckstand": round(rueckstand, 2), "ist": round(ist_total, 2),
            "debtor_count": debtor_count, "per_saldo": per_saldo}


def parity_report(db, uid: int, year: int) -> dict:
    """Compare OLD engine vs LEDGER read model across 6 metrics. Returns
    {year, passed, metrics:[{metric, old, ledger, diff, ok}]}. GATE for Faz 4."""
    old = _parity_old(db, uid, year)
    Lf = _read.offene_forderungen(db, uid, year)
    Ldebt = _read.debtor_list(db, uid, year)
    Lsal = _read.saldo_by_tenancy(db, uid, year)
    # collected (ist): exact = −Σ betrag of rent-imported entries (incl. refund=korrektur)
    imp = db.query(ImmoLedgerEntry.betrag).filter(
        ImmoLedgerEntry.user_id == uid, ImmoLedgerEntry.source == "import_rent",
        ImmoLedgerEntry.konto_art == "miete", ImmoLedgerEntry.jahr == year,
        (ImmoLedgerEntry.is_deleted == False) | (ImmoLedgerEntry.is_deleted == None)).all()  # noqa: E712
    ledger_ist = round(-sum(float(b or 0) for (b,) in imp), 2)
    # per-tenancy saldo
    o_sum = l_sum = 0.0
    mismatches = []
    for tid in set(old["per_saldo"]) | set(Lsal):
        o = round(old["per_saldo"].get(tid, 0.0), 2)
        l = round(Lsal.get(tid, {}).get("saldo", 0.0), 2)
        o_sum += o; l_sum += l
        if abs(o - l) > 0.01:
            mismatches.append({"tenancy_id": tid, "old": o, "ledger": l, "diff": round(l - o, 2)})

    def _row(metric, o, l, tol, extra=None):
        diff = round(float(l) - float(o), 2)
        ok = abs(diff) <= tol
        r = {"metric": metric, "old": o, "ledger": l, "diff": diff, "ok": bool(ok)}
        if extra is not None:
            r["mismatches"] = extra
            r["ok"] = bool(ok and not extra)
        return r

    # AUDIT-DOMAIN integrity metrics: the ledger's financial records vs the direct
    # audit-truth recomputation. UI-coupled metrics (cockpit_critical / mahnung_candidates)
    # were retired — they are operational concerns, not audit invariants.
    metrics = [
        _row("offene_forderung", old["rueckstand"], Lf["total"], 0.01),
        _row("debtor_count", old["debtor_count"], len(Ldebt), 0),
        _row("collected_rent", old["ist"], ledger_ist, 0.01),
        _row("tenancy_saldo", round(o_sum, 2), round(l_sum, 2), 0.01, mismatches),
    ]
    return {"year": year, "passed": all(m["ok"] for m in metrics), "metrics": metrics}


@router.get("/_ledger/parity")
def ledger_parity(year: Optional[int] = Query(None), user: dict = Depends(get_current_user)):
    """Admin-only parity report (OLD vs LEDGER). GATE: cutover (Faz 4) only when passed=True."""
    if not _is_admin(user):
        raise HTTPException(status_code=403, detail="Admin only")
    db = SessionLocal()
    try:
        return parity_report(db, _uid(user), year or datetime.now(timezone.utc).year)
    finally:
        db.close()


# ══════════════════════════════════════════════════════════════════════
#  LEDGER SCOPE CONSISTENCY (Faz 4.0) — delete-cascade + reconcile.
#  Keeps the ledger's scope identical to property/unit/tenancy scope so the
#  orphan drift parity caught (deleted property with live ledger rows) can
#  never recur. Pure data consistency: NO flag, NO read-path change — cockpit/
#  debtor/mahnung/dashboard untouched. Cutover (4.1+) is blocked until this ships.
# ══════════════════════════════════════════════════════════════════════
def _cascade_ledger_delete(db, uid: int, *, property_id=None, unit_id=None,
                           tenancy_id=None, tenancy_ids=None) -> int:
    """Soft-delete active ledger rows belonging to a just-deleted property/unit/
    tenancy. NOTE: payment entries carry tenancy_id but NOT unit_id, so a unit
    delete MUST also pass the unit's tenancy_ids (the caller does) — otherwise
    payments would be missed. Matches ANY given condition (OR). Same transaction
    as the parent delete. Returns rows affected."""
    conds = []
    if property_id is not None:
        conds.append(ImmoLedgerEntry.property_id == property_id)
    if unit_id is not None:
        conds.append(ImmoLedgerEntry.unit_id == unit_id)
    if tenancy_id is not None:
        conds.append(ImmoLedgerEntry.tenancy_id == tenancy_id)
    if tenancy_ids:
        conds.append(ImmoLedgerEntry.tenancy_id.in_(tenancy_ids))
    if not conds:
        return 0
    notdel = (ImmoLedgerEntry.is_deleted == False) | (ImmoLedgerEntry.is_deleted == None)  # noqa: E712
    return db.query(ImmoLedgerEntry).filter(
        ImmoLedgerEntry.user_id == uid, notdel, or_(*conds)).update(
        {ImmoLedgerEntry.is_deleted: True, ImmoLedgerEntry.deleted_at: datetime.now(timezone.utc)},
        synchronize_session=False)


@router.post("/_ledger/reconcile")
def ledger_reconcile(dry_run: bool = Query(True), user: dict = Depends(get_current_user)):
    """Admin: find (and optionally soft-delete) ORPHAN ledger rows.

    Orphan = active ledger entry NOT in the active scope, i.e. its tenancy is not
    under a non-deleted unit under a non-deleted property (entries without a
    tenancy fall back to property scope). Scope-based — does NOT rely on unit_id/
    property_id columns alone (payment entries have NULL unit_id). Belt-and-
    suspenders for the delete-cascade. dry_run=true reports only. Returns:
        {dry_run, orphan_by_property, orphan_by_unit, orphan_by_tenancy,
         total_orphan, cleaned}
    Breakdown attributes each orphan to the deepest deleted level (tenancy >
    unit > property); the three are disjoint and sum to total_orphan."""
    if not _is_admin(user):
        raise HTTPException(status_code=403, detail="Admin only")
    uid = _uid(user)
    db = SessionLocal()
    try:
        # active scope (mirrors OLD _portfolio / backfill)
        act_pids = set(_ledger._active_pids(db, uid))
        act_units = _ledger._active_units(db, uid, list(act_pids))
        act_tids = set(t.id for t in _ledger._active_tenancies(db, uid, act_units))
        # maps of ALL (incl. deleted) for breakdown
        tens = {t.id: t for t in db.query(ImmoTenancy).filter(ImmoTenancy.user_id == uid).all()}
        units = {u.id: u for u in db.query(ImmoUnit).filter(ImmoUnit.user_id == uid).all()}
        notdel = (ImmoLedgerEntry.is_deleted == False) | (ImmoLedgerEntry.is_deleted == None)  # noqa: E712
        rows = db.query(ImmoLedgerEntry).filter(ImmoLedgerEntry.user_id == uid, notdel).all()

        def _in_scope(e):
            if e.tenancy_id is not None:
                return e.tenancy_id in act_tids
            return e.property_id in act_pids  # tenancy-less entry → property scope

        by_p = by_u = by_t = 0
        orphan_ids = []
        for e in rows:
            if _in_scope(e):
                continue
            orphan_ids.append(e.id)
            t = tens.get(e.tenancy_id) if e.tenancy_id is not None else None
            if e.tenancy_id is not None and (t is None or t.is_deleted):
                by_t += 1
            else:
                u = units.get(t.unit_id) if t else None
                if t is not None and (u is None or u.is_deleted):
                    by_u += 1
                else:
                    by_p += 1  # property-level (or tenancy-less under deleted property)
        total = len(orphan_ids)
        cleaned = 0
        if not dry_run and total:
            cleaned = db.query(ImmoLedgerEntry).filter(
                ImmoLedgerEntry.id.in_(orphan_ids)).update(
                {ImmoLedgerEntry.is_deleted: True, ImmoLedgerEntry.deleted_at: datetime.now(timezone.utc)},
                synchronize_session=False)
            db.commit()
        return {"dry_run": dry_run, "orphan_by_property": by_p, "orphan_by_unit": by_u,
                "orphan_by_tenancy": by_t, "total_orphan": total, "cleaned": cleaned}
    finally:
        db.close()
