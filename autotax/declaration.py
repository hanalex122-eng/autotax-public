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

def _validate_iban_de(iban: str) -> bool:
    """DE IBAN checksum (mod 97). DE + 20 digits, total 22 chars."""
    iban = iban.replace(" ", "").upper()
    if not iban.startswith("DE") or len(iban) != 22:
        return False
    if not iban[2:].isdigit():
        return False
    # Move first 4 chars to end, replace letters with digits (A=10..Z=35)
    rearranged = iban[4:] + iban[:4]
    converted = ""
    for ch in rearranged:
        if ch.isdigit():
            converted += ch
        else:
            converted += str(ord(ch) - ord("A") + 10)
    try:
        return int(converted) % 97 == 1
    except ValueError:
        return False


def _validate_steuer_id(sid: str) -> bool:
    """Steuer-ID 11 digits with check-digit rule (Faktorenverfahren).
    One digit appears 2x or 3x in first 10 (rest unique). The 11th digit
    is the check digit computed via mod 11 on first 10."""
    sid = "".join(c for c in sid if c.isdigit())
    if len(sid) != 11:
        return False
    # Count digit frequency in first 10
    counts: dict[str, int] = {}
    for d in sid[:10]:
        counts[d] = counts.get(d, 0) + 1
    # Must have exactly one digit appearing 2x or 3x and others 1x.
    twos = sum(1 for v in counts.values() if v == 2)
    threes = sum(1 for v in counts.values() if v == 3)
    if not ((twos == 1 and threes == 0) or (twos == 0 and threes == 1)):
        return False
    # Check digit (mod 11/10 algorithm — ISO 7064 variant used by BZSt)
    product = 10
    for d in sid[:10]:
        s = (int(d) + product) % 10
        if s == 0:
            s = 10
        product = (2 * s) % 11
    check = (11 - product) % 10
    return check == int(sid[10])


