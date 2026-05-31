# Complete German Steuererklärung Form Engine — Production Specification

**User direktif (2026-05-31):** "kaliteli yapalim hiçbir form atlanmasin, ELSTER-compatible, WISO/Taxfix/Steuerberater seviyesi"

**Status:** Mevcut MVP (75 field, 11 section) → bu spec'in **Phase 1.5'i**. Bu doc target Phase 3 production.

**Süre:** 8 hafta solo dev (form database + ELSTER ERiC integration en uzun). Yeni başlangıç gibi düşünme — mevcut `autotax/declaration.py` üzerine inşa edilir.

---

## TABLE OF CONTENTS

1. Step 1 — Location Detection + Finanzamt Lookup
2. Step 2 — Form Detection Engine (20+ Anlagen)
3. Step 3 — Dynamic Questionnaire (Conditional Flow)
4. Step 4 — Form Database Schema (multi-year)
5. Step 5 — Document AI Prefill (8 doc types)
6. Step 6 — Validation Engine
7. Step 7 — Tax Optimization Engine
8. Step 8 — AI Quality Control + Completeness Score
9. Step 9 — Output Generators (ELSTER + PDF + Audit)
10. Step 10 — Self-Learning Memory System
11. Complete Database Schema (32 tables)
12. Complete API Endpoint List (60+)
13. Module File Tree
14. Workflows (8 user journeys)
15. Missing Features Audit (vs current code)
16. 8-Week Implementation Roadmap

---

## STEP 1 — LOCATION DETECTION + FINANZAMT LOOKUP

### 1.1 Address → Bundesland → Finanzamt Pipeline

**Input:** PLZ + Ort (user-entered)
**Output:** Bundesland, responsible Finanzamt with full address, BUFA-Nummer (4-digit code), DStV-Datenstelle ID

### 1.2 Finanzamt Database

```sql
CREATE TABLE finanzamt_directory (
  id            BIGSERIAL PRIMARY KEY,
  bufa_nummer   CHAR(4) UNIQUE,         -- 4-digit Bundesfinanzamt-Nr (federal)
  bufa_landes   CHAR(2),                -- 2-digit Land prefix
  bundesland    TEXT NOT NULL,          -- "Saarland", "Bayern", ...
  bundesland_code CHAR(2),              -- "SL", "BY", ...
  name          TEXT NOT NULL,          -- "Finanzamt Saarbrücken"
  street        TEXT,
  plz           CHAR(5),
  ort           TEXT,
  phone         TEXT,
  fax           TEXT,
  email         TEXT,
  website       TEXT,
  elster_endpoint TEXT,                  -- Per-Land ELSTER URL (if any)
  serves_plz_ranges TEXT[],              -- ["66001-66132","66135"] etc
  serves_quarters TEXT[],                -- e.g. "Saarbrücken Mitte,Burbach"
  steuernummer_format TEXT,              -- Regex per Land (each Land has own format)
  is_active     BOOLEAN DEFAULT TRUE,
  source        TEXT,                    -- "BMF_2024Q1_official"
  last_verified DATE
);
CREATE INDEX ix_finanzamt_bufa ON finanzamt_directory(bufa_nummer);
CREATE INDEX ix_finanzamt_plz_gin ON finanzamt_directory USING GIN (serves_plz_ranges);

CREATE TABLE plz_to_finanzamt (
  plz           CHAR(5) PRIMARY KEY,
  primary_finanzamt_id BIGINT REFERENCES finanzamt_directory(id),
  fallback_finanzamt_id BIGINT REFERENCES finanzamt_directory(id) NULL
);
```

**Data source:** BMF (Bundesministerium der Finanzen) publishes Excel monthly. Import script:
- Download from `https://www.bzst.de/SharedDocs/Downloads/DE/`
- Parse XLSX → upsert finanzamt_directory + plz_to_finanzamt
- Run quarterly via cron

**~14.000 PLZ → ~615 Finanzämter** (Stand 2025).

### 1.3 Steuernummer Format Per Land

Each Bundesland has different Steuernummer format. Validation needed:

```python
STEUERNUMMER_FORMATS = {
    "BW": r"^\d{2}/\d{3}/\d{5}$",        # 99/999/99999
    "BY": r"^\d{3}/\d{3}/\d{5}$",        # 999/999/99999
    "BE": r"^\d{2}/\d{3}/\d{5}$",
    "BB": r"^\d{3}/\d{3}/\d{5}$",
    "HB": r"^\d{2}\s\d{3}\s\d{5}$",
    "HH": r"^\d{2}/\d{3}/\d{5}$",
    "HE": r"^\d{3}/\d{3}/\d{5}$",        # Hessen: 999 lead
    "MV": r"^\d{3}/\d{3}/\d{5}$",
    "NI": r"^\d{2}/\d{3}/\d{5}$",
    "NW": r"^\d{3}/\d{4}/\d{4}$",        # NRW: special — 999/9999/9999
    "RP": r"^\d{2}/\d{3}/\d{5}$",
    "SL": r"^\d{3}/\d{3}/\d{5}$",        # Saarland
    "SN": r"^\d{3}/\d{3}/\d{5}$",
    "ST": r"^\d{3}/\d{3}/\d{5}$",
    "SH": r"^\d{2}/\d{3}/\d{5}$",
    "TH": r"^\d{3}/\d{3}/\d{5}$",
}
```

ELSTER format dönüşümü (13-digit federal): `[BUFA-Landes 2][BUFA-FA 4][Personenzeichen 6][Prüfziffer 1]`.

### 1.4 Endpoints

```
GET  /tax/finanzamt/lookup?plz=66117  → Finanzamt details + ELSTER endpoint
GET  /tax/finanzamt/by-bundesland/SL  → list all in Saarland
POST /tax/finanzamt/validate-steuernummer  → check format per Land
GET  /tax/finanzamt/all                → admin only, full directory
POST /admin/tax/finanzamt/import-bmf   → admin only, re-import official Excel
```

### 1.5 UI Integration

- Mantelbogen `plz` field → on blur → fetch `/tax/finanzamt/lookup` → display "Zuständig: Finanzamt Saarbrücken (BUFA 1095)" badge
- Steuernummer field → live validation per detected Land
- If PLZ ambiguous (border) → show dropdown of 2 candidates

---

## STEP 2 — FORM DETECTION ENGINE (20+ Anlagen)

### 2.1 All Supported Forms (2024/2025/2026)

| Code | Long Name | Used By | Auto-Trigger Conditions |
|---|---|---|---|
| **ESt 1 A** | Hauptvordruck (Mantelbogen) | Everyone | ALWAYS |
| **Anlage N** | Einkünfte aus nichtselbständiger Arbeit | Employees | `has_employment=true` OR LSB uploaded |
| **Anlage N-AUS** | Auslandstätigkeit | Workers abroad | `has_foreign_employment=true` |
| **Anlage N-Doppelte Haushaltsführung** | Double household | Weekly commuter | `has_double_household=true` |
| **Anlage S** | Selbständige Arbeit | Freelancers | `has_self_employment=true` OR EÜR exists |
| **Anlage EÜR** | Einnahmen-Überschuss-Rechnung | Selbständige | `has_self_employment=true` AND `gewinn > 0` AND no Bilanz |
| **Anlage G** | Gewerbebetrieb | Trade business | `has_gewerbe=true` (different from §18 EStG selbst.) |
| **Anlage L** | Land- und Forstwirtschaft | Farmers | `has_land_forst=true` (rare) |
| **Anlage V** | Einkünfte aus Vermietung | Landlords | `has_rental=true` OR rental data exists |
| **Anlage V-FeWo** | Ferienwohnung | Vacation rental | `has_holiday_rental=true` |
| **Anlage KAP** | Kapitalerträge | Bank interest, dividends | `bank_interest > sparer_pb` OR `has_foreign_kap=true` |
| **Anlage KAP-BET** | Beteiligungen | GmbH partners | `has_partnership=true` |
| **Anlage KAP-INV** | Investment funds | ETF/fund holders | `has_investment_funds=true` |
| **Anlage R** | Renten und sonstige Leistungen | Pensioners | `has_pension=true` OR rente_jahresbetrag > 0 |
| **Anlage R-AUS** | Auslandsrenten | Foreign pension | `has_foreign_pension=true` |
| **Anlage SO** | Sonstige Einkünfte | Misc. income (Unterhaltsempfänger, Veräußerungen) | `has_unterhalt_received=true` OR `has_private_veraeusserung=true` |
| **Anlage AV** | Altersvorsorge (Riester) | Riester saver | `has_riester=true` |
| **Anlage AUS** | Ausländische Einkünfte | Foreign income | `has_foreign_income=true` |
| **Anlage WA-ESt** | Wegzug aus Deutschland | Emigrant | `has_emigration=true` (rare) |
| **Anlage U** | Unterhaltsleistungen (geleistet) | Ex-spouse pays | `has_paid_unterhalt=true` |
| **Anlage Unterhalt** | Unterhalt an bedürftige Personen | Pays family abroad | `has_unterhalt_to_bedurftig=true` |
| **Anlage Kind** | Pro Kind (KIN, Förderung, Pauschbetrag) | Parents | `kinder_count > 0` |
| **Anlage Kind-AUS** | Auslandskind | Foreign child | `has_foreign_child=true` |
| **Anlage Sonderausgaben** | (in 2024 own Anlage SO/Spenden) | Donations etc. | `has_donations=true` OR `kirchensteuer_paid > 0` |
| **Anlage Vorsorgeaufwand** | Versicherungsbeiträge | All with insurance | `has_insurance_payment=true` (almost always) |
| **Anlage Außergewöhnliche Belastungen** | Krankheit, Pflege, Behinderung | When applicable | `medical > 0` OR `behinderung_gdb > 0` OR `pflege > 0` |
| **Anlage Haushaltsnahe Aufwendungen** | §35a (Handwerker, Haushaltshilfe) | Most homeowners/renters | `handwerker > 0` OR `haushaltsdienst > 0` |
| **Anlage Energetische Maßnahmen** | §35c (Heizung, Dämmung, Fenster) | Eco renovation 2020-2029 | `has_energetic_measure=true` |
| **Anlage Corona-Hilfen** | Corona Soforthilfen | Self-employed 2020-2022 only | year ∈ {2020,2021,2022} AND `received_corona_aid=true` |
| **Umsatzsteuererklärung (USt 1 A)** | Annual VAT return | Self-employed not Kleinunternehmer | `has_self_employment=true` AND `is_kleinunternehmer=false` |
| **Anlage UR** | Umsatzsteuer Anlage | With USt-Erklärung | always with USt 1 A |
| **Gewerbesteuererklärung (GewSt 1 A)** | Gewerbesteuer | Trade business | `has_gewerbe=true` AND `gewerbe_gewinn > 24500` |
| **Anlage EÜR-Vereinfacht** | Simplified EÜR | <€22.000 income | `selbst_revenue < 22000` |

