# Architecture

**Last updated:** 2026-05-28
**Audience:** Engineers, technical auditors, B2B due-diligence reviewers

This is a public summary. Internal AI-session details live in `.claude/architecture.md`.

---

## System overview

AutoTax-Cloud is a **single-tenant, multi-user** SaaS for German bookkeeping and tax automation.

```
┌──────────────────────────────────────────────────────┐
│  Browser / Mobile (React SPA via CDN + Babel)        │
└─────────────────────┬────────────────────────────────┘
                      │ HTTPS (TLS 1.2+)
                      ▼
┌──────────────────────────────────────────────────────┐
│  Cloudflare (DNS + WAF + DDoS + CDN)                 │
│  • SSL/TLS Full (Strict)                             │
│  • HSTS 2y + preload                                 │
│  • Email Routing (info@, support@ → Gmail)           │
└─────────────────────┬────────────────────────────────┘
                      │ HTTPS
                      ▼
┌──────────────────────────────────────────────────────┐
│  Railway Edge → AutoTax-Hub service                  │
│  ┌──────────────────────────────────────────────┐    │
│  │  Uvicorn (port 8080) → FastAPI               │    │
│  │  ┌────────────────────────────────────────┐  │    │
│  │  │  autotax/main.py (~12k lines)          │  │    │
│  │  │  ├── Auth (JWT + bcrypt)               │  │    │
│  │  │  ├── 176 endpoints                     │  │    │
│  │  │  ├── Background loops:                 │  │    │
│  │  │  │    • Reminders (daily 09:00 Berlin) │  │    │
│  │  │  │    • Email auto-sync (10min)        │  │    │
│  │  │  │    • Backup (weekly Mon 04:00 UTC)  │  │    │
│  │  │  └── Modules: helpers, legal, validators,    │
│  │  │              datev, crypto_helpers, billing, │
│  │  │              backup, ai_ocr, ai_knowledge,   │
│  │  │              parser, ocr, storage, ...        │
│  │  └────────────────────────────────────────┘  │    │
│  └──────────────────────────────────────────────┘    │
└────────────┬──────────────────────────┬──────────────┘
             │                          │
             │ pg_dump weekly           │ Internal network
             ▼                          ▼
┌────────────────────────┐  ┌──────────────────────────┐
│  Cloudflare R2         │  │  Railway PostgreSQL 18    │
│  autotax-backups-de    │  │  • 6 user-scoped tables   │
│  (EU/Frankfurt)        │  │  • pg_trgm GIN indexes    │
│  4-week retention      │  │  • Soft-delete pattern    │
└────────────────────────┘  └──────────────────────────┘

External services (outbound only):
  Stripe API         (live mode, EU)
  Anthropic Claude   (Haiku for OCR fallback)
  OCR.space          (cloud OCR fallback)
  Resend             (transactional email)
  Telegram Bot API   (notifications)
```

---

## Tech stack

| Layer | Choice | Reason |
|---|---|---|
| Backend | Python 3.11 + FastAPI | Type-safe, async-ready, fast, mature |
| ORM | SQLAlchemy 2.0 | Industry standard, no raw SQL needed |
| Database | PostgreSQL 18 (Railway) | Reliable, JSONB support, full-text + pg_trgm |
| Frontend | React 18 (CDN) + Babel-standalone | No build pipeline = fast iteration. Vite migration tracked but not urgent. |
| Auth | JWT (PyJWT) + bcrypt | Stateless, scalable, no session table |
| Payments | Stripe (Subscriptions + Customer Portal) | Industry standard, PCI-DSS handled |
| Email | Resend | Modern API, good deliverability, no SMTP pain |
| OCR | Tesseract (local) → OCR.space (cloud) → Claude Vision (AI fallback) | 3-layer fallback for difficult receipts |
| Backup | pg_dump → gzip → R2 | Off-Railway storage, S3-compatible |
| Hosting | Railway (Hobby plan) | Simple deploys, fast CI |
| CDN / DNS | Cloudflare (free tier) | DDoS protection, edge caching, SSL, Email Routing |
| Monitoring | Sentry + Telegram uptime bot | Errors + uptime |

---

## Data model (key tables)

All tables include `user_id` for tenancy isolation, soft-delete via `is_deleted` flag, and `created_at`.

| Table | Purpose |
|---|---|
| `users` | Email, hashed_password, plan, Stripe IDs, GDPR consent, email_verified |
| `invoices` | Uploaded receipts: vendor, amount, VAT, date, file_path, parsed metadata, AI evaluation |
| `cash_entries` | Manual cash book entries (income/expense) |
| `user_companies` | Multi-company support (Pro+ feature) |
| `learning_rules` | User-specific correction rules learned from edits |
| `corrections` | Audit log of manual user fixes |
| `llm_usage` | AI token consumption per user (cost control) |
| `audit_log` | Action log for compliance |
| `stripe_event_log` | Webhook idempotency |
| `ai_knowledge_cache` | Cached AI Steuerberater Q&A (pg_trgm fuzzy match) |

