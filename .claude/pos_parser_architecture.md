# Enterprise POS Receipt Parser — Architecture

**Hedef:** Tüm Almanya POS sistemlerinden (Orderbird, SumUp, Gastrofix, Lightspeed, Vectron, Ready2Order, Tillhub, HelloCash, POSmatic, Casio, Epson, unknown) gelen Z-Bon, X-Bon, daily summary, cash export ve fiscal printer çıktılarını **tek bir API üzerinden** parse edip AutoTax/EÜR/DATEV/Lexoffice/WISO formatlarına dönüştüren motor.

**Pozisyon:** Mevcut `autotax/kasse.py` (DSFinV-K + Speedy basit parser) bunun **Phase 1**'i. Bu doc tam mimari hedefi tanımlar; Phase 2+ ile bu seviyeye çıkar.

**Stack adaptasyonu:**
- Prompt'taki **Next.js + Supabase + OpenAI** → AutoTax'ta **FastAPI + PostgreSQL + Anthropic Claude** karşılığı (paralel mimari). Multi-tenant + RLS Supabase'de hazır gelir; bizde FastAPI middleware `_require_*_access` zaten benzer model.

---

## 1. SYSTEM ARCHITECTURE

```
┌────────────────────────────────────────────────────────────────────┐
│                       CUSTOMER UPLOAD LAYER                         │
│  Browser (drag-drop) · Mobile camera · Email-in · Watcher agent     │
│  Webhook from POS · Scheduled cron pulls                            │
└──────────────────────────┬─────────────────────────────────────────┘
                           │ multipart/form-data, base64 JSON, ZIP
                           ▼
┌────────────────────────────────────────────────────────────────────┐
│                      INGEST GATEWAY (FastAPI)                       │
│  · Auth (JWT) + tenant resolve (user_id → company_id)               │
│  · sha256 idempotency check                                         │
│  · MIME sniff + magic-byte validation                               │
│  · Size cap (50 MB image, 10 MB CSV)                                │
│  · Per-tenant rate limit (Pro 100/day, AI Steuer 1000/day)          │
│  · Audit log entry (upload.received)                                │
└──────────────────────────┬─────────────────────────────────────────┘
                           │ S3-compatible storage put (R2)
                           ▼
┌────────────────────────────────────────────────────────────────────┐
│                    PARSING ORCHESTRATOR (Celery)                    │
│  Async queue. Each upload → ParseJob row → workers pick up.         │
│                                                                     │
│  Stage 1: Document Classification                                   │
│  Stage 2: POS Vendor Detection                                      │
│  Stage 3: Layout Recognition + Template Match                       │
│  Stage 4: Field Extraction (per vendor parser OR Claude vision)     │
│  Stage 5: VAT Validation                                            │
│  Stage 6: Accounting Normalization                                  │
│  Stage 7: German Tax Compliance Check                               │
│                                                                     │
│  Each stage emits events to monitoring + writes to parse_attempts.  │
└──────────────────────────┬─────────────────────────────────────────┘
                           │
        ┌──────────────────┼──────────────────┐
        ▼                  ▼                  ▼
┌─────────────┐  ┌──────────────────┐  ┌────────────────────┐
│ LOCAL OCR    │  │ AI VISION        │  │ TEMPLATE ENGINE    │
│ Tesseract +  │  │ Claude Sonnet/   │  │ pg_trgm + learning │
│ OCR.space    │  │ Opus for handw.  │  │ store              │
└──────┬───────┘  └────────┬─────────┘  └──────────┬─────────┘
       └───────────────────┴────────────────────────┘
                           │
                           ▼
┌────────────────────────────────────────────────────────────────────┐
│                      OUTPUT ASSEMBLER                               │
│  · Strict JSON schema validation                                    │
│  · Confidence scoring                                               │
│  · Warning aggregation                                              │
│  · Persist to parsed_documents + line items                         │
└──────────────────────────┬─────────────────────────────────────────┘
                           │
        ┌──────────────────┼──────────────────┐
        ▼                  ▼                  ▼
┌─────────────┐  ┌──────────────────┐  ┌────────────────────┐
│ AUTOTAX     │  │ EXPORTERS        │  │ FRAUD/REVIEW QUEUE │
│ EÜR + UStVA  │  │ DATEV / Lexoff / │  │ Suspicious docs →  │
│ feeds       │  │ WISO / Taxfix    │  │ human review       │
└─────────────┘  └──────────────────┘  └────────────────────┘
```

### Component split

| Layer | Tech (mevcut) | Tech (Next.js variant) |
|---|---|---|
| API Gateway | FastAPI + slowapi + JWT | Next.js API routes + middleware |
| Queue | Celery + Redis (Phase 3 roadmap) | Inngest / Supabase Functions |
| Storage | Cloudflare R2 (boto3) | Supabase Storage |
| DB | PostgreSQL on Railway | Supabase Postgres + RLS |
| AI | Anthropic Claude API direct (httpx) | OpenAI SDK / Anthropic SDK |
| Local OCR | tesseract + OCR.space | Same (containerized) |
| Frontend | React via CDN + Babel | Next.js 14 App Router |

---

## 2. DATABASE SCHEMA

