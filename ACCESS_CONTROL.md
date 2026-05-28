# Access Control Policy

**Last updated:** 2026-05-28
**Owner:** Hüseyin Hancer
**Scope:** All systems, services, and data of AutoTax-Cloud

---

## Principles

1. **Least privilege** — every identity gets the minimum permissions required.
2. **Need-to-know** — access granted only for actively needed work.
3. **Defense in depth** — multiple layers (auth, env-scoped secrets, network).
4. **Auditability** — every privileged action is logged.

---

## Identity classes

| Class | Examples | Authentication method |
|---|---|---|
| **End user** | Customer with a free / paid plan | Email + bcrypt password + JWT |
| **Admin** | Hüseyin (operator) | Email in `ADMIN_EMAILS` env + Bearer JWT |
| **Advisor (Steuerberater)** | Tax advisor with mandate | Standard user JWT + `X-Acting-Client-Id` for mandant data |
| **Service** | AutoTax-Hub backend → external API | Per-service API key (Stripe sk_live, Anthropic, R2, Resend, Telegram) |
| **Build / deploy** | Railway, GitHub Actions | Personal access tokens, OAuth (not in code) |

---

## End user authentication

- **Registration:** Email + password (min 8 chars, 1 uppercase, 1 digit). GDPR consent required.
- **Email verification:** Required for new accounts (Resend link, 24-hour token). Existing users grandfathered.
- **CAPTCHA:** Cloudflare Turnstile on `/auth/register` (active when env keys set).
- **Login:** Email + bcrypt verification → JWT access (60 min) + refresh (7 days).
- **Sessions:** Stateless JWT signed with `JWT_SECRET`. No DB session table.
- **Logout:** Cookies cleared; JWT expires naturally. No revocation list (acceptable at current scale).
- **Password reset:** Email link with 1-hour token → set new password → redirect to login.
- **Rate limits:** 5 login attempts / minute / IP, 3 registrations / minute / IP.

---

## Admin access

- **Eligibility:** Email listed in `ADMIN_EMAILS` env variable (comma-separated).
- **Authentication:** Standard user login JWT + middleware check on every `/admin/*` request.
- **Middleware:** `main.py:188+` blocks any `/admin/*` request without a valid JWT whose email matches `ADMIN_EMAILS`.
- **Scope:** Admin endpoints include:
  - `/admin/reset-password` — reset another user's password
  - `/admin/backup/run` — manual backup trigger
  - `/admin/backup/status` — backup config diagnostic
  - `/admin/reparse` — re-OCR all user's invoices (cost-sensitive)
- **Logging:** Every admin action is logged with masked email and IP.

---

## Advisor (Steuerberater) access

When a Steuerberater is invited to a mandant's account:

1. Mandant sends invite from their account (`/advisor/invite`).
2. Invite link contains a signed token (1-week expiry).
3. Advisor clicks link → standard registration / login.
4. After accept, advisor can set `X-Acting-Client-Id` header on requests to operate on mandant's data.
5. **Write operations are blocked** by the security middleware when `X-Acting-Client-Id` is set (read-only acting mode).
6. Mandant can revoke at any time from their account.

GoBD compliance: read-only acting mode + audit log of advisor actions.

---

## Service (machine) credentials

Stored only in Railway environment variables. Never committed to git.

| Service | Env var | Scope |
|---|---|---|
| Stripe API | `STRIPE_SECRET_KEY` | Live mode, full account |
| Stripe webhook | `STRIPE_WEBHOOK_SECRET` | Signature verification |
| Anthropic Claude | `ANTHROPIC_API_KEY` | OCR + AI Steuerberater chat |
| OCR.space | `OCR_API_KEY` | Fallback OCR |
| Resend (email) | `RESEND_API_KEY` | Transactional email |
| Telegram Bot | `TELEGRAM_TOKEN` | Outgoing notifications, webhook receive |
| Cloudflare R2 | `R2_ACCESS_KEY_ID` + `R2_SECRET_ACCESS_KEY` | Bucket-scoped (only `autotax-backups-de`) |
| Cloudflare Turnstile | `TURNSTILE_SECRET_KEY` | CAPTCHA verification |
| AI Reviewer | `AI_REVIEWER_SECRET` | HMAC for webhook |
| JWT signing | `JWT_SECRET` | User token signature |

