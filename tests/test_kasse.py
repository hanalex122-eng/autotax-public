"""Kasa MVP Sprint 1 — integration tests (stdlib unittest, no pytest).

Run:  python -m unittest tests.test_kasse

Uses an in-memory SQLite (StaticPool) seeded with sample entries. Service is
tested directly; the API is tested via TestClient with SessionLocal
monkeypatched to the test DB and auth overridden. Covers: aggregation
correctness, exclusions (deleted/pending/other-user), single-source-of-truth
equality, flag gate (404), auth (401), category CRUD, user isolation, seeder
idempotency, and no-regression of existing modules.
"""
from __future__ import annotations

import os
import unittest
from datetime import date, datetime, timedelta

os.environ.setdefault("JWT_SECRET", "x" * 48)

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from autotax.models import Base, User, CashEntry, CashCategory
from autotax import kasse_service as ks
from autotax.kasse_seed import seed_system_categories

TODAY = date.today()
NOW = datetime(TODAY.year, TODAY.month, TODAY.day, 10, 0, 0)
LAST_MONTH = (TODAY.replace(day=1) - timedelta(days=1))


def _make_db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    db.add(User(id=1, email="a@b.c", hashed_password="x"))
    db.add(User(id=2, email="other@b.c", hashed_password="x"))
    db.add(CashCategory(id=10, user_id=1, name="Wareneinkauf", kind="expense"))
    # user 1 — today
    db.add(CashEntry(user_id=1, description="Umsatz", entry_type="income", gross_amount=238.0, vat_amount=38.0, vat_rate="19", date=NOW, status="confirmed"))
    db.add(CashEntry(user_id=1, description="Einkauf", entry_type="expense", gross_amount=119.0, vat_amount=19.0, vat_rate="19", category_id=10, date=NOW, status="confirmed"))
    # excluded: deleted / pending / last-month / other-user
    db.add(CashEntry(user_id=1, description="del", entry_type="income", gross_amount=999.0, date=NOW, status="confirmed", is_deleted=True))
    db.add(CashEntry(user_id=1, description="pend", entry_type="expense", gross_amount=500.0, date=NOW, status="pending_review"))
    db.add(CashEntry(user_id=1, description="lastmonth", entry_type="income", gross_amount=1000.0, date=datetime(LAST_MONTH.year, LAST_MONTH.month, LAST_MONTH.day), status="confirmed"))
    db.add(CashEntry(user_id=2, description="other", entry_type="income", gross_amount=777.0, date=NOW, status="confirmed"))
    db.commit()
    return engine, Session, db


class TestService(unittest.TestCase):
    def setUp(self):
        self.engine, self.Session, self.db = _make_db()

    def test_daily_sums_and_exclusions(self):
        d = ks.daily(self.db, 1, TODAY)
        self.assertEqual(d["total_income"], 238.0)   # excludes deleted/pending/other-user
        self.assertEqual(d["total_expense"], 119.0)
        self.assertEqual(d["vat_collected"], 38.0)
        self.assertEqual(d["vat_paid"], 19.0)
        self.assertEqual(d["profit"], round((238 - 38) - (119 - 19), 2))

    def test_monthly_excludes_last_month(self):
        m = ks.monthly(self.db, 1, TODAY.year, TODAY.month)
        self.assertEqual(m["total_income"], 238.0)   # 1000 last-month excluded

    def test_user_isolation(self):
        self.assertEqual(ks.daily(self.db, 2, TODAY)["total_income"], 777.0)
        self.assertEqual(ks.daily(self.db, 1, TODAY)["total_income"], 238.0)

    def test_single_source_equality(self):
        dash = ks.dashboard(self.db, 1, TODAY)
        m = ks.monthly(self.db, 1, TODAY.year, TODAY.month)
        self.assertEqual(dash["month"]["income"], m["total_income"])
        self.assertEqual(dash["month"]["profit"], m["profit"])

    def test_by_category_names(self):
        m = ks.monthly(self.db, 1, TODAY.year, TODAY.month)
        cats = {c["name"]: c for c in m["by_category"]}
        self.assertIn("Wareneinkauf", cats)
        self.assertIn("Sonstige", cats)  # income had no category_id


