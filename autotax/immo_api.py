"""Immobilien PRO MVP — landlord module API router.

ADDITIVE & ISOLATED: brand-new router, own tables (immo_*), own prefix /immo.
Does NOT touch OCR / Vision / Parser / VAT / Kassenbuch / Rechnungen.
Every endpoint: JWT auth + user_id isolation + soft-delete.

Resources: properties, tenants, rent (payments), expenses, documents.
Plus per-property dashboard (year) and a one-click annual PDF report.
"""
from __future__ import annotations

import io
import os
from calendar import monthrange
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from autotax import storage
from autotax import immo_ledger as _ledger
from autotax import immo_ledger_read as _read
from autotax.auth import get_current_user
from autotax.db import SessionLocal
from autotax.models import (ImmoProperty, ImmoTenant, ImmoRent, ImmoExpense, ImmoDocument,
                            ImmoUnit, ImmoTenancy, ImmoMahnung, ImmoEvent, ImmoLedgerEntry)

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
    datum: Optional[str] = None
    betrag: float = 0.0
    notiz: Optional[str] = None


class RentPatch(BaseModel):
    tenant_id: Optional[int] = None
    tenancy_id: Optional[int] = None
    datum: Optional[str] = None
    betrag: Optional[float] = None
    notiz: Optional[str] = None


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


@router.delete("/properties/{pid}")
def delete_property(pid: int, user: dict = Depends(get_current_user)):
    db = SessionLocal()
    try:
        p = _own_property(db, _uid(user), pid)
        p.is_deleted = True; p.deleted_at = datetime.now(timezone.utc)
        db.commit()
        return {"success": True}
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
    db = SessionLocal()
    try:
        _own_property(db, _uid(user), body.property_id)
        r = ImmoRent(property_id=body.property_id, tenant_id=body.tenant_id, tenancy_id=body.tenancy_id,
                     user_id=_uid(user), datum=_pdate(body.datum) or date.today(), betrag=body.betrag, notiz=body.notiz)
        db.add(r); db.commit(); db.refresh(r)
        return {"success": True, **_rent_dict(r)}
    finally:
        db.close()


@router.patch("/rent/{rid}")
def update_rent(rid: int, body: RentPatch, user: dict = Depends(get_current_user)):
    db = SessionLocal()
    try:
        r = db.query(ImmoRent).filter(ImmoRent.id == rid, ImmoRent.user_id == _uid(user)).first()
        if not r:
            raise HTTPException(status_code=404, detail="Mietzahlung nicht gefunden")
        if body.tenant_id is not None: r.tenant_id = body.tenant_id
        if body.tenancy_id is not None: r.tenancy_id = body.tenancy_id
        if body.datum is not None: r.datum = _pdate(body.datum)
        if body.betrag is not None: r.betrag = body.betrag
        if body.notiz is not None: r.notiz = body.notiz
        db.commit(); db.refresh(r)
        return {"success": True, **_rent_dict(r)}
    finally:
        db.close()


@router.delete("/rent/{rid}")
def delete_rent(rid: int, user: dict = Depends(get_current_user)):
    db = SessionLocal()
    try:
        r = db.query(ImmoRent).filter(ImmoRent.id == rid, ImmoRent.user_id == _uid(user)).first()
        if not r:
            raise HTTPException(status_code=404, detail="Mietzahlung nicht gefunden")
        r.is_deleted = True; r.deleted_at = datetime.now(timezone.utc)
        db.commit()
        return {"success": True}
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
            "kaltmiete": t.kaltmiete, "kaution": t.kaution, "nk_voraus": t.nk_voraus}


def _tenancy_active_in_month(t, y, m):
    mstart = date(y, m, 1)
    mend = date(y, m, monthrange(y, m)[1])
    von = t.von or date(1900, 1, 1)
    bis = t.bis or date(2999, 12, 31)
    return von <= mend and bis >= mstart


