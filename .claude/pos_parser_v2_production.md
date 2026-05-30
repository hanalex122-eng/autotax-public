# POS Parser v2 + AI Business Analysis — Production Plan

**User direktif (2026-05-30):** "oyuncak yapmiyoruz kaliteli yapalim müsteriye verdigimizde iş yapsın, yarım bırakma, 1 ay sürse bile yap"

**Hedef:** Almanya küçük işletmeler (Döner / Berber / Restaurant / Café / Bäckerei / Retail) için **gerçek müşteriye verildiğinde sorunsuz çalışan** POS parser + işletme analiz katmanı.

**Bu doc:** Mevcut `kasse.py` üzerine inşa edilen **practical MVP** (enterprise complexity yok, ama eksiksiz). Sister doc `pos_parser_architecture.md` enterprise-level vision; bu doc shipping plan.

**Süre:** 4 hafta solo dev. Her hafta sonu canlı testçi.

---

## 1. KAPSAM (NE YAPACAĞIZ — NE YAPMAYACAĞIZ)

### YAPILACAK ✅
- PDF / image / OCR text input
- 6 gerçek hedef sektör: Döner, Friseur, Restaurant, Café, Bäckerei, Einzelhandel
- Akıllı extraction: template-free (her Z-Bon farklı görünebilir)
- Self-learning: kullanıcı düzeltirse aynı işletmenin sonraki Z-Bon'una uygulanır
- **AI Business Analysis** (daily/weekly/monthly + XYZ + ABC + insights)
- Almanca + Türkçe çıktı
- Strict JSON + confidence skoru
- Mevcut AutoTax cash_entries tablosuna otomatik aktarım

### YAPILMAYACAK ❌ (Phase 2'de)
- Real-time POS API integration (sadece batch upload)
- TSE imza doğrulama (vendor responsibility)
- 11 vendor-spezifischer parser (Phase 1: generic AI yeter)
- ELSTER ERiC direct submission (PDF/XML export yeter)
- Multi-user team accounts

---

## 2. INPUT PIPELINE (Production-grade)

### 2.1 Upload
```
Frontend (KasseView) → POST /pos/parse multipart
  ↓
Validate:
  - MIME: pdf / image (png/jpg/webp) / csv / xlsx / txt
  - Magic bytes match extension
  - Size ≤ 25MB
  - sha256 idempotency (duplicate → return cached job)
  ↓
R2 storage put
  ↓
Create ParseJob row (status=queued)
  ↓
Return job_id + ETA
```

### 2.2 Processing (sync veya async)
**MVP: sync** (1 sayfa ~30 sn). Phase 2: Celery async.

```python
def parse_pos_document(file_bytes, mime_type, user_id, company_id):
    # 1. Convert to images (PDF→PNG via pypdf2.extract_images veya pdf2image)
    images = extract_pages_as_images(file_bytes, mime_type)
    # 2. OCR-first (cheap quality check)
    ocr_text = run_local_ocr(images[0])
    # 3. If text-receipt PDF detected → text extract direkt (no AI)
    if is_typed_pdf(file_bytes, ocr_text):
        return parse_typed_pdf(ocr_text)
    # 4. Else AI vision extraction
    return ai_extract_pos(images, ocr_text, company_id)
```

### 2.3 OCR Tier
```
Tier 1: Local tesseract + preprocessing (free)
  ↓ confidence < 0.7 (kelime sayısı / sayfa, lookup table)
Tier 2: OCR.space API ($0.001/sayfa)
  ↓ still uncertain OR vendor unknown
Tier 3: Claude Vision direkt image (Sonnet $0.05-0.10)
  ↓ critical / verification
Tier 4: Claude Opus ($0.30-0.50)
```

**Default env:** `AI_POS_PARSER_MODEL=claude-sonnet-4-6` (handwriting iyi). Per-tenant override mümkün (`Pro = Sonnet, AI Steuer = Opus`).

---

## 3. AI EXTRACTION PROMPT (Strict JSON)

