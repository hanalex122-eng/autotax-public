# Vendor Risk Assessment

**Last updated:** 2026-05-28
**Owner:** Hüseyin Hancer
**Review cadence:** Annual, or on significant vendor change

This document evaluates each third-party processor we rely on, in line with:
- DSGVO Art. 28 (Auftragsverarbeitung)
- DSGVO Art. 32 (Sicherheit der Verarbeitung)
- ISO 27001 A.15 (Supplier relationships)

---

## Risk scoring methodology

Each vendor is scored on 5 axes (1 = lowest risk, 5 = highest risk):

| Axis | Meaning |
|---|---|
| **Data sensitivity** | How much personal / financial data we share |
| **Vendor reach** | How widely used (mature vendors = lower risk) |
| **Compliance posture** | ISO 27001, SOC 2, PCI-DSS, etc. |
| **Geographic risk** | EU / US-DPF / other |
| **Replaceability** | How easy to migrate if vendor fails |

**Composite risk:** Average of 5 axes (lower = better).
**Action threshold:** Composite > 3.5 requires mitigation plan.

---

## Vendor inventory

### 1. Railway Inc.

**Service:** Hosting (compute + PostgreSQL)
**Data shared:** Full operational data (database, files, env vars)

| Axis | Score | Notes |
|---|---|---|
| Data sensitivity | 5 | Houses all customer data |
| Vendor reach | 3 | Growing platform, not yet enterprise standard |
| Compliance | 2 | SOC 2 Type 1 (announced); no ISO 27001 yet |
| Geographic | 2 | EU region available, used; US legal entity |
| Replaceability | 3 | Possible migration to Render / Fly.io / dedicated cloud — 1-2 weeks |

**Composite:** 3.0 / 5
**Action:** Acceptable for current scale. Monitor SOC 2 status. Plan to evaluate alternatives at >50 customers.

**Risk mitigations:**
- Weekly off-Railway backups (R2)
- DB credentials rotated quarterly (planned)
- Public networking disabled on Postgres
- All Railway env vars treated as secrets

---

### 2. Cloudflare, Inc.

**Service:** DNS, CDN, WAF, SSL termination, R2 object storage, Email Routing, Turnstile CAPTCHA
**Data shared:** Routing metadata, backup dumps (encrypted), email metadata for forwarding

| Axis | Score | Notes |
|---|---|---|
| Data sensitivity | 3 | Backup data + email metadata; main data still encrypted |
| Vendor reach | 1 | Industry-leading CDN, billions of users |
| Compliance | 1 | ISO 27001, SOC 2, PCI-DSS, FedRAMP, EU-US DPF certified |
| Geographic | 1 | EU edges (Frankfurt) used; bucket pinned to EU |
| Replaceability | 3 | CDN swap is feasible; R2 → AWS S3 / Backblaze B2 in 1 day |

**Composite:** 1.8 / 5
**Action:** Low risk. Continue using. No mitigation needed.

**Risk mitigations:**
- R2 token scoped to single bucket
- SSL Full (Strict) prevents downgrade attacks
- All R2 traffic over TLS

---

### 3. Stripe Payments Europe Ltd.

**Service:** Payment processing (Subscriptions, Customer Portal, Webhooks)
**Data shared:** Customer name, email, IP, payment metadata, plan / subscription state

| Axis | Score | Notes |
|---|---|---|
| Data sensitivity | 4 | Includes financial transaction history |
| Vendor reach | 1 | Largest fintech payments provider globally |
| Compliance | 1 | PCI-DSS Level 1, SOC 1/2, ISO 27001, EU-US DPF |
| Geographic | 2 | EU entity (Ireland) used for EU customers |
| Replaceability | 4 | Stripe-specific webhook + API contracts; migration to Adyen / Mollie = weeks |

**Composite:** 2.4 / 5
**Action:** Acceptable. Stripe is best-in-class for compliance.

**Risk mitigations:**
- Card numbers NEVER stored on our side (PCI scope minimized)
- Webhook signature verification mandatory
- Live keys in Railway env (never in code)
- Stripe Radar (built-in fraud detection)
- Kill switch (`STRIPE_KILL_SWITCH`) for instant pause

---

### 4. Anthropic PBC

**Service:** Claude Haiku for OCR fallback + Claude for tax Q&A chat (paid plans only)
**Data shared:** Receipt images (when OCR weak), text snippets, tax questions

