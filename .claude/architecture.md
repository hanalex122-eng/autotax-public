# AutoTax-Cloud — Architecture

## Request flow

```
Browser → Cloudflare DNS → Railway edge → Uvicorn (port 8080) → FastAPI
                                                                   │
                                                                   ├── PostgreSQL 18 (internal)
                                                                   ├── Stripe API (HTTPS)
                                                                   ├── Anthropic Claude API
                                                                   ├── OCR.space API
                                                                   ├── Resend (email)
                                                                   ├── Telegram Bot API
                                                                   └── Cloudflare R2 (backups only)
```

## Module responsibilities

| File | What it does |
|---|---|
| `main.py` | All HTTP endpoints. Monolithic by design — 176 endpoints, ~12k lines. Split would help readability but isn't urgent. |
| `models.py` | SQLAlchemy models. Every user-owned table has `user_id`. Soft delete via `is_deleted` flag. |
| `auth.py` | JWT encode/decode, password hash/verify. JWT_SECRET from env. |
| `billing.py` | Stripe wrapper. Checkout session, Customer Portal, Webhook signature verify. |
| `backup.py` | Async loop, weekly pg_dump → gzip → R2 PutObject → Telegram notify. |
| `ai_ocr.py` | When local OCR yields weak result, fallback to Claude Haiku Vision. Disabled if `AI_OCR_FALLBACK=0`. |
| `ai_knowledge.py` | AI Steuerberater Q&A cache. pg_trgm trigram index for fuzzy match. |
| `ocr.py` | Tesseract first, then OCR.space if confidence low. |
| `parser.py` | Heuristic invoice parsing — vendor, amount, VAT, date, IBAN. |
| `email_sync.py` | IMAP polling per user; downloads invoice attachments. |
| `reminders.py` | Daily 09:00 Berlin loop — sends reminders for overdue invoices. |
| `steuer.py` | EÜR generation, USt-VA dates, tax math. |
| `storage.py` | File save/load — local Railway disk for now, R2 ready when needed. |
| `db.py` | SessionLocal factory, engine, init_db. |
| `config.py` | Feature flags (FEATURES dict). Public via /api/config. |
| `audit.py` | Lightweight audit logger (to logger, not DB). |
| `corrections.py` | Manual user fixes pipeline (learning). |
| `learning.py` | Rules engine that watches user corrections. |
| `mahnung.py` | Dunning letter generation. |
| `recurring.py` | Recurring invoice templates. |
| `vendor_identity.py` | Vendor matching + IBAN/USt-IdNr deduplication. |
| `duplicate_service.py` | Cross-user duplicate detection (within own data only). |
| `qr_reader.py` | QR/SwissQR/Giro reader for receipts. |
| `receipt_ocr.py` | Photo-receipt-specific OCR tuning. |
| `jobs.py` | Background job table (long-running OCR/import status). |
| `queries.py` | Common SQLAlchemy queries reused across endpoints. |

## Background tasks (asyncio.create_task at startup)

- `reminder_loop()` — daily, sends invoice reminders.
- `start_auto_sync()` — IMAP email auto-sync every 10 min per configured user.
- `backup_loop()` — weekly, pg_dump → R2 (only if `R2_BACKUP_ENABLED=1` and creds set).

## Frontend architecture

`index.html` is one big file (~5k lines):
1. CDN React 18 + ReactDOM.
2. CDN Babel-standalone for in-browser JSX compilation (the `'unsafe-eval'` source).
3. One big `<script type="text/babel">` block with all components.
4. Components: Dashboard, Upload, Invoices, Kassenbuch, CashBook, Pricing, Profile, Chat, Steuer (EÜR), Vault.
5. Auth: `localStorage.atx_token` for Bearer + HttpOnly cookie dual-mode.

The choice to use CDN + Babel-in-browser is deliberate — no build step, easy edits, fast iteration. Migration to Vite is tracked but not urgent.

## Database schema (key tables)

- `users` — auth + plan + trial_ends_at + stripe_customer_id + stripe_subscription_id + email_verified (future)
- `invoices` — uploaded receipts (vendor, amount, vat, date, file_data, raw_text, category)
- `cash_entries` — Kassenbuch entries
- `learning_rules` — per-user correction rules
- `user_companies` — multi-company per user (Pro+ feature)
- `llm_usage` — Claude token usage tracking
- `audit` — security event log (sparse)
- `stripe_event_log` — webhook idempotency
- `ai_knowledge_cache` — Q&A cache for AI Steuerberater
- `corrections` — manual user corrections
- `reminder_sent_codes` — dedupe reminder sends

All have `user_id` foreign key (except webhook log + cache which are global by design).

## Security architecture

See `SECURITY_AUDIT.md` for current state and `.claude/auth_flow.md` for auth details.

Key boundaries:
- Public endpoints: `/`, `/health`, `/landing`, `/impressum`, `/datenschutz`, `/agb`, `/auth/*`, webhooks (with signature verification)
- Authenticated endpoints: everything else, via `get_current_user` or `get_acting_context`
- Admin endpoints: `/admin/*` gated by middleware checking `ADMIN_EMAILS`

## External integrations security

| Integration | Inbound auth | Outbound auth |
|---|---|---|
| Stripe | `/billing/webhook` → Stripe-Signature header verified via stripe-python | API key Bearer |
| AI reviewer | `/webhooks/ai-review` → HMAC-SHA256, compare_digest | shared secret |
| Telegram | `/telegram/webhook` → secret token header check | bot token |
| Resend | n/a (outbound only) | API key |
| Cloudflare R2 | n/a (outbound only) | S3-compatible signature (boto3) |

## Performance notes

- `file_data` column is `LargeBinary` — deferred in list queries to avoid loading MBs unnecessarily.
- `raw_text` is eager-loaded because `invoice_to_dict` includes `ocr_snippet` (first 200 chars).
- pg_trgm + GIN index speeds up AI Steuerberater question fuzzy search.
- All long-running OCR runs in `asyncio.create_task` background.
- No N+1 issues observed in main listing endpoints (verified via /health response time <50ms).
