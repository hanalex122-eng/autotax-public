# AutoTax-Cloud — Next Steps Roadmap

**Updated:** 2026-05-26
**Current state:** Stripe LIVE checkout verified, backup running, soft launch unblocked.

---

## 🎯 This week — Public launch prep (Phase 2)

Estimated total effort: **6-8 hours** of focused work.

### Day 1 — Anti-abuse hardening (3-4h)
- [ ] **Cloudflare Turnstile CAPTCHA on /auth/register** — 1.5h
  - Keys already provisioned in Cloudflare (2026-05-26)
  - Add `TURNSTILE_SITE_KEY` + `TURNSTILE_SECRET_KEY` to Railway env
  - Frontend: widget on register form (script tag + div + token capture)
  - Backend: validate token via `siteverify` API before user creation
  - Test: bot abuse attempt should fail with 400

- [ ] **Email verification flow** — 2-3h
  - Add `email_verified: bool` column to `User` model + Alembic migration
  - On register: generate token, send Resend email with link
  - Endpoint `/auth/verify-email?token=...` flips flag
  - Gate sensitive actions (upload, chat) on `email_verified=True` (or warn)
  - Re-send button on UI for missed emails

### Day 2 — Observability + input hardening (1-2h)
- [ ] **Sentry DSN integration** — 5min
  - Get DSN from Sentry dashboard (sentry.io)
  - Add `SENTRY_DSN` to Railway env
  - Verify `/health` shows `sentry_configured: true`
  - Trigger test error to confirm Sentry receives

- [ ] **CSV/XLSX formula injection sanitisation** — 30min
  - In export paths: when writing user-provided strings to CSV/XLSX cells, prefix with `'` if first char is `=`, `+`, `-`, `@`, `\t`, `\r`
  - Touchpoints: `/export/datev`, `/export/csv`, `/export/excel`
  - Test: cell with `=CMD()` exports as `'=CMD()` (literal)

- [ ] **pip-audit in GitHub Actions** — 30min
  - Create `.github/workflows/security.yml`
  - Job: `pip install pip-audit && pip-audit -r requirements.txt`
  - Schedule: weekly + on pull_request

### Day 3 — Polish (1h)
- [ ] **Postgres password rotation** (2min, Railway dashboard)
- [ ] **`/auth/forgot-password` end-to-end test** — verify Resend delivers
- [ ] **Update SECURITY_AUDIT.md** — mark CAPTCHA + email verify as closed
- [ ] **README badge** for security audit pass

---

## 🚀 Public launch — go criteria

All of these must be ✓:

1. CAPTCHA in production, manually tested with bot tool
2. Email verification required for any upload action
3. Sentry collecting at least one event
4. SECURITY_AUDIT.md updated, 0 open HIGH items
5. LIVE_CHECKLIST.md fully checked off in "TODO" section
6. End-to-end **real €15 payment test** completed and refunded
7. Statement descriptor confirmed on customer's bank statement (use own card to test)
8. Backup restore drill performed (download an R2 dump, restore to a temp DB, verify)

Estimated: **3-4 days from today** if focused.

---

## 📈 Post-launch (Month 1) — Growth + safety

### Customer onboarding
- [ ] Pilot Türk akraba berber feedback gathered (DSFinV-K, daily flow)
- [ ] 2-3 additional pilot customers from network (target: 5 total)
- [ ] Refine pricing copy + Anlage messaging based on feedback

### Product features (deferred from earlier roadmap)
- [ ] **Steuererklärung modülü** — Anlage N/V/S/G forms with AI auto-fill (planned 3-6 weeks)
- [ ] **DSFinV-K Kassensystem import** — universal parser (1-2 weeks, after Steuererklärung)
- [ ] **AI Steuerberater chat improvements** — citation links, better caching

### Engineering health
- [ ] **Vite build pipeline** — remove `'unsafe-inline'` + `'unsafe-eval'` from CSP (1-2 weeks)
- [ ] **HttpOnly cookie as primary auth** — drop localStorage token (already supported in dual-mode)
- [ ] **Structured audit log table** — GDPR-stronger data-access trail
- [ ] **Dependency auto-update** — Dependabot + weekly review

### Compliance
- [ ] **GoBD-Verfahrensdokumentation** — written doc (5-10 pages, BMF template)
- [ ] **AVV templates** — Auftragsverarbeitungsvertrag for B2B customers (Art. 28 DSGVO)
- [ ] At 10+ customers: schedule **GoBD-Testat** external audit (Wirtschaftsprüfer, €5-15k)

---

## 🔮 Quarter 1 — Scale prep

- [ ] **R2 file storage migration** for invoice blobs (Railway disk → R2 via signed URLs) — only when disk >70% full
- [ ] **Neon/Supabase consideration** for PostgreSQL — if Railway DB cost > €30/mo
- [ ] **Read replica** for analytics queries
- [ ] **CDN** for static assets if German user base grows beyond 100

---

## 🧠 AI workflow improvements (Claude Code session efficiency)

The `.claude/` memory system was bootstrapped 2026-05-26. To make future sessions cheaper:

- [ ] Keep `.claude/repository_map.md` updated after each significant refactor
- [ ] When adding a new module, log a one-line architectural note in `.claude/system.md`
- [ ] Memory files (`.claude/projects/.../memory/*.md`) are auto-loaded; keep them concise
- [ ] Token budget per session: aim for <30k context, prefer fresh sessions for unrelated tasks

---

## 🎯 Personal goals (Hüseyin)

- [ ] **2025 Steuererklärung** — deadline 31.07.2026 (Steuerberater'sız) or 28.02.2027 (StB)
  - Use AutoTax own DATEV export → hand to Steuerberater
  - 2 rental properties → Anlage V required, AfA optimisation
- [ ] **Kontist Free plan** monitor — upgrade if cash flow grows
- [ ] **First paying customer revenue** — target by end of June 2026