### Core tenancy
```sql
CREATE TABLE companies (
  id            BIGSERIAL PRIMARY KEY,
  user_id       BIGINT REFERENCES users(id),
  legal_name    TEXT NOT NULL,
  address       TEXT,
  tax_number    TEXT,                 -- Steuernummer (per Land format)
  vat_id        TEXT,                 -- USt-IdNr. DE+9 digits
  kassennummer  TEXT,                 -- DSFinV-K Kassenidentifikationsnummer
  tse_signature_public_key TEXT,      -- Hash of TSE Public Key
  industry      TEXT,                 -- "gastro", "friseur", "imbiss", "retail"
  created_at    TIMESTAMPTZ DEFAULT now(),
  UNIQUE (user_id, vat_id)
);
CREATE INDEX ix_companies_user ON companies(user_id);
```

### Upload + parse lifecycle
```sql
CREATE TABLE document_uploads (
  id            BIGSERIAL PRIMARY KEY,
  user_id       BIGINT REFERENCES users(id),
  company_id    BIGINT REFERENCES companies(id),
  file_name     TEXT,
  file_sha256   CHAR(64) NOT NULL,
  file_size     BIGINT,
  mime_type     TEXT,
  storage_path  TEXT,                 -- R2 key
  source        TEXT,                 -- "browser", "email", "watcher", "api"
  uploaded_at   TIMESTAMPTZ DEFAULT now(),
  UNIQUE (user_id, file_sha256)
);

CREATE TYPE parse_status AS ENUM (
  'queued','running','classified','extracted',
  'normalized','validated','ready','failed','review_required'
);

CREATE TABLE parse_jobs (
  id            BIGSERIAL PRIMARY KEY,
  upload_id     BIGINT REFERENCES document_uploads(id) ON DELETE CASCADE,
  status        parse_status NOT NULL DEFAULT 'queued',
  pos_vendor    TEXT,                 -- detected vendor or null
  document_type TEXT,                 -- "z_bon", "x_bon", "daily_summary", "receipt", "monthly", "fiscal_export"
  template_id   BIGINT REFERENCES templates(id) NULL,
  started_at    TIMESTAMPTZ,
  finished_at   TIMESTAMPTZ,
  total_attempts INT DEFAULT 0,
  error_message TEXT,
  confidence    NUMERIC(5,4),
  pages         INT,
  reviewer_user_id BIGINT NULL,
  reviewer_decision TEXT NULL          -- "accepted","corrected","rejected"
);
CREATE INDEX ix_parse_jobs_status ON parse_jobs(status);
```

### Per-stage attempts (auditing AI calls)
```sql
CREATE TABLE parse_attempts (
  id            BIGSERIAL PRIMARY KEY,
  parse_job_id  BIGINT REFERENCES parse_jobs(id) ON DELETE CASCADE,
  stage         TEXT NOT NULL,        -- "classify","vendor_detect","layout","extract","vat","normalize","compliance"
  method        TEXT NOT NULL,        -- "regex_vendor","template:abc","claude_haiku","claude_sonnet","claude_opus","tesseract","ocr_space"
  prompt_hash   CHAR(64) NULL,        -- For prompt caching analytics
  input_tokens  INT,
  output_tokens INT,
  cost_usd      NUMERIC(8,5),
  duration_ms   INT,
  confidence    NUMERIC(5,4),
  result_jsonb  JSONB,
  error_text    TEXT,
  attempted_at  TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX ix_parse_attempts_job ON parse_attempts(parse_job_id);
```

### Structured output
```sql
CREATE TABLE parsed_documents (
  id            BIGSERIAL PRIMARY KEY,
  parse_job_id  BIGINT REFERENCES parse_jobs(id) UNIQUE,
  user_id       BIGINT REFERENCES users(id),
  company_id    BIGINT REFERENCES companies(id),
  document_type TEXT,                 -- z_bon, x_bon, ...
  pos_vendor    TEXT,                 -- orderbird, sumup, ...
  date          DATE,                 -- Belegdatum / Z-Datum
  time          TIME,
  fiscal_period TEXT,                 -- e.g. "2025-05" or quarter
  gross_revenue NUMERIC(12,2),
  net_revenue   NUMERIC(12,2),
  vat_total     NUMERIC(12,2),
  discount_total NUMERIC(12,2),
  refund_total  NUMERIC(12,2),
  cancellation_total NUMERIC(12,2),
  tip_total     NUMERIC(12,2),
  confidence    NUMERIC(5,4),
  raw_text      TEXT,                 -- OCR snapshot for re-process
  warnings      JSONB,                -- ["missing_vat","total_mismatch",...]
  metadata      JSONB,                -- vendor-specific extras (TSE sig, KassenID...)
  parsed_at     TIMESTAMPTZ DEFAULT now(),
  CONSTRAINT vat_plausible CHECK (vat_total >= 0 AND vat_total <= gross_revenue * 0.21)
);
CREATE INDEX ix_parsed_user_date ON parsed_documents(user_id, date);
CREATE INDEX ix_parsed_company_date ON parsed_documents(company_id, date);
```