```python
POS_PARSE_PROMPT = """You are a German small-business POS receipt parser.

The image shows a cash register report (Kassenbericht / Z-Bon / X-Bon /
Tagesabschluss / Bon) from a Döner shop, barber, restaurant, café, bakery,
or small retail store.

Extract data and return STRICT JSON ONLY. No markdown. No commentary.

{
  "business_name": "string or null",
  "business_address": "string or null",
  "tax_number": "Steuernummer or null",
  "vat_id": "DE + 9 digits or null",
  "kassennummer": "string or null",
  "tse_serial": "string or null",
  "date": "YYYY-MM-DD",
  "time": "HH:MM or null",
  "report_type": "z_bon|x_bon|tagesabschluss|monatsabschluss|einzelbon|unknown",
  "z_nummer": <int or null>,
  "gross_revenue": <number, total brutto with VAT>,
  "net_revenue": <number, total netto>,
  "vat_total": <number>,
  "vat_rates": [
    {"rate": 19, "net": 0, "vat": 0, "gross": 0},
    {"rate": 7, "net": 0, "vat": 0, "gross": 0}
  ],
  "cash": <number, Barzahlung total>,
  "card": <number, EC/Kreditkarte total>,
  "online": <number or 0, Online/PayPal/Stripe>,
  "delivery": <number or 0, Lieferando/Uber Eats>,
  "tips": <number or 0, Trinkgeld>,
  "discounts": <number or 0>,
  "refunds": <number or 0>,
  "cancellations": <number or 0>,
  "categories": [
    {"label": "Döner", "key": "doener", "net": 0, "vat_rate": 19, "count": null}
  ],
  "warnings": [],
  "confidence": 0.0
}

Rules:
- Money: EUR, 2 decimals. Use null for missing fields. NEVER invent.
- VAT rates: typically 19% (Verzehr vor Ort, services) or 7% (Mitnahme, food retail).
- For Döner: zum Mitnehmen=7%, vor Ort=19%. If unclear, default 19%.
- For Friseur: always 19%.
- date format strict YYYY-MM-DD.
- categories.key normalize:
  doener / pizza / burger / getraenke / bier / wein / kaffee /
  kuchen / brot / gebaeck / friseur_haarschnitt / friseur_faerben /
  rasur / maniküre -> manikuere / kosmetik / lebensmittel /
  dienstleistung / sonstiges
- warnings: ["missing_vat", "z_nummer_unclear", "handwritten_uncertain",
            "duplicate_suspicion", "total_mismatch"]
- confidence 0.0-1.0:
  - 0.95+: typed receipt all fields clear
  - 0.75-0.94: minor uncertainty
  - 0.50-0.74: handwriting partly readable
  - <0.50: needs human review

Output ONLY the JSON. No code fences. No "Here is the JSON" prefix."""
```

**Post-processing validation:**
```python
def validate_extraction(result):
    errors = []
    # 1. Money math
    if result["vat_rates"]:
        for r in result["vat_rates"]:
            expected_vat = round(r["net"] * r["rate"] / 100, 2)
            if abs(expected_vat - r["vat"]) > 0.02:
                errors.append(f"VAT calc mismatch at rate {r['rate']}")
            if abs(r["net"] + r["vat"] - r["gross"]) > 0.02:
                errors.append(f"net+vat≠gross at rate {r['rate']}")
        sum_gross = sum(r["gross"] for r in result["vat_rates"])
        if abs(sum_gross - result["gross_revenue"]) > 0.10:
            errors.append("vat_rates sum doesn't match gross_revenue")
    # 2. Payment sum
    pay_total = result["cash"] + result["card"] + result["online"] + result["delivery"]
    if abs(pay_total - result["gross_revenue"]) > 0.10:
        errors.append("payment methods don't sum to gross")
    # 3. Date sanity
    if result["date"]:
        d = parse_date(result["date"])
        if d > date.today() or d.year < 2018:
            errors.append("date out of range")
    return errors
```

---

## 4. SELF-LEARNING (Business-spezifische templates)

