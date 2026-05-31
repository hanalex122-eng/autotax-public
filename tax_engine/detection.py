"""Phase B — Form Detection Engine.

Given a user profile (+ optionally uploaded documents and existing tax data),
deterministically decide which forms are required and why, with a confidence
score. Read-only: consumes the knowledge base via `loader`, mutates nothing.

The profile is a plain dict of boolean/number flags. Trigger predicates below
mirror the `triggerCondition` strings in forms.json but are expressed in Python
for deterministic evaluation (the JSON strings remain the human-readable spec).
"""
from __future__ import annotations

from typing import Any, Callable

from . import loader

_CONF_WEIGHT = {"hoch": 1.0, "mittel": 0.8, "niedrig": 0.5}

# Forms that exist as logical topics but are not yet field-complete in
# forms.json. If a trigger fires for one of these it is reported under
# `missing_forms` rather than `required_forms`.
_STUB_FORMS = {"anlage_l", "anlage_u", "anlage_unterhalt", "anlage_v_fewo", "anlage_n_aus", "anlage_corona"}


def _g(profile: dict, key: str, default: Any = False) -> Any:
    return profile.get(key, default)


# formKey -> predicate(profile) -> bool. Mirrors forms.json triggerCondition.
TRIGGERS: dict[str, Callable[[dict], bool]] = {
    "hauptvordruck": lambda p: True,
    "anlage_n": lambda p: bool(_g(p, "employment")),
    "anlage_s": lambda p: bool(_g(p, "freelance")),
    "anlage_g": lambda p: bool(_g(p, "gewerbe")),
    "anlage_euer": lambda p: bool(_g(p, "freelance") or _g(p, "gewerbe")),
    "anlage_v": lambda p: bool(_g(p, "rental")),
    "anlage_kap": lambda p: bool(_g(p, "capital_income") or _g(p, "capital_inv") or _g(p, "beteiligung")),
    "anlage_kap_inv": lambda p: bool(_g(p, "capital_inv")),
    "anlage_kap_bet": lambda p: bool(_g(p, "beteiligung")),
    "anlage_r": lambda p: bool(_g(p, "pension")),
    "anlage_r_aus": lambda p: bool(_g(p, "foreign_pension")),
    "anlage_aus": lambda p: bool(_g(p, "foreign_income")),
    "anlage_so": lambda p: bool(_g(p, "unterhalt_received") or _g(p, "private_sale")),
    "anlage_kind": lambda p: int(_g(p, "children", 0) or 0) > 0,
    "anlage_av": lambda p: bool(_g(p, "riester")),
    "anlage_vorsorge": lambda p: bool(_g(p, "employment") or _g(p, "freelance") or _g(p, "gewerbe") or _g(p, "pension")),
    "ust_1a": lambda p: bool((_g(p, "freelance") or _g(p, "gewerbe")) and not _g(p, "kleinunternehmer")),
    "gewst_1a": lambda p: bool(_g(p, "gewerbe") and (int(_g(p, "profit", 0) or 0) > 24500)),
    "aussergewoehnliche": lambda p: bool(_g(p, "disability") or _g(p, "medical")),
    "haushaltsnah": lambda p: bool(_g(p, "handwerker") or _g(p, "haushaltsdienst")),
    "energetisch": lambda p: bool(_g(p, "energetic")),
}