### Granular breakdown
```sql
-- One row per VAT rate appearing in the document
CREATE TABLE parsed_vat_rows (
  id            BIGSERIAL PRIMARY KEY,
  parsed_doc_id BIGINT REFERENCES parsed_documents(id) ON DELETE CASCADE,
  vat_rate      NUMERIC(5,2),         -- 0, 7, 19 (or 5/16 for COVID years)
  net           NUMERIC(12,2),
  vat           NUMERIC(12,2),
  gross         NUMERIC(12,2)
);

-- Payment method split (cash, EC, kreditkarte, gutschein, online)
CREATE TABLE parsed_payments (
  id            BIGSERIAL PRIMARY KEY,
  parsed_doc_id BIGINT REFERENCES parsed_documents(id) ON DELETE CASCADE,
  method        TEXT,                 -- "bar","ec","kreditkarte","paypal","gutschein","online","delivery_app","stripe"
  amount        NUMERIC(12,2),
  count         INT NULL              -- e.g. "12 Barzahlungen"
);

-- Category lines (Döner, Getränke, Pizza, Friseur, Kosmetik, etc.)
CREATE TABLE parsed_categories (
  id            BIGSERIAL PRIMARY KEY,
  parsed_doc_id BIGINT REFERENCES parsed_documents(id) ON DELETE CASCADE,
  category_key  TEXT,                 -- normalized: "doener", "getraenke", "pizza", "friseur_haarschnitt"
  category_label TEXT,                -- original text on receipt
  net           NUMERIC(12,2),
  vat_rate      NUMERIC(5,2),
  count         INT NULL,
  CONSTRAINT category_known CHECK (category_key ~ '^[a-z_0-9]+$')
);
```

### Template learning
```sql
CREATE TABLE templates (
  id            BIGSERIAL PRIMARY KEY,
  company_id    BIGINT REFERENCES companies(id),
  pos_vendor    TEXT,
  document_type TEXT,
  signature     TEXT,                 -- normalized "fingerprint" used for matching
  fingerprint_keywords JSONB,         -- top-N keywords for pg_trgm matching
  field_map     JSONB,                -- {"net":"^Gesamt netto\s+([\d,.]+)$", ...}
  layout_anchors JSONB,               -- coordinate-based for image layout
  success_count INT DEFAULT 0,
  fail_count    INT DEFAULT 0,
  last_used_at  TIMESTAMPTZ,
  created_by_user_id BIGINT REFERENCES users(id),
  manually_verified BOOLEAN DEFAULT FALSE,
  is_active     BOOLEAN DEFAULT TRUE,
  UNIQUE (company_id, pos_vendor, document_type, signature)
);
CREATE INDEX ix_templates_vendor ON templates(pos_vendor, document_type);
```

### Corrections & learning (self-improvement)
```sql
CREATE TABLE corrections (
  id            BIGSERIAL PRIMARY KEY,
  parsed_doc_id BIGINT REFERENCES parsed_documents(id),
  user_id       BIGINT REFERENCES users(id),
  field_path    TEXT,                 -- "vat_total" or "vat_rows[0].net"
  old_value     TEXT,
  new_value     TEXT,
  reason        TEXT,
  template_updated_id BIGINT REFERENCES templates(id) NULL,
  created_at    TIMESTAMPTZ DEFAULT now()
);
```

### Fraud / duplicate detection
```sql
CREATE TABLE duplicate_checks (
  id            BIGSERIAL PRIMARY KEY,
  parsed_doc_id BIGINT REFERENCES parsed_documents(id),
  duplicate_of  BIGINT REFERENCES parsed_documents(id),
  reason        TEXT,                 -- "exact_hash","fuzzy_total_date","sequential_z_bon_repeated"
  similarity    NUMERIC(5,4)
);

CREATE TABLE compliance_alerts (
  id            BIGSERIAL PRIMARY KEY,
  parsed_doc_id BIGINT REFERENCES parsed_documents(id),
  rule_key      TEXT,                 -- "vat_mismatch", "z_bon_gap", "tse_missing", "no_kassennummer"
  severity      TEXT,                 -- "info","warn","block"
  message       TEXT,
  resolved_at   TIMESTAMPTZ
);
```

### Exports for downstream
```sql
CREATE TABLE export_runs (
  id            BIGSERIAL PRIMARY KEY,
  user_id       BIGINT REFERENCES users(id),
  format        TEXT,                 -- "datev","lexoffice","wiso","taxfix","ustva","eur"
  period_start  DATE,
  period_end    DATE,
  document_ids  BIGINT[],
  file_path     TEXT,                 -- generated file
  created_at    TIMESTAMPTZ
);
```

**Indexes summary**
- `parsed_documents(user_id, date)` — dashboard queries
- `parsed_documents(company_id, date)` — per-company report
- `parse_jobs(status)` — worker queue
- `templates(pos_vendor, document_type)` — template match
- `document_uploads(user_id, file_sha256)` — dedup

---

## 3. AI PIPELINE (7-Stage Detailed)

### Stage 1 — Document Classification
**Goal:** "Is this a Z-Bon? X-Bon? Daily summary? Individual receipt? Fiscal export?"

**Method (fastest first):**
1. **Filename heuristic** (~5ms): `z_bon`, `x_bericht`, `tagesabschluss`, `monatsbericht` etc. → confidence 0.5
2. **Regex on OCR/text** (~50ms): German keywords (`Z-Bericht`, `Tagesabschluss`, `Z-Nummer`, `Z-Zähler`) → 0.8
3. **Claude Haiku one-shot** (~800ms, $0.0008): if regex fails or confidence < 0.7

```python
CLASSIFY_PROMPT = """Classify this German POS document. Reply with JSON only:
{"document_type":"z_bon|x_bon|daily_summary|monthly_summary|single_receipt|fiscal_export|unknown",
 "confidence":0.0-1.0,
 "key_signals":["..."]}"""
```

**Output:** `document_type` + confidence → persisted to `parse_jobs.document_type`.

### Stage 2 — POS Vendor Detection
**Goal:** Identify the originating POS (Orderbird, SumUp, ...) — drives Stage 4 template choice.