### 4.1 Correction lifecycle
```
User uploads Z-Bon → AI extracts → User reviews → Corrects 2 fields:
  - "business_name": "AI: 'Doner Star' → User: 'Döner Star Saarbrücken'"
  - "vat_total": "AI: 12.50 → User: 13.20"
    ↓
SAVE correction:
  - corrections table: field_path, old, new, parsed_doc_id
  - IF same business_name appears 3+ times:
    - Generate signature from latest receipt OCR
    - Extract regex patterns from corrected fields
    - Save as business-specific template
    ↓
Next Z-Bon from same business:
  - Signature match → use template hints (e.g. "business_name is always X")
  - AI prompt includes: "User confirmed company name is 'Döner Star Saarbrücken' for this business."
  - Cheaper Haiku call sufficient because of context
```

### 4.2 Template storage
```sql
CREATE TABLE pos_templates (
  id            BIGSERIAL PRIMARY KEY,
  user_id       BIGINT REFERENCES users(id),
  company_signature  TEXT,        -- hash of layout + business_name
  business_name TEXT,
  business_address TEXT,
  default_vat_rate NUMERIC(5,2),  -- mostly 19 for Friseur, 7 for Bäckerei
  category_overrides JSONB,        -- {"doener_pommes": {"rate": 19, "key": "doener"}}
  fingerprint_keywords JSONB,      -- ["Döner Star", "Saarbrücker Str."] for matching
  uses_count    INT DEFAULT 0,
  success_count INT DEFAULT 0,
  last_used_at  TIMESTAMPTZ,
  created_at    TIMESTAMPTZ DEFAULT now(),
  UNIQUE (user_id, company_signature)
);
CREATE INDEX ix_pos_templates_user ON pos_templates(user_id);
CREATE INDEX ix_pos_templates_sig ON pos_templates(company_signature);
```

### 4.3 Template matching
```python
def find_business_template(user_id, ocr_text):
    # 1. Try keyword match (cheap)
    candidates = db.query(POSTemplate).filter(
        POSTemplate.user_id == user_id
    ).all()
    best = None
    best_score = 0
    for t in candidates:
        kws = t.fingerprint_keywords or []
        hits = sum(1 for kw in kws if kw.lower() in ocr_text.lower())
        score = hits / max(len(kws), 1)
        if score > best_score and score > 0.5:
            best_score = score
            best = t
    return best, best_score
```

---

## 5. AI BUSINESS ANALYSIS LAYER

User direktif: daily/weekly/monthly + XYZ + ABC + AI insights.

Bu **POS parse sonrasında otomatik koşan analiz motoru**. Her gece cron + on-demand.

### 5.1 Endpoint set
```
GET  /pos/analysis/daily?date=2025-05-30
GET  /pos/analysis/weekly?week=2025-W22
GET  /pos/analysis/monthly?month=2025-05
GET  /pos/analysis/xyz?period=last_30_days
GET  /pos/analysis/abc?period=last_90_days
GET  /pos/analysis/insights?period=last_7_days&lang=de|tr
```

### 5.2 Data foundation
```sql
-- Materialized view, refreshed nightly
CREATE MATERIALIZED VIEW pos_daily_summary AS
SELECT
  pd.user_id,
  pd.company_id,
  pd.date,
  SUM(pd.gross_revenue)        AS gross_total,
  SUM(pd.net_revenue)          AS net_total,
  SUM(pd.vat_total)            AS vat_total,
  SUM(COALESCE(pp.amount, 0)) FILTER (WHERE pp.method='bar')         AS cash_total,
  SUM(COALESCE(pp.amount, 0)) FILTER (WHERE pp.method IN ('ec','kreditkarte')) AS card_total,
  SUM(COALESCE(pp.amount, 0)) FILTER (WHERE pp.method IN ('online','paypal','stripe')) AS online_total,
  SUM(COALESCE(pp.amount, 0)) FILTER (WHERE pp.method LIKE 'delivery%') AS delivery_total,
  COUNT(DISTINCT pd.id)        AS doc_count
FROM parsed_documents pd
LEFT JOIN parsed_payments pp ON pp.parsed_doc_id = pd.id
GROUP BY pd.user_id, pd.company_id, pd.date;

CREATE INDEX ix_pos_daily_summary_user_date ON pos_daily_summary(user_id, date DESC);
```