---

## Request flow

### Standard user request

```
1. Browser → Cloudflare HTTPS → Railway edge
2. Railway → Uvicorn (port 8080)
3. Uvicorn → FastAPI dispatcher
4. Middleware chain:
   • CORS check
   • Security headers (CSP, HSTS, COOP, CORP)
   • Rate limit (slowapi + custom sliding window)
   • Admin path check (if /admin/*)
   • Advisor read-only enforcement (if X-Acting-Client-Id)
5. Route handler:
   • Auth: get_current_user → JWT decode → user dict
   • Business logic
   • Data access: SQLAlchemy with user_id filter
6. Response (JSON or HTML) with security headers
```

### Receipt upload + OCR pipeline

```
1. POST /invoices/upload (multipart)
2. Validate: file size, magic bytes, MIME type, daily quota
3. Save file to disk (volume) → file_path
4. Compute file_hash → check for duplicate
5. OCR pipeline (parallel, async):
   a. Tesseract (local) → raw_text
   b. If text weak → OCR.space (cloud)
   c. If still weak AND ai_ocr_fallback enabled → Claude Haiku Vision
6. Parser → structured fields (vendor, amount, VAT, date, IBAN, ...)
7. AI Reviewer (async webhook callback) → KI evaluation, status, notes
8. Persist invoice row → response with parsed data
```

### Stripe subscription flow

```
1. User → "Abonnement starten" → POST /billing/checkout-session
2. Backend → Stripe API: create_checkout_session(customer, price)
3. Return Stripe Checkout URL
4. User completes payment on Stripe-hosted page
5. Stripe → POST /billing/webhook (signed payload)
6. Backend verifies signature → updates user.plan + subscription_status
7. User redirected to /app?subscription=success → sees active plan
```

---

## Background tasks (asyncio)

All started at app startup. Each has its own kill switch.

| Task | Schedule | Kill switch |
|---|---|---|
| `reminder_loop` | Daily 09:00 Europe/Berlin | (no env switch; disabled if no due invoices) |
| `email_auto_sync` | Every 10 min per configured user | `EMAIL_AUTO_SYNC_ENABLED=0` |
| `backup_loop` | Weekly Monday 04:00 UTC | `R2_BACKUP_ENABLED=0` |

---

## External integrations security

| Integration | Inbound auth | Outbound auth |
|---|---|---|
| Stripe | Signature header verified via stripe-python | Bearer API key (env) |
| AI Reviewer | HMAC-SHA256 with `compare_digest` (timing-safe) | Shared secret (env) |
| Telegram | Secret token header check | Bot token (env) |
| Resend | n/a (outbound only) | API key (env) |
| R2 backup | n/a (outbound only) | S3-compatible IAM (boto3) |

---

## Performance characteristics

| Metric | Target | Measured |
|---|---|---|
| `/health` p95 | < 100ms | ~30ms |
| Invoice list query | < 500ms | 50-200ms (deferred large columns) |
| Upload + OCR (sync part) | < 2s | ~1s |
| Upload + AI evaluation (async) | < 30s | 5-15s |
| Stripe checkout session creation | < 1s | ~400ms |
| Backup full cycle | < 5 min | ~30s at current data scale |

---

## Scaling characteristics

Current single-instance architecture supports approximately:
- **100 users** comfortably
- **1,000 users** with vertical scaling (Railway resource bump)
- **10,000+ users** would require:
  - Redis for rate limit counters (currently in-memory)
  - Read replicas for analytics
  - Horizontal scaling (sticky sessions or shared session store)
  - Object storage for invoice files (currently Railway disk; R2 migration planned)

This is acceptable for the soft-launch + first-year roadmap.

---

## What's intentionally NOT in the stack

- ❌ Redis / Celery — overkill for current scale, adds operational burden
- ❌ GraphQL — REST is fine, simpler for solo dev
- ❌ Microservices — monolith is right for this scale and complexity
- ❌ Build pipeline (Vite/Webpack) — CDN React + Babel is fast to iterate; migration planned for S6 sprint
- ❌ TypeScript — frontend is small enough; would slow iteration
- ❌ Mobile native apps — PWA is sufficient (S6+)

---

## Related docs

- `SECURITY_AUDIT.md` — security state assessment
- `BACKUP_POLICY.md` — disaster recovery procedures
- `INCIDENT_RESPONSE.md` — incident handling protocol
- `ACCESS_CONTROL.md` — identity + authorization
- `LIVE_CHECKLIST.md` — production launch readiness
- `ROADMAP.md` — long-term product plan
- `REPOSITORY_MAP.md` — file structure
- `CLAUDE.md` — AI session entry point
- `/datenschutz` — public privacy policy (DSGVO Art. 13)

---

## Change log

- 2026-05-28: Public architecture doc created
- 2026-05-27: 5 modules extracted from main.py (helpers, legal, validators, datev, crypto_helpers)
- 2026-05-25: R2 backup deployed
- 2026-05-22: Stripe LIVE keys swapped