**Method:**
1. **Logo + brand string match** in OCR text:
   - `orderbird` → "Orderbird" or "Bird Pay" header strings
   - `sumup` → "SumUp" logo + Berlin address
   - `gastrofix` → "Gastrofix" footer
   - `vectron` → "VECTRON" header
   - `ready2order` → "ready2order" footer
   - `tillhub` → "tillhub" or "tillhub GmbH"
   - `hellocash` → "HelloCash" / "hellocash.eu"
   - `posmatic` → "posmatic"
   - `casio` → "CASIO" + serial format
   - `epson` → "TM-T88" or "Epson" + fiscal sig

2. **Layout signature** (image only): pixel-density histogram + font-size cluster → matches stored `templates.signature`.

3. **Fallback `pos_vendor = "unknown"`** → falls into generic Claude vision extractor.

### Stage 3 — Layout Recognition & Template Match
**Goal:** "Do I have a memorized template for this company × POS × document_type?"

```python
def find_template(company_id, pos_vendor, document_type, current_signature):
    # 1. Exact match
    t = db.query(Template).filter(
        Template.company_id == company_id,
        Template.pos_vendor == pos_vendor,
        Template.document_type == document_type,
        Template.is_active == True,
    ).first()
    if t and t.signature == current_signature:
        return t, 1.0  # exact match
    # 2. pg_trgm similarity on signature
    sim_query = db.execute(text("""
        SELECT id, similarity(signature, :sig) AS s FROM templates
        WHERE pos_vendor=:v AND document_type=:d AND is_active
        ORDER BY s DESC LIMIT 1
    """), {"sig": current_signature, "v": pos_vendor, "d": document_type}).first()
    if sim_query and sim_query.s > 0.75:
        return db.query(Template).get(sim_query.id), float(sim_query.s)
    return None, 0.0
```

**If template found (≥0.75 similarity):** Run Stage 4 with template regex map → cheap, fast, deterministic.
**If not:** Stage 4 falls back to Claude vision.

### Stage 4 — Field Extraction (Per-vendor or Vision)
**Path A — Template-based (deterministic, ~50ms, $0):**
```python
def extract_via_template(template, ocr_text):
    out = {}
    for field, regex in template.field_map.items():
        m = re.search(regex, ocr_text)
        if m:
            out[field] = m.group(1)
    return out
```

**Path B — Claude Vision (when no template / confidence low):**
```python
EXTRACT_PROMPT = """You are a German POS receipt parser.
Extract EVERY field as strict JSON. Return ONLY the JSON object.

Schema:
{
  "business": {
    "company_name", "address", "tax_number", "vat_id",
    "kassennummer", "tse_serial", "tse_signature"
  },
  "document_type": "z_bon|x_bon|daily_summary|single_receipt|...",
  "date": "YYYY-MM-DD",
  "time": "HH:MM:SS",
  "z_nummer": <int or null>,
  "fiscal_period": "YYYY-MM" or null,
  "sales": {
    "gross_revenue", "net_revenue",
    "discount_total", "refund_total",
    "cancellation_total", "tip_total"
  },
  "vat": {
    "by_rate": [
      {"rate": 19, "net": 0, "vat": 0, "gross": 0},
      {"rate": 7, "net": 0, "vat": 0, "gross": 0}
    ]
  },
  "payments": [
    {"method": "bar|ec|kreditkarte|...", "amount": 0, "count": null}
  ],
  "categories": [
    {"key": "doener|getraenke|pizza|friseur_haarschnitt|...", "label": "...", "net": 0, "vat_rate": 19, "count": null}
  ],
  "warnings": [],
  "confidence_score": 0.0
}

Rules:
- Money in EUR. Round 2 decimals. Don't invent values.
- If a field is not visible, use null (don't fabricate).
- VAT rate 7%: usually Lebensmittel zum Mitnehmen / Backwaren.
- VAT rate 19%: most Dienstleistungen + Restaurant verzehr vor Ort.
- For Friseurleistungen: 19% (Haarschnitt, Färben). Kosmetik: 19%.
- Compute confidence based on text legibility and field completeness."""
```

**Model selection:**
- Typed text receipts (Orderbird/SumUp/Gastrofix typical) → Haiku 4.5 ($0.005-0.01)
- Handwritten / scanned thermal → Sonnet 4.6 ($0.05-0.10)
- Critical / business-grade verification → Opus 4.7 ($0.40)

Env override: `AI_VISION_TABLE_MODEL` per upload (we already wire this in iter O).

### Stage 5 — VAT Validation
```python
def validate_vat(extracted):
    warnings = []
    by_rate = extracted["vat"]["by_rate"]
    # Each row: net*rate/100 ≈ vat (allow ±0.02 rounding)
    for r in by_rate:
        expected = round(r["net"] * r["rate"] / 100, 2)
        if abs(expected - r["vat"]) > 0.02:
            warnings.append(f"VAT mismatch rate={r['rate']}: expected {expected}, got {r['vat']}")
        # net + vat ≈ gross
        if abs(r["net"] + r["vat"] - r["gross"]) > 0.02:
            warnings.append(f"net+vat≠gross at rate {r['rate']}")
    # Sum of vat by_rate ≈ vat_total in document
    sum_vat = sum(r["vat"] for r in by_rate)
    if abs(sum_vat - extracted["sales"].get("vat_total", sum_vat)) > 0.05:
        warnings.append("vat_total mismatch across rows")
    # Sum of gross ≈ gross_revenue
    sum_gross = sum(r["gross"] for r in by_rate)
    if abs(sum_gross - extracted["sales"]["gross_revenue"]) > 0.10:
        warnings.append("gross_revenue does not match sum of vat rows")
    return warnings
```

