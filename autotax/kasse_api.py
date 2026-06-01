"""Kasa MVP — read/light-write API router (Sprint 1).

ADDITIVE & SAFE: new router only; does not touch existing /kassenbuch CRUD.
Every endpoint is gated behind FEAT_KASSE_V2 (default OFF) → returns 404 when
off. Auth required. User-scoped. Summaries/dashboard delegate to the
single-source `kasse_service`. Not wired to the SPA (dashboard UI = Sprint 3).

Endpoints:
  GET    /kasse/dashboard
  GET    /kasse/summary/daily?date=YYYY-MM-DD
  GET    /kasse/summary/weekly?date=YYYY-MM-DD
  GET    /kasse/summary/monthly?month=YYYY-MM
  GET    /kasse/categories
  POST   /kasse/categories
  PATCH  /kasse/categories/{category_id}
  DELETE /kasse/categories/{category_id}   (soft: is_active=false)
"""
from __future__ import annotations

import asyncio
import json
import re
from datetime import date, datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import RedirectResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import or_

from autotax import kasse_extract, kasse_r2, kasse_reports, kasse_service
from autotax.auth import get_current_user
from autotax.config import kasse_v2_enabled
from autotax.db import SessionLocal
from autotax.models import BackgroundJob, CashCategory, CashEntry, CashReport, KasseDocument

router = APIRouter(prefix="/kasse", tags=["kasse-v2 (flag-gated, default OFF)"])

_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
_VALID_KIND = {"income", "expense", "both"}


def _require_flag() -> None:
    if not kasse_v2_enabled():
        raise HTTPException(status_code=404, detail="Not found")


def _uid(user: dict) -> int:
    return int(user["sub"])


# ── request models ───────────────────────────────────────────────────
class CategoryCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)
    kind: str = Field(..., description="income | expense | both")
    datev_konto: Optional[str] = None
    euer_line: Optional[str] = None
    default_vat_rate: Optional[str] = None
    color: Optional[str] = None
    icon: Optional[str] = None
    sort_order: int = 0


class CategoryUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=80)
    kind: Optional[str] = None
    datev_konto: Optional[str] = None
    euer_line: Optional[str] = None
    default_vat_rate: Optional[str] = None
    color: Optional[str] = None
    icon: Optional[str] = None
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None


def _cat_dict(c: CashCategory) -> dict:
    return {
        "id": c.id, "user_id": c.user_id, "name": c.name, "kind": c.kind,
        "datev_konto": c.datev_konto, "euer_line": c.euer_line,
        "default_vat_rate": c.default_vat_rate, "color": c.color, "icon": c.icon,
        "sort_order": c.sort_order, "is_system": c.is_system, "is_active": c.is_active,
    }


# ── summaries / dashboard ────────────────────────────────────────────
@router.get("/dashboard", summary="Kasa dashboard cards (read-only)")
def kasse_dashboard(target: Optional[date] = Query(None, alias="date"), user: dict = Depends(get_current_user)) -> dict:
    _require_flag()
    db = SessionLocal()
    try:
        return kasse_service.dashboard(db, _uid(user), target or date.today())
    finally:
        db.close()


@router.get("/summary/daily", summary="Daily cash summary (read-only)")
def summary_daily(target: Optional[date] = Query(None, alias="date"), user: dict = Depends(get_current_user)) -> dict:
    _require_flag()
    db = SessionLocal()
    try:
        return kasse_service.daily(db, _uid(user), target or date.today())
    finally:
        db.close()


@router.get("/summary/weekly", summary="Weekly cash summary (read-only)")
def summary_weekly(target: Optional[date] = Query(None, alias="date"), user: dict = Depends(get_current_user)) -> dict:
    _require_flag()
    db = SessionLocal()
    try:
        return kasse_service.weekly(db, _uid(user), target or date.today())
    finally:
        db.close()


@router.get("/summary/monthly", summary="Monthly cash summary (read-only)")
def summary_monthly(month: Optional[str] = Query(None, description="YYYY-MM"), user: dict = Depends(get_current_user)) -> dict:
    _require_flag()
    if month is not None and not _MONTH_RE.match(month):
        raise HTTPException(status_code=422, detail="month must be YYYY-MM")
    today = date.today()
    y, m = (int(month[:4]), int(month[5:7])) if month else (today.year, today.month)
    db = SessionLocal()
    try:
        return kasse_service.monthly(db, _uid(user), y, m)
    finally:
        db.close()


