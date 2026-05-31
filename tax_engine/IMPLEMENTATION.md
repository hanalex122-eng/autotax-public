# AutoTax-Cloud — Tax Knowledge System: Implementation Specification

**Stack:** FastAPI + SQLAlchemy + PostgreSQL (Railway; Supabase-compatible) + React (CDN).
**Knowledge base (machine-readable, no scraping):**
- `tax_engine/knowledge/forms.json` — Phase 1 master form database
- `tax_engine/knowledge/questionnaire.json` — Phase 2 dynamic interview engine
- `tax_engine/knowledge/knowledge_graph.json` — Phase 3 tax knowledge graph
- `tax_engine/knowledge/optimization_rules.json` — Phase 4 optimization rules
- `tax_engine/knowledge/coverage_report.json` — validation suite (20 personas)

**Authoring note:** The multi-agent workflow hit the account session limit mid-run; the lead architect authored these artifacts directly so the repository is left in a usable, committable state. All Zeile numbers and ELSTER Kennzahlen must be validated against the official ELSTER ERiC schema before production submission.

---

## Phase 5 — Learning Engine

Goal: never ask the same thing twice. Year N+1 onboarding ≤ 10 minutes by prefilling everything known.

### Data model (three temporalities)

- **Permanent** — identity that rarely changes (Steuer-ID, name, birth date).
- **Semi-permanent (time-effective)** — valid for a date range (address, bank, marital status, employer, insurance provider, rental property).
- **Annual** — one value per tax year (wage, profit, pension amount, child amounts).

### PostgreSQL DDL

```sql
-- Permanent
CREATE TABLE tax_profile (
  user_id        BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  steuer_id      CHAR(11),
  vorname        TEXT,
  nachname       TEXT,
  geburtsdatum   DATE,
  religion       TEXT,
  updated_at     TIMESTAMPTZ DEFAULT now()
);

-- Semi-permanent (time-effective dating)
CREATE TABLE tax_profile_address (
  id             BIGSERIAL PRIMARY KEY,
  user_id        BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  effective_from DATE NOT NULL,
  effective_to   DATE,                 -- NULL = current
  strasse        TEXT, plz CHAR(5), ort TEXT,
  finanzamt_id   BIGINT REFERENCES finanzamt_directory(id)
);
CREATE TABLE tax_profile_bank   (id BIGSERIAL PRIMARY KEY, user_id BIGINT REFERENCES users(id) ON DELETE CASCADE, effective_from DATE, effective_to DATE, iban TEXT, kontoinhaber TEXT);
CREATE TABLE tax_profile_marital(id BIGSERIAL PRIMARY KEY, user_id BIGINT REFERENCES users(id) ON DELETE CASCADE, effective_from DATE, effective_to DATE, status TEXT, spouse_steuer_id CHAR(11));
CREATE TABLE user_employers     (id BIGSERIAL PRIMARY KEY, user_id BIGINT REFERENCES users(id) ON DELETE CASCADE, name TEXT, first_seen_year INT, last_seen_year INT);
CREATE TABLE user_insurers      (id BIGSERIAL PRIMARY KEY, user_id BIGINT REFERENCES users(id) ON DELETE CASCADE, art TEXT, anbieter TEXT, vertragsnr TEXT);
CREATE TABLE rental_property     (id BIGSERIAL PRIMARY KEY, user_id BIGINT REFERENCES users(id) ON DELETE CASCADE, adresse TEXT, anschaffung DATE, gebaeudewert NUMERIC, afa_satz NUMERIC);
CREATE TABLE dependent           (id BIGSERIAL PRIMARY KEY, user_id BIGINT REFERENCES users(id) ON DELETE CASCADE, vorname TEXT, geburtsdatum DATE, steuer_id CHAR(11), gdb INT);

-- Annual snapshots + corrections
CREATE TABLE tax_year_value (
  id          BIGSERIAL PRIMARY KEY,
  user_id     BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  tax_year    INT NOT NULL,
  form_key    TEXT NOT NULL,
  field_key   TEXT NOT NULL,
  value       JSONB,
  source      TEXT,            -- 'ocr' | 'user' | 'prefill' | 'calc'
  confidence  NUMERIC,
  UNIQUE(user_id, tax_year, form_key, field_key)
);
CREATE TABLE user_correction (
  id          BIGSERIAL PRIMARY KEY,
  user_id     BIGINT REFERENCES users(id) ON DELETE CASCADE,
  field_key   TEXT, prefilled JSONB, corrected JSONB, tax_year INT, created_at TIMESTAMPTZ DEFAULT now()
);
```

### Prefill algorithm (year N+1)

```python
def prefill_declaration(user_id: int, year: int) -> dict:
    draft = {}
    apply_permanent(draft, tax_profile(user_id))
    apply_effective(draft, semi_permanent_as_of(user_id, date(year, 12, 31)))
    for fk, val in last_year_annual(user_id, year - 1):
        if field_is_stable(fk):            # employer, insurer, property -> carry
            draft[fk] = {"value": val, "source": "prefill", "confidence": 0.7}
    apply_corrections_bias(draft, user_corrections(user_id))  # learn from past fixes
    return draft
```

