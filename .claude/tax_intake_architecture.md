# AutoTax — Production Tax Intake Architecture

**Hedef:** WISO Steuer / Taxfix / Smartsteuer / SteuerGo seviyesi. AI-first, year-over-year memory, document-driven autofill.

**Mevcut MVP:** `autotax/declaration.py` (Mantelbogen + Anlage S + N + V + Vorsorge — 5 section / 34 field). Bu doc target state'i tanımlar; mevcut MVP **Phase 1** sayılır.

---

## 1. Information Architecture — Tüm Onboarding Bölümleri

| # | Bölüm | Amaç | Zorunlu | Opsiyonel | AI Autofill |
|---|---|---|---|---|---|
| 1 | **Personal** | Steuerpflichtige kişi | Vorname, Nachname, Steuer-ID, Geburtsdatum | Telefon, alt-Adresse | Lohnsteuerbescheinigung'dan tüm Adresse + birthdate |
| 2 | **Family Status** | Veranlagungsart (Splitting?) | Familienstand | Datum der Eheschließung, Trennungsdatum | Eheurkunde scan |
| 3 | **Spouse** (conditional) | Zusammenveranlagung | Spouse Vorname/Nachname/Steuer-ID | Beruf | Steuerbescheid'den auto |
| 4 | **Children** | Kinderfreibetrag, Kindergeld | Anzahl Kinder, Vorname+Geb.datum | Behinderung-Grad, Unterhalt | Kindergeld-Bescheid OCR |
| 5 | **Religion** | Kirchensteuer | Konfession | Eintrittsdatum, Austrittsdatum | Lohnsteuerbescheinigung Feld 6 |
| 6 | **Address** | Wohnsitz | Straße+Hausnr, PLZ, Ort | Nebenwohnsitz | Meldebescheinigung |
| 7 | **Bank Account** | Erstattung | IBAN, Kontoinhaber | BIC (optional) | Aus existing UserCompany / Stripe customer |
| 8 | **Tax Class** | Lohnsteuerabzug | Steuerklasse 1–6 | Faktor (bei IV/IV) | Lohnsteuerbescheinigung |
| 9 | **Employment** | Anlage N | Arbeitgeber Name+Adresse, Bruttoarbeitslohn | Mehrere AG, Sondervergütung | Lohnsteuerbescheinigung (ALLE Felder) |
| 10 | **Commuting (Pendlerpauschale)** | Anlage N Werbungskosten | Entfernung km, Arbeitstage | Verkehrsmittel, Wechselort | Address + Employer Address → Distanz |
| 11 | **Home Office** | Werbungskosten | Tage HO/Jahr | Spezielles Arbeitszimmer (€1.260) | Anlage S Kategorisierung |
| 12 | **Work Equipment** | Arbeitsmittel | Käufe >€800 (AfA) | Tablet/Phone Anteil | Invoice OCR + category="electronics"/"office" |
| 13 | **Professional Expenses** | Werbungskosten Anlage N | Fortbildung, Fachliteratur, Berufsverbände | Bewerbungskosten | Invoice category="education"/"books" |
| 14 | **Self Employment** | Anlage S + EÜR | Tätigkeit, Gewinn | Veräußerungsgewinn, §35 | EÜR aus Invoice/CashEntry tabelle |
| 15 | **Self Employment Expenses (EÜR)** | EÜR breakdown | Werbung, Reisekosten, Bewirtung, Kfz, Miete, Personal | AfA-Tabelle, Geringwertige WG | Auto from Invoice categories (mevcut) |
| 16 | **Rental Income** | Anlage V | Mietobjekt-Adresse, Mieteinnahmen | Nebenkosten, mehrere Objekte | Nebenkostenabrechnung OCR |
| 17 | **Rental Expenses** | Anlage V Werbungskosten | AfA, Zinsen, Erhaltung, Grundsteuer | Hausverwaltung, Verwaltungskosten | Bank statement + invoice scan |
| 18 | **Capital Income** | Anlage KAP | Zinsen, Dividenden, Kursgewinne | Freistellungsauftrag | Steuerbescheinigung Bank PDF |
| 19 | **Foreign Income** | Anlage AUS | Auslandseinkünfte, Land | DBA, Anrechnung | Manuel (komplex) |
| 20 | **Pension Income** | Anlage R | Rentenzahlungen | Rentenbeginn, Versorgungsbezüge | Rentenbescheid OCR |
| 21 | **Insurance — Krankenkasse** | Anlage Vorsorge | KV Basisbeitrag | Zusatzbeitrag, Pflegeversicherung | KK Beitragsbescheinigung OCR (mevcut detect_insurance_amounts) |
| 22 | **Insurance — Rente** | Anlage Vorsorge | DRV Beitrag | Rürup, BU | DRV Mitteilung OCR |
| 23 | **Donations** | Sonderausgaben | Empfänger, Betrag | Mitgliedsbeitrag Partei | Spendenbescheinigung OCR |
| 24 | **Household Services** | §35a EStG | Haushaltshilfe, Reinigung | 20% absetzbar bis €4.000 | Invoice category="household" |
| 25 | **Craftsmen Costs** | §35a EStG | Handwerker-Rechnungen | Lohnanteil getrennt | Handwerker-Rechnung OCR + Lohn vs Material |
| 26 | **Extraordinary Burdens** | §33 EStG | Krankheitskosten, Pflege, Behinderung | Grad GdB | Arzt-Rechnung + Pflegekasse Bescheid |
| 27 | **Tax Advisor Costs** | Werbungskosten/Betriebsausgaben | Steuerberater-Honorare | Aufteilung Privat/Beruflich | Invoice vendor="Steuerberater" |
| 28 | **Previous Tax Returns** | Verlustvortrag, Anrechnung | Vorjahres-Bescheid Upload | Steuerklassenoptimierung | Bescheid OCR |

