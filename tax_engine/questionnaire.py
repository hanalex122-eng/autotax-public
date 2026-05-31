"""Phase C — Questionnaire Runtime.

Drives the dynamic interview defined in questionnaire.json. The user is only
ever shown plain-language questions (questionDe); raw tax-form field objects
are never exposed by this runtime. As the interview is answered, the runtime
accumulates which forms/fields get activated and where they can be prefilled.

Two modes:
- `traverse(profile)` — auto-answer every node from a profile dict and walk the
  branch graph, returning the asked questions + activated forms/fields.
- `Interview` — stateful step-by-step driver (next_question / answer) for a UI
  where answers arrive one at a time.

Condition grammar supported in branches (see questionnaire.json):
  "default"
  "ans.<key> == true" / "== false"
  "ans.<key> == 'value'"
  "ans.<key> > <number>" / ">=" / "<" / "<="
  "<var> == true"            (bare var, resolved against profile)
  "<a> in [x, y, z]"
"""
from __future__ import annotations

import re
from typing import Any

from . import loader

_MAX_STEPS = 200  # cycle guard

# Answers that mean "no / not applicable" — used to gate form/field activation
# so a "do you have X?" node only activates X when the user actually has it.
_NEGATIVE = {"", "nein", "keine/andere", "Kleinunternehmer (keine USt)"}


def _affirmative(answer: Any) -> bool:
    if isinstance(answer, bool):
        return answer
    if isinstance(answer, (int, float)):
        return answer > 0
    if isinstance(answer, str):
        return answer not in _NEGATIVE
    return bool(answer)


def _answer_for(node_key: str, profile: dict) -> Any:
    """Derive the answer to a node from a profile dict (auto-answer mode)."""
    p = profile.get
    married = bool(p("married"))
    if node_key == "q_year":
        return str(p("tax_year") or p("year") or "2024")
    if node_key == "q_marital":
        return "verheiratet/verpartnert" if married else "ledig"
    if node_key == "q_spouse_income":
        return bool(p("spouse_income"))
    if node_key == "q_religion":
        return "römisch-katholisch" if p("church_member") else "keine/andere"
    if node_key == "q_employment":
        return bool(p("employment"))
    if node_key == "q_commute":
        return bool(p("commute"))
    if node_key == "q_homeoffice":
        return bool(p("homeoffice"))
    if node_key == "q_selfemployed":
        if p("freelance"):
            return "freiberuflich (z.B. Beratung, Kreativ)"
        if p("gewerbe"):
            return "Gewerbe (z.B. Imbiss, Friseur, Handel)"
        return "nein"
    if node_key == "q_gewerbe_profit":
        return int(p("profit", 0) or 0) > 24500
    if node_key == "q_vat":
        return "Kleinunternehmer (keine USt)" if p("kleinunternehmer") else "umsatzsteuerpflichtig"
    if node_key == "q_rental":
        return bool(p("rental"))
    if node_key == "q_capital":
        return bool(p("capital_income") or p("capital_inv") or p("beteiligung"))
    if node_key == "q_pension":
        return bool(p("pension"))
    if node_key == "q_children":
        return int(p("children", 0) or 0)
    if node_key == "q_childcare":
        return bool(p("childcare"))
    if node_key == "q_child_disability":
        return bool(p("disabled_child"))
    if node_key == "q_disability":
        return bool(p("disability"))
    if node_key == "q_medical":
        return bool(p("medical"))
    if node_key == "q_handwerker":
        return bool(p("handwerker") or p("haushaltsdienst"))
    if node_key == "q_energetic":
        return bool(p("energetic"))
    if node_key == "q_donations":
        return bool(p("donations") or p("church_member"))
    if node_key == "q_foreign":
        return bool(p("foreign_income"))
    # q_gewst, q_insurance, q_done, q_address, q_work_expenses, q_rental_details, q_euer
    return True


def _coerce(token: str) -> Any:
    token = token.strip()
    if token == "true":
        return True
    if token == "false":
        return False
    if (token.startswith("'") and token.endswith("'")) or (token.startswith('"') and token.endswith('"')):
        return token[1:-1]
    try:
        return int(token)
    except ValueError:
        try:
            return float(token)
        except ValueError:
            return token


def _resolve_var(name: str, answers: dict, profile: dict) -> Any:
    name = name.strip()
    if name.startswith("ans."):
        return answers.get(name[4:])
    # bare variable: try profile flag, then accumulated answers
    if name in profile:
        return profile[name]
    # special flags referenced by branches
    if name == "has_disabled_child":
        return bool(profile.get("disabled_child"))
    return answers.get(name)