**Total: 32 forms** + sub-forms.

### 2.2 Form Detection Algorithm

```python
@dataclass
class FormRequirement:
    form_code: str
    required: bool             # True = must, False = optional
    reason: str                # "you have employment income"
    severity: str              # "block" if missing, "warn", "info"
    dependencies: list[str]    # ["mantelbogen", "anlage_n_main"]

def detect_required_forms(profile: dict, prior_year_data: dict | None = None) -> list[FormRequirement]:
    requirements = [
        FormRequirement("est_1a", True, "ESt 1 A (Mantelbogen) ist immer erforderlich", "block", []),
    ]

    # Anlage N
    if profile.get("has_employment") or profile.get("lsb_uploaded"):
        requirements.append(FormRequirement(
            "anlage_n", True,
            "Du hast Einkünfte aus nichtselbständiger Arbeit",
            "block", ["est_1a"]))
        if profile.get("commute_distance_km") and profile.get("commute_distance_km") > 60:
            requirements.append(FormRequirement(
                "anlage_n_doppelte_haushaltsfuehrung", False,
                "Lange Pendelstrecke: möglicherweise doppelte Haushaltsführung",
                "info", ["anlage_n"]))

    # Anlage S — Selbständig
    if profile.get("has_self_employment") or profile.get("has_freelancer"):
        requirements.append(FormRequirement(
            "anlage_s", True,
            "Du bist selbständig tätig (§ 18 EStG)",
            "block", ["est_1a"]))
        # EÜR auto-attached
        if profile.get("selbst_revenue_net") and not profile.get("has_bilanz"):
            requirements.append(FormRequirement(
                "anlage_eur", True,
                "Gewinnermittlung per Einnahmen-Überschuss-Rechnung",
                "block", ["anlage_s"]))

    # Anlage G — Gewerbe (NOT same as Anlage S!)
    if profile.get("has_gewerbe"):
        requirements.append(FormRequirement(
            "anlage_g", True,
            "Du hast einen Gewerbebetrieb",
            "block", ["est_1a"]))
        if profile.get("gewerbe_gewinn") and profile.get("gewerbe_gewinn") > 24500:
            requirements.append(FormRequirement(
                "gewst_1a", True,
                "Gewerbesteuerpflicht ab €24.500 Gewinn",
                "block", ["anlage_g"]))

    # Anlage V — Vermietung
    if profile.get("has_rental") or profile.get("rental_properties_count", 0) > 0:
        requirements.append(FormRequirement(
            "anlage_v", True,
            "Du erzielst Mieteinkünfte",
            "block", ["est_1a"]))
        # Ferienwohnung separat
        if profile.get("has_holiday_rental"):
            requirements.append(FormRequirement(
                "anlage_v_fewo", True,
                "Ferienwohnung wird separat erklärt",
                "block", ["anlage_v"]))

    # Anlage KAP
    sparer_pb = 2000 if profile.get("is_zusammen") else 1000
    if (profile.get("bank_interest_year", 0) > sparer_pb
        or profile.get("has_foreign_kap")
        or profile.get("has_partnership")
        or profile.get("has_investment_funds")):
        requirements.append(FormRequirement(
            "anlage_kap", True,
            f"Kapitalerträge über Sparer-Pauschbetrag von €{sparer_pb}",
            "block", ["est_1a"]))
        if profile.get("has_partnership"):
            requirements.append(FormRequirement(
                "anlage_kap_bet", True,
                "Beteiligungseinkünfte (KAP-BET)",
                "block", ["anlage_kap"]))
        if profile.get("has_investment_funds"):
            requirements.append(FormRequirement(
                "anlage_kap_inv", True,
                "Investmentfonds (KAP-INV)",
                "block", ["anlage_kap"]))

    # Anlage R — Rente
    if profile.get("has_pension") or profile.get("rente_jahresbetrag", 0) > 0:
        requirements.append(FormRequirement(
            "anlage_r", True,
            "Du erzielst Renteneinkünfte",
            "block", ["est_1a"]))
        if profile.get("has_foreign_pension"):
            requirements.append(FormRequirement(
                "anlage_r_aus", True,
                "Auslandsrente — Anlage R-AUS",
                "block", ["anlage_r"]))

    # Anlage Kind
    if profile.get("kinder_count", 0) > 0:
        requirements.append(FormRequirement(
            "anlage_kind", True,
            f"{profile['kinder_count']} Kind(er) — Anlage Kind erforderlich",
            "block", ["est_1a"]))

    # Anlage SO — Sonstige Einkünfte
    if (profile.get("has_unterhalt_received")
        or profile.get("has_private_veraeusserung")
        or profile.get("has_speculation_gain")):
        requirements.append(FormRequirement(
            "anlage_so", True,
            "Sonstige Einkünfte (Unterhalt, Veräußerung)",
            "block", ["est_1a"]))

    # Anlage AUS — Auslandseinkünfte
    if profile.get("has_foreign_income"):
        requirements.append(FormRequirement(
            "anlage_aus", True,
            "Du hast ausländische Einkünfte",
            "block", ["est_1a"]))

    # Anlage AV — Riester
    if profile.get("has_riester"):
        requirements.append(FormRequirement(
            "anlage_av", True,
            "Riester-Vertrag (Altersvorsorgezulage)",
            "block", ["est_1a"]))

    # Anlage Vorsorgeaufwand — almost always
    if (profile.get("kv_basis", 0) > 0 or profile.get("rente_gesetz", 0) > 0
        or profile.get("rurup", 0) > 0):
        requirements.append(FormRequirement(
            "anlage_vorsorge", True,
            "Versicherungsbeiträge — Anlage Vorsorgeaufwand",
            "block", ["est_1a"]))

    # Anlage Außergewöhnliche Belastungen
    if (profile.get("krankheitskosten", 0) > 0
        or profile.get("eigene_gdb", 0) > 0
        or profile.get("pflege_grad")
        or any(k.get("behinderung_gdb") for k in (profile.get("kinder") or []))):
        requirements.append(FormRequirement(
            "anlage_aussergewoehnliche", True,
            "Außergewöhnliche Belastungen (Krankheit/Behinderung/Pflege)",
            "block", ["est_1a"]))

    # Anlage Haushaltsnahe (§35a)
    if (profile.get("handwerker_lohn", 0) > 0
        or profile.get("haushaltsdienst", 0) > 0
        or profile.get("haushaltshilfe_mini", 0) > 0):
        requirements.append(FormRequirement(
            "anlage_haushaltsnahe", True,
            "§35a (Handwerker, Haushaltshilfe)",
            "block", ["est_1a"]))

    # Anlage Energetische Maßnahmen (§35c)
    if profile.get("has_energetic_measure"):
        requirements.append(FormRequirement(
            "anlage_energetisch", True,
            "Energetische Sanierung (§ 35c EStG, 2020-2029)",
            "block", ["est_1a"]))

    # Sonderausgaben (Spenden)
    if (profile.get("spenden_geld", 0) > 0
        or profile.get("spenden_partei", 0) > 0
        or profile.get("kirchensteuer_so", 0) > 0):
        requirements.append(FormRequirement(
            "anlage_sonderausgaben", True,
            "Sonderausgaben (Spenden, Kirchensteuer)",
            "block", ["est_1a"]))

    # Umsatzsteuer (NUR wenn nicht Kleinunternehmer)
    if (profile.get("has_self_employment")
        and not profile.get("is_kleinunternehmer")):
        requirements.append(FormRequirement(
            "ust_1a", True,
            "Jahres-Umsatzsteuererklärung (kein Kleinunternehmer)",
            "block", ["anlage_s"]))
        requirements.append(FormRequirement(
            "anlage_ur", True,
            "Anlage UR — Umsatzsteuer-Anlage",
            "block", ["ust_1a"]))

    return requirements
```

### 2.3 Endpoint

```
POST /tax/forms/detect      → body: profile dict → list of required forms with reasons
GET  /tax/forms/registry    → list all 32 supported forms (codes + names)
GET  /tax/forms/{code}/help → DE help text + tooltips per field
```

### 2.4 UI

Sidebar shows "📋 Erforderliche Formulare (7)":
- ✓ ESt 1 A
- ✓ Anlage N → "weil Lohnsteuerbescheinigung hochgeladen"
- ✓ Anlage Kind → "2 Kinder im Haushalt"
- ✓ Anlage Vorsorgeaufwand → "KV/Rente erfasst"
- ⚠ Anlage S empfohlen → "selbständige Einkünfte erkannt?" (toggle)
- ❌ Anlage V → "keine Mieteinnahmen erfasst"

Click on form → opens section. **Never show form code in user-facing UI.** Use friendly labels.

---

## STEP 3 — DYNAMIC QUESTIONNAIRE (Conditional Flow)

### 3.1 State Machine Design