# ── categories CRUD ──────────────────────────────────────────────────
@router.get("/categories", summary="List categories (own + system)")
def list_categories(user: dict = Depends(get_current_user)) -> dict:
    _require_flag()
    uid = _uid(user)
    db = SessionLocal()
    try:
        rows = db.query(CashCategory).filter(
            or_(CashCategory.user_id == uid, CashCategory.user_id.is_(None)),
            CashCategory.is_active == True,  # noqa: E712
        ).order_by(CashCategory.sort_order, CashCategory.name).all()
        return {"categories": [_cat_dict(c) for c in rows]}
    finally:
        db.close()


@router.post("/categories", summary="Create a category (own)")
def create_category(body: CategoryCreate, user: dict = Depends(get_current_user)) -> dict:
    _require_flag()
    if body.kind not in _VALID_KIND:
        raise HTTPException(status_code=422, detail="kind must be income|expense|both")
    uid = _uid(user)
    db = SessionLocal()
    try:
        dup = db.query(CashCategory).filter(CashCategory.user_id == uid, CashCategory.name == body.name).first()
        if dup:
            raise HTTPException(status_code=409, detail="Kategorie existiert bereits")
        c = CashCategory(
            user_id=uid, name=body.name, kind=body.kind, datev_konto=body.datev_konto,
            euer_line=body.euer_line, default_vat_rate=body.default_vat_rate,
            color=body.color, icon=body.icon, sort_order=body.sort_order,
            is_system=False, is_active=True,
        )
        db.add(c); db.commit(); db.refresh(c)
        return _cat_dict(c)
    finally:
        db.close()


@router.patch("/categories/{category_id}", summary="Update own category")
def update_category(category_id: int, body: CategoryUpdate, user: dict = Depends(get_current_user)) -> dict:
    _require_flag()
    uid = _uid(user)
    db = SessionLocal()
    try:
        c = db.query(CashCategory).filter(CashCategory.id == category_id, CashCategory.user_id == uid).first()
        if not c:
            raise HTTPException(status_code=404, detail="Kategorie nicht gefunden")
        if body.kind is not None and body.kind not in _VALID_KIND:
            raise HTTPException(status_code=422, detail="kind must be income|expense|both")
        for field in ("name", "kind", "datev_konto", "euer_line", "default_vat_rate", "color", "icon", "sort_order", "is_active"):
            val = getattr(body, field)
            if val is not None:
                setattr(c, field, val)
        db.commit(); db.refresh(c)
        return _cat_dict(c)
    finally:
        db.close()


@router.delete("/categories/{category_id}", summary="Soft-delete own category")
def delete_category(category_id: int, user: dict = Depends(get_current_user)) -> dict:
    _require_flag()
    uid = _uid(user)
    db = SessionLocal()
    try:
        c = db.query(CashCategory).filter(CashCategory.id == category_id, CashCategory.user_id == uid).first()
        if not c:
            raise HTTPException(status_code=404, detail="Kategorie nicht gefunden")
        c.is_active = False  # soft: preserves historical entry links
        db.commit()
        return {"success": True, "id": category_id}
    finally:
        db.close()


# ── document upload + extraction ─────────────────────────────────────
_MAX_UPLOAD = 10 * 1024 * 1024  # 10 MB


def _entry_preview(entry, extract: dict) -> dict:
    return {
        "id": entry.id, "entry_type": entry.entry_type, "description": entry.description,
        "gross_amount": entry.gross_amount, "vat_amount": entry.vat_amount,
        "net_amount": entry.net_amount, "date": entry.date.isoformat() if entry.date else None,
        "status": entry.status, "source": entry.source,
        "confidence": extract.get("confidence"), "band": extract.get("band"),
        "model": extract.get("model"), "fallback_used": extract.get("fallback_used"),
    }


def _store_document(db, uid: int, content: bytes, content_type: str, doc_kind: str, business_type: str) -> KasseDocument:
    """Dedup by (user_id, sha256); store in R2 (or local fallback) if new."""
    digest = kasse_r2.sha256(content)
    existing = db.query(KasseDocument).filter(KasseDocument.user_id == uid, KasseDocument.sha256 == digest).first()
    if existing:
        return existing
    stored = kasse_r2.put_image(uid, content, content_type)
    doc = KasseDocument(
        user_id=uid, r2_key=stored["key"], content_type=content_type, sha256=digest,
        doc_kind=doc_kind, business_type=(business_type or None),
        created_at=datetime.now(timezone.utc),
    )
    db.add(doc); db.commit(); db.refresh(doc)
    return doc