Corrections feed back: if a user repeatedly overrides a prefilled field, lower its prefill confidence and stop auto-filling it. DSGVO: all learning data is user-scoped, deletable via `/account/delete` cascade, and never shared across users.

---

## Phase 6 — Form Generator

Three outputs, all driven by `forms.json` (single source of truth for field → Zeile → ELSTER-Kennzahl mapping).

1. **Official-layout PDF** — per-form renderer (reportlab) using the section/field order from `forms.json`; ESt 1 A-style header, Zeile labels, checkbox fields. One PDF per active form + a bundled ZIP.
2. **ELSTER-compatible XML** — build the ERiC `Datenlieferung` structure: `<Nutzdaten>` per form, each field emitted as its `elsterKennzahl`. Validate against the official ELSTER XML schema with `xmllint` before export. Encryption + signed transmission requires the ERiC library + ISV certification → deferred to a later phase; v1 produces a validated XML the user imports into ELSTER / Mein ELSTER manually.
3. **Human-readable report + estimate** — summary of declared income, deductions and the tax/refund/Nachzahlung estimate (Splittingtarif for married, Soli only above threshold, Kirchensteuer 8/9%, Abgeltungsteuer 25% for capital income unless Günstigerprüfung).

```python
class FormGenerator:
    def render_pdf(self, decl: Declaration, form_key: str) -> bytes: ...
    def render_elster_xml(self, decl: Declaration) -> str:        # all active forms
    def render_report(self, decl: Declaration) -> ReportModel:    # + estimate
    def field_to_kennzahl(self, form_key, field_key) -> str:      # from forms.json
```

Endpoints: `GET /tax/{year}/pdf/{form_key}`, `GET /tax/{year}/elster.xml`, `GET /tax/{year}/report`, `GET /tax/{year}/bundle.zip`.

---

## Phase 7 — Implementation Roadmap

### 7.1 Database schema (consolidated, PostgreSQL / Supabase-compatible)

| Area | Tables |
|---|---|
| Knowledge base | `tax_form_version`, `tax_form_field` (loaded from forms.json; year-versioned) |
| Location | `finanzamt_directory`, `plz_to_finanzamt` |
| Declaration | `declaration`, `declaration_value` (= `tax_year_value`), `declaration_status` |
| Questionnaire | `questionnaire_session`, `questionnaire_answer` |
| Learning | `tax_profile`, `tax_profile_address/bank/marital`, `user_employers`, `user_insurers`, `rental_property`, `dependent`, `user_correction` |
| Documents | `tax_document`, `ai_extraction` |
| Optimization | `optimization_hit` (per-declaration detected savings) |

```sql
CREATE TABLE declaration (
  id BIGSERIAL PRIMARY KEY,
  user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  tax_year INT NOT NULL,
  status TEXT NOT NULL DEFAULT 'draft',   -- draft|in_review|finalized
  completeness_score INT DEFAULT 0,
  active_forms TEXT[] DEFAULT '{}',
  created_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE(user_id, tax_year)
);
CREATE TABLE tax_document (
  id BIGSERIAL PRIMARY KEY,
  user_id BIGINT REFERENCES users(id) ON DELETE CASCADE,
  tax_year INT, doc_type TEXT, storage_key TEXT,
  ocr_status TEXT DEFAULT 'pending', uploaded_at TIMESTAMPTZ DEFAULT now()
);
CREATE TABLE ai_extraction (
  id BIGSERIAL PRIMARY KEY,
  document_id BIGINT REFERENCES tax_document(id) ON DELETE CASCADE,
  doc_type TEXT, extracted JSONB, model TEXT, cost_eur NUMERIC, confidence NUMERIC
);
```

