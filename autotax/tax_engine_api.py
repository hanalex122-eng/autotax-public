"""Read-only API router for the knowledge-driven tax engine v2.

ADDITIVE & SAFE BY DESIGN:
- New router only. Does not modify or import any existing production endpoint.
- Every endpoint is gated behind the backend feature flag
  TAX_ENGINE_V2_ENABLED (default OFF). When off, endpoints return 404 so the
  surface behaves as if it does not exist (production risk ≈ 0).
- Read-only: no database access, no writes, no side effects. Inputs are plain
  JSON; all knowledge comes from tax_engine/knowledge/*.json.
- Auth required (reuses get_current_user) so the compute surface is not public.
- Not wired to the SPA/frontend (no window.FEATURES entry).

Endpoints:
  POST /tax/{year}/detect              -> required/missing forms + confidence
  POST /tax/{year}/questionnaire/start -> first interview question + session
  POST /tax/{year}/questionnaire/next  -> submit answer -> next question
  POST /tax/{year}/build               -> full internal declaration object
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel, Field

from autotax.auth import get_current_user
from autotax.config import tax_engine_v2_enabled
from tax_engine import builder, detection, loader, questionnaire

router = APIRouter(prefix="/tax", tags=["tax-engine-v2 (read-only, flag-gated)"])


def _require_flag() -> None:
    """404 when the feature flag is off — endpoint appears not to exist."""
    if not tax_engine_v2_enabled():
        raise HTTPException(status_code=404, detail="Not found")


# ── Request models ───────────────────────────────────────────────────
class ProfileRequest(BaseModel):
    profile: dict[str, Any] = Field(default_factory=dict, description="User situation flags, e.g. {employment:true, children:2}")
    documents: Optional[list[str]] = Field(default=None, description="Optional list of uploaded document types")
    existing_data: Optional[dict[str, Any]] = Field(default=None, description="Optional {form_key:{field_key:value}} of known values")

    model_config = {"json_schema_extra": {"example": {"profile": {"employment": True, "children": 2, "rental": True}}}}


class QuestionnaireStartRequest(BaseModel):
    profile: dict[str, Any] = Field(default_factory=dict, description="Optional seed profile for auto-answering")


class QuestionnaireNextRequest(BaseModel):
    answers: dict[str, Any] = Field(default_factory=dict, description="Map of nodeKey -> answer collected so far")
    current_node: Optional[str] = Field(default=None, description="Node just answered; omit to start from entry")
    answer: Any = Field(default=None, description="Answer value for current_node")


# ── Endpoints ────────────────────────────────────────────────────────
@router.post("/{year}/detect", summary="Detect required tax forms (read-only)")
def detect(
    body: ProfileRequest,
    year: int = Path(..., ge=2020, le=2030),
    user: dict = Depends(get_current_user),
) -> dict:
    """Return the required forms (with instance counts, reason, confidence),
    forms that are triggered but not yet field-complete, and an overall
    detection confidence score. Pure function of the supplied profile."""
    _require_flag()
    result = detection.detect_forms(body.profile, documents=body.documents, existing_data=body.existing_data)
    result["year"] = year
    return result


@router.post("/{year}/questionnaire/start", summary="Start the dynamic questionnaire (read-only)")
def questionnaire_start(
    body: QuestionnaireStartRequest,
    year: int = Path(..., ge=2020, le=2030),
    user: dict = Depends(get_current_user),
) -> dict:
    """Return the first plain-language question. The client echoes `answers`
    and `current_node` back to /questionnaire/next. Raw tax-form fields are
    never returned — only question prompts."""
    _require_flag()
    nodes = {n["nodeKey"]: n for n in loader.questionnaire_nodes()}
    entry = loader.questionnaire_entry()
    node = nodes.get(entry, {})
    return {
        "year": year,
        "node": {
            "nodeKey": entry,
            "question": node.get("questionDe", ""),
            "answerType": node.get("answerType", ""),
            "options": node.get("options", []),
        },
        "answers": {},
        "done": False,
    }


@router.post("/{year}/questionnaire/next", summary="Submit an answer, get the next question (read-only)")
def questionnaire_next(
    body: QuestionnaireNextRequest,
    year: int = Path(..., ge=2020, le=2030),
    user: dict = Depends(get_current_user),
) -> dict:
    """Stateless step: replays accumulated answers through the state machine to
    determine the next question (or completion). The client holds the session
    state; the server stores nothing."""
    _require_flag()
    nodes = {n["nodeKey"]: n for n in loader.questionnaire_nodes()}
    answers = dict(body.answers or {})
    if body.current_node:
        answers[body.current_node] = body.answer

    # Advance from current_node (or entry) using the engine's condition logic.
    start = body.current_node or loader.questionnaire_entry()
    node = nodes.get(start)
    if not node:
        raise HTTPException(status_code=400, detail="Unknown questionnaire node")

    activated_forms: list[str] = []
    if questionnaire._affirmative(answers.get(start)):
        activated_forms = list(node.get("activatesForms", []))

    branches = node.get("branches", [])
    next_key = None
    for b in branches:
        if questionnaire._eval_condition(b.get("condition", ""), answers, {}):
            next_key = b.get("nextNode")
            break

    if not next_key or next_key not in nodes:
        return {"year": year, "node": None, "answers": answers, "activated_forms": activated_forms, "done": True}

    nxt = nodes[next_key]
    return {
        "year": year,
        "node": {
            "nodeKey": next_key,
            "question": nxt.get("questionDe", ""),
            "answerType": nxt.get("answerType", ""),
            "options": nxt.get("options", []),
        },
        "answers": answers,
        "activated_forms": activated_forms,
        "done": False,
    }


@router.post("/{year}/build", summary="Build the internal declaration object (read-only)")
def build(
    body: ProfileRequest,
    year: int = Path(..., ge=2020, le=2030),
    user: dict = Depends(get_current_user),
) -> dict:
    """Return the full internal declaration object: forms, interview, validation
    results, missing-documents list and optimization suggestions. Read-only —
    nothing is persisted."""
    _require_flag()
    profile = dict(body.profile)
    profile.setdefault("tax_year", str(year))
    result = builder.build_declaration(profile, documents=body.documents, existing_data=body.existing_data)
    result["year"] = year
    return result