async def _extract_for(content: bytes, content_type: str, doc_kind: str, business_type: str) -> dict:
    """doc_kind 'auto' (default) → OCR once, then heuristically classify
    pos vs expense (user is never asked). 'expense'/'pos' force the type."""
    is_pdf = (content_type or "").lower() == "application/pdf"
    pdf_bytes = content if is_pdf else None
    ocr_text = ""
    if not is_pdf:
        try:
            from autotax.ocr import extract_image_text
            ocr_text = await extract_image_text(content, "kasse") or ""
        except Exception:
            ocr_text = ""
    if doc_kind not in ("expense", "pos"):  # 'auto' or unknown → detect
        doc_kind = kasse_extract.classify_doc_kind(ocr_text)
    if doc_kind == "pos":
        return await kasse_extract.extract_pos(content, business_type=business_type, content_type=content_type)
    return await kasse_extract.extract_expense(pdf_bytes=pdf_bytes, ocr_text=ocr_text)


@router.post("/upload", summary="Upload one document → extract → reviewable Kasa entry (sync)")
async def kasse_upload(
    file: UploadFile = File(...),
    doc_kind: str = Form("auto"),
    business_type: str = Form(""),
    user: dict = Depends(get_current_user),
) -> dict:
    _require_flag()
    if doc_kind not in ("expense", "pos", "auto"):
        raise HTTPException(status_code=422, detail="doc_kind must be expense|pos|auto")
    content = await file.read()
    if not content:
        raise HTTPException(status_code=422, detail="empty file")
    if len(content) > _MAX_UPLOAD:
        raise HTTPException(status_code=413, detail="file too large (max 10MB)")
    content_type = file.content_type or "image/jpeg"
    uid = _uid(user)

    extract = await _extract_for(content, content_type, doc_kind, business_type)

    db = SessionLocal()
    try:
        doc = _store_document(db, uid, content, content_type, doc_kind, business_type)
        entry = kasse_service.create_entry_from_extraction(db, uid, extract, document_id=doc.id)
        return {"document_id": doc.id, "entry": _entry_preview(entry, extract),
                "review_required": entry.status != "confirmed"}
    finally:
        db.close()


class KasseEntryUpdate(BaseModel):
    description: Optional[str] = None
    vendor: Optional[str] = None
    gross_amount: Optional[float] = None
    vat_amount: Optional[float] = None
    vat_rate: Optional[str] = None
    category: Optional[str] = None
    category_id: Optional[int] = None
    entry_type: Optional[str] = None


def _full_entry(e) -> dict:
    return {
        "id": e.id, "entry_type": e.entry_type, "description": e.description, "vendor": e.vendor,
        "gross_amount": e.gross_amount, "vat_amount": e.vat_amount, "net_amount": e.net_amount,
        "vat_rate": e.vat_rate, "category": e.category, "category_id": e.category_id,
        "status": e.status, "source": e.source, "date": e.date.isoformat() if e.date else None,
    }


def _learn(uid: int, entry, original: dict) -> None:
    """Phase-1 learning: vendor_aliases via LearningRule (best-effort)."""
    try:
        from autotax.learning import save_learning_rule
        edited = {"vendor": entry.vendor, "vat_rate": entry.vat_rate, "category": entry.category}
        keyword = (entry.vendor or entry.description or "").strip()
        if keyword:
            save_learning_rule(uid, keyword, original, edited)
    except Exception:
        pass  # learning must never break the user action