### 5.3 Daily Analysis
```python
def daily_analysis(user_id: int, target_date: date) -> dict:
    today = get_summary(user_id, target_date)
    yesterday = get_summary(user_id, target_date - timedelta(days=1))
    last_week_same_day = get_summary(user_id, target_date - timedelta(days=7))

    if not today:
        return {"error": "no_data"}

    diff_pct_yesterday = ((today.gross_total - yesterday.gross_total)
                          / yesterday.gross_total * 100) if yesterday else 0
    diff_pct_lastweek = ((today.gross_total - last_week_same_day.gross_total)
                         / last_week_same_day.gross_total * 100) if last_week_same_day else 0
    cash_ratio = today.cash_total / max(today.gross_total, 0.01)
    card_ratio = today.card_total / max(today.gross_total, 0.01)

    top_cats = db.query(POSCategory.category_key,
                         func.sum(POSCategory.net).label("net"))\
                 .filter(POSCategory.parsed_doc_id.in_(today.doc_ids))\
                 .group_by(POSCategory.category_key)\
                 .order_by(text("net DESC")).limit(5).all()

    warnings = []
    if today.gross_total > 3 * (avg_last_28d(user_id)):
        warnings.append({"key": "revenue_spike",
                         "message_de": "Heute >3x Durchschnitt — bitte Zahlen prüfen"})
    if cash_ratio > 0.90 and today.gross_total > 1000:
        warnings.append({"key": "cash_only_high",
                         "message_de": "Sehr hoher Baranteil — Kassenprüfungsrisiko"})

    return {
        "date": target_date.isoformat(),
        "revenue_today": today.gross_total,
        "revenue_yesterday": yesterday.gross_total if yesterday else None,
        "diff_vs_yesterday_pct": round(diff_pct_yesterday, 1),
        "diff_vs_lastweek_pct": round(diff_pct_lastweek, 1),
        "cash_ratio": round(cash_ratio, 3),
        "card_ratio": round(card_ratio, 3),
        "vat_summary": {
            "total": today.vat_total,
            "rate_19": fetch_vat_at_rate(today, 19),
            "rate_7": fetch_vat_at_rate(today, 7),
        },
        "top_categories": [{"key": k, "net": float(n)} for k, n in top_cats],
        "warnings": warnings,
    }
```

### 5.4 Weekly Analysis
```python
def weekly_analysis(user_id, iso_year, iso_week):
    start, end = iso_week_range(iso_year, iso_week)
    days = get_summaries(user_id, start, end)  # 7 rows
    revenue_total = sum(d.gross_total for d in days)
    avg_daily = revenue_total / 7
    best = max(days, key=lambda d: d.gross_total)
    worst = min(days, key=lambda d: d.gross_total)
    # Growth rate vs previous week
    prev_start = start - timedelta(days=7)
    prev_days = get_summaries(user_id, prev_start, prev_start + timedelta(days=6))
    prev_total = sum(d.gross_total for d in prev_days)
    growth_pct = ((revenue_total - prev_total) / prev_total * 100) if prev_total else 0

    # Forecast: simple linear regression over last 28 days
    forecast_next_week = linear_forecast(user_id, periods=7)

    return {
        "week": f"{iso_year}-W{iso_week:02d}",
        "revenue_total": revenue_total,
        "avg_daily": avg_daily,
        "best_day": {"date": best.date.isoformat(), "revenue": best.gross_total,
                     "weekday": best.date.strftime("%A")},
        "worst_day": {"date": worst.date.isoformat(), "revenue": worst.gross_total,
                      "weekday": worst.date.strftime("%A")},
        "growth_vs_prev_week_pct": round(growth_pct, 1),
        "forecast_next_week_total": round(forecast_next_week, 2),
        "trend": "up" if growth_pct > 2 else "down" if growth_pct < -2 else "flat",
    }
```