**Toplam: 28 ana bölüm, ~250 field.** WISO Steuer'in eşdeğeri.

---

## 2. Long-Term Memory Model — Field Classification

Her field 3 sınıftan birine ait:
- **A) Permanent** — değişmez, indef. saklanır
- **B) Semi-Permanent** — yıllık doğrulama gerekir
- **C) Annual** — her yıl sıfırdan toplanır

### Tablo — Critical Field Classification

| Field | Class | Re-ask trigger |
|---|---|---|
| `name_full` | **A** | Marriage / name change |
| `birth_date` | **A** | Never |
| `steuer_id` | **A** | Never |
| `religion` | **A** | User signals "Austritt" |
| `geschlecht` | **A** | Never |
| `kv_provider` (Krankenkasse) | **A** | User signals "KK wechseln" |
| `address` | **B** | Yearly "Stand 31.12. richtig?" |
| `marital_status` | **B** | Yearly + life event button |
| `tax_class` | **B** | Yearly (kann sich durch Heirat ändern) |
| `iban` | **B** | Yearly confirm |
| `employer_current` | **B** | Yearly + "AG-Wechsel?" toggle |
| `commute_distance_km` | **B** | Yearly + bei AG-Wechsel reset |
| `homeoffice_setup` | **B** | Yearly (Räume können wechseln) |
| `dependents_count` | **B** | Yearly (Kinder werden geboren / volljährig) |
| `rental_property_list` | **B** | Yearly (Kauf/Verkauf trigger) |
| `salary_brutto` | **C** | Always re-collect (Lohnsteuerbescheinigung) |
| `bonus` | **C** | Always |
| `commute_days` | **C** | Always (Krankheitstage variieren) |
| `homeoffice_days` | **C** | Always |
| `donations_year` | **C** | Always |
| `work_equipment_purchases` | **C** | Always |
| `medical_expenses` | **C** | Always |
| `household_service_costs` | **C** | Always |
| `craftsmen_costs` | **C** | Always |
| `kv_premium_year` | **C** | Always (Bescheinigung jedes Jahr neu) |
| `rente_payment_year` | **C** | Always |
| `eur_revenue` (Selbständig) | **C** | Always (Invoice rows summen) |
| `eur_expenses` (kategorie bazlı) | **C** | Always (Invoice rows) |
| `bank_interest` (KAP) | **C** | Always |

**Sonuç:** ~25% Permanent, ~35% Semi-Permanent, ~40% Annual.
→ Onboarding **2. yıl 60% daha az tıklama** = WISO benzeri experience.

---

## 3. AI Document Strategy

Each customer document = potential autofill source.

