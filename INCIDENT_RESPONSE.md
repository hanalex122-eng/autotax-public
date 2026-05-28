# Incident Response Plan

**Last updated:** 2026-05-28
**Owner:** Hüseyin Hancer
**Scope:** Production incidents affecting autotax.cloud and connected services

---

## Definition

An **incident** is any unplanned event that:
- Reduces or removes service availability
- Compromises confidentiality, integrity, or availability of customer data
- Triggers a security alert (Sentry critical, webhook signature failures, etc.)
- Results in unexpected financial charges (Stripe, AI API)

---

## Severity levels

| Severity | Examples | Response time |
|---|---|---|
| **SEV-1** (Critical) | Total outage, data loss, security breach, real payments failing | < 30 minutes |
| **SEV-2** (High) | Partial outage (one feature broken), backup failure, suspected abuse | < 4 hours |
| **SEV-3** (Medium) | Degraded performance, non-critical feature broken, log anomalies | < 24 hours |
| **SEV-4** (Low) | Cosmetic bugs, minor UX issues, documentation errors | Next sprint |

---

## Detection sources

1. **Uptime monitor (Telegram bot)** — `UP/DOWN` notifications from `uptime-bot-production-7c87.up.railway.app`
2. **Sentry** — error rate spikes, new error types, performance regressions
3. **Backup alerts** — `❌ AutoTax DB Backup FAILED` Telegram messages
4. **Railway dashboard** — deploy failures, container restarts
5. **Customer reports** — email to `support@autotax.cloud` (forwarded to Hüseyin Gmail)
6. **Stripe Radar** — fraud alerts, chargebacks
7. **External monitoring** (planned) — third-party uptime, SSL expiry alerts

---

## First responder protocol

### Within 5 minutes of detection

1. **Acknowledge** — confirm the alert is real (not false positive)
2. **Classify severity** — SEV-1/2/3/4
3. **Communicate** — for SEV-1/2: post in `#autotax-status` channel (when team grows) or own log
4. **Stabilize first, debug later** — apply kill switch if needed (see below)

### Kill switches (instant remediation)

When safe rollback is not possible immediately, use the appropriate kill switch via Railway env vars:

| Symptom | Kill switch | Effect |
|---|---|---|
| Stripe billing error / unexpected charges | `STRIPE_KILL_SWITCH=1` | All `/billing/*` → 503 |
| Claude API runaway cost | `AI_OCR_FALLBACK=0` and/or `ANTHROPIC_API_KEY=` | AI features off |
| Mass registration abuse | `DEFAULT_REGISTRATION_PLAN=free` (already default) + frontend block | Limit blast radius |
| Email spam outbound | `RESEND_API_KEY=` (clear) | No outgoing email |
| Telegram bot misbehaving | `TELEGRAM_TOKEN=` (clear) | No bot operations |
| Backup runaway / R2 bill | `R2_BACKUP_ENABLED=0` | Loop skips |
| Full lockdown | DNS → autotax.cloud A record off in Cloudflare | Site unreachable, last resort |

Each kill switch is reversible (set back to original value), takes effect within 1-2 minutes after Railway redeploys.

---

## Response phases

### Phase 1 — Contain (minutes)

- Activate appropriate kill switch
- Confirm threat is no longer expanding
- Note start time of incident

### Phase 2 — Investigate (≤2 hours for SEV-1, hours-to-days for lower)

- Read Railway logs (last 1-4 hours)
- Read Sentry events (last 1-4 hours)
- Check `/health` for service status
- Identify root cause if possible
- Identify affected users / records if data is involved

### Phase 3 — Fix (variable)

- Develop fix (small, focused; follows `feedback_product_principles.md` rule #1)
- Test locally if possible (Python syntax check + unit test for the affected path)
- Deploy via standard commit + push flow
- Verify fix in production (`/health` + manual smoke test of affected endpoint)

### Phase 4 — Recover

- Disable kill switch (if used)
- Confirm full service restoration
- Communicate to affected users if data was impacted (GDPR Art. 34)

### Phase 5 — Postmortem (within 7 days for SEV-1/2)

Write a postmortem document with:
- Timeline (detection → containment → fix → recovery)
- Root cause
- What worked / what didn't
- Permanent prevention (code change, alert, monitoring, runbook update)

Store in `postmortems/YYYY-MM-DD-incident.md`.

---

## GDPR breach notification

If incident involves **personal data breach** (Art. 33-34 GDPR):

| Severity | Notification deadline |
|---|---|
| High risk to rights/freedoms | Authority (Saarländisches DSGVO Aufsichtsbehörde): **72 hours** |
| High risk to data subjects | Affected individuals: **without undue delay** |

The breach notification template:
- What happened (date, scope)
- What data was affected (categories: name, email, financial, etc.)
- Number of records / individuals
- Likely consequences
- Measures taken (containment, mitigation)
- Contact: datenschutz@autotax.cloud

---

## Recent incidents

### 2026-05-27 — Sentry crash → site down (SEV-1)
- **Detection:** Uptime monitor `DOWN: AutoTax-Cloud` Telegram alert
- **Root cause:** Sentry SDK init with invalid/empty DSN raised `BadDsn` at module load time, container crashloop
- **Fix:** Added DSN validation (must start with `https://`) + try/except around `sentry_sdk.init()`. Commit `0af9002`.
- **Recovery time:** ~3 minutes (push + Railway rebuild + deploy)
- **Prevention:** Defensive boot pattern — telemetry must not crash the app

---

## Contacts

| Role | Contact |
|---|---|
| Incident lead (current) | Hüseyin Hancer — hanalex122@gmail.com |
| Datenschutz / DPO | datenschutz@autotax.cloud → hanalex122@gmail.com |
| Cloudflare account | hanalex122@gmail.com |
| Railway account | hanalex122@gmail.com |
| Stripe account | Account ID `acct_1TZae71q27bc8OW5` |
| Resend (email) | hanalex122@gmail.com |

---

## Tooling

- Railway logs: dashboard.railway.com
- Sentry: sentry.io (when DSN configured)
- Cloudflare R2: dash.cloudflare.com → R2 → autotax-backups-de
- Stripe Dashboard: dashboard.stripe.com
- Status page (planned): status.autotax.cloud

---

## Change log

- 2026-05-28: Initial incident response plan created
- 2026-05-27: First real incident (Sentry crash) — handled, postmortem above