### 5.5 Monthly Analysis
```python
def monthly_analysis(user_id, year, month):
    start = date(year, month, 1)
    end = start.replace(day=monthrange(year, month)[1])
    days = get_summaries(user_id, start, end)
    revenue_total = sum(d.gross_total for d in days)
    net_total = sum(d.net_total for d in days)
    vat_total = sum(d.vat_total for d in days)

    # EÜR-style profit: revenue - estimated expenses from invoices
    expenses = db.query(func.sum(Invoice.total_amount)).filter(
        Invoice.user_id == user_id,
        Invoice.invoice_type == "expense",
        Invoice.date.like(f"{year}-{month:02d}-%"),
        Invoice.is_deleted.is_(False),
    ).scalar() or 0

    profit_estimate = net_total - float(expenses)
    # VAT liability = vat_total minus Vorsteuer (from expenses)
    vorsteuer = db.query(func.sum(Invoice.vat_amount)).filter(
        Invoice.user_id == user_id,
        Invoice.invoice_type == "expense",
        Invoice.date.like(f"{year}-{month:02d}-%"),
        Invoice.is_deleted.is_(False),
    ).scalar() or 0
    vat_liability = vat_total - float(vorsteuer)

    # Comparable month (prev year)
    prev_month_total = get_revenue_total(user_id, year - 1, month)
    yoy_growth = ((revenue_total - prev_month_total) / prev_month_total * 100) if prev_month_total else None

    # Customer traffic ≈ document count
    doc_count = sum(d.doc_count for d in days)
    prev_doc_count = get_doc_count(user_id, year - 1, month)
    traffic_growth = ((doc_count - prev_doc_count) / prev_doc_count * 100) if prev_doc_count else None

    payment_dist = {
        "cash_pct": sum(d.cash_total for d in days) / max(revenue_total, 0.01) * 100,
        "card_pct": sum(d.card_total for d in days) / max(revenue_total, 0.01) * 100,
        "online_pct": sum(d.online_total for d in days) / max(revenue_total, 0.01) * 100,
        "delivery_pct": sum(d.delivery_total for d in days) / max(revenue_total, 0.01) * 100,
    }

    return {
        "month": f"{year}-{month:02d}",
        "revenue_total": revenue_total,
        "net_total": net_total,
        "expenses_total": float(expenses),
        "profit_estimate": round(profit_estimate, 2),
        "vat_total": vat_total,
        "vorsteuer_total": float(vorsteuer),
        "vat_liability": round(vat_liability, 2),
        "yoy_growth_pct": round(yoy_growth, 1) if yoy_growth is not None else None,
        "traffic_yoy_growth_pct": round(traffic_growth, 1) if traffic_growth is not None else None,
        "payment_distribution": {k: round(v, 1) for k, v in payment_dist.items()},
    }
```

### 5.6 XYZ Analysis (Performance tiers)
```python
def xyz_analysis(user_id, days_back=30):
    """X=best, Y=medium, Z=weak performers per category."""
    cutoff = date.today() - timedelta(days=days_back)
    rows = db.execute(text("""
        SELECT pc.category_key, SUM(pc.net) AS net, COUNT(*) AS n
        FROM parsed_categories pc
        JOIN parsed_documents pd ON pd.id = pc.parsed_doc_id
        WHERE pd.user_id = :uid AND pd.date >= :cutoff
        GROUP BY pc.category_key
        ORDER BY net DESC
    """), {"uid": user_id, "cutoff": cutoff}).fetchall()

    total = sum(r.net for r in rows)
    cumulative = 0
    enriched = []
    for r in rows:
        cumulative += r.net
        share_pct = r.net / total * 100 if total else 0
        cum_pct = cumulative / total * 100 if total else 0
        # Trend: last 7d vs 7-14d ago
        last_7 = sum_net_for_category(user_id, r.category_key, date.today() - timedelta(7), date.today())
        prev_7 = sum_net_for_category(user_id, r.category_key, date.today() - timedelta(14), date.today() - timedelta(8))
        trend_pct = ((last_7 - prev_7) / prev_7 * 100) if prev_7 else 0
        tier = "X" if share_pct >= 15 else "Y" if share_pct >= 5 else "Z"
        recommendation = _generate_xyz_recommendation(tier, r.category_key, share_pct, trend_pct)
        enriched.append({
            "category": r.category_key,
            "net": round(r.net, 2),
            "share_pct": round(share_pct, 1),
            "trend_pct": round(trend_pct, 1),
            "tier": tier,
            "recommendation_de": recommendation,
        })
    return {"period_days": days_back, "total_net": round(total, 2), "tiers": enriched}


def _generate_xyz_recommendation(tier, cat_key, share, trend):
    if tier == "X":
        return f"Top-Kategorie ({share}% Umsatz). Trend {trend:+.0f}%. Bestand sichern, Preis prüfen."
    if tier == "Y":
        return f"Mittlere Kategorie ({share}%). Trend {trend:+.0f}%. Kombi-Angebote testen."
    if trend > 5:
        return f"Schwach ({share}%) aber wachsend ({trend:+.0f}%). Marketing-Push erwägen."
    return f"Schwach ({share}%) und rückläufig ({trend:+.0f}%). Listen-Bereinigung erwägen."
```