```python
# autotax/tax_engine/questionnaire.py

QUESTIONNAIRE_FLOW = {
    "start": {
        "next": "personal_data",
    },
    "personal_data": {
        "questions": ["vorname", "nachname", "geburtsdatum", "steuer_id", "religion"],
        "next": "address",
    },
    "address": {
        "questions": ["strasse", "plz", "ort"],
        "side_effect": "lookup_finanzamt",
        "next": "marital_status",
    },
    "marital_status": {
        "questions": ["familienstand"],
        "branches": {
            "ledig": "children_check",
            "verheiratet": "spouse_data",
            "geschieden": "children_check",
            "verwitwet": "children_check",
        },
    },
    "spouse_data": {
        "questions": ["spouse_vorname", "spouse_nachname", "spouse_geburtsdatum",
                      "spouse_steuer_id", "spouse_religion", "veranlagungsart"],
        "next": "children_check",
    },
    "children_check": {
        "question": "has_children",  # yes/no
        "branches": {True: "children_list", False: "employment_check"},
    },
    "children_list": {
        "repeated": True,  # array of children
        "questions_per_item": ["vorname", "geburtsdatum", "steuer_id",
                               "kindergeld", "shared_custody",
                               "has_behinderung", "behinderung_gdb",
                               "behinderung_merkmal", "behindert_uebertrag"],
        "next": "employment_check",
    },
    "employment_check": {
        "question": "has_employment",
        "branches": {True: "employment_data", False: "self_employment_check"},
    },
    "employment_data": {
        "questions": ["lohn_brutto", "lohnsteuer", "soli_n", "kirchensteuer",
                      "steuerklasse", "werbungskosten_n"],
        "section_offer_doc_upload": "lohnsteuerbescheinigung",
        "next": "commute_check",
    },
    "commute_check": {
        "question": "has_commute",
        "branches": {True: "commute_data", False: "homeoffice_check"},
    },
    "commute_data": {
        "questions": ["pendler_km", "pendler_tage", "pendler_mittel"],
        "next": "homeoffice_check",
    },
    "homeoffice_check": {
        "question": "has_homeoffice",
        "branches": {True: "homeoffice_data", False: "self_employment_check"},
    },
    "homeoffice_data": {
        "questions": ["homeoffice_tage"],
        "next": "self_employment_check",
    },
    "self_employment_check": {
        "question": "has_self_employment",
        "branches": {True: "selbst_data", False: "rental_check"},
    },
    "selbst_data": {
        "questions": ["taetigkeit", "gewinn_eur"],
        "section_offer_doc_upload": "eur_summary",
        "side_effect": "load_eur_from_invoices",
        "next": "rental_check",
    },
    "rental_check": {
        "question": "has_rental",
        "branches": {True: "rental_list", False: "kapital_check"},
    },
    "rental_list": {
        "repeated": True,
        "questions_per_item": ["v_adresse", "v_einnahmen", "v_nebenkosten",
                               "v_afa", "v_zinsen", "v_erhaltung",
                               "v_grundsteuer", "v_sonst"],
        "next": "kapital_check",
    },
    "kapital_check": {
        "question": "has_kapital_above_sparer",
        "branches": {True: "kapital_data", False: "pension_check"},
    },
    "kapital_data": {
        "questions": ["kap_zinsen", "kap_kursgewinn", "kap_quellensteuer",
                      "kap_quellensteuer_ausland", "freistellungsauftrag"],
        "next": "pension_check",
    },
    "pension_check": {
        "question": "has_pension",
        "branches": {True: "pension_data", False: "insurance"},
    },
    "pension_data": {
        "questions": ["rente_jahresbetrag", "rente_beginn"],
        "section_offer_doc_upload": "rentenbescheid",
        "next": "insurance",
    },
    "insurance": {
        "questions": ["kv_basis", "kv_zusatz", "pflege", "rente_gesetz",
                      "rurup", "bu"],
        "section_offer_doc_upload": "versicherungsnachweis",
        "next": "behinderung_check",
    },
    "behinderung_check": {
        "question": "has_behinderung_self",
        "branches": {True: "behinderung_data", False: "aussergewohnlich_check"},
    },
    "behinderung_data": {
        "questions": ["eigene_gdb", "eigene_merkmal", "pflege_grad"],
        "next": "aussergewohnlich_check",
    },
    "aussergewohnlich_check": {
        "question": "has_medical_costs",
        "branches": {True: "aussergewohnlich_data", False: "sonder_check"},
    },
    "aussergewohnlich_data": {
        "questions": ["krankheitskosten", "pflegekosten", "bestattungskosten"],
        "next": "sonder_check",
    },
    "sonder_check": {
        "question": "has_sonderausgaben",
        "branches": {True: "sonder_data", False: "haushaltsnahe_check"},
    },
    "sonder_data": {
        "questions": ["spenden_geld", "spenden_partei", "steuerberater",
                      "kirchensteuer_so"],
        "section_offer_doc_upload": "spendenbescheinigung",
        "next": "haushaltsnahe_check",
    },
    "haushaltsnahe_check": {
        "question": "has_handwerker_or_haushalt",
        "branches": {True: "haushaltsnahe_data", False: "energetisch_check"},
    },
    "haushaltsnahe_data": {
        "questions": ["handwerker_lohn", "haushaltsdienst", "haushaltshilfe_mini"],
        "next": "energetisch_check",
    },
    "energetisch_check": {
        "question": "has_energetic_measure",
        "branches": {True: "energetisch_data", False: "review"},
    },
    "energetisch_data": {
        "questions": ["energetic_cost", "energetic_year_start"],
        "next": "review",
    },
    "review": {
        "computes": ["estimate_full_tax", "completeness_score",
                     "tax_optimization_suggestions"],
        "next": "finalize",
    },
    "finalize": {
        "actions": ["generate_pdf", "generate_xml", "generate_audit_report"],
        "terminal": True,
    },
}
```

### 3.2 State persistence

```sql
CREATE TABLE questionnaire_sessions (
  id            BIGSERIAL PRIMARY KEY,
  user_id       BIGINT REFERENCES users(id),
  tax_year      INT,
  current_step  TEXT,
  state_jsonb   JSONB,                 -- {field_key: value}
  completed_steps TEXT[],
  started_at    TIMESTAMPTZ DEFAULT now(),
  last_active   TIMESTAMPTZ DEFAULT now(),
  finished_at   TIMESTAMPTZ NULL,
  resume_token  TEXT,                  -- secure URL for "Continue later"
  UNIQUE (user_id, tax_year)
);
```

### 3.3 Endpoints

```
POST /tax/questionnaire/start                    → start or resume
GET  /tax/questionnaire/state                    → current question + UI hints
POST /tax/questionnaire/answer                   → submit answer, get next
POST /tax/questionnaire/skip                     → skip current section
POST /tax/questionnaire/back                     → go back one step
POST /tax/questionnaire/jump-to/{section_key}    → free navigation
GET  /tax/questionnaire/progress                 → % complete + which sections
POST /tax/questionnaire/upload-doc?type=...      → in-flow doc upload
```

---

## STEP 4 — FORM DATABASE SCHEMA (Multi-Year)

### 4.1 Per-form field registry

```sql
CREATE TABLE tax_form_versions (
  id            BIGSERIAL PRIMARY KEY,
  form_code     TEXT NOT NULL,          -- "anlage_n", "est_1a", etc.
  tax_year      INT NOT NULL,           -- 2024, 2025, 2026
  version       INT DEFAULT 1,          -- BMF kann mid-year update yapabilir
  schema_jsonb  JSONB NOT NULL,         -- full field schema
  validation_rules JSONB,
  help_texts    JSONB,
  tooltips      JSONB,
  zeile_mapping JSONB,                  -- {field_key: "Zeile N"}
  pdf_template_path TEXT,               -- ReportLab template ref
  effective_from DATE,
  effective_to   DATE NULL,
  source        TEXT,                    -- "BMF Stand 2024-11"
  imported_at   TIMESTAMPTZ DEFAULT now(),
  UNIQUE (form_code, tax_year, version)
);
CREATE INDEX ix_form_versions ON tax_form_versions(form_code, tax_year);
```

### 4.2 Schema format example

```json
{
  "form_code": "anlage_n",
  "tax_year": 2025,
  "title_de": "Anlage N — Einkünfte aus nichtselbständiger Arbeit",
  "sections": [
    {
      "key": "section_a_dienstverhältnisse",
      "title_de": "A. Angaben zu Dienstverhältnissen",
      "fields": [
        {
          "key": "arbeitgeber_name",
          "label_de": "Arbeitgeber (Name)",
          "type": "text",
          "required": true,
          "zeile": "Zeile 4",
          "validation": {"max_length": 100},
          "help": "Vollständiger Name laut Lohnsteuerbescheinigung",
          "tooltip": "Wenn mehrere Arbeitgeber, ein eigenes Anlage N pro AG"
        },
        {
          "key": "brutto_arbeitslohn",
          "label_de": "Bruttoarbeitslohn",
          "type": "currency",
          "required": true,
          "zeile": "Zeile 6",
          "validation": {"min": 0, "max": 9999999.99},
          "auto_fill_from": "lsb_zeile_3",
          "help": "Aus Lohnsteuerbescheinigung Zeile 3",
          "tooltip": "Bruttoarbeitslohn ohne Sonderzahlungen"
        }
        // ... 50+ more fields
      ]
    },
    {
      "key": "section_b_werbungskosten",
      "title_de": "B. Werbungskosten",
      "fields": [/* commute, homeoffice, work_equipment, fortbildung, etc. */]
    },
    {
      "key": "section_c_steuerermassigung",
      "title_de": "C. Steuerermäßigungen",
      "fields": [/* §35a, §35c, etc. */]
    }
  ]
}
```

### 4.3 Form versioning + auto-update

- BMF publishes form changes annually (Nov/Dec for next year)
- Admin script `import_bmf_form_updates.py` parses official PDFs/XML
- Creates new `tax_form_versions` row, increments version
- UI shows "Form für 2026 verfügbar" banner

### 4.4 Endpoints

```
GET  /tax/form-schema/{form_code}/{tax_year} → full schema JSON
POST /tax/form-schema/import?year=YYYY        → admin, import BMF
GET  /tax/form-schema/registry                → list all available
GET  /tax/form-schema/{form_code}/changelog   → version diff
```

---

## STEP 5 — DOCUMENT AI PREFILL (8 doc types)

### 5.1 Supported documents

| Doc Type | Used For | Fields Extracted | Model |
|---|---|---|---|
| **Lohnsteuerbescheinigung** | Anlage N prefill | 12 fields (Brutto, LSt, Soli, KSt, SV, AG-Adresse, Steuerklasse) | Sonnet |
| **Versicherungsnachweis (KV)** | Anlage Vorsorge | jahresbeitrag, basis/zusatz, pflege | Haiku |
| **Beitragsnachweis Rentenversicherung** | Anlage Vorsorge | AN-Anteil DRV, Rürup, BU | Haiku |
| **Rentenbescheid (DRV)** | Anlage R | rente_jahresbetrag, beginn, anpassung | Sonnet |
| **Spendenbescheinigung** | Anlage Sonderausgaben | empfänger, betrag, datum, partei (heuristic) | Haiku |
| **Bankenbescheinigung** | Anlage KAP | zinsen, dividenden, KESt, ausl. Steuer, freistellung | Sonnet |
| **Nebenkostenabrechnung** | Anlage V | nebenkosten erhalten, einzelposten | Sonnet |
| **Handwerkerrechnung** | §35a Haushaltsnahe | lohnanteil getrennt, MwSt | Sonnet |
| **Kontoauszug** | Mieteinnahmen, KAP | regelmäßige Mietzahlungen (Pattern) | Opus |
| **Steuerbescheid Vorjahr** | Vorjahres-Verlustvortrag | Bescheid-Nr, verlust, identifikation | Sonnet |
| **Kindergeld-Bescheid** | Anlage Kind | Kind-Name, Geb, Bewilligungszeitraum | Haiku |
| **Schwerbehindertenausweis** | Behinderung | GdB, Merkmal, Gültigkeitsdauer | Haiku |
| **AG-Bestätigung Dienstreise** | Werbungskosten N | Reisetage, Fahrtkilometer | Haiku |

