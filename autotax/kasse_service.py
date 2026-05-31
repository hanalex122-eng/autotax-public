"""Kasa MVP — aggregation service (Sprint 1).

SINGLE SOURCE OF TRUTH. Dashboard, summary endpoints, PDF reports (S2) and
EÜR/Tax (S3) all call `summarize()` so the numbers can never diverge.

Pure & read-only: every function takes a `db` session and a `user_id`; no
SessionLocal, no writes, no side effects. Portable SQLAlchemy ORM aggregation
(runs on PostgreSQL prod and SQLite tests). All queries are user-scoped and
exclude soft-deleted + not-yet-confirmed (pending_review) entries.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import func

from autotax.models import CashCategory, CashEntry

# Rough effective tax rate for the dashboard "estimated tax" card. This is an
# UNVERBINDLICHE SCHÄTZUNG only — never presented as binding tax advice.
_EST_TAX_RATE = 0.29


# ── date range helpers (half-open [start, end)) ──────────────────────
def day_range(d: date) -> tuple[datetime, datetime]:
    start = datetime(d.year, d.month, d.day)
    return start, start + timedelta(days=1)


def week_range(d: date) -> tuple[datetime, datetime]:
    monday = d - timedelta(days=d.weekday())  # ISO: Monday=0
    start = datetime(monday.year, monday.month, monday.day)
    return start, start + timedelta(days=7)


def month_range(year: int, month: int) -> tuple[datetime, datetime]:
    start = datetime(year, month, 1)
    end = datetime(year + 1, 1, 1) if month == 12 else datetime(year, month + 1, 1)
    return start, end


def _base_filter(q, user_id: int):
    """User-scoped + exclude soft-deleted + exclude pending_review.

    Legacy rows may have status NULL (pre-migration) → treated as confirmed.
    """
    return q.filter(
        CashEntry.user_id == user_id,
        (CashEntry.is_deleted == False) | (CashEntry.is_deleted.is_(None)),  # noqa: E712
        (CashEntry.status == "confirmed") | (CashEntry.status.is_(None)),
    )


def summarize(db, user_id: int, start: datetime, end: datetime) -> dict[str, Any]:
    """Aggregate one half-open date range into a CashSummary dict."""
    rows = _base_filter(
        db.query(
            CashEntry.entry_type,
            CashEntry.category_id,
            func.coalesce(func.sum(CashEntry.gross_amount), 0.0),
            func.coalesce(func.sum(func.coalesce(CashEntry.vat_amount, 0.0)), 0.0),
            func.count(),
        ),
        user_id,
    ).filter(
        CashEntry.date >= start, CashEntry.date < end,
    ).group_by(CashEntry.entry_type, CashEntry.category_id).all()

    income_gross = income_vat = expense_gross = expense_vat = 0.0
    entry_count = 0
    cat_totals: dict[Any, dict] = {}

    for entry_type, category_id, gross, vat, n in rows:
        gross = float(gross or 0.0)
        vat = float(vat or 0.0)
        entry_count += int(n or 0)
        is_income = (entry_type == "income")
        if is_income:
            income_gross += gross
            income_vat += vat
        else:
            expense_gross += gross
            expense_vat += vat
        c = cat_totals.setdefault(category_id, {"category_id": category_id, "kind": entry_type, "total": 0.0})
        c["total"] += gross

    # Resolve category names (None -> "Sonstige")
    ids = [cid for cid in cat_totals if cid is not None]
    names: dict[int, str] = {}
    if ids:
        for cid, name in db.query(CashCategory.id, CashCategory.name).filter(CashCategory.id.in_(ids)).all():
            names[cid] = name
    by_category = []
    for cid, c in cat_totals.items():
        by_category.append({
            "category_id": cid,
            "name": names.get(cid, "Sonstige") if cid is not None else "Sonstige",
            "kind": c["kind"],
            "total": round(c["total"], 2),
        })
    by_category.sort(key=lambda x: x["total"], reverse=True)

    income_net = income_gross - income_vat
    expense_net = expense_gross - expense_vat
    return {
        "period_start": start.date().isoformat(),
        "period_end": end.date().isoformat(),
        "total_income": round(income_gross, 2),
        "total_expense": round(expense_gross, 2),
        "profit": round(income_net - expense_net, 2),
        "vat_collected": round(income_vat, 2),
        "vat_paid": round(expense_vat, 2),
        "entry_count": entry_count,
        "by_category": by_category,
    }


def daily(db, user_id: int, d: date) -> dict:
    s, e = day_range(d)
    out = summarize(db, user_id, s, e); out["period_type"] = "daily"; return out


def weekly(db, user_id: int, d: date) -> dict:
    s, e = week_range(d)
    out = summarize(db, user_id, s, e); out["period_type"] = "weekly"; return out


def monthly(db, user_id: int, year: int, month: int) -> dict:
    s, e = month_range(year, month)
    out = summarize(db, user_id, s, e); out["period_type"] = "monthly"; return out


def trend_30d(db, user_id: int, today: date) -> list[dict]:
    """Daily income/expense for the last 30 days (inclusive of today)."""
    start = datetime(today.year, today.month, today.day) - timedelta(days=29)
    end = datetime(today.year, today.month, today.day) + timedelta(days=1)
    rows = _base_filter(
        db.query(
            func.date(CashEntry.date),
            CashEntry.entry_type,
            func.coalesce(func.sum(CashEntry.gross_amount), 0.0),
        ),
        user_id,
    ).filter(CashEntry.date >= start, CashEntry.date < end).group_by(
        func.date(CashEntry.date), CashEntry.entry_type
    ).all()

    buckets: dict[str, dict] = {}
    for d_val, entry_type, gross in rows:
        key = str(d_val)[:10]
        b = buckets.setdefault(key, {"date": key, "income": 0.0, "expense": 0.0})
        if entry_type == "income":
            b["income"] += float(gross or 0.0)
        else:
            b["expense"] += float(gross or 0.0)
    return [
        {**buckets.get(
            (datetime(today.year, today.month, today.day) - timedelta(days=29 - i)).date().isoformat(),
            {"date": (datetime(today.year, today.month, today.day) - timedelta(days=29 - i)).date().isoformat(),
             "income": 0.0, "expense": 0.0})}
        for i in range(30)
    ]


def dashboard(db, user_id: int, today: date) -> dict:
    """Compose all dashboard cards from the single aggregation source."""
    td = daily(db, user_id, today)
    mo = monthly(db, user_id, today.year, today.month)
    est = round(max(mo["profit"], 0.0) * _EST_TAX_RATE, 2)
    return {
        "today": {"income": td["total_income"], "expense": td["total_expense"]},
        "month": {"income": mo["total_income"], "expense": mo["total_expense"], "profit": mo["profit"]},
        "estimated_tax": {"amount": est, "basis": f"profit*{_EST_TAX_RATE}", "disclaimer": "unverbindliche Schätzung"},
        "trend_30d": trend_30d(db, user_id, today),
    }
