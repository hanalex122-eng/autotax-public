"""Kasa MVP Sprint 2 — integration tests (stdlib unittest, SQLite + mocks).

Run:  python -m unittest tests.test_kasse_s2

Mocks AI (ai_ocr) and OCR so no network/cv2 needed. Covers model routing,
banding, fallback, extraction→entry (pilot no-autobook), R2 local fallback +
dedup, learning (vendor_aliases), PDF reports (numbers == summarize),
endpoints (upload/confirm/edit/report), flag gate, auth, user isolation.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import unittest
from datetime import date, datetime

os.environ.setdefault("JWT_SECRET", "x" * 48)
os.environ["UPLOADS_DIR"] = "./_kasse_s2_uploads"

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from autotax.models import Base, User, CashEntry, CashReport, LearningRule
from autotax import kasse_extract as ke, kasse_service as ks, kasse_r2, kasse_reports

TODAY = date.today()


def _db():
    eng = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(eng)
    S = sessionmaker(bind=eng)
    db = S()
    db.add(User(id=1, email="a@b.c", hashed_password="x"))
    db.add(User(id=2, email="o@b.c", hashed_password="x"))
    db.commit()
    return eng, S, db


class TestRouting(unittest.TestCase):
    def test_route_and_band(self):
        self.assertEqual(ke.route_model(1), ke.DEFAULT_MODEL)
        self.assertEqual(ke.route_model(2), ke.FALLBACK_MODEL)
        self.assertEqual((ke.band(95), ke.band(80), ke.band(50)), ("auto", "review", "manual"))
        self.assertNotIn("haiku", (ke.DEFAULT_MODEL + ke.FALLBACK_MODEL).lower())

    def test_classify_doc_kind(self):
        self.assertEqual(ke.classify_doc_kind("Tagesabschluss Z-Bon Nr 42 Gesamtumsatz 980,00 Bediener Ali"), "pos")
        self.assertEqual(ke.classify_doc_kind("LIDL GmbH Summe 23,80 EUR MwSt 7%"), "expense")
        self.assertEqual(ke.classify_doc_kind(""), "expense")  # conservative default

    def test_needs_fallback(self):
        self.assertTrue(ke.needs_fallback("pos", None))
        self.assertTrue(ke.needs_fallback("expense", {"vat_amount": 5}))  # missing total+date
        self.assertTrue(ke.needs_fallback("pos", {"gross_revenue": 238, "net_revenue": 100, "vat_total": 38, "date": "2026-05-31", "confidence": 99}))  # inconsistent
        self.assertFalse(ke.needs_fallback("pos", {"gross_revenue": 238, "net_revenue": 200, "vat_total": 38, "cash": 238, "card": 0, "date": "2026-05-31", "confidence": 95}))

    def test_pos_fallback_to_opus(self):
        calls = []
        async def fake(img, business_type="", content_type="", model="", filename=""):
            calls.append(model)
            conf = 50 if model == ke.DEFAULT_MODEL else 95
            return {"gross_revenue": 238, "net_revenue": 200, "vat_total": 38, "cash": 238, "card": 0, "date": "2026-05-31", "confidence": conf}
        import autotax.ai_ocr as ai
        ai.ai_parse_pos_receipt = fake
        res = asyncio.run(ke.extract_pos(b"img", "doener"))
        self.assertEqual(calls, [ke.DEFAULT_MODEL, ke.FALLBACK_MODEL])
        self.assertTrue(res["fallback_used"])
        self.assertEqual(res["band"], "auto")


class TestCreateEntry(unittest.TestCase):
    def setUp(self):
        self.eng, self.S, self.db = _db()
        os.environ.pop("KASSE_AUTOBOOK", None)

    def test_pilot_no_autobook(self):
        extract = {"kind": "pos", "fields": {"gross_revenue": 238.0, "vat_total": 38.0, "net_revenue": 200.0, "date": "2026-05-31", "business_name": "Doener X"}, "confidence": 95, "band": "auto", "model": "claude-sonnet-4-6", "fallback_used": False}
        e = ks.create_entry_from_extraction(self.db, 1, extract, document_id=7, today=TODAY)
        self.assertEqual(e.status, "pending_review")  # PILOT: never auto-book
        self.assertEqual(e.entry_type, "income")
        self.assertEqual(e.gross_amount, 238.0)
        self.assertEqual(e.ocr_document_id, 7)
        self.assertIn("confidence", json.loads(e.extraction_meta))

    def test_expense_mapping(self):
        extract = {"kind": "expense", "fields": {"vendor": "Lidl", "total_amount": 23.8, "vat_amount": 1.56, "vat_rate": "7", "date": "2026-05-31", "category": "food"}, "confidence": 85, "band": "review", "model": "claude-sonnet-4-6", "fallback_used": False}
        e = ks.create_entry_from_extraction(self.db, 1, extract, document_id=None, today=TODAY)
        self.assertEqual(e.entry_type, "expense")
        self.assertEqual(e.vendor, "Lidl")
        self.assertAlmostEqual(e.net_amount, 23.8 - 1.56, places=2)
        self.assertEqual(e.status, "pending_review")


class TestR2(unittest.TestCase):
    def tearDown(self):
        shutil.rmtree("./_kasse_s2_uploads", ignore_errors=True)

    def test_local_fallback_and_roundtrip(self):
        r = kasse_r2.put_image(1, b"abc123", "image/jpeg")
        self.assertEqual(r["storage"], "local")  # no R2 env in test
        self.assertEqual(len(r["sha256"]), 64)
        self.assertEqual(kasse_r2.get_image(r["key"]), b"abc123")
        self.assertIsNone(kasse_r2.presign(r["key"]))
        self.assertEqual(kasse_r2.sha256(b"abc123"), r["sha256"])  # deterministic


class TestLearning(unittest.TestCase):
    def test_save_learning_rule(self):
        eng, S, db = _db()
        import autotax.learning as learning
        learning.SessionLocal = S  # point learning at the test DB
        learning.save_learning_rule(1, "Lidl Filiale 42", {"vendor": "LIDL", "category": "food"}, {"vendor": "Lidl GmbH", "category": "food"})
        self.assertGreater(db.query(LearningRule).filter(LearningRule.user_id == 1).count(), 0)


class TestPdf(unittest.TestCase):
    def tearDown(self):
        shutil.rmtree("./_kasse_s2_uploads", ignore_errors=True)

    def test_report_matches_summarize(self):
        eng, S, db = _db()
        db.add(CashEntry(user_id=1, description="Umsatz", entry_type="income", gross_amount=238.0, vat_amount=38.0,
                         date=datetime(TODAY.year, TODAY.month, TODAY.day, 10), status="confirmed"))
        db.commit()
        pdf, summary = kasse_reports.build_report(db, 1, "monthly", TODAY.strftime("%Y-%m"))
        self.assertTrue(pdf.startswith(b"%PDF"))
        m = ks.monthly(db, 1, TODAY.year, TODAY.month)
        self.assertEqual(summary["total_income"], m["total_income"])  # single source


def _client(S, auth=True, uid=1):
    import autotax.kasse_api as api
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from autotax.auth import get_current_user
    api.SessionLocal = S
    async def fake_extract(content, content_type, doc_kind, business_type):
        if doc_kind == "pos":
            return {"kind": "pos", "fields": {"gross_revenue": 238.0, "vat_total": 38.0, "net_revenue": 200.0, "date": TODAY.isoformat()}, "confidence": 95, "band": "auto", "model": "claude-sonnet-4-6", "fallback_used": False}
        return {"kind": "expense", "fields": {"vendor": "Lidl", "total_amount": 11.9, "vat_amount": 1.9, "vat_rate": "19", "date": TODAY.isoformat(), "category": "food"}, "confidence": 85, "band": "review", "model": "claude-sonnet-4-6", "fallback_used": False}
    api._extract_for = fake_extract
    app = FastAPI(); app.include_router(api.router)
    if auth:
        app.dependency_overrides[get_current_user] = lambda: {"sub": uid}
    return TestClient(app)


class TestEndpoints(unittest.TestCase):
    def setUp(self):
        self.eng, self.S, self.db = _db()
        os.environ["FEAT_KASSE_V2"] = "1"

    def tearDown(self):
        os.environ.pop("FEAT_KASSE_V2", None)
        shutil.rmtree("./_kasse_s2_uploads", ignore_errors=True)

    def test_upload_pilot_pending_and_dedup(self):
        c = _client(self.S)
        r = c.post("/kasse/upload", files={"file": ("b.jpg", b"imgbytes", "image/jpeg")}, data={"doc_kind": "expense"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["entry"]["status"], "pending_review")
        self.assertTrue(r.json()["review_required"])
        did = r.json()["document_id"]
        r2 = c.post("/kasse/upload", files={"file": ("b2.jpg", b"imgbytes", "image/jpeg")}, data={"doc_kind": "expense"})
        self.assertEqual(r2.json()["document_id"], did)  # dedup

    def test_confirm_and_isolation(self):
        c = _client(self.S)
        eid = c.post("/kasse/upload", files={"file": ("b.jpg", b"xx", "image/jpeg")}, data={"doc_kind": "expense"}).json()["entry"]["id"]
        self.assertEqual(c.post(f"/kasse/entry/{eid}/confirm").json()["status"], "confirmed")
        c2 = _client(self.S, uid=2)
        self.assertEqual(c2.post(f"/kasse/entry/{eid}/confirm").status_code, 404)

    def test_report_endpoint(self):
        self.db.add(CashEntry(user_id=1, description="U", entry_type="income", gross_amount=238.0, vat_amount=38.0,
                              date=datetime(TODAY.year, TODAY.month, TODAY.day, 10), status="confirmed"))
        self.db.commit()
        c = _client(self.S)
        r = c.post("/kasse/report", json={"report_type": "monthly"})
        self.assertEqual(r.status_code, 200)
        dl = c.get(f"/kasse/report/{r.json()['report_id']}/download")
        self.assertEqual(dl.status_code, 200)
        self.assertTrue(dl.content.startswith(b"%PDF"))

    def test_flag_off_and_auth(self):
        os.environ["FEAT_KASSE_V2"] = "0"
        c = _client(self.S)
        self.assertEqual(c.post("/kasse/upload", files={"file": ("b.jpg", b"x", "image/jpeg")}, data={"doc_kind": "expense"}).status_code, 404)
        os.environ["FEAT_KASSE_V2"] = "1"
        cna = _client(self.S, auth=False)
        self.assertEqual(cna.get("/kasse/reports").status_code, 401)


class TestRegression(unittest.TestCase):
    def test_imports(self):
        import autotax.declaration as decl
        self.assertGreater(len(decl.FORM_SECTIONS), 0)
        import autotax.kasse_api  # noqa: F401


if __name__ == "__main__":
    unittest.main(verbosity=2)