### Stage 6 — Accounting Normalization
Map extracted category labels to internal taxonomy:
```python
CATEGORY_MAP = {
    # gastro
    "döner": "doener", "doner": "doener", "kebab": "doener", "kebap": "doener",
    "getränke": "getraenke", "drinks": "getraenke",
    "pizza": "pizza", "pizzen": "pizza",
    "imbiss": "imbiss", "snack": "imbiss",
    # friseur
    "haarschnitt": "friseur_haarschnitt", "schneiden": "friseur_haarschnitt",
    "färben": "friseur_faerben", "tönung": "friseur_faerben",
    "rasur": "friseur_rasur",
    # cosmetics
    "maniküre": "kosmetik_manikuere", "pediküre": "kosmetik_pedikuere",
    "wimpern": "kosmetik_wimpern",
    # general
    "dienstleistung": "dienstleistung",
    "ware": "lebensmittel",
}
```

Map to **DATEV Konto** (skontoplan SKR03 or SKR04):
```python
DATEV_KONTO = {
    "doener": "8400",      # 19% Verzehr vor Ort
    "doener_lieferung": "8300",  # 7% Mitnahme / Lieferung
    "getraenke": "8400",
    "friseur_haarschnitt": "8400",
    "kosmetik_manikuere": "8400",
    # Sonstige
    "_default_19": "8400",
    "_default_7": "8300",
    "_default_0": "8200",
}
```

### Stage 7 — German Tax Compliance Checks
Rules:
| Check | Severity | Action |
|---|---|---|
| Missing TSE signature on Z-Bon (post-2020) | **block** | Cannot submit to Finanzamt |
| Missing Kassennummer | warn | Manual entry possible |
| Z-Nummer gap (last Z was N, current is N+2) | **warn** | Missing Z-Bon |
| Duplicate Z-Bon (same Z-Nummer twice) | block | Reject second |
| VAT rate not in {0, 7, 19} | warn (or block if 5/16 in non-COVID year) | Verify |
| Date outside current fiscal year | warn | Manual confirm |
| Gross > €25.000/day single Z-Bon | info | Plausibility |
| No payment method breakdown | warn | Cash audit risk |

---

## 4. OCR STRATEGY

### Three-tier fallback (cost optimization)

```
1. Local tesseract (free, fast, ~70-80% on printed thermal)
   ↓ if confidence < 0.7
2. OCR.space API (cheap, ~80-85% accuracy, ~$0.001)
   ↓ if vendor/template unmatched OR confidence < 0.8
3. Claude Vision (Haiku → Sonnet → Opus escalation, $0.005-$0.40)
```

### Pre-processing pipeline (PIL)
```python
def preprocess_for_ocr(img_bytes: bytes) -> bytes:
    img = Image.open(io.BytesIO(img_bytes))
    # 1. Convert to grayscale
    img = img.convert("L")
    # 2. Auto-contrast (boost faded thermal print)
    img = ImageOps.autocontrast(img, cutoff=2)
    # 3. Deskew (correct rotation)
    img = deskew_image(img)
    # 4. Denoise (median filter)
    img = img.filter(ImageFilter.MedianFilter(size=3))
    # 5. Resize: thermal receipts often <600px wide, upscale to 2400px
    if img.width < 2000:
        scale = 2400 / img.width
        img = img.resize((int(img.width*scale), int(img.height*scale)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()
```

### Vendor-specific OCR tuning
- **Orderbird PDF** → direct PDF text extract (pypdf), no OCR needed
- **SumUp email export** → CSV parse, no OCR
- **Thermal receipt photo** → full preprocessing + Sonnet/Opus
- **Watcher scanner output** → already preprocessed, Haiku suffices

---

## 5. TEMPLATE LEARNING SYSTEM

### Lifecycle
```
First upload (cold start):
    → Stage 4 = Claude Vision
    → User confirms or corrects
    → Generate template:
        - signature = hash of layout structure
        - field_map = regex patterns derived from confirmed values
        - layout_anchors = bbox coordinates of key labels
    → Insert into templates table

Second upload of same kind:
    → Stage 3 matches template (similarity ≥0.85)
    → Stage 4 uses template regex (cheap, fast)
    → If extraction confidence drops: re-run Claude, mark template fail_count++
    → After 3 fails, deactivate + flag for regeneration

After 10 confirmed uses:
    → Mark template manually_verified = false (still auto-update)
    → Admin can promote to manually_verified for sharing across tenants
```

### Signature generation
```python
def compute_signature(ocr_text: str) -> str:
    # Extract structural fingerprint, not content
    lines = ocr_text.split("\n")
    structure = []
    for line in lines[:30]:  # First 30 lines is enough
        # Replace digits with "N", letters with "A", special with "S"
        sig = re.sub(r"\d", "N", line)
        sig = re.sub(r"[a-zA-Z]", "A", sig)
        sig = re.sub(r"\s+", " ", sig).strip()
        structure.append(sig[:40])
    return hashlib.sha256("\n".join(structure).encode()).hexdigest()[:16]
```

### Cross-tenant template sharing
- `templates.created_by_user_id` + `manually_verified=true` → admin can flag as **global template**
- Global templates fall through `find_template` after per-company match
- Privacy: only **field_map regex patterns** shared, no PII

---

## 6. CONFIDENCE SCORING MODEL