### 5.2 Pipeline (extension of `tax_doc_ocr.py`)

```python
class TaxDocumentPipeline:
    async def process(self, file_bytes, mime_type, user_id, hint_type=None):
        # Stage 1: Classify doc type (Haiku, fast)
        doc_type = hint_type or await self.classify_doc(file_bytes, mime_type)

        # Stage 2: Pick extraction model
        model = MODEL_PER_DOC_TYPE.get(doc_type, "claude-haiku-4-5")

        # Stage 3: Extract via vision
        extracted = await call_claude_vision(
            file_bytes, mime_type,
            prompt=PROMPTS[doc_type],
            model=model,
        )

        # Stage 4: Validate (per-type checksum, field plausibility)
        warnings = VALIDATORS[doc_type](extracted)

        # Stage 5: Map to TaxDeclaration field_keys
        suggested_fields = MAPPERS[doc_type](extracted)

        # Stage 6: Confidence + suggested action
        confidence = extracted.get("confidence", 0)
        action = "auto_apply" if confidence >= 0.90 else "confirm" if confidence >= 0.70 else "manual"

        # Stage 7: Persist to ai_extractions for audit + learning
        save_extraction(user_id, doc_type, extracted, confidence, model)

        return {
            "doc_type": doc_type,
            "confidence": confidence,
            "action": action,
            "suggested_fields": suggested_fields,
            "warnings": warnings,
            "raw_extraction": extracted,
        }
```

### 5.3 Endpoints

```
POST /tax/document/upload        → multipart upload + classify + extract
POST /tax/document/{id}/apply    → apply suggested_fields to declaration
GET  /tax/document/history       → user's upload history
DELETE /tax/document/{id}        → delete + un-apply (rollback)
GET  /tax/document/{id}/preview  → re-render PDF/image
```

### 5.4 Document storage

```sql
CREATE TABLE tax_documents (
  id            BIGSERIAL PRIMARY KEY,
  user_id       BIGINT REFERENCES users(id),
  tax_year      INT NOT NULL,
  doc_type      TEXT,                  -- classified type
  doc_type_confidence NUMERIC(5,4),
  file_path     TEXT,                  -- R2 storage key
  file_sha256   CHAR(64) UNIQUE,
  file_name     TEXT,
  file_size     BIGINT,
  mime_type     TEXT,
  uploaded_at   TIMESTAMPTZ DEFAULT now(),
  applied_to_declaration BOOLEAN DEFAULT FALSE,
  applied_at    TIMESTAMPTZ NULL,
  pages         INT,
  ocr_text      TEXT
);

CREATE TABLE ai_extractions (
  id            BIGSERIAL PRIMARY KEY,
  document_id   BIGINT REFERENCES tax_documents(id) ON DELETE CASCADE,
  doc_type      TEXT,
  confidence    NUMERIC(5,4),
  fields_jsonb  JSONB,
  model         TEXT,
  input_tokens  INT,
  output_tokens INT,
  cost_usd      NUMERIC(8,5),
  status        TEXT,                  -- pending|applied|rejected|outdated
  user_confirmed_at TIMESTAMPTZ NULL,
  created_at    TIMESTAMPTZ DEFAULT now()
);
```

---

## STEP 6 — VALIDATION ENGINE

### 6.1 Validation categories

```python
class Validation:
    severity: str          # "info", "warn", "block", "tax_loss"
    field_path: str        # "lohn_brutto" or "kinder[0].steuer_id"
    rule_key: str          # "missing_required", "vat_mismatch", "format_iban"
    message_de: str
    message_tr: str
    suggested_action: str  # e.g. "Upload Lohnsteuerbescheinigung"
    estimated_tax_loss_eur: float  # for "tax_loss" severity
```

### 6.2 Rule catalog (60+ rules)

```python
VALIDATION_RULES = [
    # ─── Required field rules ───
    ("missing_steuer_id", "block",
     lambda d: not d.get("steuer_id"),
     "Steuer-ID fehlt — Pflichtangabe.",
     None),
    ("missing_kind_steuer_id", "tax_loss",
     lambda d: any(not k.get("steuer_id") for k in (d.get("kinder") or [])),
     "Ohne Steuer-ID des Kindes geht der Kinderfreibetrag verloren!",
     "Steuer-ID beim Bundeszentralamt nachfragen",
     # estimated loss = 6612€ per child Kinderfreibetrag impact on tax
     ),

    # ─── Format rules ───
    ("iban_invalid", "warn",
     lambda d: d.get("iban") and not validate_iban(d["iban"]),
     "IBAN ist ungültig (Prüfziffer falsch)", None),
    ("steuer_id_invalid", "warn",
     lambda d: d.get("steuer_id") and not validate_steuer_id(d["steuer_id"]),
     "Steuer-ID Prüfziffer falsch", None),

    # ─── Math consistency rules ───
    ("anlage_n_total_mismatch", "warn",
     lambda d: d.get("lohn_brutto") and d.get("lohnsteuer")
               and d["lohnsteuer"] > d["lohn_brutto"] * 0.5,
     "Lohnsteuer > 50% des Bruttolohns — bitte prüfen", None),

    # ─── Tax optimization (missed opportunity) ───
    ("pendlerpauschale_unused", "tax_loss",
     lambda d: d.get("has_employment") and not d.get("pendler_km"),
     "Pendlerpauschale nicht angegeben — bis zu €2.400 Werbungskosten möglich!",
     "Entfernung Wohnung-Arbeitsstätte eintragen"),

    ("homeoffice_unused", "tax_loss",
     lambda d: d.get("has_employment") and not d.get("homeoffice_tage"),
     "Homeoffice-Pauschale ungenutzt — €6/Tag bis €1.260 möglich!",
     "Homeoffice-Tage eintragen"),

    ("krankheitskosten_unused", "tax_loss",
     lambda d: gesamteinkommen(d) > 30000
               and not d.get("krankheitskosten"),
     "Krankheitskosten könnten absetzbar sein bei höheren Einkünften",
     "Eigenbeteiligungen, Praxisgebühren, Brille sammeln"),

    # ─── Contradiction rules ───
    ("verheiratet_no_spouse", "warn",
     lambda d: d.get("familienstand") == "verheiratet"
               and not d.get("spouse_vorname"),
     "Familienstand 'verheiratet' aber keine Ehepartner-Daten",
     "Ehepartner-Sektion ausfüllen"),

    ("kein_lsb_aber_lohn", "warn",
     lambda d: d.get("lohn_brutto") and not d.get("lsb_uploaded"),
     "Lohnsteuerbescheinigung sollte hochgeladen werden",
     "Doc hochladen"),

    # ─── Compliance / legal ───
    ("religion_kirchenst_mismatch", "warn",
     lambda d: d.get("religion") in ("ev", "rk")
               and not d.get("kirchensteuer")
               and d.get("lohn_brutto", 0) > 20000,
     "Religion angegeben aber keine Kirchensteuer — prüfen",
     None),

    ("vorjahres_verlustvortrag_check", "info",
     lambda d: prior_year_loss(d) > 0,
     f"Verlustvortrag aus Vorjahr: €{prior_year_loss(d)}",
     "Wird automatisch übernommen"),

    # ─── 60+ more rules ...
]


def validate_all(profile: dict, tax_year: int) -> list[Validation]:
    results = []
    for key, severity, predicate, msg_de, action in VALIDATION_RULES:
        try:
            if predicate(profile):
                results.append(Validation(
                    rule_key=key, severity=severity,
                    field_path=None, message_de=msg_de,
                    message_tr=translate(msg_de, "tr"),
                    suggested_action=action,
                    estimated_tax_loss_eur=compute_loss(key, profile),
                ))
        except Exception:
            logger.exception("Validation rule %s failed", key)
    return results
```

### 6.3 Cross-form consistency check

```python
def cross_form_validate(forms_data: dict) -> list[Validation]:
    """Detect contradictions across multiple forms."""
    results = []
    # Example: Anlage S Gewinn must match Anlage EÜR Gewinn
    if "anlage_s" in forms_data and "anlage_eur" in forms_data:
        if abs(forms_data["anlage_s"]["gewinn"] - forms_data["anlage_eur"]["gewinn"]) > 0.01:
            results.append(...)

    # Anlage N Brutto must match all Lohnsteuerbescheinigung sums
    if "anlage_n" in forms_data and "uploaded_lsbs" in forms_data:
        sum_lsb = sum(l["brutto"] for l in forms_data["uploaded_lsbs"])
        if abs(forms_data["anlage_n"]["brutto"] - sum_lsb) > 1.0:
            results.append(...)

    # Anlage Vorsorge KV must match Anlage N KV (if AG provided)
    # Anlage KAP Freistellungsauftrag <= €1000/€2000 per veranlagung
    # ...

    return results
```

### 6.4 Endpoint

```
POST /tax/validate                       → run all rules
POST /tax/validate/cross-form            → consistency check
GET  /tax/validate/rules                 → list all 60+ rules
GET  /tax/validate/{year}/issues         → current issues for a year
POST /tax/validate/dismiss?rule_key=...  → user dismisses warning
```

---

## STEP 7 — TAX OPTIMIZATION ENGINE

### 7.1 Optimization rules (10+ patterns)