### 5.7 ABC Analysis (Pareto 80/20)
```python
def abc_analysis(user_id, days_back=90):
    """A = top items making up 80% of revenue; B = next 15%; C = bottom 5%."""
    cutoff = date.today() - timedelta(days=days_back)
    rows = db.execute(text("""
        SELECT pc.category_key, SUM(pc.net) AS net
        FROM parsed_categories pc
        JOIN parsed_documents pd ON pd.id = pc.parsed_doc_id
        WHERE pd.user_id = :uid AND pd.date >= :cutoff
        GROUP BY pc.category_key
        ORDER BY net DESC
    """), {"uid": user_id, "cutoff": cutoff}).fetchall()

    total = sum(r.net for r in rows)
    cumulative = 0
    out = {"A": [], "B": [], "C": []}
    for r in rows:
        cumulative += r.net
        cum_pct = cumulative / total * 100 if total else 100
        tier = "A" if cum_pct <= 80 else "B" if cum_pct <= 95 else "C"
        out[tier].append({
            "category": r.category_key,
            "net": round(r.net, 2),
            "share_pct": round(r.net / total * 100, 1) if total else 0,
        })
    return {"period_days": days_back, "total_net": round(total, 2),
            "A_top80": out["A"], "B_mid": out["B"], "C_bottom": out["C"]}
```

### 5.8 AI Insights Generator (LLM-driven)
```python
INSIGHTS_PROMPT = """You are a business advisor for a German small-business owner
(Döner shop / barber / restaurant / café / bakery / retail).

Given the following data, generate 3-7 ACTIONABLE insights in {lang}.
Each insight: short title + 1-2 sentences + suggested action.

Data:
{data_json}

Output JSON only:
{{
  "insights": [
    {{
      "title": "Card payments rose 15%",
      "explanation": "...",
      "action": "Card terminal fees verhandeln, ggf. günstigeren Anbieter suchen.",
      "severity": "info|positive|warning|critical",
      "metric_change_pct": 15
    }}
  ]
}}

Rules:
- Be CONCRETE: use actual numbers from the data
- Be ACTIONABLE: every insight has a recommended action
- German for {lang}=de, Turkish for {lang}=tr
- 3-7 insights total (don't pad)"""


async def generate_ai_insights(user_id, period_days=7, lang="de"):
    # Aggregate context
    daily = daily_analysis(user_id, date.today())
    weekly = weekly_analysis(user_id, *date.today().isocalendar()[:2])
    xyz = xyz_analysis(user_id, days_back=period_days)
    abc = abc_analysis(user_id, days_back=period_days * 3)
    monthly = monthly_analysis(user_id, date.today().year, date.today().month)

    data = {
        "daily": daily, "weekly": weekly,
        "monthly": monthly, "xyz": xyz, "abc": abc,
    }
    # Cache layer check (same data hash → same insights)
    cache_key = hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()
    cached = check_cache(cache_key, lang)
    if cached:
        return cached

    prompt = INSIGHTS_PROMPT.format(data_json=json.dumps(data, indent=2),
                                    lang="Deutsch" if lang == "de" else "Türkçe")
    response = await call_claude(
        model="claude-sonnet-4-6", system="", user_msg=prompt, max_tokens=1500,
    )
    insights = json.loads(extract_json(response))
    save_cache(cache_key, lang, insights, ttl=3600 * 6)
    return insights
```