def validate(data: dict) -> dict:
    """Return {field_key: error_message} for invalid/missing fields.

    Multi-level checks: required + regex pattern + semantic (IBAN checksum,
    Steuer-ID check digit). Labels in German for matching UI tone.
    """
    import re as _re
    errors: dict[str, str] = {}
    for f in _flat_fields():
        key = f["key"]
        value = data.get(key)
        # Required check
        if f.get("required") and (value is None or value == ""):
            errors[key] = f"Pflichtfeld fehlt ({f['label_de']})"
            continue
        # Pattern check (raw regex)
        pat = f.get("pattern")
        if pat and value:
            if not _re.match(pat, str(value)):
                errors[key] = f"Format ungültig ({f['label_de']})"
                continue
        # Semantic checks for specific fields
        if value:
            if key == "iban":
                if not _validate_iban_de(str(value)):
                    errors[key] = "IBAN ungültig (Prüfziffer)"
            elif key == "steuer_id":
                if not _validate_steuer_id(str(value)):
                    errors[key] = "Steuer-ID ungültig (Prüfziffer)"
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
    """Render declaration as PDF with form-like layout (tax-office inspired).

    Each section has a header band, labeled rows with underline-style value
    boxes. Cover page has year + status. Footer disclaimer on every page.
    Not the actual ESt 1 A scan but close enough for review-before-ELSTER.
    """
    import io
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas as pdf_canvas
    from reportlab.lib.units import cm
    from reportlab.lib.colors import HexColor

    NAVY = HexColor("#0f1a2e")
    INK = HexColor("#1a2d4a")
    MUTED = HexColor("#7a8ba8")
    ACCENT = HexColor("#10b981")
    LIGHT_BG = HexColor("#f3f6fa")
    BORDER = HexColor("#cdd5e0")

    buf = io.BytesIO()
    c = pdf_canvas.Canvas(buf, pagesize=A4)
    w, h = A4
    data = deserialize_data(declaration.data)
    margin_l = 1.8 * cm
    margin_r = 1.8 * cm
    content_w = w - margin_l - margin_r

    def draw_footer():
        c.setFillColor(MUTED)
        c.setFont("Helvetica", 7)
        c.drawString(margin_l, 1.4 * cm,
                     f"AutoTax.Cloud · {user.email if user else ''} · "
                     f"Erstellt {date.today().strftime('%d.%m.%Y')}")
        c.drawString(margin_l, 1.0 * cm,
                     "Entwurf — Keine Steuerberatung. Bitte vor Übermittlung an ELSTER prüfen.")
        c.drawRightString(w - margin_r, 1.0 * cm,
                          f"Steuererklärung {declaration.year}")

    def new_page():
        draw_footer()
        c.showPage()
        return h - 2.5 * cm

    # ─── Cover band ───
    c.setFillColor(NAVY)
    c.rect(0, h - 4 * cm, w, 4 * cm, fill=1, stroke=0)
    c.setFillColor(HexColor("#ffffff"))
    c.setFont("Helvetica-Bold", 22)
    c.drawString(margin_l, h - 2.5 * cm, f"Steuererklärung {declaration.year}")
    c.setFont("Helvetica", 11)
    c.setFillColor(HexColor("#a8b8d0"))
    c.drawString(margin_l, h - 3.3 * cm,
                 f"Entwurf — {user.email if user else ''} — "
                 f"Stand {date.today().strftime('%d.%m.%Y')}")
    # Status badge
    status_label = "ABGESCHLOSSEN" if declaration.status == "finalized" else "ENTWURF"
    badge_color = ACCENT if declaration.status == "finalized" else HexColor("#f59e0b")
    badge_w = 3.5 * cm
    c.setFillColor(badge_color)
    c.roundRect(w - margin_r - badge_w, h - 3.0 * cm, badge_w, 0.7 * cm, 0.15 * cm, fill=1, stroke=0)
    c.setFillColor(HexColor("#0f1a2e"))
    c.setFont("Helvetica-Bold", 9)
    c.drawCentredString(w - margin_r - badge_w / 2, h - 2.8 * cm, status_label)

    y = h - 5 * cm

    # ─── Sections ───
    for section in FORM_SECTIONS:
        # Section header band
        if y < 5 * cm:
            y = new_page()
        c.setFillColor(LIGHT_BG)
        c.rect(margin_l, y - 0.7 * cm, content_w, 0.9 * cm, fill=1, stroke=0)
        c.setFillColor(INK)
        c.setFont("Helvetica-Bold", 11)
        c.drawString(margin_l + 0.3 * cm, y - 0.45 * cm, section["title_de"])
        y -= 1.3 * cm

        # Fields as label + value rows
        for f in section["fields"]:
            if y < 3.5 * cm:
                y = new_page()
            label = f["label_de"]
            value = data.get(f["key"], "")
            value_str = str(value) if value not in (None, "") else "—"

            c.setFillColor(MUTED)
            c.setFont("Helvetica", 8)
            c.drawString(margin_l + 0.3 * cm, y, label.upper())
            # Value with underline
            c.setFillColor(INK)
            c.setFont("Helvetica-Bold" if value not in (None, "") else "Helvetica", 11)
            c.drawString(margin_l + 0.3 * cm, y - 0.5 * cm, value_str)
            c.setStrokeColor(BORDER)
            c.setLineWidth(0.4)
            c.line(margin_l + 0.3 * cm, y - 0.65 * cm,
                   margin_l + content_w - 0.3 * cm, y - 0.65 * cm)
            y -= 1.1 * cm
        y -= 0.3 * cm

    # ─── Summary box at the end ───
    if y < 5 * cm:
        y = new_page()
    c.setFillColor(LIGHT_BG)
    c.rect(margin_l, y - 2.5 * cm, content_w, 2.5 * cm, fill=1, stroke=0)
    c.setStrokeColor(BORDER)
    c.setLineWidth(0.6)
    c.rect(margin_l, y - 2.5 * cm, content_w, 2.5 * cm, fill=0, stroke=1)
    c.setFillColor(INK)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(margin_l + 0.3 * cm, y - 0.6 * cm, "ZUSAMMENFASSUNG")
    c.setFont("Helvetica", 9)
    gewinn = data.get("gewinn_eur", "—")
    kv_basis = data.get("kv_basis", "—")
    c.drawString(margin_l + 0.3 * cm, y - 1.2 * cm,
                 f"Gewinn aus selbständiger Tätigkeit:  {gewinn} €")
    c.drawString(margin_l + 0.3 * cm, y - 1.7 * cm,
                 f"Krankenversicherung Basis:           {kv_basis} €")
    c.drawString(margin_l + 0.3 * cm, y - 2.2 * cm,
                 "Diese Angaben dienen als Übersicht. Verbindlich nur nach Einreichung bei ELSTER.")

    draw_footer()
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
