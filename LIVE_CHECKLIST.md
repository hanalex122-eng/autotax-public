# AutoTax-Cloud LIVE Launch Checklist

**Target:** Soft launch (pilot customer) on 2026-05-26 → public launch when full checklist passes.

---

## ✅ DONE — Soft launch unblocked

### Infrastructure & Deploy
- [x] Production hosting on Railway (autotax.cloud)
- [x] PostgreSQL 18 production database
- [x] Docker image with all required system deps (pg_dump 18, tesseract, libzbar)
- [x] CSP + security headers (HSTS preload 2y, COOP, CORP, Permissions-Policy)
- [x] HttpOnly + secure + samesite=strict cookies (dual-mode with Bearer)
- [x] CORS configured with explicit allow list

### Authentication
- [x] bcrypt password hashing
- [x] JWT access (60min) + refresh (7d) separation
- [x] JWT_SECRET configured (stable across restarts)
- [x] Login rate limit (5/min/IP)
- [x] Admin endpoint middleware (`/admin/*` requires ADMIN_EMAILS)
- [x] DSGVO Art. 6 consent capture on registration

### Anti-abuse (initial set)
- [x] Default registration plan = `free` (commit `29e7665`)
- [x] User input max length caps: chat=2000, feedback=5000, /steuer/ask=1000
- [x] Per-user daily quotas (free=25 uploads, 10 chats)
- [x] Per-minute burst caps
- [x] Disk quota guards
- [x] Frontend `maxLength` on all textareas

### Payments
- [x] Stripe LIVE account approved (KYC done 2026-05-22)
- [x] 3 LIVE products created (Starter €15, Pro €39, AI Steuer €89, recurring monthly EUR)
- [x] Live Price IDs in Railway env
- [x] Live Secret Key + Publishable Key in Railway env
- [x] Live Webhook Secret in Railway env
- [x] Stripe Checkout opens on real key (verified 2026-05-26)
- [x] Bank linked (Kontist, SEPA payout via Solarisbank)
- [x] Payout schedule: Täglich (T+2)
- [x] Statement descriptor: `AUTOTAX.CLOUD` / `AUTOTAX`
- [x] 2FA enabled on Stripe

### Data protection
- [x] Weekly PostgreSQL backup → Cloudflare R2 (EU/Frankfurt)
- [x] Backup retention: 4 weeks (auto-prune)
- [x] Backup notification via Telegram
- [x] First production backup verified (415 KB dump.gz, 2026-05-25)

### Legal pages
- [x] `/impressum` — name, address, contact, USt note, dispute notice
- [x] `/datenschutz` (DE) — DSGVO Art. 13 sections, third-party processors listed
- [x] `/privacy` (EN) — mirror of datenschutz
- [x] `/agb` — terms of service
- [x] Multilang privacy: `/confidentialite`, `/privacidad`, `/gizlilik`, `/khususiyya`
- [x] Third-party processor list updated 2026-05-26 (Stripe + Cloudflare + Resend + Telegram added)

### Audit & Monitoring
- [x] Security audit completed 2026-05-26 (SECURITY_AUDIT.md)
- [x] Uptime monitor active (Telegram alerts)
- [x] Stripe webhook signing verification active
- [x] AI reviewer HMAC verification active

---

## 🟡 TODO — Required before public marketing launch

### Anti-abuse Phase 2
- [ ] Cloudflare Turnstile CAPTCHA on `/auth/register` (keys provisioned 2026-05-26)
- [ ] Email verification via Resend (signup → verify link → flag verified)
- [ ] Optional: rate-limit registration by IP+email hash

### Observability
- [ ] Sentry DSN configured in Railway env (SDK already integrated, DSN missing)
- [ ] Structured logging review (replace key f-strings with structured fields)

### Input hardening
- [ ] CSV/XLSX formula injection sanitisation (M-3 from audit)
- [ ] `pip-audit` in CI to catch vulnerable deps

### Operational
- [ ] Postgres password rotation (low risk per public networking off — hygiene)
- [ ] `/auth/forgot-password` end-to-end test (email actually arrives?)

---

## ⚪ NICE TO HAVE — post-launch

- [ ] Vite build pipeline → CSP nonce-strict (remove `'unsafe-inline'`/`'unsafe-eval'`)
- [ ] HttpOnly cookie as primary token storage (drop localStorage usage)
- [ ] Structured audit log table for GDPR data-access trail
- [ ] GoBD-Testat external audit (recommended at 10+ paying customers)
- [ ] At-rest encryption for invoice file blobs (currently relies on Railway disk encryption)

---

## 🚨 Rollback Plan

If LIVE goes wrong (unexpected charges, abuse wave, broken checkout):

1. **Instant kill switch:** Railway → AutoTax-Hub → Variables → set `STRIPE_SECRET_KEY=` (empty)
   → `stripe_configured: false` → all `/billing/*` endpoints return 503.
2. **Block new registrations:** Railway → Variables → set `REGISTRATION_DISABLED=1` *(env flag not yet implemented — add if needed)*
3. **Stripe Dashboard side:** Disable LIVE products (Stripe → Products → each product → "Archive")
4. **Webhook side:** Stripe → Webhooks → disable endpoint
5. **DNS-level:** Cloudflare → DNS → autotax.cloud → A record off (last resort, takes ~minutes to propagate)

Backups can be restored from R2 via `pg_restore`:
```bash
pg_restore -h <RAILWAY_HOST> -p <PORT> -U postgres -d railway autotax_db_YYYY-MM-DD_HHMMSS.dump.gz
```