| Document | Format | Extracted Fields | Confidence Min | Validation |
|---|---|---|---|---|
| **Lohnsteuerbescheinigung** | PDF / Image | AG-Adresse, Brutto, Lohnsteuer, Soli, KS, SV-Beiträge | 0.85 (numbers), 0.7 (names) | Brutto > Lohnsteuer; SV-Anteile checksum |
| **Gehaltsabrechnung** | PDF/Image | Monatswert, deduce annual (×12) | 0.7 | LSB > Gehalt summe |
| **Rentenbescheid** (DRV) | PDF | Jahresbetrag, Beginnjahr | 0.85 | < bei 85% Besteuerungsanteil |
| **Versicherungsnachweis (KV)** | PDF | Jahresbeitrag basis/zusatz | 0.9 | Beitrag plausibel (3–20% Brutto) |
| **DRV-Mitteilung** | PDF | AN-Beitrag | 0.9 | 9.3% Brutto (gesetzlich) |
| **Rürup Bescheinigung** | PDF | Jahresbeitrag, Vertrag-ID | 0.85 | < €27.566 max |
| **Spendenbescheinigung** | PDF / Image | Empfänger, Betrag, Datum | 0.9 (Betrag), 0.7 (Empfänger) | <20% Einkommen plausibel |
| **Nebenkostenabrechnung** | PDF | Mietnebenkosten Detail | 0.7 | Bewohnerbetrag konsistent |
| **Handwerkerrechnung** | PDF / OCR | Lohnanteil getrennt, MwSt | 0.8 | Lohnanteil > 0, MwSt valid |
| **Kontoauszug** | PDF / CSV | Mieteinnahmen (Verwendungszweck Match) | 0.7 | Pattern matching Mietzahlung |
| **Steuerbescheid Vorjahr** | PDF | Carry-forward Verlust, Identifikation Probleme | 0.8 | Bescheid-Nr formal valid |
| **Kindergeld-Bescheid** | PDF | Kind Name + Geb.datum + Bewilligungszeitraum | 0.9 | <18 oder Studierend |
| **DSFinV-K Kasse Export** | ZIP/CSV | CashEntry rows (mevcut Phase B) | 0.95 | TSE-Signatur (sonra) |

**Pipeline:**
```
Document Upload
    ↓
1. Doc-Type Classification (vision LLM: Claude Haiku, 1-shot)
    ↓
2. Field Extraction (vision LLM with type-specific prompt)
    ↓
3. Confidence + Validation rules
    ↓
4a. confidence >= 0.85 → auto-apply to user_tax_profile
4b. confidence 0.7–0.85 → show user "wir haben X gefunden, bestätigen?"
4c. confidence < 0.7 → manuel
    ↓
5. Save to ai_extractions table (audit)
```

---

## 4. Smart Interview Flow (Conditional Logic)

```
START
  ↓
[Personal] → always
  ↓
[Family Status] → always
  ↓
{if marital_status == "verheiratet"}
  → [Spouse]
{else}
  → skip
  ↓
[Children: count?]
  ↓
{if count > 0}
  → [Per-Child detail]
  → [Kinderbetreuungskosten]
{else}
  → skip
  ↓
[Employment: employed this year?]
  ↓
{yes}
  → [Lohnsteuerbescheinigung Upload]
  → [Commute / Home Office / Work Equipment]
{no}
  → skip Anlage N
  ↓
[Self-Employment: tätig?]
  ↓
{yes}
  → [Anlage S — auto Gewinn aus EÜR DB]
  → [EÜR Detail review]
{no}
  → skip
  ↓
[Rental: vermietest du?]
  ↓
{yes}
  → [Per-Property detail]
{no}
  → skip Anlage V
  ↓
[Capital: hast du Bank-Kapitalerträge?]
  ↓
{yes & Freistellungsauftrag voll genutzt?}
  → [Anlage KAP detail]
{no/voll genutzt}
  → skip
  ↓
[Pension] → only if age >= 60 ODER user toggles
  ↓
[Insurance Vorsorge] → always
  → KV Pflicht
  → DRV
  → optional Rürup/BU
  ↓
[Sonderausgaben] → always
  → Spenden, Kirchensteuer (auto from LSB), Steuerberater
  ↓
[Außergewöhnliche Belastungen] → optional (toggle "Krankheitskosten 2025?")
  ↓
[Handwerker / Haushaltsdienst] → always (häufig)
  ↓
REVIEW SCREEN
  → AI Summary: "Geschätzte Erstattung XX€"
  → Liste fehlender Dokumente
  → Vergleich Vorjahr
  ↓
PDF / ELSTER Export
```

