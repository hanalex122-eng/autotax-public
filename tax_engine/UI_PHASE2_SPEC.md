# Phase 2 — Tax Assistant UI: Complete Specification

**Status:** Design only. No production code is changed by this document. The
backend feature flag `TAX_ENGINE_V2_ENABLED` remains OFF.
**Goal:** A first-time taxpayer completes the declaration without external help.
**Depends on:** the Phase 1 read-only API (`/tax/{year}/detect`,
`/questionnaire/start`, `/questionnaire/next`, `/build`) — already shipped,
flag-gated.

---

## 0. Hard constraints (must hold)

These derive from CLAUDE.md and the existing architecture:

- **Stack unchanged.** Frontend is React via CDN + Babel-in-browser inside
  `index.html`. No Vite, no TypeScript, no build step, no bundler. Components
  are plain functions; JSX is transpiled in the browser.
- **Additive only.** New components live in `index.html` alongside the existing
  SPA. No existing view, endpoint, or workflow is modified.
- **Flag-gated end to end.** The UI renders only when the SPA knows v2 is on.
  Because the SPA reads `window.FEATURES` (via `config.features_js_literal()`),
  a new key **`tax_engine_v2`** must be added there when implementation starts
  (mirrors `TAX_ENGINE_V2_ENABLED`). Until then the view is unreachable.
- **Localization** uses the existing helpers: `getLang()` → `"de"|"tr"|"en"`,
  and the `tr(de, en, tr)` ternary already used across the SPA.
- **Read-only engine.** The UI never writes tax data through the v2 endpoints
  (they are read-only). Persisting answers reuses the existing declaration
  save path in a later phase — out of scope here.

---

## 1. UX principles

1. **One question at a time, never a raw form.** The questionnaire drives the
   flow; the user sees plain German/Turkish/English questions, not Zeilen.
2. **Explain in place.** Every field carries a tooltip; a focused field opens a
   richer right-side help panel. Help is always one glance away.
3. **Trust through transparency.** Show *why* a form/field is needed, what
   document proves it, and a confidence signal when a value is uncertain.
4. **Calm, practical voice.** Per `ux_voice.md`: avoid "AI" hype; say
   "automatischer/intelligenter Helfer". Suggestions are *Vorschlag/Empfehlung*,
   never prescriptive tax advice (StBerG).
5. **Mobile-first, accessible.** 48px touch targets, 16px inputs (no iOS zoom),
   full keyboard + screen-reader support.

---

## 2. UI architecture

### 2.1 Where it plugs in

A new SPA view `declaration_v2` (the "Steuer-Assistent"), registered in the
existing `views` map in `index.html`, shown only when
`window.FEATURES.tax_engine_v2 === true`. Sidebar entry hidden otherwise
(same pattern as `_hiddenPages`).

### 2.2 Layout regions (desktop)

```
┌───────────────────────────────────────────────────────────────┐
│ Top bar: Steuerjahr ▾   Sprache ▾   Fortschritt ███░░ 60%       │
├───────────────────────┬───────────────────────────────────────┤
│  MAIN COLUMN (flex 2)  │  HELP PANEL (flex 1, sticky)            │
│                        │                                        │
│  Interview / Field     │  Context help for focused field:       │
│  card (one step)       │  • Beschreibung                        │
│                        │  • Warum dieses Feld?                  │
│  [ ? Was ist das ]     │  • Beispielwert                        │
│                        │  • Benötigte Belege  [Upload]          │
│  Confidence badge      │  • Validierungsregel                   │
│                        │  • "Was ist das?" (DE/TR/EN)           │
├───────────────────────┴───────────────────────────────────────┤
│ Footer: ◀ Zurück     Entwurf gespeichert      Weiter ▶          │
└───────────────────────────────────────────────────────────────┘
```

On mobile the help panel is not a side column but a **bottom sheet** that slides
up when a field is focused or the tooltip "?" is tapped.

### 2.3 Layers

- **Data layer** — `TaxApiClient` (thin fetch wrapper around the 4 endpoints).
- **State layer** — `useTaxAssistant` reducer/context (Section 6).
- **Presentation layer** — components (Section 3).
- **Knowledge layer** — `forms.json` field metadata is *not* fetched directly by
  the SPA; it is surfaced through `/build` (which already returns the active
  forms) and a future read-only `/tax/{year}/form/{key}/fields` endpoint for
  field-level tooltip metadata (see Section 9, additive).