**Rotation policy:**
- High-sensitivity (Stripe, Anthropic, JWT_SECRET): rotate annually or on suspected compromise.
- Medium (R2, Resend, Telegram): rotate every 18-24 months or on departure of any team member with access.
- Database password: rotated via Railway dashboard, 2-click operation.

**Secret leak protocol:**
1. Rotate immediately on any suspicion.
2. Review logs for unauthorized usage.
3. Document in `INCIDENT_RESPONSE.md` postmortems.

---

## Network access

- **Inbound:** HTTPS only (HSTS 2 years + preload). HTTP requests are 301-redirected to HTTPS via Cloudflare + CSP `upgrade-insecure-requests`.
- **CORS:** Strict allow-list of origins (`autotax.cloud`, Railway preview, local dev). Credentials never sent (Bearer token auth).
- **Database:** PostgreSQL on Railway, **public networking disabled** (only Railway internal network can connect).
- **R2 backup bucket:** Public read disabled. Access only via API token with bucket-scoped permissions.

---

## Data classification + access matrix

| Data category | Examples | Who can access |
|---|---|---|
| **Public** | Marketing copy, /impressum content | Anyone |
| **User personal data (DSGVO)** | Email, full_name, address, IBAN | Owner user only + admin (read-only for support) |
| **Bookkeeping data** | Invoices, cash entries, exports | Owner user + invited advisor (acting mode) |
| **Payment data** | Stripe card numbers — never stored | Stripe (PCI-DSS); we only see masked metadata via API |
| **Service secrets** | Stripe sk_live, JWT_SECRET, R2 keys | Operator (Hüseyin) via Railway env vars only |
| **System logs** | Railway logs, Sentry events | Operator only |
| **Database backups** | R2 dumps | Backend (write), operator (read-restore) |

---

## Auditing

Current state (small-scale):
- **Standard logger** writes to Railway log stream
- `_SanitizeLogFilter` masks API keys / DATABASE_URL / JWT in log output (DSGVO Art. 25)
- Login successes / failures logged with masked email + IP
- Admin actions logged
- Stripe webhooks logged

Planned (S2 sprint or later):
- Structured `audit_log` DB table for GDPR data-access trail (10-year retention)
- IP geo-location enrichment for suspicious access detection
- Export `audit_log` via DATEV-friendly format for compliance audits

---

## Compliance mapping

| Standard | Requirement | Satisfied by |
|---|---|---|
| GDPR Art. 32(1)(b) | Confidentiality of processing | bcrypt, HTTPS, JWT, secret env vars, log sanitization |
| GDPR Art. 32(1)(d) | Regular testing | Security audit (semi-annual planned) |
| GoBD §3 | Datenintegrität + Zugriffsschutz | Auth + advisor read-only + audit log |
| ISO 27001 A.9.2 | User access management | This policy + ADMIN_EMAILS allowlist |
| ISO 27001 A.9.4 | System and application access | JWT + middleware checks |

---

## Onboarding / offboarding (future, when team grows)

Currently solo (Hüseyin only). When team members are added:

**Onboarding:**
1. Add email to relevant env vars (`ADMIN_EMAILS`) only if admin role needed
2. Issue separate Stripe / Cloudflare / Railway invites if their role requires
3. Sign confidentiality + access-rights agreement
4. Read this policy

**Offboarding:**
1. Remove from `ADMIN_EMAILS`
2. Revoke Stripe / Cloudflare / Railway invites
3. Rotate any service secret they had access to
4. Document in incident log

---

## Change log

- 2026-05-28: Initial access control policy
- 2026-05-27: Email verification flow deployed → access strengthened
- 2026-05-26: ADMIN_EMAILS middleware verified (security audit closed C-1)
