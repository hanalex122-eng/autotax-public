# Product Principles & Working Rules

Long-term direction set by founder Hüseyin on 2026-05-27.
**These are binding for all future changes.**

---

## 10 Working Principles

### 1. Small safe commits only
- Incremental changes preferred
- No large risky rewrites
- Easy rollback always possible

### 2. Test after every important change
Especially on:
- auth
- billing (Stripe)
- OCR pipeline
- AI endpoints
- uploads
- Stripe webhooks

How: manual smoke test + `/health` verification + CI workflow (`.github/workflows/test.yml`).

### 3. Gradually modularize main.py
- Piece-by-piece only (file-by-file)
- No aggressive rewrites
- Stability first
- Plan order: helpers first (csv_safe, safe_*), then route groups, then full modules
- Each commit moves max ~500 lines

### 4. Mobile-first UX
Target users: **barbers, döner shops, kiosks, small restaurants, freelancers**

Optimize for:
- Phone camera uploads (primary input)
- Touch UI (44px+ tap targets)
- Fast workflows (1-2 taps to complete a task)
- Simple onboarding (max 3 screens)

### 5. Build DSFinV-K / German small-business workflows
Focus:
- Cash register receipts (Speedy, Vectron, Orderbird, Lightspeed)
- POS exports (DSFinV-K standard)
- Receipt automation (photo → DATEV)
- DATEV-ready exports
- Automated bookkeeping flows

### 6. Expand AI tax advisor
Future capabilities:
- Deductible expense guidance (Werbungskosten)
- VAT explanations (USt-Voranmeldung)
- Business-type-specific advice (Friseur, Gastro, Kiosk)
- Industry workflows
- German tax education content

### 7. WISO-like tax filing system (Future — Phase 9)
Future modules:
- Einkommensteuer (Anlage N, V, S, G)
- Anlage EÜR
- Umsatzsteuer (USt-VA)
- ELSTER export (XML signed)
- Automated tax form assistance

This is the **real value proposition** of the AI Steuer €89/month plan.

### 8. RED LINE — No soft-launch-destabilizing refactors
**Working product > perfect architecture.**

Forbidden:
- Large rewrites
- Stack migration (Python+FastAPI is fixed)
- DB schema breaking changes
- Auth flow refactor (current works)

Open after soft launch is stable + 10+ customers.

### 9. AI cost protection (always priority)
- AI usage limits (per-user daily caps — implemented)
- Abuse protection (CAPTCHA + email verify — implemented)
- Upload limits (file size + daily count — implemented)
- Queue protection (async job table — implemented)
- Rate limiting (slowapi + custom — implemented)
- Token efficiency (prompt caching, AI knowledge cache)

### 10. Product direction
**Goal:** AutoTax → AI-powered German bookkeeping + tax automation platform for small businesses.

**Core promise:**
> "Take a photo → bookkeeping + DATEV automatically."

---

## Decision Matrix (apply before every change)

| Condition | Decision |
|---|---|
| Backward compat + <30 min + rollback path + production-safe | **GO** |
| >30 min or production-breaking risk | **ASK first** |
| Could delay soft launch | **STOP** |