---

## 3. Component hierarchy

```
DeclarationV2View                      (root, gated on FEATURES.tax_engine_v2)
├── AssistantTopBar
│   ├── YearSelector
│   ├── LanguageSelector            (de/tr/en → setLang)
│   └── ProgressMeter               (field_completeness_percent)
├── AssistantLayout                 (2-col desktop / stacked mobile)
│   ├── MainColumn
│   │   ├── InterviewStep           (questionnaire mode)
│   │   │   ├── QuestionCard
│   │   │   │   ├── QuestionPrompt
│   │   │   │   ├── AnswerInput      (boolean/choice/number/text/date)
│   │   │   │   └── FieldTooltip ("?")
│   │   │   └── StepNav (Zurück / Weiter)
│   │   ├── FormReview              (review/edit detected forms after interview)
│   │   │   └── FormSectionCard[]   (one per active form/instance)
│   │   │       └── FieldRow[]
│   │   │           ├── FieldLabel + FieldTooltip
│   │   │           ├── FieldInput
│   │   │           └── ConfidenceWarning (conditional)
│   │   └── OptimizationBanner[]     (suggestions from /build)
│   └── HelpPanel                    (desktop sticky / mobile bottom-sheet)
│       ├── HelpHeader (field label + Zeile)
│       ├── HelpDescription
│       ├── HelpWhy
│       ├── HelpExample
│       ├── MissingDocumentAssistant
│       │   ├── DocChecklistItem[]   (required documents)
│       │   └── DocUploadButton[]    (reuses existing upload endpoint)
│       ├── HelpValidationRule
│       └── WhatIsThisButton         ("Was ist das?" → AI explain, DE/TR/EN)
├── DocumentTray                     (uploaded docs + OCR status — reuses existing)
└── AssistantFooter (Save draft / nav)
```

Shared primitives (new, small): `Tooltip`, `BottomSheet`, `Badge`,
`LangText` (renders the right language string), `Spinner`.

---

## 4. The 8 features — detailed spec

### 4.1 Smart Tooltips
- Trigger: hover (desktop) / tap on "?" (mobile/keyboard). Dismiss on blur/esc.
- Content (per field): **Beschreibung**, **Beispielwert**, **Häufige Fehler**,
  **Verwandte Belege**.
- Data source: `helpTextDe` (description) and `prefillSource` (related doc) exist
  today in `forms.json`. **Beispielwert** and **Häufige Fehler** require two new
  *optional* field properties — `example` and `commonMistakes` — added to
  `forms.json` (additive, Section 9). Until present, the tooltip shows
  description + related document only and hides the empty rows.
- A11y: `role="tooltip"`, `aria-describedby` links input → tooltip; focusable;
  Esc closes.

### 4.2 Right-side Help Panel
- Opens on field focus; reflects the **currently focused** field.
- Sections: Beschreibung · Warum dieses Feld? · Beispielwerte · Benötigte
  Belege (+Upload) · Validierungsregel.
- Desktop: sticky right column. Mobile: `BottomSheet` (swipe-down to close).
- Empty-state when no field focused: short "Wählen Sie ein Feld…" hint.

### 4.3 AI "What is this?" assistant
- Button in the help panel + inline next to complex fields.
- Returns a **simple** explanation in **all three** languages (DE/TR/EN).
- Backend: a new read-only, flag-gated endpoint
  `POST /tax/explain` (Section 9) that wraps the existing AI knowledge / chat
  infrastructure, with caching to control cost (target ≤ €0.01/explain).
  StBerG-safe wording. Falls back to `helpTextDe` if AI is unavailable.

### 4.4 German / Turkish / English support
- All UI chrome via `tr(de, en, tr)` + `getLang()`.
- Field labels stay **German** (official Bezeichnung) but get a localized
  sub-label/explanation from the explain endpoint (cached) for TR/EN users.
- Language selector persists to `localStorage` (existing pattern).