```python
@dataclass
class Optimization:
    rule_key: str
    title_de: str
    explanation_de: str
    required_data: list[str]      # missing fields to check
    estimated_savings_eur: float
    confidence: float
    action: str                   # "add_field", "upload_doc", "consult_advisor"

OPTIMIZATIONS = [
    # ─── Werbungskosten (Anlage N) ───
    Optimization(
        rule_key="commute_distance",
        title_de="Pendlerpauschale anwenden",
        explanation_de="Pro km einfacher Fahrt × Arbeitstage × €0,30/€0,38 = bis zu €2.400 Werbungskosten",
        required_data=["pendler_km", "pendler_tage"],
        estimated_savings_eur=lambda d: compute_pendler_tax_savings(d),
        confidence=0.95,
        action="add_field",
    ),
    Optimization(
        rule_key="homeoffice_pauschale",
        title_de="Homeoffice-Pauschale",
        explanation_de="€6 pro Homeoffice-Tag, max €1.260 = bis zu €420 Steuerersparnis (bei 25% Grenzsteuer)",
        required_data=["homeoffice_tage"],
        estimated_savings_eur=lambda d: min(d.get("homeoffice_tage", 0) * 6, 1260) * 0.25,
        confidence=0.90,
        action="add_field",
    ),
    Optimization(
        rule_key="work_equipment",
        title_de="Arbeitsmittel absetzen",
        explanation_de="Laptop, Schreibtisch, Bücher beruflich genutzt → Werbungskosten",
        required_data=["work_equipment_costs"],
        estimated_savings_eur=lambda d: invoice_sum_by_category(d, "office_equipment") * 0.25,
        confidence=0.85,
        action="upload_doc",
    ),

    # ─── Children (Anlage Kind) ───
    Optimization(
        rule_key="kinderbetreuungskosten",
        title_de="Kinderbetreuungskosten absetzen",
        explanation_de="2/3 der Kosten bis €4.000 pro Kind absetzbar (KiTa, Babysitter, Schulgeld)",
        required_data=["kinderbetreuung_kosten"],
        estimated_savings_eur=lambda d: min(d.get("kinderbetreuung_kosten", 0) * 2/3, 4000) * 0.30,
        confidence=0.90,
        action="add_field",
    ),
    Optimization(
        rule_key="kinder_freibetrag_check",
        title_de="Kinderfreibetrag-Günstigerprüfung",
        explanation_de="Bei Einkommen >€60k oft günstiger als Kindergeld",
        required_data=[],
        estimated_savings_eur=lambda d: kinder_freibetrag_savings(d),
        confidence=0.95,
        action="auto",
    ),

    # ─── Pension (Anlage Vorsorgeaufwand) ───
    Optimization(
        rule_key="rurup_einzahlung",
        title_de="Rürup-Rente einzahlen",
        explanation_de="100% absetzbar (2025), bis zu €27.566/Jahr (Single)",
        required_data=["rurup"],
        estimated_savings_eur=lambda d: max_rurup_savings(d),
        confidence=0.85,
        action="advice",
    ),

    # ─── Sonderausgaben ───
    Optimization(
        rule_key="kirchensteuer_zusatz",
        title_de="Kirchensteuer nachträglich absetzen",
        explanation_de="KSt wird voll als Sonderausgabe abgesetzt — oft vergessen wenn nicht aus LSB",
        required_data=["kirchensteuer_so"],
        estimated_savings_eur=lambda d: d.get("kirchensteuer_lohnst", 0) * 0.30,
        confidence=0.95,
        action="add_field",
    ),

    # ─── §35a Haushaltsnahe ───
    Optimization(
        rule_key="handwerker_max_used",
        title_de="Handwerker-Lohnanteil maximieren",
        explanation_de="20% des Lohnanteils, max €1.200 = bis zu €240 direkte Steuerersparnis",
        required_data=["handwerker_lohn"],
        estimated_savings_eur=lambda d: min(d.get("handwerker_lohn", 0) * 0.20, 1200),
        confidence=0.98,
        action="add_field",
    ),

    # ─── Außergewöhnliche Belastungen ───
    Optimization(
        rule_key="behindertenpauschbetrag",
        title_de="Behindertenpauschbetrag prüfen",
        explanation_de="Bei GdB ab 20% Pauschbetrag €384-€2.840, bei H/Bl/TBl €7.400",
        required_data=["eigene_gdb", "eigene_merkmal"],
        estimated_savings_eur=lambda d: behindert_savings(d),
        confidence=0.95,
        action="add_field",
    ),
    Optimization(
        rule_key="behindertenpauschbetrag_kind",
        title_de="Übertragung Kinder-Behindertenpauschbetrag",
        explanation_de="Wenn das Kind den Pauschbetrag nicht nutzt → auf Eltern übertragen",
        required_data=["kinder.behindert_uebertrag"],
        estimated_savings_eur=lambda d: kind_behindert_savings(d),
        confidence=0.95,
        action="add_field",
    ),

    # ─── Anlage V — Vermietung ───
    Optimization(
        rule_key="erhaltungsaufwand_aufteilung",
        title_de="Erhaltungsaufwand >€4.000 auf 5 Jahre verteilen",
        explanation_de="Steueroptimal in progressiven Jahren — gleichmäßige Verteilung möglich",
        required_data=["v_erhaltung"],
        estimated_savings_eur=lambda d: erhaltung_optimization(d),
        confidence=0.70,
        action="advice",
    ),

    # ─── Selbständig ───
    Optimization(
        rule_key="bewirtung_30_70",
        title_de="Bewirtungskosten 70% absetzen",
        explanation_de="Kundengespräche im Restaurant → 70% Bewirtung, 100% Vorsteuer",
        required_data=[],
        estimated_savings_eur=lambda d: bewirtung_optimization(d),
        confidence=0.85,
        action="auto",
    ),
    # ... 50+ more
]
```

### 7.2 Algorithm — `find_optimizations(profile)`

```python
def find_optimizations(profile, tax_year) -> list[Optimization]:
    suggestions = []
    for opt in OPTIMIZATIONS:
        # Check if this optimization is "available" (missing data exists)
        missing = [f for f in opt.required_data if not profile.get(f)]
        if not missing:
            continue  # already filled, no opportunity
        savings = opt.estimated_savings_eur(profile) if callable(opt.estimated_savings_eur) else opt.estimated_savings_eur
        if savings < 5:
            continue  # not worth mentioning
        suggestions.append({
            **opt.__dict__,
            "missing_fields": missing,
            "savings_eur": round(savings, 2),
            "priority": savings * opt.confidence,  # sort by impact × confidence
        })
    suggestions.sort(key=lambda x: -x["priority"])
    return suggestions[:20]  # top 20
```

### 7.3 Endpoints

```
GET  /tax/optimize/{year}             → list of all opportunities
GET  /tax/optimize/{year}/summary     → total potential savings
POST /tax/optimize/dismiss?rule=...   → user dismisses suggestion
POST /tax/optimize/apply?rule=...     → jump to relevant section
```

---

## STEP 8 — AI QUALITY CONTROL + COMPLETENESS SCORE

### 8.1 Completeness algorithm

```python
def compute_completeness(profile, required_forms, validations) -> dict:
    """Score 0-100% based on filled fields per required form."""
    total_required_fields = 0
    filled_required_fields = 0
    block_issues = 0
    warn_issues = 0
    tax_loss_issues = 0

    for form in required_forms:
        schema = get_form_schema(form.form_code, profile["year"])
        for section in schema["sections"]:
            for field in section["fields"]:
                if field.get("required"):
                    total_required_fields += 1
                    if profile.get(field["key"]) not in (None, "", 0):
                        filled_required_fields += 1

    for v in validations:
        if v.severity == "block":   block_issues += 1
        elif v.severity == "warn":   warn_issues += 1
        elif v.severity == "tax_loss": tax_loss_issues += 1

    # Base score = filled %
    base = (filled_required_fields / total_required_fields * 100) if total_required_fields > 0 else 0
    # Penalties
    score = base - block_issues * 10 - warn_issues * 2 - tax_loss_issues * 1
    score = max(0, min(100, score))

    can_submit = (block_issues == 0 and warn_issues <= 2)

    return {
        "score": round(score, 1),
        "total_required": total_required_fields,
        "filled_required": filled_required_fields,
        "block_issues": block_issues,
        "warn_issues": warn_issues,
        "tax_loss_issues": tax_loss_issues,
        "can_submit": can_submit,
        "blocker_messages": [v.message_de for v in validations if v.severity == "block"],
        "estimated_tax_loss_eur": sum(v.estimated_tax_loss_eur or 0 for v in validations if v.severity == "tax_loss"),
    }
```

### 8.2 AI sanity check (LLM final review)

Before allowing finalize, run Claude Sonnet to:
- Cross-check field values for plausibility ("Brutto €500.000 bei Lehrer ungewöhnlich")
- Spot missing common fields ("kein Pendlerpauschale erfasst aber Anlage N voll")
- Generate summary text for review screen

```python
QUALITY_CHECK_PROMPT = """You are a senior German Steuerberater reviewing
a citizen's draft tax declaration. Review the following declaration and:
1. Flag any data points that seem unusual or implausible
2. Spot likely missing fields commonly relevant
3. Note tax-saving opportunities the user missed

Declaration:
{declaration_json}

Forms detected as required:
{forms_list}

Return JSON only:
{{
  "plausibility_warnings": ["..."],
  "missing_field_suggestions": ["..."],
  "optimization_hints": ["..."],
  "overall_assessment": "ready|needs_review|major_issues",
  "summary_de": "1-paragraph reviewer note in German"
}}"""
```

### 8.3 Endpoint

```
GET  /tax/{year}/completeness         → score + breakdown
POST /tax/{year}/quality-check        → AI sanity (Sonnet, $0.05)
POST /tax/{year}/finalize             → mark as ready (only if score>=80, can_submit=true)
```

---

## STEP 9 — OUTPUT GENERATORS

### 9.1 ELSTER ERiC Integration

**ELSTER ERiC** (Elektronische Rechtssichere Empfangs- und Datenübertragungs-Infrastruktur Komponente) is the official client library for submission.

**Two paths:**

**Path A — Native ERiC (C++ library)**
- Download ERiC SDK from BMF developer portal (free for ISVs after registration)
- Wrap with `cffi` Python bindings
- Provides certificate validation, encryption, signing, ELSTER server transmission
- **Investment:** 2-3 weeks integration + ELSTER ISV certification
- Production-grade — direct submission

**Path B — XML Export + manual upload**
- Generate ELSTER-compatible XML per schema
- User downloads XML
- User uploads at `elster.de` via their personal account
- Faster to ship, no certification needed

**Recommendation:** Phase 1 = Path B (already in mevcut). Phase 2+ = Path A.

### 9.2 ELSTER XML Schema

