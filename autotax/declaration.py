"""Steuererklärung (annual tax return) helpers.

MVP scope (2026-05-30):
- Form schema definition (Mantelbogen + Anlage S + Anlage Vorsorgeaufwand).
- Auto-fill helpers from existing user/company/EÜR data.
- Validation rules (required fields, format checks).
- PDF generation skeleton (real layout comes in next iteration).

OUT OF SCOPE for now:
- ELSTER XML/XBRL export
- Anlage KAP / R / V (special situations)
- Multi-year parallel work (only one year at a time)

See `.claude/steuererklaerung_plan.md` for full plan.
"""
from __future__ import annotations

import json
import logging
from datetime import date
from typing import Any, Optional

logger = logging.getLogger("autotax.declaration")


# ───────────────────────────────────────────────────────────────────
# Form schema — single source of truth for field metadata.
# Used by both backend validation and frontend rendering.
# ───────────────────────────────────────────────────────────────────

FORM_SECTIONS = [
    {
        "key": "mantelbogen",
        "title_de": "Mantelbogen (ESt 1 A)",
        "title_tr": "Ana Form (Mantelbogen)",
        "fields": [
            {"key": "steuer_id",      "label_de": "Steuer-ID (11-stellig)",       "label_tr": "Vergi kimlik no (11 hane)",          "type": "text",   "required": True,  "pattern": r"^\d{11}$"},
            {"key": "steuer_nummer",  "label_de": "Steuernummer (optional)",       "label_tr": "Steuernummer (opsiyonel)",            "type": "text",   "required": False},
            {"key": "vorname",        "label_de": "Vorname",                       "label_tr": "Ad",                                  "type": "text",   "required": True},
            {"key": "nachname",       "label_de": "Nachname",                      "label_tr": "Soyad",                               "type": "text",   "required": True},
            {"key": "geburtsdatum",   "label_de": "Geburtsdatum",                  "label_tr": "Doğum tarihi",                        "type": "date",   "required": True},
            {"key": "religion",       "label_de": "Religion",                      "label_tr": "Din",                                 "type": "select", "required": True,
             "options": [{"v": "none", "de": "Keine", "tr": "Yok"}, {"v": "ev", "de": "Evangelisch", "tr": "Evanjelik"}, {"v": "rk", "de": "Römisch-katholisch", "tr": "Katolik"}, {"v": "other", "de": "Andere", "tr": "Diğer"}]},
            {"key": "strasse",        "label_de": "Straße + Hausnummer",           "label_tr": "Sokak + ev no",                       "type": "text",   "required": True},
            {"key": "plz",            "label_de": "PLZ",                           "label_tr": "Posta kodu",                          "type": "text",   "required": True,  "pattern": r"^\d{5}$"},
            {"key": "ort",            "label_de": "Ort",                           "label_tr": "Şehir",                               "type": "text",   "required": True},
            {"key": "familienstand",  "label_de": "Familienstand",                 "label_tr": "Medeni hal",                          "type": "select", "required": True,
             "options": [{"v": "ledig", "de": "Ledig", "tr": "Bekar"}, {"v": "verheiratet", "de": "Verheiratet", "tr": "Evli"}, {"v": "geschieden", "de": "Geschieden", "tr": "Boşanmış"}, {"v": "verwitwet", "de": "Verwitwet", "tr": "Dul"}]},
            {"key": "iban",           "label_de": "IBAN (Erstattung)",             "label_tr": "IBAN (iade için)",                    "type": "text",   "required": True,  "pattern": r"^DE\d{20}$"},
            {"key": "kontoinhaber",   "label_de": "Kontoinhaber",                  "label_tr": "Hesap sahibi",                        "type": "text",   "required": True},
        ],
    },
    {
        "key": "anlage_s",
        "title_de": "Anlage S — Selbständige Tätigkeit",
        "title_tr": "Anlage S — Serbest meslek",
        "fields": [
            {"key": "taetigkeit",         "label_de": "Tätigkeit (z.B. IT-Consulting)", "label_tr": "Meslek (örn. IT danışmanlık)",  "type": "text",   "required": True},
            {"key": "gewinn_eur",         "label_de": "Gewinn aus EÜR (€)",             "label_tr": "EÜR kazancı (€)",                "type": "number", "required": True, "auto_fill_from": "eur_profit"},
            {"key": "veraeusserungsgewinn", "label_de": "Veräußerungsgewinn (€)",       "label_tr": "Sermaye gain (€)",               "type": "number", "required": False, "default": 0},
        ],
    },
    {
        "key": "anlage_vorsorge",
        "title_de": "Anlage Vorsorgeaufwand",
        "title_tr": "Anlage Vorsorgeaufwand (sigortalar)",
        "fields": [
            {"key": "kv_basis",   "label_de": "Krankenversicherung Basis (€)",       "label_tr": "Temel sağlık sigortası (€)",  "type": "number", "required": True},
            {"key": "kv_zusatz",  "label_de": "Krankenversicherung Zusatz (€)",      "label_tr": "Ek sağlık sigortası (€)",     "type": "number", "required": False, "default": 0},
            {"key": "pflege",     "label_de": "Pflegeversicherung (€)",              "label_tr": "Bakım sigortası (€)",         "type": "number", "required": False, "default": 0},
            {"key": "rente_gesetz", "label_de": "Gesetzliche Rentenversicherung (€)", "label_tr": "Yasal emekli sigortası (€)",  "type": "number", "required": False, "default": 0},
            {"key": "rurup",      "label_de": "Rürup-Rente (€)",                     "label_tr": "Rürup emekliliği (€)",        "type": "number", "required": False, "default": 0},
            {"key": "bu",         "label_de": "Berufsunfähigkeitsversicherung (€)",  "label_tr": "Maluliyet sigortası (€)",     "type": "number", "required": False, "default": 0},
        ],
    },
]