| Axis | Score | Notes |
|---|---|---|
| Data sensitivity | 4 | Receipt images may contain IBAN, addresses, business names |
| Vendor reach | 2 | Major AI lab, growing enterprise adoption |
| Compliance | 2 | SOC 2 Type 2; EU-US DPF certified; no ISO 27001 yet |
| Geographic | 3 | US-based; SCCs + DPF for EU data transfer |
| Replaceability | 3 | OpenAI / Google Gemini / Mistral are alternatives — 1 week migration |

**Composite:** 2.8 / 5
**Action:** Acceptable. Monitor compliance roadmap.

**Risk mitigations:**
- AI_OCR_FALLBACK kill switch (`AI_OCR_FALLBACK=0`)
- Anthropic does NOT train on user data (explicit policy)
- Daily user quotas prevent runaway costs
- Receipt images are not stored at Anthropic (transient inference)
- Sensitive customer data (passwords, full IBAN match) never sent

---

### 5. OCR.space (a9t9 Software GmbH)

**Service:** Cloud OCR fallback (between local Tesseract and Claude)
**Data shared:** Receipt image content for OCR processing

| Axis | Score | Notes |
|---|---|---|
| Data sensitivity | 3 | Receipt images |
| Vendor reach | 3 | Smaller vendor, less enterprise traction |
| Compliance | 3 | German company (privacy-friendly), no specific certifications |
| Geographic | 1 | Germany / EU |
| Replaceability | 2 | Google Cloud Vision / AWS Textract alternatives |

**Composite:** 2.4 / 5
**Action:** Acceptable. Lower-priority for migration.

**Risk mitigations:**
- Used only as fallback (most OCR done locally with Tesseract)
- OCR_API_KEY rotation on suspected compromise
- Images sent over HTTPS only

---

### 6. Resend

**Service:** Transactional email delivery
**Data shared:** Recipient email addresses + message content (verification links, reminders, invoice PDFs)

| Axis | Score | Notes |
|---|---|---|
| Data sensitivity | 2 | Email metadata + content (no passwords) |
| Vendor reach | 3 | Modern entrant, growing |
| Compliance | 2 | SOC 2 Type 2; EU-US DPF (in progress) |
| Geographic | 3 | US-based |
| Replaceability | 1 | SendGrid / Postmark / SES — 1 day swap |

**Composite:** 2.2 / 5
**Action:** Acceptable. Monitor EU DPF certification finalization.

**Risk mitigations:**
- API key in Railway env only
- SPF + DKIM + DMARC configured to prevent spoofing
- Email logs retained per Resend's policy
- Domain restricted to `noreply@autotax.cloud`

---

### 7. Telegram Messenger Inc.

**Service:** Optional bot notifications (per-user opt-in)
**Data shared:** Only what user explicitly sends to the bot + reminders configured

| Axis | Score | Notes |
|---|---|---|
| Data sensitivity | 2 | User-initiated, opt-in only |
| Vendor reach | 1 | Billions of users; mature platform |
| Compliance | 4 | No major Western enterprise certifications |
| Geographic | 5 | UAE / UK / undisclosed servers |
| Replaceability | 1 | Discord / WhatsApp / SMS alternatives |

**Composite:** 2.6 / 5
**Action:** Use is opt-in only; acceptable when user explicitly chooses.

**Risk mitigations:**
- User must explicitly enable Telegram binding
- Bot can be unbound at any time
- Sensitive PII never sent via Telegram (just reminders / alerts)
- Webhook secret token check
- TELEGRAM_TOKEN kill switch (clear env)

---

## Composite risk map

| Vendor | Composite | Status |
|---|---|---|
| Cloudflare | 1.8 | ✅ Low risk |
| Resend | 2.2 | ✅ Acceptable |
| Stripe | 2.4 | ✅ Acceptable |
| OCR.space | 2.4 | ✅ Acceptable |
| Telegram | 2.6 | ✅ Acceptable (opt-in) |
| Anthropic | 2.8 | ✅ Acceptable |
| Railway | 3.0 | ⚠️ Monitor (migration path documented) |

**Highest risk:** Railway (3.0). Below action threshold (3.5). No immediate mitigation required but contingency plan exists.

---

## Vendor offboarding checklist

When discontinuing a vendor:

1. Revoke API keys / credentials
2. Confirm vendor deletes our data per their retention policy
3. Update DNS / env vars
4. Remove from `PRIVACY_POLICY.md` processor list
5. Update this `VENDOR_RISK_ASSESSMENT.md`
6. Notify users if data subjects affected (Art. 28(3)(h))

---

## Review history

- 2026-05-28: Initial vendor risk assessment (7 vendors)
- Next review: 2027-05-28 (annual)