**Implementation:** State machine in JSON, frontend renders dynamic. Backend `/tax/interview/state` GET/POST.

---

## 5. Database Schema

```sql
-- Permanent user-level data
CREATE TABLE tax_profiles (
  id            BIGSERIAL PK,
  user_id       BIGINT UNIQUE REFERENCES users(id),
  vorname       TEXT,
  nachname      TEXT,
  geburtsdatum  DATE,
  steuer_id     CHAR(11) UNIQUE,
  steuer_nummer TEXT,
  religion      TEXT,           -- 'none', 'ev', 'rk', 'other'
  geschlecht    TEXT,
  kv_provider   TEXT,           -- Krankenkasse persistent
  created_at    TIMESTAMPTZ,
  updated_at    TIMESTAMPTZ
);

-- Semi-permanent (yearly confirm)
CREATE TABLE tax_profile_address (
  id            BIGSERIAL PK,
  user_id       BIGINT REFERENCES users(id),
  effective_from DATE,
  effective_to   DATE NULL,    -- NULL = current
  strasse       TEXT,
  plz           CHAR(5),
  ort           TEXT,
  UNIQUE(user_id, effective_from)
);

CREATE TABLE tax_profile_bank (
  id            BIGSERIAL PK,
  user_id       BIGINT REFERENCES users(id),
  effective_from DATE,
  effective_to   DATE NULL,
  iban          TEXT,
  kontoinhaber  TEXT
);

CREATE TABLE tax_profile_marital (
  id            BIGSERIAL PK,
  user_id       BIGINT REFERENCES users(id),
  effective_from DATE,
  effective_to   DATE NULL,
  status        TEXT,           -- 'ledig', 'verheiratet', 'geschieden'
  spouse_user_id BIGINT NULL    -- if also AutoTax user
);

-- Per-year tax declaration (mevcut TaxDeclaration genişletilir)
CREATE TABLE tax_years (
  id            BIGSERIAL PK,
  user_id       BIGINT REFERENCES users(id),
  year          INT,
  status        TEXT,           -- 'draft', 'submitted', 'accepted', 'rejected'
  veranlagungsart TEXT,         -- 'einzel', 'zusammen'
  steuerklasse  INT,            -- 1..6
  estimated_refund DECIMAL(12,2),
  submitted_at  TIMESTAMPTZ NULL,
  bescheid_date DATE NULL,
  data_jsonb    JSONB,          -- all flexible fields
  UNIQUE(user_id, year)
);

-- Annual: Employment per tax year
CREATE TABLE employment_years (
  id            BIGSERIAL PK,
  tax_year_id   BIGINT REFERENCES tax_years(id),
  employer_name TEXT,
  employer_address TEXT,
  brutto        DECIMAL(12,2),
  lohnsteuer    DECIMAL(12,2),
  soli          DECIMAL(12,2),
  kirchensteuer DECIMAL(12,2),
  sv_kv         DECIMAL(12,2),
  sv_rv         DECIMAL(12,2),
  sv_av         DECIMAL(12,2),
  sv_pv         DECIMAL(12,2),
  doc_lohnsteuerbescheinigung_id BIGINT NULL
);

-- Dependents (children mostly)
CREATE TABLE dependents (
  id            BIGSERIAL PK,
  user_id       BIGINT REFERENCES users(id),
  vorname       TEXT,
  geburtsdatum  DATE,
  steuer_id     CHAR(11) NULL,
  kindergeld_received BOOLEAN DEFAULT TRUE,
  shared_custody BOOLEAN DEFAULT FALSE,
  ended_at      DATE NULL       -- volljährig oder ausgezogen
);

-- Annual rental properties (Anlage V)
CREATE TABLE rental_properties (
  id            BIGSERIAL PK,
  user_id       BIGINT REFERENCES users(id),
  adresse       TEXT,
  acquired      DATE,
  sold          DATE NULL
);

CREATE TABLE rental_year_data (
  id            BIGSERIAL PK,
  property_id   BIGINT REFERENCES rental_properties(id),
  tax_year_id   BIGINT REFERENCES tax_years(id),
  mieteinnahmen DECIMAL(12,2),
  nebenkosten_erhalten DECIMAL(12,2),
  afa           DECIMAL(12,2),
  zinsen        DECIMAL(12,2),
  erhaltung     DECIMAL(12,2),
  grundsteuer   DECIMAL(12,2),
  sonst         DECIMAL(12,2)
);

-- Document storage (existing invoices/vault, plus new types)
CREATE TABLE tax_documents (
  id            BIGSERIAL PK,
  user_id       BIGINT REFERENCES users(id),
  tax_year_id   BIGINT NULL REFERENCES tax_years(id),
  doc_type      TEXT,           -- 'lohnsteuerbescheinigung', 'spende', ...
  file_path     TEXT,
  file_sha256   CHAR(64),
  uploaded_at   TIMESTAMPTZ,
  UNIQUE(user_id, file_sha256)
);

CREATE TABLE ai_extractions (
  id            BIGSERIAL PK,
  document_id   BIGINT REFERENCES tax_documents(id),
  doc_type_detected TEXT,
  confidence    DECIMAL(3,2),   -- 0.00–1.00
  fields_json   JSONB,
  model         TEXT,           -- 'claude-haiku-4-5', etc
  status        TEXT,           -- 'pending', 'applied', 'rejected', 'manual'
  user_confirmed_at TIMESTAMPTZ NULL,
  created_at    TIMESTAMPTZ
);

-- Insurance per year
CREATE TABLE insurance_records (
  id            BIGSERIAL PK,
  user_id       BIGINT REFERENCES users(id),
  tax_year_id   BIGINT REFERENCES tax_years(id),
  type          TEXT,           -- 'kv_basis', 'kv_zusatz', 'pflege', 'drv', 'rurup', 'bu'
  amount        DECIMAL(10,2),
  doc_id        BIGINT NULL REFERENCES tax_documents(id)
);

-- Commute (Anlage N)
CREATE TABLE commute_records (
  id            BIGSERIAL PK,
  tax_year_id   BIGINT REFERENCES tax_years(id),
  from_address  TEXT,
  to_address    TEXT,
  distance_km   INT,
  arbeitstage   INT,
  homeoffice_tage INT,
  verkehrsmittel TEXT
);

-- Donations
CREATE TABLE donation_records (
  id            BIGSERIAL PK,
  user_id       BIGINT REFERENCES users(id),
  tax_year_id   BIGINT REFERENCES tax_years(id),
  empfaenger    TEXT,
  betrag        DECIMAL(10,2),
  datum         DATE,
  doc_id        BIGINT NULL REFERENCES tax_documents(id)
);

-- Tax returns submitted
CREATE TABLE tax_returns (
  id            BIGSERIAL PK,
  tax_year_id   BIGINT REFERENCES tax_years(id),
  elster_xml    TEXT NULL,
  pdf_path      TEXT NULL,
  submitted_at  TIMESTAMPTZ NULL,
  bescheid_pdf_path TEXT NULL,
  bescheid_received_at TIMESTAMPTZ NULL,
  actual_refund DECIMAL(12,2) NULL
);
```