def _flat_fields() -> list[dict]:
    out: list[dict] = []
    for section in FORM_SECTIONS:
        for f in section["fields"]:
            out.append({**f, "section": section["key"]})
    return out


# ───────────────────────────────────────────────────────────────────
# Auto-fill from user/company/invoice data.
# ───────────────────────────────────────────────────────────────────

def autofill_from_user_data(user, companies: list, eur_profit: float) -> dict:
    """Pre-populate form with data we already have from the app.

    Caller passes already-loaded User + UserCompany list + computed
    EÜR profit (sum of income - sum of expenses for the year).
    """
    out: dict[str, Any] = {}

    # Mantelbogen: from User profile
    if user:
        full_name = (getattr(user, "full_name", "") or "").strip()
        if full_name:
            parts = full_name.split(" ", 1)
            if len(parts) >= 1:
                out["vorname"] = parts[0]
            if len(parts) >= 2:
                out["nachname"] = parts[1]

    # Mantelbogen: from primary UserCompany (address)
    if companies:
        primary = next((c for c in companies if getattr(c, "is_default", False)), companies[0])
        out["strasse"] = (getattr(primary, "company_address", "") or "").strip()
        # PLZ + Ort would need separate fields in UserCompany — skip for now
        # IBAN from UserCompany
        iban = (getattr(primary, "company_iban", "") or "").strip().replace(" ", "").upper()
        if iban:
            out["iban"] = iban
            out["kontoinhaber"] = (getattr(primary, "company_name", "") or full_name or "").strip()

    # Anlage S: from EÜR profit
    if eur_profit is not None:
        out["gewinn_eur"] = round(float(eur_profit), 2)

    return out


# ───────────────────────────────────────────────────────────────────
# Validation.
# ───────────────────────────────────────────────────────────────────

def validate(data: dict) -> dict:
    """Return {field_key: error_message} for invalid/missing fields."""
    import re as _re
    errors: dict[str, str] = {}
    for f in _flat_fields():
        key = f["key"]
        value = data.get(key)
        # Required check
        if f.get("required") and (value is None or value == ""):
            errors[key] = f"Pflichtfeld fehlt ({f['label_de']})"
            continue
        # Pattern check
        pat = f.get("pattern")
        if pat and value:
            if not _re.match(pat, str(value)):
                errors[key] = f"Format ungültig ({f['label_de']})"
    return errors


# ───────────────────────────────────────────────────────────────────
# Data serialization.
# ───────────────────────────────────────────────────────────────────

def serialize_data(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True)


def deserialize_data(raw: Optional[str]) -> dict:
    if not raw:
        return {}
    try:
        d = json.loads(raw)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


# ───────────────────────────────────────────────────────────────────
# PDF generation — SKELETON only. Real layout next iteration.
# ───────────────────────────────────────────────────────────────────

def generate_pdf_skeleton(declaration, user, companies: list) -> bytes:
    """Minimal PDF that proves the data flows. Not tax-office final layout."""
    import io
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas as pdf_canvas
    from reportlab.lib.units import cm
    from reportlab.lib.colors import HexColor

    buf = io.BytesIO()
    c = pdf_canvas.Canvas(buf, pagesize=A4)
    w, h = A4
    data = deserialize_data(declaration.data)

    c.setFillColor(HexColor("#1a2d4a"))
    c.setFont("Helvetica-Bold", 18)
    c.drawString(2 * cm, h - 2.5 * cm, f"Steuererklärung {declaration.year}")
    c.setFont("Helvetica", 10)
    c.setFillColor(HexColor("#7a8ba8"))
    c.drawString(2 * cm, h - 3.2 * cm,
                 "Entwurf — kein offizielles Formular. Bitte Inhalt manuell in ELSTER übertragen.")

    y = h - 4.5 * cm
    for section in FORM_SECTIONS:
        c.setFillColor(HexColor("#1a2d4a"))
        c.setFont("Helvetica-Bold", 12)
        c.drawString(2 * cm, y, section["title_de"])
        y -= 0.7 * cm
        c.setFont("Helvetica", 10)
        for f in section["fields"]:
            label = f["label_de"]
            value = data.get(f["key"], "—")
            c.drawString(2.3 * cm, y, f"{label}:")
            c.drawString(11 * cm, y, str(value))
            y -= 0.5 * cm
            if y < 3 * cm:
                c.showPage()
                y = h - 2.5 * cm
        y -= 0.4 * cm

    c.setFillColor(HexColor("#7a8ba8"))
    c.setFont("Helvetica", 7)
    c.drawString(2 * cm, 1.5 * cm,
                 f"AutoTax.Cloud · {user.email if user else ''} · "
                 f"Entwurf erstellt am {date.today().strftime('%d.%m.%Y')}")
    c.drawString(2 * cm, 1.0 * cm,
                 "Keine Steuerberatung. Bitte vor Übermittlung an ELSTER prüfen.")

    c.save()
    buf.seek(0)
    return buf.getvalue()


__all__ = [
    "FORM_SECTIONS",
    "autofill_from_user_data",
    "validate",
    "serialize_data",
    "deserialize_data",
    "generate_pdf_skeleton",
]