### 5.9 Dashboard cards (frontend)

```jsx
<DashboardCard
  title="Umsatz heute"
  value={daily.revenue_today}
  diff={daily.diff_vs_yesterday_pct}
  diffLabel="vs. gestern"
  color={daily.diff_vs_yesterday_pct >= 0 ? "green" : "red"}
/>

<DashboardCard
  title="Wochenumsatz"
  value={weekly.revenue_total}
  badge={`Bester Tag: ${weekly.best_day.weekday}`}
/>

<XYZTable tiers={xyz.tiers} />

<InsightsPanel insights={insights}>
  {insights.map(i => (
    <Insight
      severity={i.severity}
      title={i.title}
      action={i.action}
    />
  ))}
</InsightsPanel>
```

---

## 6. 4-WEEK ROADMAP (Production-grade)

### Hafta 1 — Foundation (5 gün)
- [ ] DB schema: `parsed_documents`, `parsed_vat_rows`, `parsed_payments`, `parsed_categories`, `pos_templates`, `corrections`
- [ ] R2 storage adapter (upload + retrieval)
- [ ] `autotax/pos/parser.py` core: OCR-first, Claude vision second, JSON validation third
- [ ] Strict JSON validation + post-processing (VAT math, payment sum, date sanity)
- [ ] Idempotency (sha256 dedup)
- [ ] Endpoint `POST /pos/parse`
- [ ] **TEST**: Berber'in 5 farklı Z-Bon'unu doğru parse et

### Hafta 2 — Self-Learning + Correction UI (5 gün)
- [ ] `pos_templates` matching (signature + keyword + pg_trgm)
- [ ] Correction frontend modal: extracted JSON gösterip user düzeltsin
- [ ] Correction → template auto-generation
- [ ] Same business 3+ correction → permanent template
- [ ] Endpoint `POST /pos/parse/{job_id}/correct`
- [ ] **TEST**: 1. Z-Bon AI, 2. Z-Bon AI + hint, 3. Z-Bon template (cheap)

### Hafta 3 — Business Analysis Layer (5 gün)
- [ ] Materialized view `pos_daily_summary` + nightly refresh job
- [ ] `pos/analysis.py`: daily, weekly, monthly fonksiyonları
- [ ] XYZ + ABC analizleri
- [ ] AI Insights endpoint with cache layer (re-use ai_knowledge.py)
- [ ] Endpoints: `/pos/analysis/{daily,weekly,monthly,xyz,abc,insights}`
- [ ] **TEST**: 30 günlük gerçek/sentetik veri ile her endpoint sonuç döndürür

### Hafta 4 — Dashboard UI + Production polish (5 gün)
- [ ] `POSAnalyticsView` React component
- [ ] Dashboard cards (Umsatz heute, Trend, Top kategoriler, Insights)
- [ ] XYZ tier visualization (chart.js)
- [ ] ABC Pareto chart
- [ ] Print-friendly aylık rapor (PDF)
- [ ] **CANLI TEST**: Berber akraba + 1 Döner shop tester ile gerçek data
- [ ] Bug fixes + edge cases
- [ ] Documentation update

### Çıktı
- 4 hafta sonu: **müşteriye verilebilir, gerçekten çalışan POS Parser + Business Analytics**
- Pricing: **Pro plan'a dahil** (€39/ay) — Free/Starter erişemez
- Maliyet/müşteri: $1-3/ay (AI calls)

---

## 7. KALİTE STANDARTLARI

### Code quality
- Her endpoint için **integration test** (real test fixtures)
- Her parser fonksiyonu için **unit test**
- Coverage hedef: %75+ pos/ klasörü için
- Type hints zorunlu (`mypy --strict`)

### Production checks
- Every parse logged to `parse_attempts` (audit + analytics)
- Confidence < 0.70 → review queue (frontend banner)
- Daily monitoring: failure rate > 5% → Telegram alert
- Cost tracking per user (admin dashboard)