**Migration path from current MVP:**
Mevcut `TaxDeclaration.data JSONB` schema esnek — yeni şema tabloları üstüne build edilir, eski TaxDeclaration rows JSONB'den structure'a otomatik migrate edilir (bir migration script).

---

## 6. AI Recommendation Engine

Triggered on data change or year-open.

| Recommendation | Trigger | Required Data | Confidence | Action |
|---|---|---|---|---|
| **Pendlerpauschale ungenutzt** | Anlage N filled, no commute_records | tax_year_id + employer address + home address | 0.95 (computed) | Banner "Du fährst zur Arbeit? Trag die Distanz ein, Erstattung ~€XYZ" |
| **Home-Office-Pauschale fehlt** | Anlage N + no homeoffice_tage | LSB exists, no record | 0.85 | Banner "Hast du im Homeoffice gearbeitet? €6/Tag bis €1.260" |
| **Krankheitskosten möglich** | Vorsorge filled, no Außergewöhnliche Belastungen | Income > €15k | 0.6 (Schätzung) | Soft hint "Hast du dieses Jahr hohe Krankheitskosten gehabt? Manche sind absetzbar" |
| **Handwerker absetzbar** | Invoice category="handwerker" exists | Invoice rows | 0.95 | Banner "Wir haben Handwerker-Rechnungen — 20% absetzbar" |
| **Haushaltshilfe absetzbar** | Invoice category="cleaning"/"household" | Invoice rows | 0.95 | Banner "Reinigung/Haushalt — 20% absetzbar bis €4.000" |
| **Spendenbescheinigung fehlt** | donation_records mentions amount, no doc_id | Mismatch | 1.0 | Block "Bitte Beleg hochladen — Pflichtnachweis" |
| **Lohnsteuerbescheinigung fehlt** | employment_year exists, no doc | Mismatch | 1.0 | Block "Lohnsteuerbescheinigung muss hochgeladen werden" |
| **Vorjahres-Verlustvortrag** | Previous bescheid_pdf has Verlust | bescheid OCR | 0.9 | Banner "Du hast €X Verlust aus Vorjahr — wird übernommen" |
| **Splittingvorteil prüfen** | Verheiratet, separate Veranlagung | Beide Einkommen | 0.95 (computed) | Banner "Zusammenveranlagung würde €Y sparen" |
| **Arbeitsmittel >€800** | Invoice category="electronics"/"office", betrag>800 | Invoice | 0.9 | Banner "Arbeitsmittel >€800 → AfA über 3-5 Jahre statt sofort" |

