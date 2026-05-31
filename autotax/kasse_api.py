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

import re
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import or_

from autotax import kasse_service
from autotax.auth import get_current_user
from autotax.config import kasse_v2_enabled
from autotax.db import SessionLocal
from autotax.models import CashCategory

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