### 4.5 Missing Document Assistant
- Per focused field and as a global checklist: list **required documents** from
  `/build` → `missing_documents` and per-rule `requiredEvidence`.
- Each item: name, short example/description, **Upload** button (reuses the
  existing document upload endpoint and OCR pipeline — no new write path here),
  and a status chip (fehlt / hochgeladen / erkannt).
- A "Dokument-Beispiel" link shows what the document looks like.

### 4.6 Confidence warnings
- Source: `confidence` per form (`hoch|mittel|niedrig`) and
  `form_detection_confidence` / `confidence_score` (0..1) from detect/build.
- Rule: if a form/value confidence is below threshold (default **0.8**, i.e.
  `mittel`/`niedrig`), show an inline amber notice: *"Bitte diesen Wert prüfen."*
  (TR: "Lütfen bu değeri kontrol edin." EN: "Please verify this value.")
- Never blocks progress; advisory only. Aggregated count shown in the top bar.

### 4.7 Accessibility
- Full keyboard nav (logical tab order, visible focus ring, Enter/Space activate,
  arrow keys in choice groups).
- ARIA: `aria-live="polite"` for validation/confidence messages; `role` on
  tooltip/dialog/bottom-sheet; `aria-invalid` on errored inputs; labels bound
  via `htmlFor`/`id`.
- Screen-reader: question prompt announced on step change; help panel is a
  labelled region.
- Targets ≥ 48px; inputs ≥ 16px (no iOS zoom); WCAG AA contrast.

### 4.8 Mobile responsive design
- Single column; help panel → bottom sheet; sticky footer nav; one question per
  screen. Breakpoint reuse: `window.innerWidth < 768` (existing `isMobile`).

---

## 5. API integration map

| Component / action | Endpoint | Method | Notes |
|---|---|---|---|
| Enter assistant / detect forms from profile | `/tax/{year}/detect` | POST | after a short profile pre-step |
| Start interview | `/tax/{year}/questionnaire/start` | POST | returns first `node` |
| Answer → next question | `/tax/{year}/questionnaire/next` | POST | client holds `answers` + `current_node` |
| Build full declaration (review screen) | `/tax/{year}/build` | POST | forms + validation + missing_docs + suggestions |
| "Was ist das?" | `/tax/explain` (future, §9) | POST | DE/TR/EN explanation, cached |
| Field tooltip metadata | `/tax/{year}/form/{key}/fields` (future, §9) | GET | read-only field list w/ example/mistakes |
| Document upload | existing upload endpoint | POST | reused, unchanged |

All v2 calls send `Authorization: Bearer <atx_token>` (auth required) and expect
JSON. On `404` the client treats v2 as disabled and hides the view.

---

## 6. Data contracts

Plain-JS shapes (documented as TS-style interfaces for clarity; no TS in code).

### 6.1 Requests
```ts
// /detect and /build
interface ProfileRequest {
  profile: Record<string, boolean | number | string>;   // situation flags
  documents?: string[];                                   // uploaded doc types
  existing_data?: Record<string, Record<string, unknown>>;// {form:{field:value}}
}
// /questionnaire/start
interface StartRequest { profile?: Record<string, unknown>; }
// /questionnaire/next
interface NextRequest {
  answers: Record<string, unknown>;   // nodeKey -> answer
  current_node?: string;
  answer?: unknown;
}
```

### 6.2 Responses (exact shapes returned by Phase 1)
```ts
interface FormRef { formKey: string; formCode: string; instances: number;
                    reason: string; confidence: "hoch"|"mittel"|"niedrig"; }

interface DetectResponse {
  year: number; tax_year: string | null;
  required_forms: FormRef[];
  missing_forms: { formKey: string; reason: string }[];
  confidence_score: number;          // 0..1
}

interface QNode { nodeKey: string; question: string; answerType: string;
                  options: string[]; }
interface StartResponse { year:number; node: QNode; answers:{}; done:false; }
interface NextResponse  { year:number; node: QNode | null;
                          answers: Record<string,unknown>;
                          activated_forms: string[]; done: boolean; }

interface BuildResponse {
  year: number; tax_year: string | null;
  forms: FormRef[];
  missing_forms: { formKey:string; reason:string }[];
  form_detection_confidence: number;
  interview: { questions: { nodeKey:string; question:string;
                            answerType:string; answer:unknown }[];
               prefill_sources: string[]; activated_forms: string[]; };
  validation: { errors: VMsg[]; warnings: VMsg[]; ok: boolean };
  missing_documents: string[];
  optimization_suggestions: { ruleKey:string; name:string; category:string;
                              suggestion:string; legalBasis:string }[];
  field_completeness_percent: number;  // 0..100
}
interface VMsg { form:string; field:string; message:string; }
```