**Implementation:**
- Background job runs daily on changed tax_years
- Recommendations table:
  ```sql
  CREATE TABLE recommendations (
    id BIGSERIAL PK,
    user_id BIGINT,
    tax_year_id BIGINT,
    rule_key TEXT,
    severity TEXT,        -- 'info', 'warn', 'block'
    estimated_value DECIMAL(10,2) NULL,
    dismissed_at TIMESTAMPTZ NULL,
    applied_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ
  );
  ```
- Frontend banner stack with dismiss + "Apply" button per rec

---

## 7. UX Requirements

### Mobile-First
- 16px+ inputs (no iOS zoom) ✅ (mevcut)
- 48px+ touch targets ✅ (mevcut iter 4.4)
- Bottom-sheet sections on mobile
- Swipe between Anlage sections

### Progress Indicator
- Multi-step bar: "Personal → Family → Employment → ... → Review"
- % completion per section
- Sticky header zeigt "8 / 12 sections complete"

### Auto-Save
- Mevcut 600ms debounce ✅
- WIP-Recovery: server-side draft state + localStorage fallback
- "Saved 2 minutes ago" indicator

### Resume Later
- Section bookmarklike: "Continue where you left off"
- Email reminder day 3 / day 7 / day 14 wenn nicht abgeschlossen

### AI-Assisted Completion
- Doc upload triggers extraction → "Auto-applied 12 fields" badge
- Per-field "AI suggests: X" pill (kann reject)
- Voice-input optional (mobile)

### Minimal Manual Typing
- Address autocomplete (Mapbox / Nominatim)
- Employer database (largest 5000 DE companies suggest)
- Steuernummer / Steuer-ID kept once

### Annual Review Mode
- Year 2'de: tüm "B" fields önceki yıldan pre-fill + "ist das noch aktuell?" toggle
- Year 2 onboarding: ~10 dakika (Year 1: 45–60 min)

### GDPR Compliance
- Per-section "Why we need this" tooltip
- Right-to-delete + download all
- Audit log per data access
- Retention: tax docs 10 yıl (gesetzlich), anderes konfigurierbar

### Visual Design Quality
- WISO Steuer / Taxfix referansı
- Sektion cards mit subtle gradients
- Numbered timeline left rail
- Success animations on section complete
- Premium typography (DM Sans / Inter heavy hierarchy)

---

## 8. Implementation Phases — Roadmap from MVP

Mevcut: **Phase 1 done** = Mantelbogen + Anlage S/N/V/Vorsorge + 34 field + PDF + auto-detect.