### Customer-visible quality
- **No silent failures**: her hata user'a anlamlı mesaj
- **Resilience**: AI down → "Wir versuchen es später" + queue
- **Privacy**: extracted data sadece o tenant'a görünür
- **Speed**: ≤30 saniye per Z-Bon (Sonnet, 1-2 page)

---

## 8. PRICING + REVENUE MODEL

| Plan | Mevcut | POS+Analytics |
|---|---|---|
| Free | ❌ | ❌ |
| Starter €15 | ❌ | ❌ |
| **Pro €39** | ✅ Kassensystem MVP | ✅ **POS Parser v2 + Daily/Weekly Analysis** |
| **AI Steuer €89** | ✅ + AI Chat | ✅ **+ Monthly + XYZ + ABC + AI Insights + Opus model** |
| Premium €149 (yeni?) | — | ✅ All + Multi-Filiale + Predictive Forecast |

**Tahmini revenue:** 50 müşteri Pro (€39 × 50 = €1.950) + 20 AI Steuer (€89 × 20 = €1.780) = **€3.730/ay**.
Cost: €30 AI + €25 Railway + €5 R2 = €60. **Net margin: %98**.

---

## 9. RISKS + MITIGATIONS

| Risk | Olasılık | Etki | Mitigation |
|---|---|---|---|
| AI extraction yanlış → vergi hatası | Orta | Yüksek | Confidence threshold + review queue + disclaimer + 4-eyes check |
| Müşteri gizli veri ifşası (Z-Bon → log) | Düşük | Yüksek | PII redaction in logs, R2 server-side encryption, audit |
| Claude API down 24h | Düşük | Orta | Queue + retry + email "wir versuchen weiter" |
| Aggressive cost (1 müşteri 1000 Bon yükler) | Orta | Düşük | Rate limit per plan (100/day Pro, 1000/day AI Steuer) |
| TSE compliance gap (post-2020 receipts) | Orta | Yüksek | Warning sadece, kullanıcı sorumluluğu (kasse vendor responsibility) |
| Template false-positive (yanlış business match) | Orta | Orta | Confidence eşik 0.85+, mismatch → fallback AI |

---

## 10. DEFINITION OF DONE (Production checklist)

**Phase 1 release** ancak şunlar TAMAM ise:

- [ ] 5 farklı gerçek Z-Bon (Döner, Berber, Café, Bäckerei, Retail) hatasız parse
- [ ] Correction kaydedip 2. upload'da kullanılması doğrulanmış
- [ ] Confidence skorlaması test edilmiş (3 örnekte: yüksek/orta/düşük)
- [ ] Daily/Weekly/Monthly analytics endpointleri çalışıyor
- [ ] XYZ + ABC analizleri doğru hesaplıyor (manuel doğrulama)
- [ ] AI Insights DE + TR sonuç dönüyor
- [ ] Frontend dashboard mobil-friendly
- [ ] Auto-import to AutoTax cash_entries çalışıyor
- [ ] PDF rapor export (aylık) çalışıyor
- [ ] Stripe Pro plan lock test edilmiş
- [ ] Failure modes test edilmiş (AI down, malformed PDF, encrypted PDF, etc.)
- [ ] Berber akraba pilot **3 hafta sorunsuz** kullandı
- [ ] Pricing landing'de güncel
- [ ] Help docs (DE + TR)
- [ ] Privacy policy / AVV güncellendi (Claude API processor)

---

## 11. REFERENCES

- `.claude/pos_parser_architecture.md` — Enterprise-level vision (11 vendor)
- `.claude/kasse_plan.md` — Phase 1 mevcut MVP
- `.claude/tax_intake_architecture.md` — Steuererklärung (related, ayrı modül)
- `autotax/kasse.py` — current generic parser (yenilenecek)
- `autotax/ai_ocr.py` — vision OCR (iter O fixes applied)
- `autotax/ai_knowledge.py` — Q&A cache layer (re-use for insights)

**Document status:** Living spec. Update after each phase.
**Last update:** 2026-05-30 (after user "kaliteli yap 1 ay sürse" direktifi).
**Next milestone:** Hafta 1 foundation complete by 2026-06-06.