### 6.3 Future contracts (Section 9, not built yet)
```ts
// POST /tax/explain
interface ExplainRequest { form:string; field:string; lang?:"de"|"tr"|"en"; }
interface ExplainResponse { de:string; tr:string; en:string; cached:boolean; }
// GET /tax/{year}/form/{key}/fields  (field metadata for tooltips)
interface FieldMeta { fieldKey:string; zeile:string; label:string;
  dataType:string; required:boolean; helpTextDe:string;
  example?:string; commonMistakes?:string[]; relatedDocuments?:string[];
  validation:{type:string;constraint:string;message:string}; }
```

---

## 7. State management design

No Redux. A single `useReducer` in `DeclarationV2View`, shared via React context
so the help panel and inputs read the same state.

```ts
interface AssistantState {
  year: number;
  lang: "de" | "tr" | "en";
  phase: "profile" | "interview" | "review";
  // interview
  node: QNode | null;
  answers: Record<string, unknown>;
  // detection/build snapshot
  forms: FormRef[];
  missingDocuments: string[];
  suggestions: Suggestion[];
  validation: { errors: VMsg[]; warnings: VMsg[]; ok: boolean };
  completeness: number;
  // ui
  focusedField: { form: string; field: string } | null;
  helpOpen: boolean;        // mobile bottom-sheet
  loading: boolean;
  error: string | null;
}
```

Actions: `SET_LANG`, `SET_YEAR`, `START_OK`, `NEXT_OK`, `BUILD_OK`,
`FOCUS_FIELD`, `BLUR_FIELD`, `TOGGLE_HELP`, `SET_LOADING`, `SET_ERROR`,
`SET_ANSWER`. Side effects (fetch) live in async action creators that dispatch
`SET_LOADING` → call `TaxApiClient` → dispatch the `*_OK`/`SET_ERROR`.
Interview answers are the client's source of truth (server is stateless), so
`answers` + `node` fully describe resume state; persisted to `localStorage`
under `atx_v2_session_{year}` for crash-safe resume.

---

## 8. Text wireframes

### 8.1 Interview step (desktop)
```
Steuer-Assistent 2024            Sprache: [DE ▾]      Fortschritt ████░ 60%
─────────────────────────────────────────────────────────────────────────
 Frage 7 von ~20

   Haben Sie 2024 Kinder gehabt, für die Sie Kindergeld    │ HELP
   bekommen haben?                                         │ ───────────────
                                                           │ Warum?
   (•) Ja, Anzahl: [ 2 ]      ( ) Nein         [ ? ]       │ Für jedes Kind
                                                           │ erstellen wir eine
   ▸ intelligenter Helfer: "Was ist das?"                  │ Anlage Kind.
                                                           │ Beispiel: 2
   ⚠ Bitte Steuer-ID jedes Kindes bereithalten.            │ Belege: Steuer-ID
                                                           │ des Kindes [Upload]
 ◀ Zurück                              Entwurf gespeichert      Weiter ▶
```

### 8.2 Review screen (desktop) — after interview
```
Ihre Formulare (automatisch ermittelt)            Vollständigkeit 78%
─────────────────────────────────────────────────────────────────────────
 ✓ Hauptvordruck (ESt 1 A)            Konfidenz: hoch
 ✓ Anlage N                           Konfidenz: hoch
 ✓ Anlage Kind  ×2                    Konfidenz: hoch
 ⚠ Anlage V                           Konfidenz: mittel  → "Bitte prüfen"
─────────────────────────────────────────────────────────────────────────
 💡 Vorschlag: Entfernungspauschale erfassen (0,30 €/km).         [ Mehr ]
 💡 Vorschlag: Handwerker-Lohnanteil §35a (20%, max 1.200 €).     [ Mehr ]
─────────────────────────────────────────────────────────────────────────
 Fehlende Belege:  • Lohnsteuerbescheinigung [Upload]
                   • Steuer-ID der Kinder    [Upload]
```

