# AutoTax-Cloud (autotax-public) — Claude Code Context

This file is automatically loaded by Claude Code at session start. Keep it concise; expand topic-specific notes in `.claude/*.md`.

---

## ⚠️ Sprint discipline (BINDING — read before proposing or writing anything)

**AutoTax is no longer in feature-collection mode. It is in FINISHING and RELIABILITY mode.**
**Priority: Finish > New Features.** Work like someone who *completes a product*, not someone who writes code.

1. **Never switch topic mid-sprint.** Do not move to another module before the current one is *done*.
2. **"Done" requires ALL eight:** code complete · tests green · UX checked · **contradicting legacy flows removed** · review done · deployed · smoke-tested · no critical gap left from the *user's* point of view.
3. **New idea → BACKLOG, not code.** Write it in `SPRINT.md` (Backlog section). Do not interrupt the active sprint.
4. **Do not propose new features while a sprint is open.** Finish first, then propose the next sprint.
5. **End every sprint with an honest report:** completed · deliberately deferred · open risks · *"Is this sprint really finished?"* — if the answer is **no**, no new topic is started.

The single source of truth for what is currently in flight is **`SPRINT.md`** (one active sprint at a time).
The locked product roadmap for the landlord platform is **`VERMIETER_MASTERPLAN.md`** — it is not a
backlog, it is mandatory scope; new ideas do not jump ahead of it.

### 🔒 Architecture law — ONE accounting model, many UIs (Immobilien)

**Never maintain two parallel debt systems.** Every payment path is a *user interface*, not a second
book. All of them must go through **one Payment Service** that writes the **Exception Engine** model:

```
Payment arrives (any UI)
        │
        ├── "Bezahlt" button        ┐
        ├── Partial payment          │
        ├── Mieteingang tab          ├──►  PAYMENT SERVICE  ──►  EXCEPTION ENGINE (single truth)
        └── Bank import (future)     ┘                               │
                                                                     ├── Bu Ay
                                                                     ├── Mietkonto
                                                                     ├── Mahnung
                                                                     ├── Reports (Berichte)
                                                                     └── Nebenkosten
```

The landlord may pick whichever workflow fits them; **all roads must lead to the same ledger and the
same exception model.** This is mandatory — the future bank import will use the same path.

**The law, verbatim (binding):**
1. **Every payment enters the system exactly once.**
2. **No UI is allowed to calculate debt independently.**
3. **Debt is derived only from the Exception Engine.**
4. **Every screen is read-only with respect to debt calculation.**
5. **Only the Payment Service may modify payment state.**

Practical consequences for any future change: a new payment surface (bank import, CSV, mobile,
webhook) calls the Payment Service — it never writes `ImmoRent`, `offene_monate` or a ledger entry
directly. A new read surface (screen, report, PDF, Nebenkostenabrechnung) calls the debt/derivation
helpers — it never sums rows into its own private total.

**Single-Ledger Principle (verbatim):** *an economic event is represented in exactly one place in the
system.* The NK Vorauszahlung is computed only from `monat_nk_soll` (the Mietkonto) — never a second
Vorauszahlung field/source. A finalised Nebenkostenabrechnung is immutable: its `ergebnis_snapshot`
(not the PDF) is the record of truth, and a correction requires an explicit Unlock or a new
Revision — never an in-place edit. See `.claude/nk_architecture.md` → "Binding architecture principles".

---

## Project at a glance

**AutoTax-Cloud** is a German-language SaaS for self-employed people and small businesses to manage receipts, VAT, and tax-related bookkeeping. Customers are Selbständige, Freelancer, Kleinunternehmer in Germany.

- **Domain (prod):** https://autotax.cloud
- **Repo:** `hanalex122-eng/autotax-public` (this repo)
- **Hosting:** Railway (project `tranquil-forgiveness`, service `AutoTax-Hub`)
- **Stack:** FastAPI + SQLAlchemy + PostgreSQL + React (CDN, Babel in-browser) + Uvicorn
- **Payments:** Stripe (LIVE since 2026-05-26)
- **Storage:** Railway disk for invoice files, Cloudflare R2 for weekly DB backups
- **AI:** Anthropic Claude (Haiku) for OCR fallback + tax-question chat

---

## Repository map (top-level)

```
autotax/                  Python package — backend
├── main.py               FastAPI app, all endpoints (~12k lines, monolithic)
├── models.py             SQLAlchemy ORM models (User, Invoice, CashEntry, etc.)
├── auth.py               JWT helpers, password hashing
├── billing.py            Stripe wrapper (Checkout, Portal, Webhook)
├── backup.py             Weekly pg_dump → R2 (2026-05-25)
├── ai_ocr.py             Claude Haiku fallback OCR
├── ai_knowledge.py       AI Steuerberater cache (pg_trgm)
├── ocr.py                Local OCR (tesseract + OCR.space)
├── parser.py             Invoice text parsing heuristics
├── email_sync.py         IMAP auto-sync for customer emails
├── reminders.py          Rechnung overdue alerts
├── steuer.py             EÜR + tax calculations
├── storage.py            Local + cloud file storage abstraction
└── db.py / config.py     DB session + feature flags
index.html                Frontend SPA (React via CDN + Babel in-browser, ~5k lines)
Dockerfile                Python 3.11-slim + tesseract + postgresql-client-18
requirements.txt          ~25 deps (FastAPI 0.115, SQLAlchemy 2.0, stripe 11.4, boto3 1.35)
railway.json              Railway service config
Procfile                  uvicorn entrypoint
```