def _months_active_in_year(t, y):
    return sum(1 for m in range(1, 13) if _tenancy_active_in_month(t, y, m))


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
    db = SessionLocal()
    try:
        u = _own_unit(db, _uid(user), uid_)
        u.is_deleted = True; u.deleted_at = datetime.now(timezone.utc)
        db.commit()
        return {"success": True}
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
        db.commit(); db.refresh(t)
        return {"success": True, **_tenancy_dict(t)}
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
    rents = db.query(ImmoRent).filter(ImmoRent.property_id == pid, ImmoRent.user_id == uid, _notdel(ImmoRent),
                                      ImmoRent.datum >= date(year, 1, 1), ImmoRent.datum <= date(year, 12, 31)).all()
    ist_by_tenancy = {}
    ist_total = 0.0
    for r in rents:
        ist_total += float(r.betrag or 0)
        if r.tenancy_id:
            ist_by_tenancy[r.tenancy_id] = ist_by_tenancy.get(r.tenancy_id, 0) + float(r.betrag or 0)
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
                soll_u += float(act[0].kaltmiete or 0)
            else:
                vac += 1
        leer = vac * float(u.soll_miete or 0)
        unit_results.append({"unit_id": u.id, "name": u.name or ("Whg " + str(u.id)),
                             "soll_miete": u.soll_miete, "occupied_months": occ, "vacant_months": vac,
                             "belegungsquote": round(occ / 12 * 100, 1), "soll": round(soll_u, 2),
                             "leerstandsverlust": round(leer, 2)})
        total_soll += soll_u; total_occ += occ; total_vac += vac; total_leer += leer
        for t in u_ten:
            ma = _months_active_in_year(t, year)
            soll_t = ma * float(t.kaltmiete or 0)
            ist_t = round(ist_by_tenancy.get(t.id, 0), 2)
            tenancy_results.append({"tenancy_id": t.id, "unit_id": u.id, "mieter_name": t.mieter_name,
                                    "von": str(t.von) if t.von else "", "bis": str(t.bis) if t.bis else "",
                                    "kaltmiete": t.kaltmiete, "monate": ma, "soll": round(soll_t, 2),
                                    "ist": ist_t, "rueckstand": round(max(0, soll_t - ist_t), 2),
                                    "kaution": t.kaution})
    exps = db.query(ImmoExpense).filter(ImmoExpense.property_id == pid, ImmoExpense.user_id == uid, _notdel(ImmoExpense),
                                        ImmoExpense.datum >= date(year, 1, 1), ImmoExpense.datum <= date(year, 12, 31)).all()
    by_kat = {}
    for e in exps:
        by_kat[e.kategorie] = round(by_kat.get(e.kategorie, 0) + float(e.betrag or 0), 2)
    ausgaben = round(sum(by_kat.values()), 2)
    gewinn = round(ist_total - ausgaben, 2)
    rendite = round(gewinn / float(p.kaufpreis) * 100, 2) if (p and p.kaufpreis) else None
    soll_sum = round(sum(t["soll"] for t in tenancy_results), 2)
    ist_sum = round(sum(t["ist"] for t in tenancy_results), 2)
    zahlungsausfall = round(max(0, soll_sum - ist_sum), 2)
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
    rents = db.query(ImmoRent).filter(ImmoRent.user_id == uid, _notdel(ImmoRent), ImmoRent.property_id.in_(pids),
                                      ImmoRent.datum >= date(year, 1, 1), ImmoRent.datum <= date(year, 12, 31)).all() if pids else []
    exps = db.query(ImmoExpense).filter(ImmoExpense.user_id == uid, _notdel(ImmoExpense), ImmoExpense.property_id.in_(pids),
                                        ImmoExpense.datum >= date(year, 1, 1), ImmoExpense.datum <= date(year, 12, 31)).all() if pids else []
    ten_by_unit = {}
    for t in tenancies:
        ten_by_unit.setdefault(t.unit_id, []).append(t)
    unit_by_id = {u.id: u for u in units}
    # monthly series + per-tenancy Ist
    monthly_income = [0.0] * 12
    monthly_expenses = [0.0] * 12
    ist_by_ten = {}
    for r in rents:
        if r.datum:
            monthly_income[r.datum.month - 1] += float(r.betrag or 0)
        if r.tenancy_id:
            ist_by_ten[r.tenancy_id] = ist_by_ten.get(r.tenancy_id, 0) + float(r.betrag or 0)
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
                soll_total += float(act[0].kaltmiete or 0)
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
    for t in tenancies:
        ma = _months_active_in_year(t, year)
        soll_t = ma * float(t.kaltmiete or 0)
        ist_t = round(ist_by_ten.get(t.id, 0), 2)
        arr = round(max(0, soll_t - ist_t), 2)
        if arr > 0:
            ausfall_total += arr
            mo = round(arr / float(t.kaltmiete)) if t.kaltmiete else None
            top_debtors.append({"tenant": t.mieter_name, "debt": arr, "months_overdue": mo})
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