@router.patch("/entry/{entry_id}", summary="Edit a Kasa entry (records learning)")
def kasse_edit_entry(entry_id: int, body: KasseEntryUpdate, user: dict = Depends(get_current_user)) -> dict:
    _require_flag()
    uid = _uid(user)
    db = SessionLocal()
    try:
        e = db.query(CashEntry).filter(CashEntry.id == entry_id, CashEntry.user_id == uid,
                                       (CashEntry.is_deleted == False) | (CashEntry.is_deleted.is_(None))).first()  # noqa: E712
        if not e:
            raise HTTPException(status_code=404, detail="Eintrag nicht gefunden")
        original = {"vendor": e.vendor, "vat_rate": e.vat_rate, "category": e.category}
        if body.entry_type is not None and body.entry_type not in ("income", "expense"):
            raise HTTPException(status_code=422, detail="entry_type must be income|expense")
        for f in ("description", "vendor", "gross_amount", "vat_amount", "vat_rate", "category", "category_id", "entry_type"):
            v = getattr(body, f)
            if v is not None:
                setattr(e, f, v)
        if e.gross_amount is not None and e.vat_amount is not None:
            e.net_amount = e.gross_amount - e.vat_amount
        db.commit(); db.refresh(e)
        if e.source == "ocr":
            _learn(uid, e, original)
        return _full_entry(e)
    finally:
        db.close()


@router.post("/entry/{entry_id}/confirm", summary="Confirm a pending Kasa entry (books it)")
def kasse_confirm_entry(entry_id: int, user: dict = Depends(get_current_user)) -> dict:
    _require_flag()
    uid = _uid(user)
    db = SessionLocal()
    try:
        e = db.query(CashEntry).filter(CashEntry.id == entry_id, CashEntry.user_id == uid,
                                       (CashEntry.is_deleted == False) | (CashEntry.is_deleted.is_(None))).first()  # noqa: E712
        if not e:
            raise HTTPException(status_code=404, detail="Eintrag nicht gefunden")
        # learning from AI-extracted original vs confirmed values
        original = {}
        if e.source == "ocr" and e.extraction_meta:
            try:
                raw = (json.loads(e.extraction_meta) or {}).get("raw") or {}
                original = {"vendor": raw.get("vendor"), "vat_rate": raw.get("vat_rate"), "category": raw.get("category")}
            except Exception:
                original = {}
        e.status = "confirmed"
        db.commit(); db.refresh(e)
        if e.source == "ocr":
            _learn(uid, e, original)
        return _full_entry(e)
    finally:
        db.close()


async def _process_batch(uid: int, items: list[tuple], job_id: int) -> None:
    db = SessionLocal()
    processed, entry_ids = 0, []
    try:
        for content, content_type, doc_kind, business_type in items:
            try:
                extract = await _extract_for(content, content_type, doc_kind, business_type)
                doc = _store_document(db, uid, content, content_type, doc_kind, business_type)
                entry = kasse_service.create_entry_from_extraction(db, uid, extract, document_id=doc.id)
                processed += 1; entry_ids.append(entry.id)
            except Exception:
                pass
        job = db.query(BackgroundJob).filter(BackgroundJob.id == job_id).first()
        if job:
            job.status = "success"; job.finished_at = datetime.now(timezone.utc)
            job.payload = json.dumps({"processed": processed, "entry_ids": entry_ids})
            db.commit()
    except Exception:
        job = db.query(BackgroundJob).filter(BackgroundJob.id == job_id).first()
        if job:
            job.status = "failed"; job.finished_at = datetime.now(timezone.utc); db.commit()
    finally:
        db.close()


@router.post("/upload-batch", summary="Upload multiple documents → background processing", status_code=202)
async def kasse_upload_batch(
    files: list[UploadFile] = File(...),
    doc_kind: str = Form("auto"),
    business_type: str = Form(""),
    user: dict = Depends(get_current_user),
) -> dict:
    _require_flag()
    if doc_kind not in ("expense", "pos", "auto"):
        raise HTTPException(status_code=422, detail="doc_kind must be expense|pos|auto")
    uid = _uid(user)
    items = []
    for f in files:
        content = await f.read()
        if content and len(content) <= _MAX_UPLOAD:
            items.append((content, f.content_type or "image/jpeg", doc_kind, business_type))
    if not items:
        raise HTTPException(status_code=422, detail="no valid files")
    db = SessionLocal()
    try:
        job = BackgroundJob(job_type="kasse_ocr", user_id=uid, status="running",
                            started_at=datetime.now(timezone.utc), payload=json.dumps({"count": len(items)}))
        db.add(job); db.commit(); db.refresh(job)
        job_id = job.id
    finally:
        db.close()
    asyncio.create_task(_process_batch(uid, items, job_id))
    return {"job_id": job_id, "queued": len(items), "status": "running"}