```xml
<?xml version="1.0" encoding="UTF-8"?>
<Elster xmlns="http://www.elster.de/elsterxml/schema/v11">
  <TransferHeader version="11">
    <Verfahren>ElsterAnmeldung</Verfahren>
    <DatenArt>ESt</DatenArt>
    <Vorgang>send-Auth</Vorgang>
    <Testmerker>700000004</Testmerker>  <!-- test mode -->
    <HerstellerID>{your_isv_id}</HerstellerID>
    <Datei>
      <Verschluesselung>CMSEncryptedData</Verschluesselung>
      <Kompression>GZIP</Kompression>
    </Datei>
  </TransferHeader>
  <DatenTeil>
    <Nutzdatenblock>
      <NutzdatenHeader version="11">
        <NutzdatenTicket>{uuid}</NutzdatenTicket>
        <Empfaenger id="F">{bufa_nummer}</Empfaenger>
      </NutzdatenHeader>
      <Nutzdaten>
        <ESt_1A jahr="2025">
          <Mantelbogen>
            <Steuernummer>{formatted_per_land}</Steuernummer>
            <Steuerpflichtiger>
              <SteuerID>{11_digit}</SteuerID>
              <Vorname>...</Vorname>
              <Nachname>...</Nachname>
              <Geburtsdatum>YYYY-MM-DD</Geburtsdatum>
              <!-- ... -->
            </Steuerpflichtiger>
            <!-- ... -->
          </Mantelbogen>
          <AnlageN nummer="1">...</AnlageN>
          <AnlageEUR>...</AnlageEUR>
          <!-- ... -->
        </ESt_1A>
      </Nutzdaten>
    </Nutzdatenblock>
  </DatenTeil>
</Elster>
```

### 9.3 PDF generator

- Per form: reportlab template fidelity to BMF official layout (Zeile numbers + spacing)
- Multi-page output (Mantelbogen + each Anlage)
- Watermark "ENTWURF" until finalized
- Comprehensive cover sheet listing all included forms

### 9.4 Human-readable summary

Generate German narrative:
> "Lieber Hüseyin Hancer,
>
> deine Steuererklärung 2025 ist abgeschlossen. Hier eine Zusammenfassung:
>
> **Erwartete Erstattung: 1.234,56 €**
>
> Du hast Einkommen aus folgenden Quellen erzielt:
> - Selbständige Tätigkeit (IT-Consulting): 50.000 € Gewinn
> - Vermietung (Saarbrücker Str. 5): 12.000 € Überschuss
>
> Steuermindernde Posten:
> - Werbungskosten: 1.230 €
> - Sonderausgaben: 5.000 €
> ...
>
> **Bitte folgende Anlagen einreichen:**
> ☐ Spendenbescheinigung Rotes Kreuz €100
> ☐ Handwerkerrechnung Schmidt €2.500
> ..."

### 9.5 Audit report (compliance trail)

```sql
CREATE TABLE submission_audit (
  id            BIGSERIAL PRIMARY KEY,
  user_id       BIGINT,
  tax_year      INT,
  action        TEXT,                  -- "field_changed", "doc_uploaded", "validation_ran"
  before_value  TEXT,
  after_value   TEXT,
  field_path    TEXT,
  source        TEXT,                  -- "user", "ai_extraction", "carry_forward"
  ip_address    INET,
  user_agent    TEXT,
  timestamp     TIMESTAMPTZ DEFAULT now()
);
```

Output PDF report listing every change made.

### 9.6 Endpoints

```
GET /tax/{year}/output/elster-xml      → XML file
GET /tax/{year}/output/pdf-full        → full multi-form PDF
GET /tax/{year}/output/pdf-summary     → executive summary 1-page
GET /tax/{year}/output/audit-report    → compliance audit PDF
GET /tax/{year}/output/datev-csv       → for Steuerberater
GET /tax/{year}/output/bundle.zip      → all of the above
POST /tax/{year}/submit-via-elster     → Phase 2 ERiC submission
```

---

## STEP 10 — SELF-LEARNING MEMORY SYSTEM

### 10.1 Permanent / Semi / Annual classification (extend existing)

```python
# Already in autotax/declaration.py - extend significantly
_PERMANENT_FIELDS = {
    # Identity
    "steuer_id", "vorname", "nachname", "geburtsdatum", "religion",
    # Disability (recognized status)
    "eigene_gdb", "eigene_merkmal",
    # Spouse identity
    "spouse_vorname", "spouse_nachname", "spouse_geburtsdatum",
    "spouse_steuer_id", "spouse_religion",
    # Kind identity (per row)
    "kinder.vorname", "kinder.geburtsdatum", "kinder.steuer_id",
    # Bank
    "iban", "kontoinhaber",
}

_SEMI_PERMANENT_FIELDS = {
    # Address — yearly confirm
    "strasse", "plz", "ort",
    # Employment (current job)
    "ag_name", "ag_address", "steuerklasse",
    # Marital
    "familienstand", "veranlagungsart",
    # Commute (until job change)
    "pendler_km", "pendler_mittel",
    # Rental properties (per property)
    "v_adresse",  # per property
    # Activity
    "taetigkeit",
    # Pension grade (reassessment)
    "pflege_grad",
}

# Everything else (lohn_brutto, gewinn_eur, kv_basis, spende_geld, ...) = ANNUAL.
```

### 10.2 Year-over-year carry-forward (extended)

```python
def carry_forward_full_profile(prev_year_profile: dict, target_year: int) -> dict:
    """Generate new year draft from previous, applying:
    - Permanent: copied as-is
    - Semi: copied + 'please verify' flag
    - Annual: empty + 'please collect' flag
    - Auto-update: brackets, Pauschbeträge, dates
    """
    new = {}
    for field, val in prev_year_profile.items():
        if field in _PERMANENT_FIELDS:
            new[field] = val
        elif field in _SEMI_PERMANENT_FIELDS:
            new[field] = val
            new.setdefault("_verify_required", []).append(field)
        # Annual fields not copied
    # Apply year-specific defaults
    new["werbungskosten_n"] = ARBEITNEHMER_PAUSCHBETRAG.get(target_year, 1230)
    new["sparer_pauschbetrag"] = 1000  # single, 2000 zusammen
    return new
```

### 10.3 Learning system tables

```sql
-- Track field-level user behavior to improve UX
CREATE TABLE user_field_history (
  id            BIGSERIAL PRIMARY KEY,
  user_id       BIGINT REFERENCES users(id),
  field_key     TEXT,
  value_text    TEXT,
  tax_year      INT,
  source        TEXT,                  -- "manual","ai_extracted","carry_forward"
  changed_at    TIMESTAMPTZ DEFAULT now()
);

-- Aggregate frequently used vendors for pre-population
CREATE TABLE user_frequent_payees (
  id            BIGSERIAL PRIMARY KEY,
  user_id       BIGINT REFERENCES users(id),
  category      TEXT,                  -- "krankenkasse","versicherung","spendenempfaenger"
  name          TEXT,
  vat_id        TEXT NULL,
  use_count     INT DEFAULT 1,
  last_used_at  TIMESTAMPTZ
);

-- Employer history (changing jobs)
CREATE TABLE user_employers (
  id            BIGSERIAL PRIMARY KEY,
  user_id       BIGINT REFERENCES users(id),
  ag_name       TEXT,
  ag_address    TEXT,
  ag_steuernummer TEXT,
  start_date    DATE,
  end_date      DATE NULL,
  is_current    BOOLEAN
);

-- Per-property rental history
CREATE TABLE user_rental_properties (
  id            BIGSERIAL PRIMARY KEY,
  user_id       BIGINT REFERENCES users(id),
  adresse       TEXT,
  acquired      DATE,
  sold          DATE NULL,
  monthly_kaltmiete NUMERIC(10,2)
);

-- Insurance providers (carry across years)
CREATE TABLE user_insurance_providers (
  id            BIGSERIAL PRIMARY KEY,
  user_id       BIGINT REFERENCES users(id),
  type          TEXT,                  -- "krankenkasse","rurup","bu","pflege"
  provider_name TEXT,
  contract_id   TEXT,
  yearly_premium_est NUMERIC(10,2)
);
```

### 10.4 Auto-prefill next year

```python
def auto_prefill_year(user_id: int, year: int) -> dict:
    """Year N+1 onboarding: combine all known data sources."""
    prev = get_declaration(user_id, year - 1)
    carried = carry_forward_full_profile(prev or {}, year)

    # Employer continuation
    cur_employer = get_current_employer(user_id)
    if cur_employer:
        carried["ag_name"] = cur_employer.ag_name
        carried["ag_address"] = cur_employer.ag_address

    # Rental properties continuation
    active_properties = get_active_rental_properties(user_id)
    carried["rental_properties_count"] = len(active_properties)

    # Pension provider continuation
    insurances = get_user_insurances(user_id)
    for ins in insurances:
        if ins.type == "krankenkasse":
            carried["kv_provider"] = ins.provider_name
            carried["kv_basis_estimated"] = ins.yearly_premium_est

    # Previous Verlustvortrag
    bescheid = get_latest_bescheid(user_id)
    if bescheid and bescheid.verlustvortrag:
        carried["vorjahres_verlustvortrag"] = bescheid.verlustvortrag

    return carried
```

### 10.5 Endpoint

```
POST /tax/{new_year}/onboarding/auto-prefill  → returns carried-forward profile
GET  /tax/user-history                         → my known data
PATCH /tax/user-history                        → user updates (e.g. new employer)
```

---

## STEP 11 — COMPLETE DATABASE SCHEMA (32 tables)

```sql
-- ─── User & Tenancy ───
users (existing)
tax_profiles                  -- Permanent identity
tax_profile_addresses         -- Semi, time-effective
tax_profile_bank              -- Semi, time-effective
tax_profile_marital           -- Semi, time-effective

-- ─── Year-level declaration ───
tax_years                     -- Per (user, year)
tax_declarations_jsonb        -- Backwards-compat data store (existing TaxDeclaration)

-- ─── Per-form data (relational denormal) ───
form_anlage_n                 -- Employment year
form_anlage_n_employers       -- Multiple AG per year
form_anlage_eur               -- EÜR
form_anlage_v_properties      -- Per property
form_anlage_v_property_year   -- Per (property, year)
form_anlage_kap               -- Capital
form_anlage_r                 -- Pension
form_anlage_kind              -- Per child entry
form_anlage_kind_year         -- Per (child, year)
form_anlage_sonder
form_anlage_haushaltsnahe
form_anlage_aussergewohnliche
form_anlage_behinderung
form_anlage_aus               -- Foreign
form_anlage_so                -- Sonstige
form_anlage_av                -- Riester
form_anlage_energetisch
form_ust_1a                   -- USt-Erklärung
form_gewst_1a                 -- GewSt-Erklärung

-- ─── Documents & AI ───
tax_documents                 -- Uploaded files
ai_extractions                -- Per extraction with cost/confidence

-- ─── Questionnaire state ───
questionnaire_sessions

-- ─── Form schema registry ───
tax_form_versions             -- Per (form_code, year) schema

-- ─── Validation + Optimization ───
validation_runs               -- Per run: rules executed + results
optimization_dismissed        -- User-dismissed suggestions

-- ─── Finanzamt directory ───
finanzamt_directory
plz_to_finanzamt

-- ─── Submission ───
elster_submissions            -- ERiC submission attempts
elster_submission_logs        -- Server responses
submission_audit              -- Per change audit
bescheids                     -- Received Bescheid PDFs

-- ─── Learning ───
user_field_history
user_frequent_payees
user_employers
user_rental_properties
user_insurance_providers
recommendations               -- Across users (anonymized patterns)
```