@router.get("/dashboard")
def immo_dashboard(year: Optional[int] = Query(None), user: dict = Depends(get_current_user)):
    db = SessionLocal()
    try:
        return _portfolio(db, _uid(user), year or datetime.now(timezone.utc).year)
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


def _cockpit(db, uid, year):
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
    # missing rent for current month (only when viewing current year)
    if year == today.year:
        cm = today.month
        pids = [p.id for p in props]
        units = db.query(ImmoUnit).filter(ImmoUnit.user_id == uid, _notdel(ImmoUnit), ImmoUnit.property_id.in_(pids)).all() if pids else []
        uids2 = [u.id for u in units]
        tens = db.query(ImmoTenancy).filter(ImmoTenancy.user_id == uid, _notdel(ImmoTenancy), ImmoTenancy.unit_id.in_(uids2)).all() if uids2 else []
        cm_rents = db.query(ImmoRent).filter(ImmoRent.user_id == uid, _notdel(ImmoRent),
                                             ImmoRent.datum >= date(year, cm, 1),
                                             ImmoRent.datum <= date(year, cm, monthrange(year, cm)[1])).all() if pids else []
        paid = set(r.tenancy_id for r in cm_rents if r.tenancy_id)
        for t in tens:
            if _tenancy_active_in_month(t, year, cm) and t.id not in paid:
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
        return _cockpit(db, _uid(user), year or datetime.now(timezone.utc).year)
    finally:
        db.close()


# ══════════════════════════════════════════════════════════════════════
#  P2 — Mahnung (dunning) PDF + history, Erinnerungen/Events, Timeline
# ══════════════════════════════════════════════════════════════════════
_STUFE_TXT = {1: "Zahlungserinnerung", 2: "1. Mahnung", 3: "2. Mahnung"}
EVENT_TYPEN = {"wartung", "versicherung", "grundsteuer", "mieterhoehung", "sonstige"}


