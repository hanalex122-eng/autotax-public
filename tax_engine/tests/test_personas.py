"""Phase E — integration tests (stdlib unittest, no pytest dependency).

Run:  python -m unittest tax_engine.tests.test_personas
  or:  python tax_engine/tests/test_personas.py

Asserts:
- Knowledge base loads (Phase A).
- Detection covers every persona's expected forms with no missing mandatory
  form; average coverage >= 95% (Phase B / regression gate).
- Multi-instance counts correct where specified.
- Questionnaire runtime yields questions and never leaks raw form fields (Phase C).
- Declaration builder produces a complete, serialisable object (Phase D).
- No regression: existing autotax.declaration still imports with FORM_SECTIONS.
"""
from __future__ import annotations

import json
import unittest

from tax_engine import builder, detection, loader, questionnaire
from tax_engine.personas import INSTANCE_EXPECTATIONS, PERSONAS

COVERAGE_TARGET = 0.95


class TestPhaseALoader(unittest.TestCase):
    def test_all_four_files_load(self):
        self.assertGreaterEqual(len(loader.forms()), 21)
        self.assertGreaterEqual(len(loader.questionnaire_nodes()), 20)
        self.assertGreaterEqual(len(loader.graph_nodes()), 50)
        self.assertGreaterEqual(len(loader.optimization_rules()), 40)

    def test_accessors(self):
        self.assertIsNotNone(loader.form_by_key("anlage_av"))
        self.assertIn("anlage_kind", loader.multi_instance_forms())
        self.assertIsNotNone(loader.rule_by_key("homeoffice_pauschale"))


class TestPhaseBDetection(unittest.TestCase):
    def test_no_missing_mandatory_form_per_persona(self):
        for p in PERSONAS:
            detected = detection.required_form_keys(p["profile"])
            missing = p["expected"] - detected
            self.assertEqual(missing, set(), f"{p['id']}: missing mandatory forms {missing}")

    def test_average_coverage_at_least_95(self):
        ratios = []
        for p in PERSONAS:
            detected = detection.required_form_keys(p["profile"])
            inter = len(p["expected"] & detected)
            ratios.append(inter / len(p["expected"]))
        avg = sum(ratios) / len(ratios)
        self.assertGreaterEqual(avg, COVERAGE_TARGET, f"avg coverage {avg:.3f} < {COVERAGE_TARGET}")

    def test_instance_counts(self):
        for pid, expected_counts in INSTANCE_EXPECTATIONS.items():
            profile = next(p["profile"] for p in PERSONAS if p["id"] == pid)
            det = detection.detect_forms(profile)
            counts = {f["formKey"]: f["instances"] for f in det["required_forms"]}
            for fk, n in expected_counts.items():
                self.assertEqual(counts.get(fk), n, f"{pid}: {fk} instances {counts.get(fk)} != {n}")

    def test_confidence_score_in_range(self):
        for p in PERSONAS:
            score = detection.detect_forms(p["profile"])["confidence_score"]
            self.assertGreaterEqual(score, 0.0)
            self.assertLessEqual(score, 1.0)


class TestPhaseCQuestionnaire(unittest.TestCase):
    def test_questions_produced_and_no_raw_fields(self):
        result = questionnaire.traverse({"employment": True, "children": 1})
        self.assertGreater(len(result["questions"]), 5)
        allowed = {"nodeKey", "question", "answerType", "answer"}
        for q in result["questions"]:
            self.assertEqual(set(q.keys()), allowed, "questionnaire leaked non-question keys")
            self.assertIsInstance(q["question"], str)

    def test_interview_step_by_step(self):
        iv = questionnaire.Interview()
        first = iv.next_question()
        self.assertIn("question", first)
        steps = 0
        while iv.next_question() is not None and steps < 100:
            iv.answer(True)
            steps += 1
        self.assertTrue(iv.done)


class TestPhaseDBuilder(unittest.TestCase):
    def test_build_is_serialisable_and_complete(self):
        for p in PERSONAS:
            decl = builder.build_declaration(p["profile"])
            json.dumps(decl)  # must be serialisable
            self.assertIn("forms", decl)
            self.assertGreater(len(decl["forms"]), 0)
            self.assertIn("validation", decl)
            self.assertIn("optimization_suggestions", decl)
            self.assertIn("missing_documents", decl)
            self.assertIn("interview", decl)

    def test_existing_data_raises_completeness(self):
        # supply the mandatory hauptvordruck values -> completeness should rise
        profile = {"employment": True}
        empty = builder.build_declaration(profile)["field_completeness_percent"]
        filled = builder.build_declaration(profile, existing_data={
            "hauptvordruck": {"steuer_id": "12345678901", "vorname": "A", "nachname": "B",
                               "geburtsdatum": "01.01.1980", "strasse_hausnr": "X 1",
                               "plz": "66117", "ort": "SB", "familienstand": "ledig"},
        })["field_completeness_percent"]
        self.assertGreaterEqual(filled, empty)


class TestNoRegression(unittest.TestCase):
    def test_existing_declaration_module_intact(self):
        import autotax.declaration as decl
        self.assertTrue(hasattr(decl, "FORM_SECTIONS"))
        self.assertGreater(len(decl.FORM_SECTIONS), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