For detailed structure see `.claude/architecture.md`.

---

## Critical conventions

1. **Auth:** Every data endpoint requires `Depends(get_current_user)` or `Depends(get_acting_context)` (advisor mode).
2. **Data isolation:** Every query filters by `user_id` (or `user["sub"]`). NEVER select across users.
3. **No raw SQL with user input.** Use SQLAlchemy ORM. SQL injection forbidden by convention.
4. **Secrets via `os.getenv` only.** No hardcoded secrets — verified clean in audit 2026-05-26.
5. **Language:** UI/messages German (DE) primary, EN/TR fallback. Code comments TR or DE mixed; new code prefer English.
6. **StBerG compliance:** AI messages must use "Vorschlag/Empfehlung", NOT prescriptive tax advice.
7. **Commit messages:** Conventional (feat/fix/docs/refactor), Co-Authored-By trailer for AI commits.
8. **Git workflow (BINDING — replaces the old "auto-push" rule):**
   - Commit **locally** after meaningful, self-contained changes.
   - **Do NOT push automatically.**
   - Always wait for **explicit user approval** before: `git push` · production deployment.
   - **Default state:** local commits are preferred until approval is given. Approval is
     per-action — approving one push does not authorise the next.

---

## Live integrations (env vars)

```
STRIPE_SECRET_KEY=sk_live_...
STRIPE_PUBLISHABLE_KEY=pk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...
STRIPE_PRICE_STARTER=price_1...
STRIPE_PRICE_PRO=price_1...
STRIPE_PRICE_PREMIUM=price_1...
ANTHROPIC_API_KEY=sk-ant-...
OCR_API_KEY=...
JWT_SECRET=...
RESEND_API_KEY=re_...
RESEND_FROM=AutoTax
TELEGRAM_TOKEN=...
TELEGRAM_CHAT_ID=...
TELEGRAM_WEBHOOK_SECRET=...
R2_BACKUP_ENABLED=1
R2_ACCOUNT_ID=...
R2_ACCESS_KEY_ID=...
R2_SECRET_ACCESS_KEY=...
R2_BUCKET=autotax-backups-de
DATABASE_URL=...           (auto-injected by Railway)
PUBLIC_APP_URL=https://autotax.cloud
ADMIN_EMAILS=hanalex122@gmail.com,...
DEFAULT_REGISTRATION_PLAN=free  (anti-abuse default)
AI_OCR_FALLBACK=1
```

See `.claude/env_vars.md` for full list with descriptions.

---

## How to verify production state

```bash
curl -s https://autotax.cloud/health | python -m json.tool
```

Expected: `status:"ok"`, `db.connected:true`, `stripe_configured:true`, `backup_r2.pg_dump_available:true`.

---

## Common operations

- **Run a manual backup:** `POST /admin/backup/run` (Bearer token + ADMIN_EMAILS).
- **Trial Pro for paying customers:** Admin panel → user → "Pro+Cloud" button (sets `trial_ends_at=NULL`).
- **Stripe webhook test:** Stripe Dashboard → Webhooks → "Send test event".
- **Restore from R2 backup:** Download `.dump.gz` from R2 bucket → `pg_restore -h ... <file>`.

---

## Related docs

- `SECURITY_AUDIT.md` — current security state (2026-05-26)
- `LIVE_CHECKLIST.md` — launch readiness checklist
- `NEXT_STEPS.md` — prioritised roadmap
- `ROADMAP.md` — full product roadmap (10 phases)
- `SECURITY_REPORT.md` — historical audit (2026-04, mostly resolved)
- `.claude/architecture.md` — deeper system architecture
- `.claude/auth_flow.md` — auth/JWT details
- `.claude/deployment.md` — Railway deploy + ops runbook
- **`.claude/product_principles.md`** — 10 binding working principles (read before every change)
- **`.claude/ux_voice.md`** — UX language strategy (no "AI" hype; practical/calm tone)

---

## Anti-patterns (do NOT do)

- ❌ Do not introduce Node.js tooling (this is a Python project).
- ❌ Do not migrate to TypeScript (frontend is CDN React + Babel in-browser by design).
- ❌ Do not rename modules or refactor file structure without explicit user request.
- ❌ Do not add new infrastructure (Redis, Celery, etc.) — keep stack minimal for solo dev.
- ❌ Do not commit large binaries or test fixtures > 1 MB.
- ❌ Do not bypass `/admin/*` middleware for new admin endpoints.
- ❌ Do not give tax advice in AI messages — only suggestions ("Vorschlag").