### 8.3 Mobile (interview + bottom sheet)
```
┌─────────────────────────┐
│ Assistent 2024   60% ███ │
│                          │
│ Hatten Sie Kinder?       │
│ (•) Ja  Anzahl [2]       │
│ ( ) Nein          [ ? ]  │
│                          │
│ [ Weiter ▶ ]             │
└─────────────────────────┘
        ▲ tap "?"
┌─────────────────────────┐   ← bottom sheet slides up
│ Anzahl Kinder        ✕   │
│ Warum: je Kind eine      │
│ Anlage Kind.             │
│ Beispiel: 2              │
│ Beleg: Steuer-ID [⬆]     │
│ [ Was ist das? DE/TR/EN ]│
└─────────────────────────┘
```

---

## 9. Required additive changes (when implementation starts — NOT now)

These are additive and flag-gated; listed so the build phase is unambiguous:

1. **`window.FEATURES.tax_engine_v2`** — add to `config.features_js_literal()`
   payload, resolved from `tax_engine_v2_enabled()`. (One additive line; SPA gate.)
2. **`forms.json` optional field props** — `example`, `commonMistakes`,
   `relatedDocuments` (purely additive; existing loaders ignore unknown keys).
3. **`GET /tax/{year}/form/{key}/fields`** — read-only field metadata endpoint
   (flag-gated) for tooltips/help panel.
4. **`POST /tax/explain`** — read-only, flag-gated AI explanation (DE/TR/EN),
   cached, StBerG-safe, fallback to `helpTextDe`.
5. **Persistence** — saving reviewed values reuses the *existing* declaration
   save path; no new write endpoint in v2 (kept read-only until a later phase).

No production code is modified by THIS document.

---

## 10. Implementation roadmap (relative weeks, dependency-ordered)

- **W1 — Shell & gate.** Add `tax_engine_v2` to FEATURES; `DeclarationV2View`
  skeleton + `TaxApiClient` + reducer/context; top bar + language selector.
  Acceptance: view appears only when flag on; calls `/detect` and renders forms.
- **W2 — Interview.** `InterviewStep`, `/questionnaire/start`+`/next`,
  localStorage resume, progress meter. Acceptance: full interview for 5 personas.
- **W3 — Review + validation + confidence.** `FormReview`, `ConfidenceWarning`,
  `/build` integration, optimization banners. Acceptance: 22-persona walk-through.
- **W4 — Help system.** `forms.json` example/mistakes fields + `/form/.../fields`
  endpoint; `FieldTooltip` + `HelpPanel` (+ mobile bottom sheet).
- **W5 — Missing-doc assistant + uploads.** Wire existing upload endpoint;
  doc checklist + status chips.
- **W6 — AI "Was ist das?".** `/tax/explain` endpoint + button + caching;
  TR/EN sub-labels.
- **W7 — Accessibility + mobile polish.** Keyboard, ARIA, screen-reader pass;
  responsive QA; contrast audit.
- **W8 — Localization completeness + UAT.** DE/TR/EN string sweep; first-time
  taxpayer usability test; bug fixes.

---

## 11. Definition of Done

- View renders only when `FEATURES.tax_engine_v2` is true; invisible/inert otherwise.
- All copy localized DE/TR/EN; language switch instant, persisted.
- Every field has a tooltip; focus opens the help panel with description, why,
  example, required documents (+upload), and validation rule.
- "Was ist das?" returns DE/TR/EN explanations; falls back gracefully offline.
- Confidence < 0.8 shows a non-blocking "Bitte prüfen" notice.
- Missing-document checklist reflects `/build`; uploads use the existing pipeline.
- Keyboard-only and screen-reader complete the full flow; WCAG AA contrast;
  48px targets / 16px inputs; works at 360px width.
- No existing endpoint/view/workflow changed; backend flag still default OFF;
  all new endpoints flag-gated and covered by tests before UI enablement.
- A first-time taxpayer completes a declaration end-to-end in usability testing
  without external help.
```