### Per-stage confidence aggregation
```python
def aggregate_confidence(stages: dict) -> float:
    # Weighted geometric mean
    weights = {
        "classify":     0.10,
        "vendor":       0.10,
        "layout":       0.10,
        "extract":      0.30,
        "vat_check":    0.20,
        "normalize":    0.10,
        "compliance":   0.10,
    }
    score = 1.0
    for stage, w in weights.items():
        s = stages.get(stage, {}).get("confidence", 0.5)
        score *= s ** w
    return round(score, 4)
```

### Confidence-based routing
| Score | Routing |
|---|---|
| ≥ 0.90 | Auto-import to user's books, no review |
| 0.70 – 0.90 | Auto-import + "please verify" badge |
| 0.50 – 0.70 | Review queue (frontend modal) |
| < 0.50 | Reject + ask user to re-upload better photo |

---

## 7. FRAUD DETECTION IDEAS

### Duplicate detection
1. **Exact hash** (file_sha256): trivially duplicate upload
2. **Fuzzy match** by (company_id, date, gross_revenue): same total on same day → likely duplicate
3. **Z-Nummer collision**: same Z-Bon # twice in 24h → reject second
4. **OCR text similarity**: pg_trgm on `raw_text` > 0.95 → flag

### Anomaly rules
```python
ANOMALY_RULES = [
    # (rule_key, severity, predicate)
    ("z_bon_gap", "warn",
     lambda d: d.z_nummer and last_z_nummer(d.company_id) is not None
               and d.z_nummer - last_z_nummer(d.company_id) > 1),
    ("revenue_spike", "info",
     lambda d: d.gross_revenue > 3 * avg_revenue_28d(d.company_id)),
    ("revenue_drop", "info",
     lambda d: d.gross_revenue < 0.3 * avg_revenue_28d(d.company_id)),
    ("cash_only_high_revenue", "warn",
     lambda d: cash_share(d) > 0.95 and d.gross_revenue > 1000),
    ("vat_zero_with_19_categories", "block",
     lambda d: d.vat_total == 0 and has_19_rate_categories(d)),
    ("future_date", "block",
     lambda d: d.date > date.today()),
    ("very_old_date", "warn",
     lambda d: (date.today() - d.date).days > 365),
    ("tse_missing_post_2020", "block",
     lambda d: not d.metadata.get("tse_signature") and d.date.year >= 2020),
]
```

### ML-based scoring (Phase 4+)
- Train on `corrections` table — if many users correct same field on same vendor, the parser is systematically biased
- Anomaly score per user: time-series of revenue, payment-method ratio, category mix

---

## 8. AUTO-TAX INTEGRATION

### Downstream consumers and their needs

| Consumer | Required Fields | Format |
|---|---|---|
| **AutoTax EÜR** | gross, net, vat by rate, category | Direct DB insert into CashEntry |
| **UStVA** (monthly) | Sum vat_by_rate per period | XML to ELSTER |
| **DATEV-CSV** | One row per Buchung: Umsatz, S/H, Konto, BU, Datum, Text, USt | Existing /export/datev — extend with kasse rows |
| **Lexoffice** | API push: invoice, vat, payment | `/lexoffice/sync` endpoint |
| **WISO** | XLSX with prescribed columns | `/export/wiso-xlsx` |
| **Taxfix** | JSON with their schema | `/export/taxfix-json` |

### Push to AutoTax flow
```
parsed_documents.status = 'ready'
   ↓ on user click "in Buchhaltung übernehmen" (or auto for confidence ≥0.90)
For each VAT row → INSERT INTO cash_entries (
   user_id, date=parsed.date, amount=row.gross,
   category=mapped_category, vat_rate=row.rate, vat_amount=row.vat,
   description="Z-Bon #N · Tagesabschluss",
   source="pos_parser:{vendor}:{job_id}"
)
For each payment → metadata on cash_entries (payment_method)
For each category → fine-grained cash_entries (one per category)
Audit: pos_parser.import_to_books
```

---

## 9. EXAMPLE CODE ARCHITECTURE

### File tree
```
autotax/
├── kasse.py                  # Current basic parser (Phase 1 — keep)
├── pos/
│   ├── __init__.py
│   ├── pipeline.py           # Orchestrator (run all 7 stages)
│   ├── classify.py           # Stage 1
│   ├── vendor_detect.py      # Stage 2
│   ├── template_engine.py    # Stage 3 + learning
│   ├── extractors/
│   │   ├── __init__.py
│   │   ├── orderbird.py
│   │   ├── sumup.py
│   │   ├── gastrofix.py
│   │   ├── vectron.py
│   │   ├── lightspeed.py
│   │   ├── ready2order.py
│   │   ├── tillhub.py
│   │   ├── hellocash.py
│   │   ├── posmatic.py
│   │   ├── casio.py
│   │   ├── epson.py
│   │   └── claude_vision.py  # Generic fallback
│   ├── vat_validator.py      # Stage 5
│   ├── normalize.py          # Stage 6 (CATEGORY_MAP + DATEV_KONTO)
│   ├── compliance.py         # Stage 7
│   ├── confidence.py         # Aggregation
│   ├── duplicate_check.py
│   └── ingest_to_books.py    # Push to cash_entries
└── pos_models.py             # SQLAlchemy models (companies, parse_jobs, ...)
```