class ReportCreate(BaseModel):
    report_type: str = Field(..., description="daily | weekly | monthly")
    period: Optional[str] = Field(None, description="daily/weekly=YYYY-MM-DD, monthly=YYYY-MM; default=today")


def _default_period(report_type: str) -> str:
    today = date.today()
    return today.strftime("%Y-%m") if report_type == "monthly" else today.isoformat()


@router.post("/report", summary="Generate a PDF report (daily/weekly/monthly)")
def kasse_create_report(body: ReportCreate, user: dict = Depends(get_current_user)) -> dict:
    _require_flag()
    if body.report_type not in ("daily", "weekly", "monthly"):
        raise HTTPException(status_code=422, detail="report_type must be daily|weekly|monthly")
    period = body.period or _default_period(body.report_type)
    uid = _uid(user)
    db = SessionLocal()
    try:
        try:
            pdf, summary = kasse_reports.build_report(db, uid, body.report_type, period)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
        rep = kasse_reports.store_report(db, uid, body.report_type, summary, pdf)
        return {"report_id": rep.id, "download_url": f"/kasse/report/{rep.id}/download",
                "totals": {"income": summary["total_income"], "expense": summary["total_expense"], "profit": summary["profit"]}}
    finally:
        db.close()


@router.get("/reports", summary="List generated reports")
def kasse_list_reports(user: dict = Depends(get_current_user)) -> dict:
    _require_flag()
    db = SessionLocal()
    try:
        rows = db.query(CashReport).filter(CashReport.user_id == _uid(user)).order_by(CashReport.created_at.desc()).limit(100).all()
        return {"reports": [{
            "id": r.id, "report_type": r.report_type,
            "period_start": r.period_start.isoformat() if r.period_start else None,
            "period_end": r.period_end.isoformat() if r.period_end else None,
            "total_income": r.total_income, "total_expense": r.total_expense, "profit": r.profit,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        } for r in rows]}
    finally:
        db.close()


@router.get("/report/{report_id}/download", summary="Download a report PDF")
def kasse_download_report(report_id: int, user: dict = Depends(get_current_user)):
    _require_flag()
    db = SessionLocal()
    try:
        rep = db.query(CashReport).filter(CashReport.id == report_id, CashReport.user_id == _uid(user)).first()
        if not rep or not rep.r2_key:
            raise HTTPException(status_code=404, detail="Report nicht gefunden")
        url = kasse_r2.presign(rep.r2_key)
        if url:
            return RedirectResponse(url)
        pdf = kasse_r2.get_image(rep.r2_key)
        return Response(content=pdf, media_type="application/pdf",
                        headers={"Content-Disposition": f'inline; filename="kasse_{rep.report_type}_{rep.id}.pdf"'})
    finally:
        db.close()


@router.get("/document/{document_id}", summary="View/download an original document (own only)")
def kasse_document_view(document_id: int, user: dict = Depends(get_current_user)):
    _require_flag()
    db = SessionLocal()
    try:
        doc = db.query(KasseDocument).filter(KasseDocument.id == document_id, KasseDocument.user_id == _uid(user)).first()
        if not doc or not doc.r2_key:
            raise HTTPException(status_code=404, detail="Dokument nicht gefunden")
        url = kasse_r2.presign(doc.r2_key)
        if url:
            return RedirectResponse(url)
        data = kasse_r2.get_image(doc.r2_key)
        return Response(content=data, media_type=doc.content_type or "application/octet-stream",
                        headers={"Content-Disposition": f'inline; filename="beleg_{doc.id}"'})
    finally:
        db.close()


@router.get("/jobs/{job_id}", summary="Batch upload job status")
def kasse_job_status(job_id: int, user: dict = Depends(get_current_user)) -> dict:
    _require_flag()
    db = SessionLocal()
    try:
        job = db.query(BackgroundJob).filter(BackgroundJob.id == job_id, BackgroundJob.user_id == _uid(user)).first()
        if not job:
            raise HTTPException(status_code=404, detail="job not found")
        payload = {}
        try:
            payload = json.loads(job.payload) if job.payload else {}
        except Exception:
            payload = {}
        return {"job_id": job.id, "status": job.status, "started_at": job.started_at.isoformat() if job.started_at else None,
                "finished_at": job.finished_at.isoformat() if job.finished_at else None, "result": payload}
    finally:
        db.close()
