"""Phase A — Knowledge Base Loader.

Read-only, cached loaders for the four knowledge files plus convenience
accessors. No mutation, no DB, stdlib only. Paths resolve relative to this
file so loading works regardless of the process working directory.
"""
from __future__ import annotations

import functools
import json
import pathlib
from typing import Any

_KB_DIR = pathlib.Path(__file__).resolve().parent / "knowledge"


@functools.lru_cache(maxsize=None)
def _load_json(name: str) -> dict:
    path = _KB_DIR / name
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


# ── Raw documents ────────────────────────────────────────────────────
def load_forms() -> dict:
    return _load_json("forms.json")


def load_questionnaire() -> dict:
    return _load_json("questionnaire.json")


def load_knowledge_graph() -> dict:
    return _load_json("knowledge_graph.json")


def load_optimization_rules() -> dict:
    return _load_json("optimization_rules.json")


# ── Convenience accessors ────────────────────────────────────────────
def forms() -> list[dict]:
    return load_forms().get("forms", [])


@functools.lru_cache(maxsize=None)
def _forms_index() -> dict[str, dict]:
    return {f["formKey"]: f for f in forms()}


def form_by_key(form_key: str) -> dict | None:
    return _forms_index().get(form_key)


def form_keys() -> list[str]:
    return [f["formKey"] for f in forms()]


def multi_instance_forms() -> set[str]:
    return set(load_forms().get("meta", {}).get("multiInstanceForms", []))


def is_multi_instance(form_key: str) -> bool:
    form = form_by_key(form_key)
    if form and "multiInstance" in form:
        return bool(form["multiInstance"])
    return form_key in multi_instance_forms()


def fields_of(form_key: str) -> list[dict]:
    form = form_by_key(form_key) or {}
    out: list[dict] = []
    for section in form.get("sections", []):
        out.extend(section.get("fields", []))
    return out


def optimization_rules() -> list[dict]:
    return load_optimization_rules().get("rules", [])


@functools.lru_cache(maxsize=None)
def _rules_index() -> dict[str, dict]:
    return {r["ruleKey"]: r for r in optimization_rules()}


def rule_by_key(rule_key: str) -> dict | None:
    return _rules_index().get(rule_key)


def questionnaire_nodes() -> list[dict]:
    return load_questionnaire().get("nodes", [])


def questionnaire_entry() -> str:
    return load_questionnaire().get("entryNode", "")


def graph_nodes() -> list[dict]:
    return load_knowledge_graph().get("nodes", [])


def graph_edges() -> list[dict]:
    return load_knowledge_graph().get("edges", [])


def summary() -> dict:
    """Lightweight health/coverage summary of the loaded knowledge base."""
    return {
        "forms": len(forms()),
        "multi_instance_forms": len(multi_instance_forms()),
        "optimization_rules": len(optimization_rules()),
        "questionnaire_nodes": len(questionnaire_nodes()),
        "graph_nodes": len(graph_nodes()),
        "graph_edges": len(graph_edges()),
    }