**Total: 32 tables.**

---

## STEP 12 — COMPLETE API ENDPOINT LIST (60+)

### 12.1 Profile & Setup
```
POST /tax/profile                            → create/update permanent profile
GET  /tax/profile                            → current
POST /tax/profile/spouse                     → spouse setup
POST /tax/profile/children                   → children list
GET  /tax/finanzamt/lookup?plz=...           → lookup
POST /tax/finanzamt/validate-steuernummer    → format check per Land
```

### 12.2 Questionnaire
```
POST /tax/questionnaire/start
GET  /tax/questionnaire/state
POST /tax/questionnaire/answer
POST /tax/questionnaire/skip
POST /tax/questionnaire/back
POST /tax/questionnaire/jump-to/{section}
GET  /tax/questionnaire/progress
POST /tax/questionnaire/upload-doc
```

### 12.3 Forms
```
POST /tax/forms/detect                       → list required forms
GET  /tax/forms/registry                     → all 32 forms
GET  /tax/forms/{code}/schema/{year}         → field schema
GET  /tax/forms/{code}/help                  → tooltips
GET  /tax/{year}/forms/required              → for current user
POST /tax/{year}/forms/{code}/enable
POST /tax/{year}/forms/{code}/disable
```

### 12.4 Declaration data
```
GET  /tax/{year}                             → current draft
PATCH /tax/{year}                            → update fields
POST /tax/{year}/copy-from/{prev_year}       → carry forward
DELETE /tax/{year}                           → start over
GET  /tax/{year}/timeline                    → field-change history
```

### 12.5 Document AI
```
POST /tax/document/upload                    → multipart + auto-classify
GET  /tax/document/{id}
DELETE /tax/document/{id}
POST /tax/document/{id}/apply                → push to declaration
GET  /tax/document/history?year=YYYY
POST /tax/document/{id}/re-extract           → retry with different model
```

### 12.6 Validation & Optimization
```
POST /tax/{year}/validate
POST /tax/{year}/validate/cross-form
GET  /tax/{year}/issues
POST /tax/{year}/issues/{rule_key}/dismiss
GET  /tax/{year}/optimize
GET  /tax/{year}/optimize/summary
POST /tax/{year}/optimize/{rule_key}/dismiss
POST /tax/{year}/optimize/{rule_key}/apply
```

### 12.7 Tax computation
```
GET  /tax/{year}/calc                        → live tax estimate
POST /tax/{year}/calc/what-if                → run scenario
GET  /tax/{year}/calc/breakdown              → detailed decomposition
GET  /tax/{year}/calc/comparison/{prev}      → year-vs-year
```

### 12.8 Quality + Finalize
```
GET  /tax/{year}/completeness                → score + gaps
POST /tax/{year}/quality-check               → AI reviewer (Sonnet)
POST /tax/{year}/finalize                    → lock + generate outputs
POST /tax/{year}/unfinalize                  → reopen (audit logged)
```

### 12.9 Outputs
```
GET  /tax/{year}/output/elster-xml
GET  /tax/{year}/output/pdf-full
GET  /tax/{year}/output/pdf-summary
GET  /tax/{year}/output/audit-report
GET  /tax/{year}/output/datev-csv
GET  /tax/{year}/output/bundle.zip
POST /tax/{year}/submit-via-elster           → Phase 2 ERiC
```

### 12.10 Bescheid (Tax Notice)
```
POST /tax/{year}/bescheid/upload             → user uploads received Bescheid PDF
GET  /tax/{year}/bescheid/extract            → AI extracts vs. declared
GET  /tax/{year}/bescheid/comparison
```

### 12.11 Self-Learning
```
GET  /tax/user-history
PATCH /tax/user-history
POST /tax/employers                          → add new employer
POST /tax/rental-properties                  → add property
POST /tax/insurance-providers                → add insurance
POST /tax/{new_year}/onboarding/auto-prefill
```

### 12.12 Admin
```
GET  /admin/tax/stats                         → AI cost per user, completion rate
POST /admin/tax/forms/import-bmf?year=YYYY    → import form updates
GET  /admin/tax/validation-rule-impact        → which rules trigger most
```

**Total: 60+ endpoints.**

---

## STEP 13 — MODULE FILE TREE

```
autotax/
├── tax_engine/
│   ├── __init__.py
│   ├── finanzamt.py            # Step 1: Lookup + Steuernummer validation
│   ├── form_detection.py       # Step 2: Required forms engine
│   ├── questionnaire.py        # Step 3: State machine
│   ├── form_schema.py          # Step 4: Multi-year schema registry
│   ├── doc_pipeline.py         # Step 5: Document AI orchestrator
│   ├── validators.py           # Step 6: 60+ rule engine
│   ├── optimizer.py            # Step 7: Tax optimization engine
│   ├── quality_control.py      # Step 8: Completeness + AI sanity
│   ├── outputs/
│   │   ├── elster_xml.py       # XML generator
│   │   ├── pdf_full.py         # ReportLab per-form templates
│   │   ├── pdf_summary.py
│   │   ├── audit_report.py
│   │   └── datev_csv.py
│   ├── elster/
│   │   ├── eric_wrapper.py     # Phase 2: ERiC C++ binding
│   │   └── transfer.py         # Phase 2: submission flow
│   ├── learning/
│   │   ├── carry_forward.py    # Permanent/Semi/Annual
│   │   ├── employer_history.py
│   │   ├── property_history.py
│   │   └── insurance_history.py
│   ├── forms/                  # Per-form business logic
│   │   ├── est_1a.py
│   │   ├── anlage_n.py
│   │   ├── anlage_s.py
│   │   ├── anlage_eur.py
│   │   ├── anlage_g.py
│   │   ├── anlage_v.py
│   │   ├── anlage_kap.py
│   │   ├── anlage_r.py
│   │   ├── anlage_so.py
│   │   ├── anlage_kind.py
│   │   ├── anlage_aus.py
│   │   ├── anlage_av.py
│   │   ├── anlage_vorsorge.py
│   │   ├── anlage_aussergewohnliche.py
│   │   ├── anlage_sonder.py
│   │   ├── anlage_haushaltsnahe.py
│   │   ├── anlage_energetisch.py
│   │   ├── ust_1a.py
│   │   └── gewst_1a.py
│   └── tests/
│       ├── test_finanzamt.py
│       ├── test_form_detection.py
│       ├── test_questionnaire.py
│       ├── test_validators.py
│       ├── test_optimizer.py
│       └── fixtures/
│           ├── lsb_sample.pdf
│           ├── rentenbescheid.pdf
│           └── ...
├── tax_data/                   # static reference data
│   ├── bmf_2024/
│   ├── bmf_2025/
│   ├── bmf_2026/
│   ├── finanzaemter.csv        # 615 Finanzämter
│   ├── plz_finanzamt_2025.csv  # 14k PLZ mappings
│   └── steuernummer_formats.json
└── main.py                      # endpoints wire-up
```

---

## STEP 14 — WORKFLOWS (8 user journeys)

### W1 — First-time user, single employee
1. Land on `/tax/2025`
2. "Erste Steuererklärung?" prompt → guided setup
3. Profile section: name + address + Steuer-ID
4. Auto-detect Finanzamt
5. Upload LSB → AI extracts → confirms 12 fields
6. Werbungskosten section: commute + homeoffice
7. Vorsorge: KV/Rente
8. Review: completeness 95%, **+€324 erwartete Erstattung**
9. Finalize → PDF download → upload to ELSTER manually

**Total time:** 12 min (vs WISO 45 min first-time).

### W2 — Returning user (year 2)
1. Land on `/tax/2026`
2. Banner: "Möchtest du aus 2025 fortsetzen?" → ja
3. **Permanent fields autofilled, marked green**
4. Semi fields shown for verification ("Adresse noch aktuell?")
5. Annual fields empty → guided fill
6. Upload new LSB → AI extracts (95% similar to 2025)
7. Diff vs 2025 shown: "Brutto +5%, Pendelweg gleich"
8. Finalize.

**Total time:** 6 min.

### W3 — Self-employed Friseur (Anlage S + EÜR + USt)
1. Profile → industry: "Friseur" → flag `has_self_employment`, `has_gewerbe?`
2. Form detection: ESt 1 A + Anlage S + Anlage EÜR + Anlage Vorsorge + USt 1 A
3. Anlage S: Tätigkeit "Friseur" + Gewinn auto from `cash_entries` (Kasse import)
4. Anlage EÜR: live populated from `invoices` + `cash_entries`
5. USt: alle USt-Voranmeldungen YTD vs Jahressumme
6. Validate cross-form: EÜR Gewinn = Anlage S Gewinn (auto)
7. Finalize → PDF Mantelbogen + S + EÜR + USt 1 A all in bundle.

### W4 — Married couple Zusammenveranlagung
1. Profile → familienstand = verheiratet → spouse subsection appears
2. Spouse data: name + Steuer-ID + Lohnsteuerbescheinigung upload
3. Anlage N per partner (auto numbered "N (1)" + "N (2)")
4. Veranlagungsart = "zusammen" → Splittingtarif applied in calc
5. Children: per child Steuer-ID, behinderung, Kinderbetreuungskosten

### W5 — Landlord with 2 rental properties
1. Profile → has_rental = true
2. Property registry: add property 1, property 2
3. Anlage V automatically × 2 (one per property)
4. Auto-suggest documents to upload: Nebenkostenabrechnung, Zinsenbescheinigung
5. AfA calculator: Anschaffungskosten Gebäude × 2% (auto from acquired date)
6. Validation: Schuldzinsen tatsächlich gezahlt vs. erwartet

