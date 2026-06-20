"""Immobilien PRO MVP — landlord module API router.

ADDITIVE & ISOLATED: brand-new router, own tables (immo_*), own prefix /immo.
Does NOT touch OCR / Vision / Parser / VAT / Kassenbuch / Rechnungen.
Every endpoint: JWT auth + user_id isolation + soft-delete.

Resources: properties, tenants, rent (payments), expenses, documents.
Plus per-property dashboard (year) and a one-click annual PDF report.
"""
from __future__ import annotations

import io
from datetime import date, datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from autotax import storage
from autotax.auth import get_current_user
from autotax.db import SessionLocal
from autotax.models import ImmoProperty, ImmoTenant, ImmoRent, ImmoExpense, ImmoDocument

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
    return {"id": r.id, "property_id": r.property_id, "tenant_id": r.tenant_id,
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
    datum: Optional[str] = None
    betrag: float = 0.0
    notiz: Optional[str] = None


class RentPatch(BaseModel):
    tenant_id: Optional[int] = None
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
        r = ImmoRent(property_id=body.property_id, tenant_id=body.tenant_id, user_id=_uid(user),
                     datum=_pdate(body.datum) or date.today(), betrag=body.betrag, notiz=body.notiz)
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