### Pipeline orchestrator skeleton
```python
# autotax/pos/pipeline.py
import logging
from autotax.pos import classify, vendor_detect, template_engine, vat_validator
from autotax.pos import normalize, compliance, confidence
from autotax.pos.extractors import claude_vision, EXTRACTORS_BY_VENDOR

logger = logging.getLogger("autotax.pos.pipeline")


async def run_pipeline(parse_job_id: int, upload, db):
    job = db.query(ParseJob).get(parse_job_id)
    job.status = "running"
    job.started_at = datetime.now(timezone.utc)
    db.commit()
    stages_meta = {}

    try:
        # Stage 1
        c = classify.classify_document(upload.raw_text or "", upload.file_name)
        stages_meta["classify"] = c
        job.document_type = c["document_type"]

        # Stage 2
        v = vendor_detect.detect_vendor(upload)
        stages_meta["vendor"] = v
        job.pos_vendor = v["vendor"]

        # Stage 3
        t, t_confidence = template_engine.find_template(
            upload.company_id, v["vendor"], c["document_type"], v["signature"]
        )
        stages_meta["layout"] = {"template_id": t.id if t else None, "confidence": t_confidence}

        # Stage 4
        if t and t_confidence >= 0.85:
            extracted = template_engine.extract_via_template(t, upload.raw_text)
        elif v["vendor"] != "unknown" and v["vendor"] in EXTRACTORS_BY_VENDOR:
            extracted = await EXTRACTORS_BY_VENDOR[v["vendor"]].extract(upload)
        else:
            extracted = await claude_vision.extract(upload)
        stages_meta["extract"] = {"confidence": extracted.get("confidence_score", 0.7)}

        # Stage 5
        warnings = vat_validator.validate(extracted)
        stages_meta["vat_check"] = {"confidence": 0.9 if not warnings else 0.6}
        extracted.setdefault("warnings", []).extend(warnings)

        # Stage 6
        extracted = normalize.normalize_categories_and_konto(extracted)
        stages_meta["normalize"] = {"confidence": 0.95}

        # Stage 7
        alerts = compliance.check(extracted, upload)
        for a in alerts:
            db.add(ComplianceAlert(parsed_doc_id=None,  # set after persist
                                   rule_key=a["rule"],
                                   severity=a["severity"],
                                   message=a["message"]))
        stages_meta["compliance"] = {"confidence": 1.0 if not any(a["severity"]=="block" for a in alerts) else 0.0}

        # Aggregate confidence
        final_conf = confidence.aggregate_confidence(stages_meta)
        job.confidence = final_conf

        # Persist
        doc = persist_parsed_doc(extracted, upload, job, db)

        # Route based on confidence
        if final_conf >= 0.90:
            job.status = "ready"
            ingest_to_books.push(doc, db)
        elif final_conf >= 0.50:
            job.status = "review_required"
        else:
            job.status = "failed"

    except Exception as e:
        logger.exception("Pipeline failed for job %s", parse_job_id)
        job.status = "failed"
        job.error_message = str(e)[:500]
    finally:
        job.finished_at = datetime.now(timezone.utc)
        db.commit()
```

### Per-vendor extractor pattern
```python
# autotax/pos/extractors/sumup.py
"""SumUp POS — daily summary email export parser.

SumUp emails arrive with Subject "Daily summary [date]" containing
CSV attachment. Headers: Date,Net,VAT,Gross,Payment Method,Status.
"""
import csv
import io
from autotax.pos.extractors.base import BaseExtractor


class SumUpExtractor(BaseExtractor):
    vendor = "sumup"

    @classmethod
    async def can_handle(cls, upload) -> float:
        text = (upload.raw_text or "").lower()
        if "sumup" in text and ("daily summary" in text or "tagesübersicht" in text):
            return 0.95
        return 0.0

    @classmethod
    async def extract(cls, upload) -> dict:
        # Parse CSV
        reader = csv.DictReader(io.StringIO(upload.raw_text))
        sales_gross = 0.0
        sales_vat = 0.0
        by_method: dict[str, float] = {}
        for row in reader:
            gross = float(row.get("Gross", 0) or 0)
            vat = float(row.get("VAT", 0) or 0)
            method = (row.get("Payment Method") or "").lower()
            sales_gross += gross
            sales_vat += vat
            by_method[method] = by_method.get(method, 0) + gross
        return {
            "business": {"company_name": "SumUp Customer"},
            "document_type": "daily_summary",
            "date": _detect_date(upload.raw_text),
            "sales": {
                "gross_revenue": round(sales_gross, 2),
                "net_revenue": round(sales_gross - sales_vat, 2),
            },
            "vat": {"by_rate": [
                {"rate": 19, "net": round(sales_gross - sales_vat, 2),
                 "vat": round(sales_vat, 2), "gross": round(sales_gross, 2)}
            ]},
            "payments": [{"method": m, "amount": round(a, 2)} for m, a in by_method.items()],
            "categories": [],  # SumUp summary doesn't break down by category
            "warnings": [],
            "confidence_score": 0.92,  # CSV is structured, high trust
        }
```