### W6 — Pensioner with foreign pension
1. Profile → has_pension = true → Anlage R required
2. + has_foreign_pension = true → Anlage R-AUS + AUS
3. Upload Rentenbescheid DRV → 5 fields auto
4. Upload foreign pension statement → Sonnet extracts (lower confidence)
5. DBA-Berechnung (Doppelbesteuerungsabkommen) shown

### W7 — Child with disability + parent transfer
1. Anlage Kind → add child
2. Child fields: name, geb, Steuer-ID, kindergeld
3. Behinderung: GdB 80, Merkmal H → Pauschbetrag €7.400
4. "Pauschbetrag auf Eltern übertragen?" → ja
5. Calc: +€7.400 abzug on parent's zvE → savings ~€2.220 @ 30% tax bracket

### W8 — Energetische Sanierung (§35c)
1. Sonderausgaben section → "Hast du 2025 energetisch saniert?" → ja
2. Anlage Energetische Maßnahmen aktiviert
3. Fields: Maßnahme-Art (Heizung/Fenster/Dämmung), Datum, Kosten
4. §35c: 20% verteilt auf 3 Jahre → Jahr 1 = 7%, Jahr 2 = 7%, Jahr 3 = 6%
5. Calc: bis €40.000 absetzbar (max €8.000/Jahr) = €2.400 direkte Steuerersparnis

---

## STEP 15 — MISSING FEATURES AUDIT (vs current MVP)

| Feature | Status | Gap |
|---|---|---|
| **75-field flat schema** | ✅ Mevcut iter A-N | OK Phase 1 |
| **11 sections** | ✅ Mevcut | Eksik: Anlage G, S, EÜR, AUS, SO, AV, Haushaltsnahe, Energetisch, KAP-BET, KAP-INV, R-AUS, USt, GewSt — **12 form missing** |
| **Zeile numbers** | ✅ | OK |
| **Carry-forward** | ✅ Basic (iter B) | Eksik: tax_profile relational, semi-effective dating |
| **LSB OCR** | ✅ (iter 5) | OK |
| **Spende OCR** | ✅ (iter A) | Eksik: Rentenbescheid, Versicherung, Bankenbescheinigung OCR |
| **Live tax calc** | ✅ (iter M) | Geliştirilmeli: Splittingtarif edge cases, KAP teilweise pauschal, §35a/§35c reductions |
| **ELSTER XML** | ✅ Skeleton (iter D) | Eksik: official ELSTER schema validation, encryption, ERiC transmission |
| **Finanzamt lookup** | ❌ Yok | **YOK — Step 1 komplet eksik** |
| **Form detection engine** | ❌ Yok | **YOK — Step 2 komplet eksik** |
| **Dynamic questionnaire** | ❌ Yok | Form düz akış var, conditional state machine yok |
| **Validation engine 60 rules** | ⚠ Partial | Pattern + Steuer-ID + IBAN var, 50+ kural eksik |
| **Tax optimization engine** | ❌ Yok | Step 7 komplet eksik |
| **AI quality control** | ⚠ Basic | Confidence var, full LLM review yok |
| **Completeness score** | ❌ Yok | Bilgilendirici yok |
| **AI Steuerberater chat** | ⚠ Partial (`/steuer/declaration/ask`) | Field-context'li var, generic eksik |
| **Bescheid OCR + comparison** | ❌ Yok | Step 9.X |
| **Employer history table** | ❌ Yok | Phase 2 memory |
| **Property history** | ❌ Yok | Phase 2 |
| **Insurance providers** | ❌ Yok | Phase 2 |
| **§35c Energetische** | ❌ Yok | Yeni form |
| **Riester (Anlage AV)** | ❌ Yok | Yeni form |
| **Sonderausgaben — Korean adoption** | N/A | Edge case |

**Gap toplam:** ~%55 production-complete. **~%45 yapılması gerek.**

---

## STEP 16 — 8-WEEK IMPLEMENTATION ROADMAP

### Hafta 1 — Foundation
- [ ] `tax_engine/` package + module skeletons
- [ ] Finanzamt directory import (BMF Excel parser)
- [ ] PLZ → Finanzamt lookup endpoint + UI auto-detect
- [ ] Steuernummer per-Land format validator
- [ ] Tests for 5 Bundesländer

### Hafta 2 — Form Detection + Schema Registry
- [ ] `tax_form_versions` table + 2024 schema imports for all 32 forms
- [ ] `form_detection.py` engine (32 rules)
- [ ] Endpoint `/tax/forms/detect` + UI sidebar
- [ ] Migration: existing FORM_SECTIONS → schema registry

### Hafta 3 — Dynamic Questionnaire
- [ ] `questionnaire.py` state machine (40+ steps)
- [ ] `questionnaire_sessions` table + resume token
- [ ] Frontend: replace static form with question-by-question flow
- [ ] Skip / back / jump-to navigation

### Hafta 4 — Document AI Expansion
- [ ] All 13 document types: prompts + extractors + mappers
- [ ] `ai_extractions` table + cost analytics
- [ ] Per-doc-type confidence thresholds
- [ ] Upload UI with auto-classify

### Hafta 5 — Validation + Optimization
- [ ] 60 validation rules (per-form + cross-form)
- [ ] 50 tax optimization patterns
- [ ] `/tax/{year}/optimize` endpoint + UI banner
- [ ] Live "missed savings" indicator

### Hafta 6 — Per-form Logic Modules
- [ ] 19 form modules implemented (`tax_engine/forms/*.py`)
- [ ] Per-form PDF templates
- [ ] Cross-form validations
- [ ] Multi-employer Anlage N support

### Hafta 7 — Quality Control + Output Layer
- [ ] Completeness scoring + finalize gate
- [ ] AI sanity check (Sonnet, $0.05 per declaration)
- [ ] Full PDF generator (multi-form bundle)
- [ ] Audit report PDF
- [ ] DATEV CSV per Land mapping

### Hafta 8 — Self-Learning + ELSTER XML Path B + Polish
- [ ] `user_employers`, `user_rental_properties`, `user_insurance_providers` tables
- [ ] Year-N+1 auto-prefill
- [ ] Bescheid upload + AI compare to declared
- [ ] Frontend dashboard "Jahresübersicht"
- [ ] **Berber pilot + 5 freelancer pilot** (canlı test)
- [ ] Pricing tier ayarları
- [ ] Help dökümanları DE+TR
- [ ] Bug fixes

### Phase 2 (Hafta 9-12+) — ELSTER ERiC + Power Features
- ERiC C++ binding + ELSTER ISV certification
- Direct submission with electronic signature
- Bescheid auto-fetch via ELSTER (when supported by Land)
- Multi-tenant Steuerberater portal

---

## STEP 17 — DEFINITION OF DONE (Production Acceptance)

Phase 1 ancak şunlar TAMAM ise release:

- [ ] 32 form'un hepsi field schema'ya sahip (2024 ve 2025)
- [ ] 14.000 PLZ lookup'ı çalışıyor (5+ test scenario)
- [ ] 60+ validation rule LIVE + test coverage %80
- [ ] 50+ optimization pattern + estimated savings hesap
- [ ] Dynamic questionnaire state machine 40+ adım test edilmiş
- [ ] 13 doc type extraction çalışıyor + confidence threshold
- [ ] Live tax calc Splittingtarif + edge cases doğru
- [ ] ELSTER XML schema validation (xmllint) geçer
- [ ] Multi-form PDF render hatasız (32 form)
- [ ] Cross-form validation: Anlage S Gewinn = EÜR Gewinn auto-check
- [ ] Carry-forward Permanent/Semi/Annual doğru çalışıyor
- [ ] Year-N+1 onboarding ≤10 dakika (pilot test)
- [ ] 5 gerçek müşteri pilot bitmiş (Steuerberater inceledi)
- [ ] **AI cost per declaration ≤ €0.50** (target margin)
- [ ] **Completion rate ≥ 80%** (user starts → finalizes)
- [ ] Stripe pricing tiers (Starter €15, Pro €39, AI Steuer €89) güncel
- [ ] Help docs DE + TR per form
- [ ] Privacy policy + AVV güncel (BMF veri akışı dokümante)
- [ ] Berber + IT-Freelancer + Lehrer + Vermieter + Rentner canlı pilot başarılı

---

## FINAL SUMMARY

**Toplam scope:**
- 32 form
- 32 DB tablo
- 60+ API endpoint
- 60+ validation rule
- 50+ tax optimization
- 13 doc type AI extraction
- 8 yıl form versioning support
- 615 Finanzamt + 14k PLZ
- 8 hafta implementasyon (solo dev)

**Mevcut durum:** ~%45 hazır (`autotax/declaration.py` 75 field 11 section + live calc + LSB OCR + Pendlerpauschale + Behindertenpauschbetrag + 6 commit iter A-N).

**Eksik en kritik 5:**
1. Finanzamt lookup (Step 1) — komplet yok
2. Form detection engine (Step 2) — komplet yok
3. Dynamic questionnaire (Step 3) — komplet yok
4. 12 form eksik (Anlage G, EÜR, AUS, SO, AV, Haushaltsnahe, Energetisch, KAP-BET, KAP-INV, R-AUS, USt 1 A, GewSt)
5. Validation/optimization rule motoru (Step 6, 7) — sadece 10/60+ kural var

**1 ay sürer mi?** Hayır, **8 hafta = 2 ay solo dev tempo**. Sıkıştırılabilir 6 hafta (günde 10 saat), ama kalite riski.

**Önerim:** "Kaliteli yapalım" direktifi ile **8 hafta**. Her hafta sonu canlı test + iterasyon.

**Document status:** Living spec.
**Last update:** 2026-05-31.
**Next milestone:** Hafta 1 (Finanzamt lookup + schema registry) — target 2026-06-07.

## REFERENCES
- `.claude/tax_intake_architecture.md` — onceki vision doc
- `.claude/steuererklaerung_plan.md` — Phase 1 MVP plan
- `.claude/pos_parser_v2_production.md` — Kassensystem ayrı modül
- `autotax/declaration.py` — current 75-field schema
- `autotax/main.py` — declaration endpoints
- `autotax/tax_calc.py` — live tax estimator
- `autotax/tax_doc_ocr.py` — document AI