# Human-readable reason per form (German, shown to the user as "why").
_REASONS = {
    "hauptvordruck": "Grundformular — für jede Steuererklärung erforderlich.",
    "anlage_n": "Einkünfte aus nichtselbständiger Arbeit (Lohn/Gehalt).",
    "anlage_s": "Einkünfte aus freiberuflicher/selbständiger Tätigkeit.",
    "anlage_g": "Einkünfte aus Gewerbebetrieb.",
    "anlage_euer": "Gewinnermittlung (Einnahmenüberschussrechnung).",
    "anlage_v": "Einkünfte aus Vermietung und Verpachtung.",
    "anlage_kap": "Kapitalerträge (Zinsen/Dividenden) zur Veranlagung.",
    "anlage_kap_inv": "Investmenterträge ohne Steuerabzug (Vorabpauschale).",
    "anlage_kap_bet": "Erträge aus Beteiligungen (gesonderte Feststellung).",
    "anlage_r": "Renten und sonstige Leistungen.",
    "anlage_r_aus": "Ausländische Renten.",
    "anlage_aus": "Ausländische Einkünfte und Steuern.",
    "anlage_so": "Sonstige Einkünfte (Unterhalt erhalten / private Veräußerung).",
    "anlage_kind": "Angaben zu Kindern (eine Anlage je Kind).",
    "anlage_av": "Altersvorsorgebeiträge (Riester).",
    "anlage_vorsorge": "Versicherungsbeiträge (Kranken-/Pflege-/Rentenversicherung).",
    "ust_1a": "Umsatzsteuer-Jahreserklärung (kein Kleinunternehmer).",
    "gewst_1a": "Gewerbesteuererklärung (Gewinn über 24.500 €).",
    "aussergewoehnliche": "Außergewöhnliche Belastungen / Behinderten-Pauschbetrag.",
    "haushaltsnah": "Haushaltsnahe Dienstleistungen / Handwerkerleistungen (§35a).",
    "energetisch": "Energetische Maßnahmen am Eigenheim (§35c).",
}


def _instance_count(form_key: str, profile: dict) -> int:
    """How many copies of a multi-instance form this profile needs."""
    if not loader.is_multi_instance(form_key):
        return 1
    if form_key == "anlage_kind":
        return max(1, int(_g(profile, "children", 0) or 0))
    if form_key == "anlage_n":
        # one per earner: spouse with own income -> 2
        return 2 if (_g(profile, "married") and _g(profile, "spouse_income")) else 1
    if form_key == "anlage_v":
        return max(1, int(_g(profile, "properties", 1) or 1)) if _g(profile, "rental") else 1
    if form_key in ("anlage_s", "anlage_g"):
        return max(1, int(_g(profile, "businesses", 1) or 1))
    if form_key in ("anlage_aus", "anlage_r_aus", "anlage_kap_bet"):
        return max(1, int(_g(profile, f"{form_key}_count", 1) or 1))
    return 1


def detect_forms(profile: dict, documents: list | None = None, existing_data: dict | None = None) -> dict:
    """Detect required & missing forms for a profile.

    Returns:
        {
          "tax_year": str|None,
          "required_forms": [{formKey, formCode, instances, reason, confidence}],
          "missing_forms":  [{formKey, reason}],   # triggered but not field-complete
          "confidence_score": float (0..1),
        }
    """
    documents = documents or []
    existing_data = existing_data or {}

    required: list[dict] = []
    missing: list[dict] = []

    for form_key, predicate in TRIGGERS.items():
        try:
            fires = predicate(profile)
        except Exception:  # never let a bad profile crash detection
            fires = False
        if not fires:
            continue
        if form_key in _STUB_FORMS or loader.form_by_key(form_key) is None:
            missing.append({"formKey": form_key, "reason": "Erforderlich, aber noch nicht feldvollständig im Knowledge Base."})
            continue
        form = loader.form_by_key(form_key)
        required.append({
            "formKey": form_key,
            "formCode": form.get("formCode", form_key),
            "instances": _instance_count(form_key, profile),
            "reason": _REASONS.get(form_key, form.get("purpose", "")),
            "confidence": form.get("confidence", "mittel"),
        })

    # Also surface stub topics that the profile implies but aren't in TRIGGERS.
    if _g(profile, "foreign_income") and _g(profile, "employment"):
        # foreign wage may need Anlage N-AUS (stub)
        if not any(m["formKey"] == "anlage_n_aus" for m in missing):
            pass  # only flagged when explicitly profiled; kept conservative

    weights = [_CONF_WEIGHT.get(f["confidence"], 0.8) for f in required]
    confidence_score = round(sum(weights) / len(weights), 3) if weights else 0.0

    return {
        "tax_year": _g(profile, "tax_year", None) or _g(profile, "year", None),
        "required_forms": required,
        "missing_forms": missing,
        "confidence_score": confidence_score,
    }


def required_form_keys(profile: dict) -> set[str]:
    """Convenience: the set of required form keys (ignoring instance counts)."""
    return {f["formKey"] for f in detect_forms(profile)["required_forms"]}
