"""Phase D — Declaration Builder.

Combines the read-only engine pieces into one internal declaration object:
- form set + instances        (detection, Phase B — authoritative)
- interview questions/prefill  (questionnaire, Phase C)
- validation results           (forms.json required fields / format rules)
- missing-documents list       (optimization rules' requiredEvidence)
- optimization suggestions     (optimization rules referenced by active forms)

Read-only and side-effect free. `existing_data` is an optional nested dict
{form_key: {field_key: value}} of already-known values; with it the builder
also computes a per-form completeness score. Nothing here touches the DB or the
existing declaration.py module.
"""
from __future__ import annotations

import re
from typing import Any

from . import detection, loader, questionnaire


def _collect_optimization(active_keys: list[str]) -> tuple[list[dict], list[str]]:
    """Suggestions + missing documents implied by the active forms' fields."""
    rule_keys: list[str] = []
    for fk in active_keys:
        for field in loader.fields_of(fk):
            for ref in field.get("optimizationRefs", []) or []:
                if ref not in rule_keys:
                    rule_keys.append(ref)
    suggestions: list[dict] = []
    documents: list[str] = []
    for rk in rule_keys:
        rule = loader.rule_by_key(rk)
        if not rule:
            continue
        suggestions.append({
            "ruleKey": rk,
            "name": rule.get("name", rk),
            "category": rule.get("category", ""),
            "suggestion": rule.get("suggestionDe", ""),
            "legalBasis": rule.get("legalBasis", ""),
        })
        for ev in rule.get("requiredEvidence", []) or []:
            if ev not in documents:
                documents.append(ev)
    return suggestions, documents


def _validate(active_keys: list[str], existing_data: dict) -> tuple[list[dict], list[dict], int, int]:
    """Return (errors, warnings, filled_required, total_required)."""
    errors: list[dict] = []
    warnings: list[dict] = []
    total_required = 0
    filled_required = 0
    for fk in active_keys:
        form_values = existing_data.get(fk, {}) if existing_data else {}
        for field in loader.fields_of(fk):
            key = field.get("fieldKey")
            required = bool(field.get("required"))
            present = key in form_values and form_values[key] not in (None, "", [])
            if required:
                total_required += 1
                if present:
                    filled_required += 1
                else:
                    warnings.append({
                        "form": fk, "field": key,
                        "message": f"Pflichtfeld fehlt: {field.get('label', key)}",
                    })
            # format validation when a value is present
            if present:
                val = form_values[key]
                v = field.get("validation", {}) or {}
                if v.get("type") == "regex":
                    m = re.search(r"\^.*\$", v.get("constraint", ""))
                    pattern = m.group(0) if m else None
                    if pattern:
                        try:
                            if not re.match(pattern, str(val)):
                                errors.append({"form": fk, "field": key, "message": v.get("message", "Ungültiges Format.")})
                        except re.error:
                            pass
    return errors, warnings, filled_required, total_required


def build_declaration(profile: dict, documents: list | None = None, existing_data: dict | None = None) -> dict:
    """Build the internal declaration object for a profile.

    Returns a JSON-serialisable dict — the single object the UI/PDF/ELSTER
    layers consume. Authoritative form set comes from the detection engine;
    the questionnaire supplies the interview + prefill sources.
    """
    existing_data = existing_data or {}

    det = detection.detect_forms(profile, documents=documents, existing_data=existing_data)
    active_keys = [f["formKey"] for f in det["required_forms"]]

    interview = questionnaire.traverse(profile)
    suggestions, missing_docs = _collect_optimization(active_keys)
    errors, warnings, filled_req, total_req = _validate(active_keys, existing_data)

    completeness = round(100 * filled_req / total_req) if total_req else (100 if active_keys else 0)

    return {
        "tax_year": det["tax_year"],
        "forms": det["required_forms"],
        "missing_forms": det["missing_forms"],
        "form_detection_confidence": det["confidence_score"],
        "interview": {
            "questions": interview["questions"],
            "prefill_sources": interview["prefill_sources"],
            "activated_forms": interview["activated_forms"],
        },
        "validation": {
            "errors": errors,
            "warnings": warnings,
            "ok": not errors,
        },
        "missing_documents": missing_docs,
        "optimization_suggestions": suggestions,
        "field_completeness_percent": completeness,
    }