def _client(engine, Session, auth=True, uid=1):
    import autotax.kasse_api as api
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from autotax.auth import get_current_user
    api.SessionLocal = Session  # monkeypatch to test DB
    app = FastAPI()
    app.include_router(api.router)
    if auth:
        app.dependency_overrides[get_current_user] = lambda: {"sub": uid, "email": "t@e.c"}
    return TestClient(app)


class TestApi(unittest.TestCase):
    def setUp(self):
        self.engine, self.Session, self.db = _make_db()
        os.environ["FEAT_KASSE_V2"] = "1"

    def tearDown(self):
        os.environ.pop("FEAT_KASSE_V2", None)

    def test_flag_off_returns_404(self):
        os.environ["FEAT_KASSE_V2"] = "0"
        c = _client(self.engine, self.Session)
        self.assertEqual(c.get("/kasse/dashboard").status_code, 404)

    def test_auth_required_401(self):
        c = _client(self.engine, self.Session, auth=False)
        self.assertEqual(c.get("/kasse/dashboard").status_code, 401)

    def test_dashboard_ok(self):
        c = _client(self.engine, self.Session)
        r = c.get("/kasse/dashboard")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["today"]["income"], 238.0)
        self.assertEqual(data["month"]["expense"], 119.0)
        self.assertEqual(len(data["trend_30d"]), 30)
        self.assertIn("disclaimer", data["estimated_tax"])

    def test_summary_monthly_validation(self):
        c = _client(self.engine, self.Session)
        self.assertEqual(c.get("/kasse/summary/monthly?month=2026-13").status_code, 422)
        ok = c.get(f"/kasse/summary/monthly?month={TODAY.strftime('%Y-%m')}")
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(ok.json()["total_income"], 238.0)

    def test_categories_crud(self):
        c = _client(self.engine, self.Session)
        # list: own (Wareneinkauf)
        names = [x["name"] for x in c.get("/kasse/categories").json()["categories"]]
        self.assertIn("Wareneinkauf", names)
        # create
        r = c.post("/kasse/categories", json={"name": "Trinkgeld", "kind": "income"})
        self.assertEqual(r.status_code, 200)
        cid = r.json()["id"]
        # duplicate -> 409
        self.assertEqual(c.post("/kasse/categories", json={"name": "Trinkgeld", "kind": "income"}).status_code, 409)
        # invalid kind -> 422
        self.assertEqual(c.post("/kasse/categories", json={"name": "X", "kind": "bogus"}).status_code, 422)
        # patch
        self.assertEqual(c.patch(f"/kasse/categories/{cid}", json={"name": "Tips"}).status_code, 200)
        # delete (soft)
        self.assertEqual(c.delete(f"/kasse/categories/{cid}").status_code, 200)
        names2 = [x["name"] for x in c.get("/kasse/categories").json()["categories"]]
        self.assertNotIn("Tips", names2)  # soft-deleted -> inactive

    def test_user_isolation_api(self):
        c2 = _client(self.engine, self.Session, uid=2)
        # user 2 cannot patch user 1's category 10
        self.assertEqual(c2.patch("/kasse/categories/10", json={"name": "hack"}).status_code, 404)


class TestSeedIdempotent(unittest.TestCase):
    def test_idempotent(self):
        _, _, db = _make_db()
        n1 = seed_system_categories(db)
        n2 = seed_system_categories(db)
        total = db.query(CashCategory).filter(CashCategory.user_id.is_(None)).count()
        self.assertEqual(n2, 0)
        self.assertEqual(total, n1)
        self.assertGreater(n1, 0)


class TestNoRegression(unittest.TestCase):
    def test_existing_modules_import(self):
        import autotax.declaration as decl
        self.assertTrue(hasattr(decl, "FORM_SECTIONS"))
        self.assertGreater(len(decl.FORM_SECTIONS), 0)
        import autotax.config as cfg
        self.assertIsInstance(cfg.kasse_v2_enabled(), bool)


if __name__ == "__main__":
    unittest.main(verbosity=2)