### 7.2 API design

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/tax/finanzamt/lookup?plz=` | user | PLZ → responsible Finanzamt |
| POST | `/tax/{year}/questionnaire/start` | user | begin interview, returns first node |
| POST | `/tax/{year}/questionnaire/answer` | user | submit answer, returns next node + activated forms |
| GET | `/tax/{year}/forms/detect` | user | required forms + reasons from profile |
| GET/PUT | `/tax/{year}/declaration` | user | read/update draft values |
| POST | `/tax/{year}/document/upload` | user | upload doc → OCR queue |
| GET | `/tax/{year}/optimize` | user | run optimization rules → suggestions |
| GET | `/tax/{year}/validate` | user | validation engine → errors/warnings |
| GET | `/tax/{year}/completeness` | user | completeness score + missing fields |
| POST | `/tax/{year}/finalize` | user | gate: refuse if mandatory fields missing |
| GET | `/tax/{year}/pdf/{form}` · `/elster.xml` · `/report` · `/bundle.zip` | user | outputs |
| POST | `/admin/tax/forms/reload` | admin | reload forms.json into DB |
| POST | `/admin/tax/finanzamt/import` | admin | import Finanzamt directory |

### 7.3 AI workflows (model + cost)

- **Questionnaire reasoning** — deterministic state machine (no LLM) for the path; optional Haiku "clarifier" only when an answer is free-text/ambiguous (~€0.002).
- **Field prefill from documents** — Haiku/Sonnet vision extraction (see OCR). Maps extracted values → `forms.json` field keys.
- **Sanity QC (Phase 8)** — one Sonnet call per finalize: "given these values, flag implausible/contradictory entries" (~€0.03–0.05/declaration). Target AI cost ≤ €0.50 per declaration.
- **AI Steuerberater chat** — existing `/steuer/declaration/ask`, field-context aware, StBerG-compliant.

### 7.4 OCR workflows

`upload → classify(doc_type) → extract(fields) → map(form fields) → confidence-gate → write tax_year_value(source='ocr')`. Pipeline: Tesseract/OCR.space first; Claude Haiku vision fallback for low-confidence or photo input. Doc types: Lohnsteuerbescheinigung, Versicherungsbescheinigung, Rentenbezugsmitteilung, Steuerbescheinigung (Bank), Handwerkerrechnung, Spendenbescheinigung, Schwerbehindertenausweis, Mietvertrag/Nebenkostenabrechnung, Steuerbescheid, Kindergeldbescheid. Values below the per-type confidence threshold are flagged for user confirmation, never auto-committed.

### 7.5 Frontend pages (React)

| Page | Purpose |
|---|---|
| `InterviewView` | renders questionnaire.json node-by-node; the user never sees raw forms |
| `DeclarationView` | per-form sections (driven by forms.json) for review/edit + prefilled values |
| `DocumentsView` | upload + OCR status + confirm extracted values |
| `OptimizeView` | optimization suggestions + missing-document checklist + estimated savings |
| `SummaryView` | completeness score, validation results, estimate, finalize gate |
| `OutputView` | download PDF / ELSTER XML / report / bundle |

### 7.6 Admin tools

- Forms registry browser + reload from `forms.json` (diff old vs new year).
- Finanzamt directory import/verify.
- Per-user declaration inspector (status, completeness, active forms) — already partially in `/admin`.
- OCR extraction review queue (low-confidence items).
- Optimization-rule hit analytics.

### 7.7 Missing features (vs current AutoTax MVP)

Current MVP: `declaration.py` ~75-field/11-section flat form, live tax estimator, LSB OCR, Behindertenpauschbetrag, Anlage Kind dynamic list, ELSTER XML skeleton.

Prioritized gaps:
1. **Finanzamt lookup** (PLZ → FA) — not built.
2. **Form detection engine** consuming knowledge_graph.json — not built.
3. **Dynamic questionnaire runtime** consuming questionnaire.json — not built (current form is flat/static).
4. **Knowledge base loader** — load forms.json into `tax_form_field`, render forms dynamically.
5. **Validation engine** (currently ~10 ad-hoc rules; target 60+ incl. cross-form).
6. **Optimization runtime** consuming optimization_rules.json + missing-doc detection.
7. **Completeness score + finalize gate**.
8. **Learning/prefill tables + year N+1 prefill**.
9. **Remaining forms** to full field-level depth (KAP-BET/INV, R-AUS, AV, SO, AUS, U, Unterhalt, L, V-FeWo, N-AUS, Corona).
10. **ELSTER ERiC** binding for direct signed submission (later phase, needs ISV cert).

### Rollout (relative weeks, dependency-ordered)

- **W1** Knowledge-base loader + forms.json → dynamic DeclarationView; Finanzamt lookup.
- **W2** Form detection engine (graph) + questionnaire runtime.
- **W3** Document AI expansion (all doc types) + prefill writing.
- **W4** Validation engine (60+ rules) + optimization runtime + missing-doc checklist.
- **W5** Completeness score + finalize gate + report/estimate.
- **W6** Learning tables + year N+1 prefill + corrections feedback.
- **W7** Form generator (PDF bundle + ELSTER XML validation) + admin tools.
- **W8** Remaining forms to depth + pilot (Selbständig, Familie, Vermieter, Rentner, Döner/Friseur).

### Definition of Done (production acceptance)

- All active forms render dynamically from `forms.json`; 0 hardcoded form fields.
- Finanzamt lookup correct for ≥ 5 test PLZ across Bundesländer.
- Validation: 60+ rules live, cross-form checks (Anlage S/EÜR Gewinn equality) pass.
- Completeness gate refuses finalize on missing mandatory fields.
- ELSTER XML validates against the official schema (`xmllint`).
- AI cost per declaration ≤ €0.50; completion rate (start → finalize) ≥ 80% in pilot.
- 20-persona validation suite (`coverage_report.json`) all green or documented.
- DSGVO: learning data user-scoped + cascade-deletable.