### Claude vision generic fallback
```python
# autotax/pos/extractors/claude_vision.py
"""Generic Claude vision parser for unknown POS systems."""
import os, json, base64
import httpx

from autotax.pos.extractors.base import BaseExtractor


GENERIC_POS_PROMPT = """You are a German POS receipt parser ...
[full prompt from Section 4 above]"""


class ClaudeVisionExtractor(BaseExtractor):
    vendor = "unknown"

    @classmethod
    async def extract(cls, upload) -> dict:
        model = (
            os.getenv("AI_POS_VISION_MODEL")  # opt-in upgrade
            or os.getenv("AI_VISION_TABLE_MODEL")
            or "claude-sonnet-4-6"  # default for POS — handwriting common
        )
        # Read image bytes from storage
        img_bytes = read_from_r2(upload.storage_path)
        # Preprocess (see Section 4)
        img_bytes = preprocess_for_ocr(img_bytes)
        # Call Claude
        payload = {
            "model": model, "max_tokens": 4096,
            "messages": [{
                "role": "user", "content": [
                    {"type": "image", "source": {
                        "type": "base64", "media_type": "image/jpeg",
                        "data": base64.b64encode(img_bytes).decode(),
                    }},
                    {"type": "text", "text": GENERIC_POS_PROMPT},
                ],
            }],
        }
        async with httpx.AsyncClient(timeout=90) as c:
            r = await c.post(
                "https://api.anthropic.com/v1/messages", json=payload,
                headers={"x-api-key": os.environ["ANTHROPIC_API_KEY"],
                         "anthropic-version": "2023-06-01"},
            )
            text = "".join(b.get("text", "") for b in r.json().get("content", []))
        return json.loads(text)
```

---

## 10. PRODUCTION-READY IMPLEMENTATION PLAN

### Phase 1 — Foundation (1 hafta)
**Mevcut `kasse.py` üzerine inşa et:**
- [ ] `pos/` package iskeleti + base classes
- [ ] DB tabloları: `parse_jobs`, `parsed_documents`, `parsed_vat_rows`, `parsed_payments`, `parsed_categories`, `templates`, `corrections`
- [ ] Orchestrator skeleton (`pipeline.py`)
- [ ] Generic Claude vision extractor (re-use iter O fixes)
- [ ] Endpoint: `POST /pos/parse` (multipart upload → ParseJob)
- [ ] Endpoint: `GET /pos/jobs/{id}` (status polling)

### Phase 2 — First 3 vendors (1 hafta)
- [ ] `extractors/sumup.py` (CSV email export — easiest)
- [ ] `extractors/orderbird.py` (PDF Z-Bon)
- [ ] `extractors/gastrofix.py` (PDF + CSV)
- [ ] VAT validator + compliance checks
- [ ] Confidence aggregation

### Phase 3 — Template learning (1 hafta)
- [ ] Signature generation
- [ ] Template match in Stage 3
- [ ] Correction UI (frontend modal)
- [ ] Correction → template regeneration logic

### Phase 4 — Remaining vendors + fraud (1.5 hafta)
- [ ] `vectron.py`, `lightspeed.py`, `ready2order.py`, `tillhub.py`, `hellocash.py`, `posmatic.py`, `casio.py`, `epson.py`
- [ ] Duplicate detection (sha256 + fuzzy)
- [ ] Anomaly rules
- [ ] Review queue UI

### Phase 5 — Exports (1 hafta)
- [ ] DATEV CSV (extend mevcut `/export/datev`)
- [ ] UStVA XML (ELSTER format)
- [ ] Lexoffice push (API key per user)
- [ ] WISO XLSX
- [ ] Taxfix JSON

### Phase 6 — Polish & Pricing (3-4 gün)
- [ ] Pricing tiers (Kasse = Pro+ ✅ already)
- [ ] Admin dashboard for cost / hit-rate
- [ ] Marketing: "Wir unterstützen 11 deutsche POS-Systeme"

**Toplam: 6-7 hafta solo dev → production-ready** (vs 6-9 ay ekiple ticari ürün).

---

## 11. COST + MARGINS (1000 documents/month projection)

| Workload | Count | Per-doc cost | Total |
|---|---|---|---|
| CSV / direct text (no AI) | 600 | $0 | $0 |
| Haiku vision (typed PDF) | 250 | $0.005 | $1.25 |
| Sonnet vision (handwritten) | 100 | $0.10 | $10 |
| Opus vision (verification) | 50 | $0.40 | $20 |
| **Total AI cost / month** | 1000 | — | **$31.25** |

Cache hit (Q&A asked questions) reduces ~%30 of Sonnet/Opus calls in steady state.

**Revenue:** Pro plan €39 × 50 customers = €1.950/month. AI cost = €30 = 1.5% gross margin impact. **Healthy.**

---

## 12. NEXT.JS + SUPABASE VARIANT (Eğer Ayrı Servis Olarak)

Eğer bunu **ayrı bir mikroservis** olarak yaparsan (AutoTax'tan bağımsız):

```
pos-parser-service/
├── app/
│   ├── api/
│   │   ├── parse/route.ts         # POST upload
│   │   └── jobs/[id]/route.ts     # GET status
│   ├── (admin)/dashboard/page.tsx
│   └── layout.tsx
├── lib/
│   ├── supabase.ts                # Supabase client
│   ├── claude.ts                  # Anthropic SDK
│   └── pipeline/                  # 7-stage modules (TypeScript port)
├── workers/
│   └── parse-worker.ts            # Background worker (Inngest)
└── supabase/migrations/           # SQL files (same schema as above)
```

**RLS policies** on all tables: `auth.uid() = user_id` ensures multi-tenant isolation.

**Edge functions** for stages 1-2 (low latency); heavy AI calls go to long-running worker via Inngest.

---

## 13. REFERENCES & RELATED DOCS

- `.claude/kasse_plan.md` — Phase 1 MVP (mevcut)
- `.claude/tax_intake_architecture.md` — Steuererklärung intake (related)
- `.claude/architecture.md` — overall AutoTax system
- `autotax/kasse.py` — current generic CSV parser
- `autotax/ai_ocr.py` — current vision OCR (iter O fixed)

**Document status:** Living spec. Update when phase implemented.
**Last update:** 2026-05-30
**Next milestone:** Phase 1 (foundation) — target 2026-06-07