| Phase | Scope | Duration | Output |
|---|---|---|---|
| **2** | Long-term memory model — split TaxDeclaration into tax_profiles + tax_years + per-year tables. Migrate JSON → relational. | 1 hafta | Year 2 pre-fill works |
| **3** | Document upload + AI extraction — Lohnsteuerbescheinigung first | 1 hafta | LSB upload → 12 fields auto |
| **4** | Conditional interview flow — state machine + 28 sections | 1.5 hafta | Taxfix-like guided flow |
| **5** | Recommendation engine — 10 başlangıç kuralı | 1 hafta | Pendlerpauschale banner çalışır |
| **6** | Dependents + Spouse modules | 5 gün | Familien-Splitting destek |
| **7** | Anlage KAP + R + AUS | 1.5 hafta | Capital + Pension + Foreign |
| **8** | Donations + Handwerker + Haushalt + Außergewöhnliche Belastungen | 1 hafta | Sonderausgaben tamam |
| **9** | Doc OCR full library — 13 doc types | 2 hafta | Hands-off intake |
| **10** | ELSTER ERiC integration — XML/XBRL export | 2-3 hafta | Direkt-Versendung |
| **11** | Year-over-year review mode — 10 min onboarding 2. yıl | 1 hafta | Returning user retention |
| **12** | Premium polish — animations, typography, progress, voice input | 2 hafta | WISO quality |

**Toplam: ~3-4 ay solo dev tempo.** Bunlar TEK BAŞINA geliştirilir — ekiple 5-6 hafta.

**Bu ay focus:** Phase 2 + 3 (memory + LSB OCR) = "Returning user year 2 30dk → 15dk".

---

## 9. Reference Comparisons

| Feature | WISO Steuer | Taxfix | AutoTax-Cloud (target) |
|---|---|---|---|
| Year-over-year memory | ✅ | ✅ | ⏳ Phase 2 |
| AI doc OCR | ❌ (manuel) | ⚠️ (basic) | ✅ (claude vision, Phase 3) |
| Conditional flow | ✅ | ✅ | ⏳ Phase 4 |
| ELSTER direct | ✅ | ✅ | ⏳ Phase 10 |
| Recommendation engine | ⚠️ | ⚠️ | ✅ planned Phase 5 |
| Self-employed (EÜR) | ✅ pro | ❌ | ✅ (mevcut) |
| Kassensystem integration | ❌ | ❌ | ✅ planned Path B |
| Mobile-first | ❌ | ✅ | ✅ (mevcut) |
| Price (annual) | €30–€60 | €40–€60 | €15–€89/Monat |

**Differentiation:** Self-employed + Kasse + AI-first → WISO ve Taxfix yapmaz.

---

## 10. Memory & Versioning Strategy

```
tax_profiles (1 row per user)
    ↓ has many
tax_profile_address (multiple, time-effective)
tax_profile_bank
tax_profile_marital
tax_profile_employer (current + history)
    ↓
tax_years (1 per year per user)
    ↓ has many
employment_years
rental_year_data
insurance_records
donation_records
commute_records
dependents_for_year
ai_extractions (audit)
recommendations
```

**Returning user Year 2 flow:**
```
1. /tax/onboard/2026 → check tax_years where user=X, year=2025
2. Found → fetch tax_profile (Permanent) + latest-effective tax_profile_* (Semi)
3. Pre-populate everything possible
4. Highlight "Annual" fields in red badge "needs input"
5. Show diff summary "vs. 2025: Brutto +12%, Pendelweg gleich, Spenden +€500"
6. Confirm-and-continue
```

---

## 11. Next Actionable Steps (bu hafta)

Şu an MVP (Phase 1) çalışıyor. **Sıradaki konkret işler** (hangisi seçilir → yapılır):

| # | İş | Etki | Süre |
|---|---|---|---|
| 1 | tax_profiles + tax_year tabloları (memory foundation) | yüksek | 1 gün |
| 2 | Lohnsteuerbescheinigung OCR (mevcut Claude vision'la) | çok yüksek | 1 gün |
| 3 | "Year-over-year" pre-fill prototype | yüksek | 1 gün |
| 4 | Dependents (Children) modülü | orta | 0.5 gün |
| 5 | Pendlerpauschale + commute_records | yüksek | 0.5 gün |
| 6 | Recommendation engine başlangıç (3 kural) | orta | 0.5 gün |
| 7 | Kassensystem (Path B) devamı | orta | 1 gün |

**Önerim Pazartesi başlangıç:** #1 (memory tables) + #2 (LSB OCR) parallel. Bu ikisi tax software'i WISO seviyesine taşır.

---

**Document Status:** Living spec — her implementasyon sonrası güncellenir.
**Last update:** 2026-05-30 — Phase 1 (5 section MVP) complete.
**Next milestone:** Phase 2 (memory model) — target 2026-06-06.
