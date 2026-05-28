# Privacy Policy / Datenschutzerklärung

**Last updated:** 2026-05-28
**Effective:** From service launch
**Languages:** Live multilingual versions at:
- 🇩🇪 https://autotax.cloud/datenschutz (DE — canonical, legally binding)
- 🇬🇧 https://autotax.cloud/privacy (EN)
- 🇫🇷 https://autotax.cloud/confidentialite (FR)
- 🇪🇸 https://autotax.cloud/privacidad (ES)
- 🇹🇷 https://autotax.cloud/gizlilik (TR)
- 🇸🇦 https://autotax.cloud/khususiyya (AR)

This file is a **repository-accessible reference**. The live `/datenschutz` page is the legally binding source of truth (regenerated from `autotax/legal.py`).

---

## 1. Data Controller (Art. 4 Nr. 7 DSGVO)

```
Hüseyin Hancer
Wiesenstr. 10
66115 Saarbrücken
Deutschland

E-Mail (general):       info@autotax.cloud
E-Mail (data privacy):  datenschutz@autotax.cloud
```

No Data Protection Officer (DPO) is appointed at this time — not legally required at current operational scale.

---

## 2. Data we collect

### 2.1 Account data
- Email address (required for login + verification)
- Password (stored as bcrypt hash — original never accessible)
- Full name (required for invoices, GDPR Art. 6(1)(b) — contract performance)
- Company name (optional)
- IP address (logged for security; anonymized in logs per Art. 25)

### 2.2 Bookkeeping data (uploaded by user)
- Receipt photos / PDFs / scans
- OCR-extracted text and parsed fields (vendor, amount, VAT, date, IBAN, etc.)
- Manual cash book entries
- Categorizations and corrections made by user
- AI evaluation notes (when AI features used)

### 2.3 Payment data (when subscribing)
- Stripe customer ID
- Subscription status + plan
- **Card numbers are NEVER stored by us** — Stripe is PCI-DSS Level 1 certified processor

### 2.4 Communication
- Emails sent to/from `support@autotax.cloud`, `info@autotax.cloud`, etc. (forwarded to operator Gmail)
- Telegram messages (only if user binds Telegram bot in their account)
- Reminder notifications (configurable per user)

### 2.5 Logs (DSGVO Art. 25 — anonymized)
- Request paths and status codes
- Anonymized IP addresses (last octet stripped)
- Masked emails (`hu***@example.com`)
- Stripe webhook events (idempotency tracking)
- Error stack traces (when configured: Sentry)

---

## 3. Legal basis (Art. 6 DSGVO)

| Data | Legal basis | Article |
|---|---|---|
| Account creation | Contract performance | Art. 6(1)(b) |
| Bookkeeping data | Contract performance | Art. 6(1)(b) |
| Email verification | Legitimate interest (abuse prevention) | Art. 6(1)(f) |
| Marketing communication | Consent (opt-in) | Art. 6(1)(a) |
| Payment processing | Contract performance | Art. 6(1)(b) |
| Security logs | Legitimate interest (system security) | Art. 6(1)(f) |
| Compliance (GoBD) | Legal obligation | Art. 6(1)(c) |

---

## 4. Third-party processors

We use the following processors (Auftragsverarbeiter under Art. 28 DSGVO). Each has its own Auftragsverarbeitungsvertrag (AVV) signed with us.

| Processor | Country | Purpose | Data shared |
|---|---|---|---|
| **Railway Inc.** | USA / EU | Hosting (compute + DB) | All operational data |
| **Cloudflare, Inc.** | USA / EU-Frankfurt | DNS, CDN, R2 backup, Email Routing | Routing metadata, backup dumps |
| **Stripe Payments Europe Ltd.** | Ireland | Payment processing | Name, email, IP, payment metadata |
| **Anthropic PBC** | USA | AI OCR fallback + tax Q&A | Receipt images, text excerpts |
| **OCR.space (a9t9 Software GmbH)** | Germany | OCR cloud service | Receipt image data |
| **Resend** | USA | Transactional email | Recipient email, message content |
| **Telegram Messenger Inc.** | UK / UAE | Optional bot notifications | Only if user enables Telegram bind |

### International data transfers

For US-based processors (Stripe, Anthropic, Resend), data transfers are governed by:
- **Standard Contractual Clauses** (Art. 46 DSGVO), and/or
- **EU-US Data Privacy Framework** (DPF certification)