def _tenancy_arrears(db, uid, t, year):
    ma = _months_active_in_year(t, year)
    soll = ma * float(t.kaltmiete or 0)
    rents = db.query(ImmoRent).filter(ImmoRent.user_id == uid, ImmoRent.tenancy_id == t.id, _notdel(ImmoRent),
                                      ImmoRent.datum >= date(year, 1, 1), ImmoRent.datum <= date(year, 12, 31)).all()
    ist = sum(float(r.betrag or 0) for r in rents)
    return round(max(0, soll - ist), 2)


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
        return {"mahnungen": [{"id": m.id, "datum": str(m.datum) if m.datum else "", "betrag": m.betrag,
                               "stufe": m.stufe, "stufe_text": _STUFE_TXT.get(m.stufe, "Mahnung"),
                               "notiz": m.notiz or ""} for m in rows]}
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
        betrag = _tenancy_arrears(db, uid, t, y)
        stufe = body.stufe if body.stufe in (1, 2, 3) else 1
        m = ImmoMahnung(tenancy_id=tid, user_id=uid, datum=date.today(), betrag=betrag, stufe=stufe, notiz=body.notiz)
        db.add(m); db.commit(); db.refresh(m)
        ss = getSampleStyleSheet()
        buf = io.BytesIO()
        doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=22 * mm, bottomMargin=18 * mm, leftMargin=22 * mm, rightMargin=22 * mm)
        objekt = (p.name if p else "") + (" · " + p.adresse if (p and p.adresse) else "")
        whg = u.name if u else ""
        heute = date.today().strftime("%d.%m.%Y")
        body_txt = (
            f"<b>{_STUFE_TXT.get(stufe, 'Mahnung')}</b><br/><br/>"
            f"Sehr geehrte/r {t.mieter_name},<br/><br/>"
            f"für die von Ihnen gemietete Einheit <b>{whg}</b> ({objekt}) ist zum heutigen Tag "
            f"ein offener Mietbetrag in Höhe von <b>{betrag:.2f} EUR</b> fällig.<br/><br/>"
            f"Wir bitten Sie, den offenen Betrag innerhalb von <b>14 Tagen</b> auf das bekannte Konto "
            f"zu überweisen. Sollte sich Ihre Zahlung mit diesem Schreiben überschnitten haben, "
            f"betrachten Sie es bitte als gegenstandslos.<br/><br/>"
            f"Mit freundlichen Grüßen<br/>Die Hausverwaltung"
        )
        el = [Paragraph(heute, ss["Normal"]), Spacer(1, 10 * mm),
              Paragraph(t.mieter_name, ss["Normal"]), Spacer(1, 12 * mm),
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
def _parity_old(db, uid: int, year: int) -> dict:
    """OLD-engine metrics, mirroring _portfolio's scoping exactly."""
    P = _portfolio(db, uid, year)
    props = db.query(ImmoProperty).filter(ImmoProperty.user_id == uid, _notdel(ImmoProperty)).all()
    pids = [p.id for p in props]
    units = db.query(ImmoUnit).filter(ImmoUnit.user_id == uid, _notdel(ImmoUnit),
                                      ImmoUnit.property_id.in_(pids)).all() if pids else []
    uids = [u.id for u in units]
    tens = db.query(ImmoTenancy).filter(ImmoTenancy.user_id == uid, _notdel(ImmoTenancy),
                                        ImmoTenancy.unit_id.in_(uids)).all() if uids else []
    rents = db.query(ImmoRent).filter(ImmoRent.user_id == uid, _notdel(ImmoRent), ImmoRent.property_id.in_(pids),
                                      ImmoRent.datum >= date(year, 1, 1), ImmoRent.datum <= date(year, 12, 31)).all() if pids else []
    ist_by = {}
    for r in rents:
        if r.tenancy_id:
            ist_by[r.tenancy_id] = ist_by.get(r.tenancy_id, 0) + float(r.betrag or 0)
    debtor_count = 0
    per_saldo = {}
    for t in tens:
        soll_t = _months_active_in_year(t, year) * float(t.kaltmiete or 0)
        ist_t = round(ist_by.get(t.id, 0), 2)
        per_saldo[t.id] = round(soll_t - ist_t, 2)
        if round(max(0, soll_t - ist_t), 2) > 0:
            debtor_count += 1
    C = _cockpit(db, uid, year)
    red = [a for a in C["actions"] if a.get("severity") == "red"]
    return {"rueckstand": P["financial"]["rueckstand"], "ist": P["financial"]["ist"],
            "debtor_count": debtor_count, "per_saldo": per_saldo,
            "cockpit_red": len(red), "cockpit_red_nondebt": sum(1 for a in red if a.get("typ") != "debt")}


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
    ledger_cockpit_red = old["cockpit_red_nondebt"] + sum(1 for d in Ldebt[:5] if d["risk_level"] == "high")
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

    metrics = [
        _row("offene_forderung", old["rueckstand"], Lf["total"], 0.01),
        _row("debtor_count", old["debtor_count"], len(Ldebt), 0),
        _row("mahnung_candidates", old["debtor_count"], len(Ldebt), 0),
        _row("cockpit_critical", old["cockpit_red"], ledger_cockpit_red, 0),
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
