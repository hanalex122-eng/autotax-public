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
            {"key": "steuer_id",      "label_de": "Steuer-ID (11-stellig)",       "label_tr": "Vergi kimlik no (11 hane)",          "type": "text",   "required": True,  "pattern": r"^\d{11}$",
             "hint_de": "Findest du auf jedem Steuerbescheid oder Lohnabrechnung. Beispiel: 12345678901",
             "hint_tr": "Her Steuerbescheid veya Lohnabrechnung'da bulursun. Örnek: 12345678901"},
            {"key": "steuer_nummer",  "label_de": "Steuernummer (optional)",       "label_tr": "Steuernummer (opsiyonel)",            "type": "text",   "required": False,
             "hint_de": "Vom Finanzamt erteilt — anders als Steuer-ID. Format z.B. 040/123/45678",
             "hint_tr": "Finanzamt'tan alınan numara — Steuer-ID'den farklı. Format örn. 040/123/45678"},
            {"key": "vorname",        "label_de": "Vorname",                       "label_tr": "Ad",                                  "type": "text",   "required": True,
             "hint_de": "Wie im Personalausweis",
             "hint_tr": "Kimlik kartındaki gibi"},
            {"key": "nachname",       "label_de": "Nachname",                      "label_tr": "Soyad",                               "type": "text",   "required": True,
             "hint_de": "Wie im Personalausweis",
             "hint_tr": "Kimlik kartındaki gibi"},
            {"key": "geburtsdatum",   "label_de": "Geburtsdatum",                  "label_tr": "Doğum tarihi",                        "type": "date",   "required": True,
             "hint_de": "TT.MM.JJJJ",
             "hint_tr": "GG.AA.YYYY"},
            {"key": "religion",       "label_de": "Religion",                      "label_tr": "Din",                                 "type": "select", "required": True,
             "options": [{"v": "none", "de": "Keine", "tr": "Yok"}, {"v": "ev", "de": "Evangelisch", "tr": "Evanjelik"}, {"v": "rk", "de": "Römisch-katholisch", "tr": "Katolik"}, {"v": "other", "de": "Andere", "tr": "Diğer"}],
             "hint_de": "Nur Kirchensteuer-pflichtige Konfessionen ankreuzen. Muslime / Atheisten → 'Keine'",
             "hint_tr": "Sadece kilise vergisi yükümlü dinler. Müslüman / Ateist → 'Yok'"},
            {"key": "strasse",        "label_de": "Straße + Hausnummer",           "label_tr": "Sokak + ev no",                       "type": "text",   "required": True,
             "hint_de": "Wohnadresse zum 31.12. des Steuerjahres",
             "hint_tr": "Vergi yılı 31.12 itibarıyla ev adresi"},
            {"key": "plz",            "label_de": "PLZ",                           "label_tr": "Posta kodu",                          "type": "text",   "required": True,  "pattern": r"^\d{5}$",
             "hint_de": "5-stellig",
             "hint_tr": "5 hane"},
            {"key": "ort",            "label_de": "Ort",                           "label_tr": "Şehir",                               "type": "text",   "required": True,
             "hint_de": "Stadt / Gemeinde",
             "hint_tr": "Şehir / belediye"},
            {"key": "familienstand",  "label_de": "Familienstand",                 "label_tr": "Medeni hal",                          "type": "select", "required": True,
             "options": [{"v": "ledig", "de": "Ledig", "tr": "Bekar"}, {"v": "verheiratet", "de": "Verheiratet", "tr": "Evli"}, {"v": "geschieden", "de": "Geschieden", "tr": "Boşanmış"}, {"v": "verwitwet", "de": "Verwitwet", "tr": "Dul"}],
             "hint_de": "Status zum 31.12. des Steuerjahres. Verheiratet → Splittingtarif möglich.",
             "hint_tr": "Vergi yılı 31.12 itibarıyla durum. Evli → Splittingtarif olası."},
            {"key": "iban",           "label_de": "IBAN (Erstattung)",             "label_tr": "IBAN (iade için)",                    "type": "text",   "required": True,  "pattern": r"^DE\d{20}$",
             "hint_de": "Wohin soll das Finanzamt eine Erstattung überweisen? Nur deutsche IBAN.",
             "hint_tr": "Finanzamt iade tutarı nereye gönderecek? Sadece Alman IBAN."},
            {"key": "kontoinhaber",   "label_de": "Kontoinhaber",                  "label_tr": "Hesap sahibi",                        "type": "text",   "required": True,
             "hint_de": "Name auf dem Konto — bei eigenem Konto: dein Name",
             "hint_tr": "Hesap üstündeki isim — kendi hesabınsa: kendi adın"},
        ],
    },
    {
        "key": "anlage_s",
        "title_de": "Anlage S — Selbständige Tätigkeit",
        "title_tr": "Anlage S — Serbest meslek",
        "fields": [
            {"key": "taetigkeit",         "label_de": "Tätigkeit (z.B. IT-Consulting)", "label_tr": "Meslek (örn. IT danışmanlık)",  "type": "text",   "required": True,
             "hint_de": "Kurze Beschreibung deiner freiberuflichen Tätigkeit (1-3 Wörter)",
             "hint_tr": "Serbest mesleki faaliyetinin kısa açıklaması (1-3 kelime)"},
            {"key": "gewinn_eur",         "label_de": "Gewinn aus EÜR (€)",             "label_tr": "EÜR kazancı (€)",                "type": "number", "required": True, "auto_fill_from": "eur_profit",
             "hint_de": "Einnahmen minus Ausgaben für das gesamte Jahr. Wir füllen automatisch aus deinen Belegen.",
             "hint_tr": "Yıl boyunca gelirler eksi giderler. Belgelerinden otomatik doldurulur."},
            {"key": "veraeusserungsgewinn", "label_de": "Veräußerungsgewinn (€)",       "label_tr": "Sermaye gain (€)",               "type": "number", "required": False, "default": 0,
             "hint_de": "Verkauf von Praxis / Firma / Wertpapieren. In den meisten Fällen 0.",
             "hint_tr": "Praxis / firma / hisse satışından gelen. Çoğu durumda 0."},
        ],
    },
    {
        "key": "anlage_n",
        "title_de": "Anlage N — Lohn aus Anstellung (optional)",
        "title_tr": "Anlage N — Maaş (varsa, opsiyonel)",
        "fields": [
            {"key": "lohn_brutto", "label_de": "Bruttoarbeitslohn (Jahres)", "label_tr": "Yıllık brüt maaş",     "type": "number", "required": False, "default": 0,
             "hint_de": "Aus deiner Lohnsteuerbescheinigung Zeile 3 (Bruttoarbeitslohn).",
             "hint_tr": "Lohnsteuerbescheinigung Zeile 3'ten al."},
            {"key": "lohnsteuer", "label_de": "Einbehaltene Lohnsteuer (€)", "label_tr": "Kesilen Lohnsteuer (€)", "type": "number", "required": False, "default": 0,
             "hint_de": "Lohnsteuerbescheinigung Zeile 4 (einbehaltene Lohnsteuer).",
             "hint_tr": "Lohnsteuerbescheinigung Zeile 4."},
            {"key": "soli_n",     "label_de": "Solidaritätszuschlag (€)",     "label_tr": "Soli vergisi (€)",       "type": "number", "required": False, "default": 0,
             "hint_de": "Lohnsteuerbescheinigung Zeile 5.", "hint_tr": "Lohnsteuerbescheinigung Zeile 5."},
            {"key": "kirchensteuer", "label_de": "Kirchensteuer (€)",          "label_tr": "Kilise vergisi (€)",     "type": "number", "required": False, "default": 0,
             "hint_de": "Falls religiöse Konfession; sonst 0.", "hint_tr": "Dini mensubiyet varsa; yoksa 0."},
            {"key": "werbungskosten_n", "label_de": "Werbungskosten (Pauschbetrag €1.230 oder höher)", "label_tr": "Werbungskosten (sabit €1.230 veya yüksek)", "type": "number", "required": False, "default": 1230,
             "hint_de": "Arbeitnehmer-Pauschbetrag (2025: €1.230). Höher nur wenn nachgewiesen.",
             "hint_tr": "İşçi sabit indirimi (2025: €1.230). Yüksek için kanıt gerekir."},
        ],
    },
    {
        "key": "anlage_v",
        "title_de": "Anlage V — Vermietung & Verpachtung (optional)",
        "title_tr": "Anlage V — Kira gelirleri (varsa, opsiyonel)",
        "fields": [
            {"key": "v_adresse",    "label_de": "Adresse Mietobjekt",          "label_tr": "Kiralanan mülk adresi",  "type": "text",   "required": False,
             "hint_de": "Straße + Hausnummer + PLZ + Ort der vermieteten Immobilie.",
             "hint_tr": "Kiralanan mülkün sokak + ev no + PLZ + şehri."},
            {"key": "v_einnahmen", "label_de": "Mieteinnahmen Jahres (€)",     "label_tr": "Yıllık kira geliri (€)",  "type": "number", "required": False, "default": 0,
             "hint_de": "Summe aller Mieteinnahmen ohne Nebenkosten-Vorauszahlungen.",
             "hint_tr": "Tüm kira gelirlerinin toplamı (yan giderler ön ödemeleri hariç)."},
            {"key": "v_nebenkosten", "label_de": "Umlagefähige Nebenkosten erhalten (€)", "label_tr": "Alınan ortak giderler (€)", "type": "number", "required": False, "default": 0,
             "hint_de": "Vorauszahlungen vom Mieter (Wasser, Heizung etc).",
             "hint_tr": "Kiracıdan alınan ön ödemeler (su, ısınma vs.)."},
            {"key": "v_afa",       "label_de": "AfA Gebäude 2% pro Jahr (€)",  "label_tr": "Yıllık bina AfA %2 (€)",   "type": "number", "required": False, "default": 0,
             "hint_de": "Anschaffungskosten Gebäude × 2% (50 Jahre Nutzungsdauer).",
             "hint_tr": "Bina edinme bedeli × %2 (50 yıl kullanım ömrü)."},
            {"key": "v_zinsen",    "label_de": "Schuldzinsen Darlehen (€)",    "label_tr": "Kredi faizleri (€)",       "type": "number", "required": False, "default": 0,
             "hint_de": "Hypothek-Zinsen für die Mietimmobilie.",
             "hint_tr": "Kira mülkü için ipotek faizleri."},
            {"key": "v_erhaltung", "label_de": "Erhaltungsaufwand (Reparatur) (€)", "label_tr": "Bakım/onarım gideri (€)", "type": "number", "required": False, "default": 0,
             "hint_de": "Reparaturen, Instandhaltung (sofort absetzbar). Größere Umbauten sind Herstellungskosten.",
             "hint_tr": "Onarım, bakım (hemen düşülebilir). Büyük tadilatlar Herstellungskosten'dir."},
            {"key": "v_grundsteuer", "label_de": "Grundsteuer + Versicherung (€)", "label_tr": "Emlak vergisi + sigorta (€)", "type": "number", "required": False, "default": 0,
             "hint_de": "Grundsteuer, Wohngebäudeversicherung etc.",
             "hint_tr": "Emlak vergisi, bina sigortası vb."},
            {"key": "v_sonst",     "label_de": "Sonstige Werbungskosten (€)",  "label_tr": "Diğer giderler (€)",       "type": "number", "required": False, "default": 0,
             "hint_de": "Hausverwaltung, Inserate, Anwaltskosten etc.",
             "hint_tr": "Yönetim, ilan, avukat masrafları vs."},
        ],
    },
    {
        "key": "anlage_sonderausgaben",
        "title_de": "Sonderausgaben & §35a (haushaltsnahe)",
        "title_tr": "Özel giderler + §35a (ev hizmetleri)",
        "fields": [
            {"key": "spenden_geld",    "label_de": "Spenden — Geldspenden gemeinnützig (€)",  "label_tr": "Geldspende (€)",        "type": "number", "required": False, "default": 0,
             "hint_de": "Steuerlich begünstigt bis 20% des Gesamtbetrags der Einkünfte. Spendenbescheinigung Pflicht.",
             "hint_tr": "Toplam gelirin %20'sine kadar düşülebilir. Spendenbescheinigung zorunlu."},
            {"key": "spenden_partei",  "label_de": "Spenden Parteien (€)",                    "label_tr": "Parti bağışı (€)",       "type": "number", "required": False, "default": 0,
             "hint_de": "50% absetzbar bis €825 Single / €1.650 Verheiratet (§34g EStG).",
             "hint_tr": "%50 düşülebilir; bekar €825 / evli €1.650'ye kadar."},
            {"key": "steuerberater",   "label_de": "Steuerberaterkosten (privat) (€)",        "label_tr": "Mali müşavir ücreti (€)", "type": "number", "required": False, "default": 0,
             "hint_de": "Privater Anteil — beruflicher Anteil ist Werbungskosten / Betriebsausgaben.",
             "hint_tr": "Özel kısmı — iş kısmı Werbungskosten/EÜR'de."},
            {"key": "kirchensteuer_so","label_de": "Kirchensteuer (gezahlt) (€)",             "label_tr": "Kilise vergisi (€)",      "type": "number", "required": False, "default": 0,
             "hint_de": "Voll absetzbar als Sonderausgabe (außer auf Kapitalerträge).",
             "hint_tr": "Tam düşülebilir (sermaye gelirlerine ait hariç)."},
            {"key": "handwerker_lohn", "label_de": "Handwerker-Lohnanteil §35a (€)",          "label_tr": "Esnaf işçilik ücreti (€)","type": "number", "required": False, "default": 0,
             "hint_de": "20% absetzbar bis €1.200/Jahr. Nur Lohn (nicht Material). Rechnung + Überweisung Pflicht.",
             "hint_tr": "%20 düşülebilir, yıllık €1.200'e kadar. Sadece işçilik (malzeme değil). Fatura + havale zorunlu."},
            {"key": "haushaltsdienst", "label_de": "Haushaltsnahe Dienstleistungen §35a (€)", "label_tr": "Ev hizmeti (€)",          "type": "number", "required": False, "default": 0,
             "hint_de": "20% absetzbar bis €4.000/Jahr. Reinigung, Gartenpflege, Pflegedienst.",
             "hint_tr": "%20 düşülebilir, yıllık €4.000'e kadar. Temizlik, bahçe, bakım."},
            {"key": "haushaltshilfe_mini", "label_de": "Mini-Job Haushalt §35a (€)",          "label_tr": "Mini-Job ev (€)",         "type": "number", "required": False, "default": 0,
             "hint_de": "20% absetzbar bis €510/Jahr. Geringfügig Beschäftigte im Haushalt.",
             "hint_tr": "%20 düşülebilir, yıllık €510'a kadar. Küçük istihdamlı ev çalışanı."},
        ],
    },
    {
        "key": "anlage_vorsorge",
        "title_de": "Anlage Vorsorgeaufwand",
        "title_tr": "Anlage Vorsorgeaufwand (sigortalar)",
        "fields": [
            {"key": "kv_basis",   "label_de": "Krankenversicherung Basis (€)",       "label_tr": "Temel sağlık sigortası (€)",  "type": "number", "required": True,
             "hint_de": "Jahresbeitrag ohne Wahlleistungen. Aus Bescheinigung der Krankenkasse §10 EStG.",
             "hint_tr": "Yıllık prim, ek hizmetler hariç. Sağlık kasası §10 EStG belgesinden."},
            {"key": "kv_zusatz",  "label_de": "Krankenversicherung Zusatz (€)",      "label_tr": "Ek sağlık sigortası (€)",     "type": "number", "required": False, "default": 0,
             "hint_de": "Krankentagegeld, Chefarzt, Einzelzimmer etc.",
             "hint_tr": "Hastalık günlüğü, baş doktor, tek kişilik oda vs."},
            {"key": "pflege",     "label_de": "Pflegeversicherung (€)",              "label_tr": "Bakım sigortası (€)",         "type": "number", "required": False, "default": 0,
             "hint_de": "Pflichtbeitrag + ggf. Zusatz. Aus Beitragsbescheinigung.",
             "hint_tr": "Zorunlu prim + opsiyonel ek. Beitragsbescheinigung'dan."},
            {"key": "rente_gesetz", "label_de": "Gesetzliche Rentenversicherung (€)", "label_tr": "Yasal emekli sigortası (€)",  "type": "number", "required": False, "default": 0,
             "hint_de": "Eigene Beiträge an Deutsche Rentenversicherung (DRV).",
             "hint_tr": "Deutsche Rentenversicherung'a (DRV) ödenen kendi primler."},
            {"key": "rurup",      "label_de": "Rürup-Rente (€)",                     "label_tr": "Rürup emekliliği (€)",        "type": "number", "required": False, "default": 0,
             "hint_de": "Basis-Rente nach §10 Abs.1 Nr.2 EStG. Aus Jahresbescheinigung.",
             "hint_tr": "§10 Abs.1 Nr.2 EStG'e göre temel emeklilik. Yıllık belge'den."},
            {"key": "bu",         "label_de": "Berufsunfähigkeitsversicherung (€)",  "label_tr": "Maluliyet sigortası (€)",     "type": "number", "required": False, "default": 0,
             "hint_de": "Berufsunfähigkeitsversicherung — meist absetzbar.",
             "hint_tr": "Maluliyet sigortası — genelde düşülebilir."},
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
# Insurance detection — vendor + raw_text patterns for Vorsorge fields.
# ───────────────────────────────────────────────────────────────────

# Krankenkassen patterns (gesetzlich). Each tuple = (key, pattern).
_KRANKENKASSE_PATTERNS = [
    "tk", "techniker krankenkasse", "aok", "barmer", "dak", "ikk",
    "kkh", "hkk", "bkk", "knappschaft", "siemens-betriebskrankenkasse",
    "viactiv", "mobil krankenkasse", "audi bkk",
]

# Privat Krankenversicherung (basis) — wenn vendor PKV insurance gibt
_PKV_PATTERNS = [
    "debeka", "allianz private", "axa krankenversicherung", "ergo direkt kranken",
    "huk-coburg krankenversicherung", "barmenia kranken", "central kranken",
    "continentale kranken", "dkv", "gothaer kranken", "hallesche", "hanse merkur",
    "inter krankenversicherung", "nuernberger kranken", "signal iduna kranken",
    "uniVersa kranken",
]

_PFLEGE_PATTERNS = ["pflegeversicherung", "pflege-pflichtversicherung"]
_RENTE_PATTERNS = ["deutsche rentenversicherung", "drv ", "drv-bund",
                   "rentenversicherung bund", "gesetzliche rente"]
_RURUP_PATTERNS = ["rürup", "rurup", "basisrente", "basis-rente"]
_BU_PATTERNS = ["berufsunfähigkeit", "berufsunfaehigkeit", "berufsunfäh",
                "bu-versicherung", "bu versicherung"]


def _match_any(text: str, patterns: list) -> bool:
    t = (text or "").lower()
    return any(p in t for p in patterns)


def detect_insurance_amounts(db, user_id: int, year: int) -> dict:
    """Scan year's invoices, group expense amounts by Vorsorge category.

    Heuristic: vendor name + raw_text matched against pattern lists.
    Returns dict with keys matching form fields (kv_basis, pflege, etc.).
    Only sums (no field gets overwritten if already partial).
    """
    out: dict[str, float] = {}
    try:
        # Import models locally to avoid circular import at module load time.
        from autotax.models import Invoice
        from sqlalchemy import func as _func
        year_prefix = f"{year}-"
        rows = db.query(Invoice).filter(
            Invoice.user_id == user_id,
            Invoice.invoice_type == "expense",
            Invoice.is_deleted.is_(False),
            Invoice.date.like(f"{year_prefix}%"),
        ).all()
        for inv in rows:
            vendor = (inv.vendor or "")
            raw = (inv.raw_text or "")[:2000]  # cap to limit work
            amt = float(inv.total_amount or 0)
            if amt <= 0:
                continue
            combined = f"{vendor} {raw}".lower()
            if _match_any(combined, _KRANKENKASSE_PATTERNS) or \
               _match_any(combined, _PKV_PATTERNS):
                out["kv_basis"] = out.get("kv_basis", 0.0) + amt
            if _match_any(combined, _PFLEGE_PATTERNS):
                out["pflege"] = out.get("pflege", 0.0) + amt
            if _match_any(combined, _RENTE_PATTERNS):
                out["rente_gesetz"] = out.get("rente_gesetz", 0.0) + amt
            if _match_any(combined, _RURUP_PATTERNS):
                out["rurup"] = out.get("rurup", 0.0) + amt
            if _match_any(combined, _BU_PATTERNS):
                out["bu"] = out.get("bu", 0.0) + amt
    except Exception:
        logger.exception("detect_insurance_amounts failed")
    # Round 2 decimals
    return {k: round(v, 2) for k, v in out.items()}


# ───────────────────────────────────────────────────────────────────
# Auto-fill from user/company/invoice data.
# ───────────────────────────────────────────────────────────────────

def autofill_from_user_data(user, companies: list, eur_profit: float,
                            *, insurance_amounts: Optional[dict] = None) -> dict:
    """Pre-populate form with data we already have from the app.

    Caller passes already-loaded User + UserCompany list + computed
    EÜR profit (sum of income - sum of expenses for the year).
    Optional `insurance_amounts` dict (from detect_insurance_amounts) is
    merged into Anlage Vorsorgeaufwand fields.
    """
    out: dict[str, Any] = {}

    # Mantelbogen: from User profile
    full_name = ""
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

    # Anlage Vorsorgeaufwand: from detected insurance payments
    if insurance_amounts:
        for k, v in insurance_amounts.items():
            if v > 0:
                out[k] = v

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

def _human_value(value, options: list | None = None, lang: str = "de") -> str:
    """Format raw form value for display (Religion → 'Keine', etc)."""
    if value in (None, ""):
        return "—"
    if options:
        for o in options:
            if str(o.get("v")) == str(value):
                return o.get(lang) or o.get("de") or str(value)
    return str(value)


def generate_pdf_skeleton(declaration, user, companies: list) -> bytes:
    """Render declaration as ESt 1 A-inspired PDF.

    Structure mimics official ELSTER form:
    - Header band: "Einkommensteuererklärung YYYY" + tax office (Finanzamt)
      placeholder + Steuernummer/Steuer-ID boxes.
    - Numbered Zeilen (lines) like real form (Zeile 1, 2, 3 ...).
    - 2-column field layout where it fits.
    - Checkbox-style options for select fields (Familienstand, Religion).
    - Section dividers with title bands.
    - Summary block + Anlagen tick list at end.
    - Footer disclaimer.
    """
    import io
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas as pdf_canvas
    from reportlab.lib.units import cm
    from reportlab.lib.colors import HexColor

    NAVY = HexColor("#0f1a2e")
    INK = HexColor("#1a2d4a")
    MUTED = HexColor("#7a8ba8")
    DIM = HexColor("#9aa5b5")
    ACCENT = HexColor("#10b981")
    BAND_BG = HexColor("#eaeff5")
    LIGHT_BG = HexColor("#f7f9fc")
    BORDER = HexColor("#c5cfdb")
    BOX_BORDER = HexColor("#9aa5b5")
    LINE_NUM = HexColor("#788599")

    buf = io.BytesIO()
    c = pdf_canvas.Canvas(buf, pagesize=A4)
    w, h = A4
    data = deserialize_data(declaration.data)

    margin_l = 1.5 * cm
    margin_r = 1.5 * cm
    content_w = w - margin_l - margin_r
    col_gap = 0.5 * cm
    col_w = (content_w - col_gap) / 2

    line_counter = [1]

    def draw_footer(pageno: int):
        c.setFillColor(MUTED)
        c.setFont("Helvetica", 7)
        c.drawString(margin_l, 1.3 * cm,
                     f"AutoTax.Cloud · Entwurf · Erstellt {date.today().strftime('%d.%m.%Y')}")
        c.drawString(margin_l, 0.95 * cm,
                     "Keine rechtsverbindliche Steuerberatung — bitte vor ELSTER-Übermittlung prüfen.")
        c.drawRightString(w - margin_r, 0.95 * cm,
                          f"Seite {pageno} · ESt {declaration.year}")

    page_no = [1]

    def new_page():
        draw_footer(page_no[0])
        c.showPage()
        page_no[0] += 1
        # Slim header band on continuation pages
        c.setFillColor(NAVY)
        c.rect(0, h - 1.4 * cm, w, 1.4 * cm, fill=1, stroke=0)
        c.setFillColor(HexColor("#ffffff"))
        c.setFont("Helvetica-Bold", 11)
        c.drawString(margin_l, h - 0.95 * cm,
                     f"Einkommensteuererklärung {declaration.year} (Fortsetzung)")
        c.setFont("Helvetica", 9)
        c.setFillColor(HexColor("#a8b8d0"))
        c.drawRightString(w - margin_r, h - 0.95 * cm,
                          f"{user.email if user else ''}")
        return h - 2.2 * cm

    def ensure_space(y, needed):
        if y - needed < 2 * cm:
            return new_page()
        return y

    def draw_line_num(y, x=None):
        if x is None:
            x = margin_l - 0.0 * cm
        c.setFillColor(LINE_NUM)
        c.setFont("Helvetica-Bold", 7)
        c.drawString(x - 0.7 * cm, y, f"{line_counter[0]}")
        line_counter[0] += 1

    def draw_field_box(x, y, box_w, label, value, *, show_line_num=False):
        """Single field: tiny uppercase label above a bordered value box."""
        if show_line_num:
            draw_line_num(y)
        c.setFillColor(LIGHT_BG)
        c.setStrokeColor(BOX_BORDER)
        c.setLineWidth(0.5)
        c.roundRect(x, y - 0.95 * cm, box_w, 0.85 * cm, 0.08 * cm, fill=1, stroke=1)
        c.setFillColor(MUTED)
        c.setFont("Helvetica", 6.5)
        c.drawString(x + 0.18 * cm, y - 0.2 * cm, label.upper())
        c.setFillColor(INK)
        c.setFont("Helvetica-Bold" if value and value != "—" else "Helvetica", 10.5)
        c.drawString(x + 0.18 * cm, y - 0.7 * cm, str(value)[:60])

    def draw_checkbox_row(x, y, options, selected, lang="de"):
        """Render select field as horizontal checkbox row (ELSTER style)."""
        cur_x = x
        for o in options:
            is_sel = str(o.get("v")) == str(selected)
            # Box
            c.setStrokeColor(BOX_BORDER)
            c.setLineWidth(0.5)
            c.setFillColor(INK if is_sel else HexColor("#ffffff"))
            c.rect(cur_x, y - 0.32 * cm, 0.32 * cm, 0.32 * cm, fill=1, stroke=1)
            if is_sel:
                c.setStrokeColor(HexColor("#ffffff"))
                c.setLineWidth(1.4)
                c.line(cur_x + 0.06 * cm, y - 0.16 * cm,
                       cur_x + 0.13 * cm, y - 0.26 * cm)
                c.line(cur_x + 0.13 * cm, y - 0.26 * cm,
                       cur_x + 0.27 * cm, y - 0.05 * cm)
            c.setFillColor(INK)
            c.setFont("Helvetica-Bold" if is_sel else "Helvetica", 9)
            label = o.get(lang) or o.get("de") or o.get("v")
            c.drawString(cur_x + 0.45 * cm, y - 0.22 * cm, label)
            cur_x += 0.45 * cm + c.stringWidth(label, "Helvetica", 9) + 0.6 * cm

    # ─────────────────────────────────────────────────────────
    # PAGE 1 — HEADER + Steuerpflichtige (Mantelbogen part 1)
    # ─────────────────────────────────────────────────────────

    # Top header band
    c.setFillColor(NAVY)
    c.rect(0, h - 3.5 * cm, w, 3.5 * cm, fill=1, stroke=0)
    c.setFillColor(HexColor("#ffffff"))
    c.setFont("Helvetica-Bold", 19)
    c.drawString(margin_l, h - 1.7 * cm, "Einkommensteuererklärung")
    c.setFont("Helvetica-Bold", 14)
    c.drawString(margin_l, h - 2.5 * cm, str(declaration.year))
    c.setFont("Helvetica", 9)
    c.setFillColor(HexColor("#a8b8d0"))
    c.drawString(margin_l, h - 3.1 * cm,
                 "Entwurf, erstellt mit AutoTax.Cloud — kein offizielles ELSTER-Formular")

    # Status badge top-right
    status_label = "ABGESCHLOSSEN" if declaration.status == "finalized" else "ENTWURF"
    badge_color = ACCENT if declaration.status == "finalized" else HexColor("#f59e0b")
    badge_w = 3.2 * cm
    c.setFillColor(badge_color)
    c.roundRect(w - margin_r - badge_w, h - 2.4 * cm, badge_w, 0.7 * cm,
                0.15 * cm, fill=1, stroke=0)
    c.setFillColor(NAVY)
    c.setFont("Helvetica-Bold", 9)
    c.drawCentredString(w - margin_r - badge_w / 2, h - 2.2 * cm, status_label)

    # Steuernummer / Steuer-ID boxes
    c.setFillColor(HexColor("#ffffff"))
    box_y = h - 3.2 * cm
    c.setFont("Helvetica", 7)
    c.drawRightString(w - margin_r - 4.7 * cm, box_y + 0.5 * cm, "Steuer-ID")
    c.setFont("Helvetica-Bold", 10)
    c.drawRightString(w - margin_r, box_y + 0.5 * cm,
                      data.get("steuer_id", "—"))

    y = h - 4.2 * cm

    # ─── Section: STEUERPFLICHTIGE / Wohnanschrift ───
    def section_band(title, y_pos):
        c.setFillColor(BAND_BG)
        c.rect(margin_l, y_pos - 0.65 * cm, content_w, 0.7 * cm, fill=1, stroke=0)
        c.setStrokeColor(INK)
        c.setLineWidth(0.6)
        c.line(margin_l, y_pos - 0.65 * cm,
               margin_l + content_w, y_pos - 0.65 * cm)
        c.setFillColor(INK)
        c.setFont("Helvetica-Bold", 10)
        c.drawString(margin_l + 0.2 * cm, y_pos - 0.45 * cm, title.upper())
        return y_pos - 1.1 * cm

    y = section_band("A — Steuerpflichtige Person", y)

    # Row 1: Vorname | Nachname (2 cols)
    draw_field_box(margin_l, y, col_w, "Vorname",
                   _human_value(data.get("vorname"), None, "de"), show_line_num=True)
    draw_field_box(margin_l + col_w + col_gap, y, col_w, "Nachname",
                   _human_value(data.get("nachname"), None, "de"))
    y -= 1.25 * cm

    # Row 2: Geburtsdatum | Steuernummer
    draw_field_box(margin_l, y, col_w, "Geburtsdatum",
                   _human_value(data.get("geburtsdatum"), None, "de"), show_line_num=True)
    draw_field_box(margin_l + col_w + col_gap, y, col_w, "Steuernummer",
                   _human_value(data.get("steuer_nummer"), None, "de"))
    y -= 1.25 * cm

    # Religion — checkbox row (with Zeile number)
    draw_line_num(y - 0.1 * cm)
    c.setFillColor(MUTED)
    c.setFont("Helvetica", 7)
    c.drawString(margin_l + 0.18 * cm, y, "RELIGION (KIRCHENSTEUER)")
    religion_options = next((f["options"] for f in FORM_SECTIONS[0]["fields"]
                            if f["key"] == "religion"), [])
    draw_checkbox_row(margin_l + 0.18 * cm, y - 0.55 * cm,
                      religion_options, data.get("religion"))
    y -= 1.4 * cm

    # Familienstand — checkbox row
    draw_line_num(y - 0.1 * cm)
    c.setFillColor(MUTED)
    c.setFont("Helvetica", 7)
    c.drawString(margin_l + 0.18 * cm, y, "FAMILIENSTAND")
    fs_options = next((f["options"] for f in FORM_SECTIONS[0]["fields"]
                      if f["key"] == "familienstand"), [])
    draw_checkbox_row(margin_l + 0.18 * cm, y - 0.55 * cm,
                      fs_options, data.get("familienstand"))
    y -= 1.7 * cm

    # ─── Section: WOHNANSCHRIFT ───
    y = ensure_space(y, 4 * cm)
    y = section_band("B — Wohnanschrift (Stand 31.12.)", y)

    # Strasse (full width) — Zeile
    draw_field_box(margin_l, y, content_w, "Straße + Hausnummer",
                   _human_value(data.get("strasse"), None, "de"), show_line_num=True)
    y -= 1.25 * cm
    # PLZ (kurz) + Ort (rest)
    plz_w = 3.5 * cm
    ort_w = content_w - plz_w - col_gap
    draw_field_box(margin_l, y, plz_w, "PLZ",
                   _human_value(data.get("plz"), None, "de"), show_line_num=True)
    draw_field_box(margin_l + plz_w + col_gap, y, ort_w, "Ort",
                   _human_value(data.get("ort"), None, "de"))
    y -= 1.6 * cm

    # ─── Section: BANKVERBINDUNG (Erstattung) ───
    y = ensure_space(y, 4 * cm)
    y = section_band("C — Bankverbindung für Erstattung", y)

    draw_field_box(margin_l, y, content_w, "IBAN",
                   _human_value(data.get("iban"), None, "de"), show_line_num=True)
    y -= 1.25 * cm
    draw_field_box(margin_l, y, content_w, "Kontoinhaber",
                   _human_value(data.get("kontoinhaber"), None, "de"), show_line_num=True)
    y -= 1.6 * cm

    # ─── Section: ANLAGE S ───
    y = ensure_space(y, 5 * cm)
    y = section_band("D — Anlage S (Selbständige Tätigkeit)", y)

    # Tätigkeit full width
    draw_field_box(margin_l, y, content_w, "Tätigkeit",
                   _human_value(data.get("taetigkeit"), None, "de"), show_line_num=True)
    y -= 1.25 * cm
    # Gewinn (left) + Veräußerungsgewinn (right)
    eur_w = (content_w - col_gap) / 2
    gewinn_val = data.get("gewinn_eur")
    gewinn_str = f"{float(gewinn_val):.2f} €" if gewinn_val not in (None, "") else "—"
    vg_val = data.get("veraeusserungsgewinn")
    vg_str = f"{float(vg_val):.2f} €" if vg_val not in (None, "") else "—"
    draw_field_box(margin_l, y, eur_w, "Gewinn aus EÜR",
                   gewinn_str, show_line_num=True)
    draw_field_box(margin_l + eur_w + col_gap, y, eur_w,
                   "Veräußerungsgewinn", vg_str)
    y -= 1.6 * cm

    # ─── Section: ANLAGE N (Lohnsteuer — falls vorhanden) ───
    anlage_n = data.get("lohn_brutto") or data.get("lohnsteuer")
    if anlage_n:
        y = ensure_space(y, 6 * cm)
        y = section_band("E — Anlage N (Lohn aus Anstellung)", y)
        n_rows = [
            ("lohn_brutto", "Bruttoarbeitslohn (Jahres)"),
            ("lohnsteuer", "Einbehaltene Lohnsteuer"),
            ("soli_n", "Solidaritätszuschlag"),
            ("kirchensteuer", "Kirchensteuer"),
            ("werbungskosten_n", "Werbungskosten (Pauschbetrag)"),
        ]
        for i in range(0, len(n_rows), 2):
            y = ensure_space(y, 2.5 * cm)
            for j, (key, label) in enumerate(n_rows[i:i + 2]):
                x = margin_l + j * (eur_w + col_gap)
                val = data.get(key)
                val_str = f"{float(val):.2f} €" if val not in (None, "") else "—"
                draw_field_box(x, y, eur_w, label, val_str,
                               show_line_num=(j == 0))
            y -= 1.25 * cm
        y -= 0.3 * cm

    # ─── Section: ANLAGE V (Vermietung — falls vorhanden) ───
    anlage_v = data.get("v_einnahmen") or data.get("v_adresse")
    if anlage_v:
        y = ensure_space(y, 10 * cm)
        y = section_band("F — Anlage V (Vermietung & Verpachtung)", y)
        # Adresse full-width
        draw_field_box(margin_l, y, content_w, "Adresse Mietobjekt",
                       _human_value(data.get("v_adresse"), None, "de"),
                       show_line_num=True)
        y -= 1.25 * cm
        v_rows = [
            ("v_einnahmen", "Mieteinnahmen"),
            ("v_nebenkosten", "Umlagef. Nebenkosten erhalten"),
            ("v_afa", "AfA Gebäude 2%"),
            ("v_zinsen", "Schuldzinsen"),
            ("v_erhaltung", "Erhaltungsaufwand"),
            ("v_grundsteuer", "Grundsteuer + Versicherung"),
            ("v_sonst", "Sonstige Werbungskosten"),
        ]
        for i in range(0, len(v_rows), 2):
            y = ensure_space(y, 2.5 * cm)
            for j, (key, label) in enumerate(v_rows[i:i + 2]):
                x = margin_l + j * (eur_w + col_gap)
                val = data.get(key)
                val_str = f"{float(val or 0):.2f} €"
                draw_field_box(x, y, eur_w, label, val_str,
                               show_line_num=(j == 0))
            y -= 1.25 * cm
        # V net calculation
        v_net = (
            float(data.get("v_einnahmen") or 0)
            + float(data.get("v_nebenkosten") or 0)
            - float(data.get("v_afa") or 0)
            - float(data.get("v_zinsen") or 0)
            - float(data.get("v_erhaltung") or 0)
            - float(data.get("v_grundsteuer") or 0)
            - float(data.get("v_sonst") or 0)
        )
        c.setFillColor(INK)
        c.setFont("Helvetica-Bold", 10)
        c.drawString(margin_l + 0.3 * cm, y,
                     f"Überschuss Vermietung: {v_net:.2f} €")
        y -= 0.8 * cm

    # ─── Section: ANLAGE SONDERAUSGABEN (only if any field filled) ───
    so_keys = ("spenden_geld", "spenden_partei", "steuerberater",
               "kirchensteuer_so", "handwerker_lohn", "haushaltsdienst",
               "haushaltshilfe_mini")
    has_so = any(data.get(k) for k in so_keys)
    section_counter = ord("E")  # E is base after mandatory sections
    if anlage_n:
        section_counter += 1
    if anlage_v:
        section_counter += 1
    if has_so:
        letter_so = chr(section_counter)
        y = ensure_space(y, 6 * cm)
        y = section_band(f"{letter_so} — Sonderausgaben & §35a", y)
        so_rows = [
            ("spenden_geld", "Spenden Gemeinnützig"),
            ("spenden_partei", "Spenden Parteien"),
            ("steuerberater", "Steuerberater (privat)"),
            ("kirchensteuer_so", "Kirchensteuer gezahlt"),
            ("handwerker_lohn", "Handwerker §35a"),
            ("haushaltsdienst", "Haushaltsdienst §35a"),
            ("haushaltshilfe_mini", "Mini-Job Haushalt §35a"),
        ]
        for i in range(0, len(so_rows), 2):
            y = ensure_space(y, 2.5 * cm)
            for j, (key, label) in enumerate(so_rows[i:i + 2]):
                x = margin_l + j * (eur_w + col_gap)
                val = data.get(key)
                val_str = f"{float(val or 0):.2f} €"
                draw_field_box(x, y, eur_w, label, val_str,
                               show_line_num=(j == 0))
            y -= 1.25 * cm
        # §35a savings calculation
        so_handwerker = float(data.get("handwerker_lohn") or 0)
        so_haushalt = float(data.get("haushaltsdienst") or 0)
        so_mini = float(data.get("haushaltshilfe_mini") or 0)
        so_savings = (
            min(so_handwerker * 0.20, 1200)
            + min(so_haushalt * 0.20, 4000)
            + min(so_mini * 0.20, 510)
        )
        if so_savings > 0:
            c.setFillColor(INK)
            c.setFont("Helvetica-Bold", 10)
            c.drawString(margin_l + 0.3 * cm, y,
                         f"§35a Steuerermäßigung (geschätzt): {so_savings:.2f} €")
            y -= 0.8 * cm
        section_counter += 1

    # ─── Section: ANLAGE VORSORGEAUFWAND ───
    next_letter = chr(section_counter)
    y = ensure_space(y, 8 * cm)
    y = section_band(f"{next_letter} — Anlage Vorsorgeaufwand", y)

    vorsorge_rows = [
        ("kv_basis", "Krankenversicherung Basis"),
        ("kv_zusatz", "Krankenversicherung Zusatz"),
        ("pflege", "Pflegeversicherung"),
        ("rente_gesetz", "Gesetzliche Rente"),
        ("rurup", "Rürup-Rente"),
        ("bu", "Berufsunfähigkeit"),
    ]
    # 2-column layout for these
    for i in range(0, len(vorsorge_rows), 2):
        y = ensure_space(y, 2.5 * cm)
        for j, (key, label) in enumerate(vorsorge_rows[i:i + 2]):
            x = margin_l + j * (eur_w + col_gap)
            val = data.get(key)
            val_str = f"{float(val):.2f} €" if val not in (None, "") else "—"
            draw_field_box(x, y, eur_w, label, val_str,
                           show_line_num=(j == 0))
        y -= 1.25 * cm
    y -= 0.4 * cm

    # ─── Section: SUMMARY + Anlagen tick list ───
    y = ensure_space(y, 6 * cm)
    c.setStrokeColor(INK)
    c.setLineWidth(0.8)
    c.setFillColor(BAND_BG)
    c.rect(margin_l, y - 4.5 * cm, content_w, 4.5 * cm, fill=1, stroke=1)
    c.setFillColor(INK)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(margin_l + 0.3 * cm, y - 0.6 * cm,
                 f"ZUSAMMENFASSUNG — VERANLAGUNG {declaration.year}")

    c.setFont("Helvetica", 9)
    rows = [
        ("Gewinn aus selbständiger Tätigkeit (Anlage S)", gewinn_str),
        ("Krankenversicherung Basis (§10 Abs.1 Nr.3 EStG)",
         f"{float(data.get('kv_basis') or 0):.2f} €"),
        ("Krankenversicherung Zusatz",
         f"{float(data.get('kv_zusatz') or 0):.2f} €"),
        ("Pflegeversicherung",
         f"{float(data.get('pflege') or 0):.2f} €"),
        ("Gesetzliche Rentenversicherung",
         f"{float(data.get('rente_gesetz') or 0):.2f} €"),
        ("Rürup-Rente / Berufsunfähigkeitsversicherung",
         f"{float(data.get('rurup') or 0) + float(data.get('bu') or 0):.2f} €"),
    ]
    row_y = y - 1.2 * cm
    for label, val in rows:
        c.setFillColor(INK)
        c.setFont("Helvetica", 9)
        c.drawString(margin_l + 0.4 * cm, row_y, label)
        c.setFont("Helvetica-Bold", 9)
        c.drawRightString(margin_l + content_w - 0.4 * cm, row_y, val)
        row_y -= 0.5 * cm
    y -= 5.0 * cm

    # Anlagen tick list
    y = ensure_space(y, 3 * cm)
    c.setFillColor(MUTED)
    c.setFont("Helvetica-Bold", 8)
    c.drawString(margin_l, y, "ABGEGEBENE ANLAGEN")
    y -= 0.45 * cm
    anlagen = ["Anlage S", "Anlage EÜR", "Anlage Vorsorgeaufwand"]
    ax = margin_l
    c.setFont("Helvetica", 9)
    for a in anlagen:
        c.setFillColor(INK)
        c.rect(ax, y - 0.3 * cm, 0.3 * cm, 0.3 * cm, fill=1, stroke=1)
        c.setStrokeColor(HexColor("#ffffff"))
        c.setLineWidth(1.3)
        c.line(ax + 0.05 * cm, y - 0.15 * cm, ax + 0.12 * cm, y - 0.25 * cm)
        c.line(ax + 0.12 * cm, y - 0.25 * cm, ax + 0.25 * cm, y - 0.04 * cm)
        c.setFillColor(INK)
        c.setStrokeColor(BOX_BORDER)
        c.setFont("Helvetica-Bold", 9)
        c.drawString(ax + 0.45 * cm, y - 0.2 * cm, a)
        ax += 0.45 * cm + c.stringWidth(a, "Helvetica-Bold", 9) + 0.8 * cm

    draw_footer(page_no[0])
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