See `VENDOR_RISK_ASSESSMENT.md` for the full risk evaluation per processor.

---

## 5. Retention

| Data | Retention |
|---|---|
| Account data (active) | While account exists |
| Bookkeeping data (legal retention) | **10 years** (§147 AO — Abgabenordnung, GoBD requirement) |
| Bookkeeping data (after account deletion request) | Anonymized after 10 years; user can export full copy any time |
| Logs (operational) | 30 days (Railway / Sentry default) |
| Backup dumps | 4 weeks rolling (see `BACKUP_POLICY.md`) |
| Stripe webhook log | 90 days (idempotency window) |
| Email forwarding metadata | Per Cloudflare retention policy |

---

## 6. User rights (Art. 15-22 DSGVO)

Users have the following rights, exercisable via:
- Account → Daten exportieren (data portability, Art. 20)
- Account → Konto löschen (deletion, Art. 17)
- Email: datenschutz@autotax.cloud

| Right | Article | Implementation |
|---|---|---|
| Information / Access | Art. 15 | "Daten exportieren" button → JSON export |
| Rectification | Art. 16 | Inline edit on every record |
| Erasure | Art. 17 | "Konto löschen" with soft-delete then hard-delete after grace period |
| Restriction | Art. 18 | Email datenschutz@... — manual process |
| Portability | Art. 20 | JSON export + DATEV export |
| Objection | Art. 21 | Email datenschutz@... |
| Complaint to authority | Art. 77 | https://datenschutz.saarland.de/ (Saarländische Aufsichtsbehörde) |

---

## 7. Security measures

Technical and organizational measures per Art. 32 DSGVO are documented in:
- `ACCESS_CONTROL.md` — identity + authorization
- `BACKUP_POLICY.md` — disaster recovery
- `INCIDENT_RESPONSE.md` — incident handling
- `SECURITY_AUDIT.md` — current security posture
- `TOMs.md` — formal Art. 32 TOMs declaration

Highlights:
- TLS 1.2+ in transit (HSTS 2y + preload)
- bcrypt for passwords
- JWT-based stateless auth
- Anonymized logging (Art. 25)
- Off-site encrypted backups
- Webhook signature verification
- Rate limiting + CAPTCHA on registration

---

## 8. Cookies & local storage

| What | Type | Purpose | Duration |
|---|---|---|---|
| `atx_token` | HttpOnly + Secure + SameSite=Strict cookie | Authentication | 1 hour |
| `atx_refresh` | HttpOnly + Secure + SameSite=Strict cookie | Token refresh | 7 days |
| `atx_theme` | localStorage | UI preference (dark/light) | Until manually cleared |
| `atx_token` (legacy) | localStorage | Auth fallback (being phased out) | Until logout |

We do **NOT** use:
- Marketing tracking cookies
- Third-party advertising cookies
- Cross-site tracking
- Fingerprinting

---

## 9. Tax-advice disclaimer

**AutoTax-Cloud is not a Steuerberatung** (tax advisory service) within the meaning of §1 Steuerberatungsgesetz (StBerG).

We provide:
- Technical tools for receipt capture and archiving
- Suggestions ("Vorschlag" / "Empfehlung") for categorization
- DATEV-format exports for Steuerberater

We do NOT provide:
- Binding tax advice
- Legal opinions
- Representation before tax authorities

For tax advice, please consult a licensed Steuerberater.

---

## 10. Children's data

This service is intended for users 18 years or older (Vollgeschäftsfähigkeit). We do not knowingly collect data from minors. If we become aware of such data, it will be deleted.

---

## 11. Changes to this policy

We may update this policy. Material changes will be communicated via:
- In-app notification on next login
- Email to registered users (if substantial)

The "Last updated" date at the top reflects the current version.

---

## 12. Authority / Aufsichtsbehörde

Complaints can be filed with:

**Saarländisches Datenschutzzentrum**
Fritz-Dobisch-Straße 12
66111 Saarbrücken
Tel.: +49 681 94781-0
Web: https://datenschutz.saarland.de/

---

## Document versions

- `2026-05-28`: Repository-accessible mirror created
- `April 2026`: Initial /datenschutz endpoint deployed
- `2026-05-26`: Updated to include Stripe + Cloudflare + Resend + Telegram processors
