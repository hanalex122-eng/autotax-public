"""Phase / API integration tests for the tax-engine v2 router (stdlib unittest).

Run:  python -m unittest tax_engine.tests.test_api

Covers all four endpoints, the feature-flag gate (404 when OFF, 200 when ON),
JSON-only responses, and OpenAPI documentation presence. Builds a minimal
FastAPI app that mounts ONLY the new router and overrides auth — it does not
import autotax.main, so it exercises the router in isolation without DB or
production startup.
"""
from __future__ import annotations

import os
import unittest

# auth.py fails fast without JWT_SECRET; set a dummy before importing.
os.environ.setdefault("JWT_SECRET", "x" * 48)

from fastapi import FastAPI
from fastapi.testclient import TestClient

from autotax.auth import get_current_user
from autotax.tax_engine_api import router


def _make_client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: {"sub": "1", "email": "test@example.com"}
    return TestClient(app)


class TestFeatureFlagGate(unittest.TestCase):
    def setUp(self):
        self.client = _make_client()

    def tearDown(self):
        os.environ.pop("TAX_ENGINE_V2_ENABLED", None)

    def test_endpoints_404_when_flag_off(self):
        os.environ["TAX_ENGINE_V2_ENABLED"] = "0"
        for path in ("/tax/2024/detect", "/tax/2024/questionnaire/start",
                     "/tax/2024/questionnaire/next", "/tax/2024/build"):
            r = self.client.post(path, json={"profile": {}})
            self.assertEqual(r.status_code, 404, f"{path} should be 404 when flag off")

    def test_endpoints_live_when_flag_on(self):
        os.environ["TAX_ENGINE_V2_ENABLED"] = "1"
        r = self.client.post("/tax/2024/detect", json={"profile": {"employment": True}})
        self.assertEqual(r.status_code, 200)


class TestEndpoints(unittest.TestCase):
    def setUp(self):
        os.environ["TAX_ENGINE_V2_ENABLED"] = "1"
        self.client = _make_client()

    def tearDown(self):
        os.environ.pop("TAX_ENGINE_V2_ENABLED", None)

    def test_detect_returns_forms_json(self):
        r = self.client.post("/tax/2024/detect", json={"profile": {"gewerbe": True, "profit": 45000, "kleinunternehmer": False}})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers["content-type"].split(";")[0], "application/json")
        data = r.json()
        keys = {f["formKey"] for f in data["required_forms"]}
        self.assertIn("anlage_g", keys)
        self.assertIn("gewst_1a", keys)
        self.assertEqual(data["year"], 2024)
        self.assertGreaterEqual(data["confidence_score"], 0.0)

    def test_questionnaire_start_returns_first_question(self):
        r = self.client.post("/tax/2024/questionnaire/start", json={"profile": {}})
        self.assertEqual(r.status_code, 200)
        node = r.json()["node"]
        self.assertEqual(node["nodeKey"], "q_year")
        self.assertIn("question", node)
        # must not leak raw form fields
        self.assertNotIn("fields", node)

    def test_questionnaire_next_advances(self):
        start = self.client.post("/tax/2024/questionnaire/start", json={"profile": {}}).json()
        r = self.client.post("/tax/2024/questionnaire/next", json={
            "answers": start["answers"], "current_node": "q_year", "answer": "2024",
        })
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertFalse(body["done"])
        self.assertEqual(body["node"]["nodeKey"], "q_marital")

    def test_build_returns_full_declaration(self):
        r = self.client.post("/tax/2024/build", json={"profile": {"employment": True, "children": 1}})
        self.assertEqual(r.status_code, 200)
        data = r.json()
        for key in ("forms", "validation", "missing_documents", "optimization_suggestions", "interview"):
            self.assertIn(key, data)
        self.assertEqual(data["year"], 2024)
        self.assertGreater(len(data["forms"]), 0)

    def test_year_path_validation(self):
        r = self.client.post("/tax/1999/detect", json={"profile": {}})
        self.assertEqual(r.status_code, 422)  # year < 2020 rejected by Path(ge=2020)


class TestOpenAPI(unittest.TestCase):
    def test_endpoints_documented(self):
        app = FastAPI()
        app.include_router(router)
        schema = app.openapi()
        paths = schema["paths"]
        for p in ("/tax/{year}/detect", "/tax/{year}/questionnaire/start",
                  "/tax/{year}/questionnaire/next", "/tax/{year}/build"):
            self.assertIn(p, paths, f"{p} missing from OpenAPI schema")
            self.assertIn("post", paths[p])
            self.assertIn("summary", paths[p]["post"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