def _eval_condition(cond: str, answers: dict, profile: dict) -> bool:
    cond = (cond or "").strip()
    if cond == "" or cond == "default":
        return True
    # membership: "<var> in [a, b, c]"
    m = re.match(r"^(.+?)\s+in\s+\[(.*)\]$", cond)
    if m:
        left = _resolve_var(m.group(1), answers, profile)
        opts = [_coerce(x) for x in m.group(2).split(",") if x.strip()]
        return left in opts
    # comparison operators
    for op in ("==", "!=", ">=", "<=", ">", "<"):
        if op in cond:
            left_s, right_s = cond.split(op, 1)
            left = _resolve_var(left_s, answers, profile)
            right = _coerce(right_s)
            try:
                if op == "==":
                    return left == right
                if op == "!=":
                    return left != right
                if op == ">=":
                    return (left or 0) >= right
                if op == "<=":
                    return (left or 0) <= right
                if op == ">":
                    return (left or 0) > right
                if op == "<":
                    return (left or 0) < right
            except TypeError:
                return False
    # bare truthy var
    return bool(_resolve_var(cond, answers, profile))


def traverse(profile: dict) -> dict:
    """Auto-answer the interview from a profile and walk the branch graph.

    Returns {questions, activated_forms, activated_fields, prefill_sources,
    visited}. `questions` are the plain-language prompts the user would see —
    never raw form-field objects (enforces 'user never sees raw forms').
    """
    nodes = {n["nodeKey"]: n for n in loader.questionnaire_nodes()}
    current = loader.questionnaire_entry()
    answers: dict[str, Any] = {}
    questions: list[dict] = []
    activated_forms: list[str] = []
    activated_fields: list[str] = []
    prefill: set[str] = set()
    visited: list[str] = []

    steps = 0
    while current and current in nodes and steps < _MAX_STEPS:
        steps += 1
        node = nodes[current]
        visited.append(current)
        ans = _answer_for(current, profile)
        answers[current] = ans

        questions.append({
            "nodeKey": current,
            "question": node.get("questionDe", ""),
            "answerType": node.get("answerType", ""),
            "answer": ans,
        })
        if _affirmative(ans):
            for f in node.get("activatesForms", []):
                if f not in activated_forms:
                    activated_forms.append(f)
            for f in node.get("activatesFields", []):
                if f not in activated_fields:
                    activated_fields.append(f)
            src = node.get("prefillFrom")
            if src and src != "—":
                prefill.add(src)

        branches = node.get("branches", [])
        if not branches:
            break
        nxt = None
        for b in branches:
            if _eval_condition(b.get("condition", ""), answers, profile):
                nxt = b.get("nextNode")
                break
        if not nxt or nxt == current:
            break
        current = nxt

    return {
        "questions": questions,
        "activated_forms": activated_forms,
        "activated_fields": activated_fields,
        "prefill_sources": sorted(prefill),
        "visited": visited,
    }


class Interview:
    """Stateful step-by-step driver for a UI that submits one answer at a time.

    The UI calls `next_question()` to get the current prompt, then `answer(value)`
    to advance. Only question prompts cross the boundary — no raw form fields.
    """

    def __init__(self) -> None:
        self._nodes = {n["nodeKey"]: n for n in loader.questionnaire_nodes()}
        self.current = loader.questionnaire_entry()
        self.answers: dict[str, Any] = {}
        self.activated_forms: list[str] = []
        self.activated_fields: list[str] = []
        self.done = False

    def next_question(self) -> dict | None:
        if self.done or self.current not in self._nodes:
            return None
        node = self._nodes[self.current]
        return {
            "nodeKey": self.current,
            "question": node.get("questionDe", ""),
            "answerType": node.get("answerType", ""),
            "options": node.get("options", []),
        }

    def answer(self, value: Any) -> dict | None:
        if self.done or self.current not in self._nodes:
            return None
        node = self._nodes[self.current]
        self.answers[self.current] = value
        if _affirmative(value):
            for f in node.get("activatesForms", []):
                if f not in self.activated_forms:
                    self.activated_forms.append(f)
            for f in node.get("activatesFields", []):
                if f not in self.activated_fields:
                    self.activated_fields.append(f)
        branches = node.get("branches", [])
        if not branches:
            self.done = True
            return None
        for b in branches:
            if _eval_condition(b.get("condition", ""), self.answers, {}):
                self.current = b.get("nextNode")
                break
        else:
            self.done = True
        if not self.current:
            self.done = True
        return self.next_question()
