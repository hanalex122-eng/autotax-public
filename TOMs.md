# TOMs — Technische und Organisatorische Maßnahmen

**Technical and Organizational Measures per DSGVO Art. 32**

**Last updated:** 2026-05-28
**Owner / Verantwortlicher:** Hüseyin Hancer, Wiesenstr. 10, 66115 Saarbrücken
**Service:** AutoTax-Cloud (https://autotax.cloud)

This document is referenced by all Auftragsverarbeitungsverträge (AVV) we sign with B2B customers (Steuerberater, businesses with employee data on platform).

---

## 1. Vertraulichkeit (Confidentiality) — Art. 32(1)(b)

### 1.1 Zutrittskontrolle (Physical access control)

| Measure | Status |
|---|---|
| Servers hosted in Railway-managed EU data centers | ✅ |
| No physical infrastructure operated by us | ✅ |
| Operator workstation (Saarbrücken) — password + full-disk encryption | ✅ |
| Backup data in Cloudflare R2 EU-Frankfurt (ISO 27001 certified DC) | ✅ |

### 1.2 Zugangskontrolle (System access control)

| Measure | Status |
|---|---|
| User accounts require email + password (bcrypt, min 8 char + complexity) | ✅ |
| Email verification mandatory for new accounts | ✅ |
| CAPTCHA on registration (Cloudflare Turnstile) | ✅ (env-controlled) |
| JWT-based sessions (access 60 min + refresh 7 d) | ✅ |
| HttpOnly + Secure + SameSite=Strict cookies | ✅ |
| Rate limiting on auth endpoints | ✅ |
| Admin access restricted by ADMIN_EMAILS allowlist + middleware | ✅ |
| Service credentials stored in env vars (never in code) | ✅ |
| Secret rotation policy documented | ✅ (see `ACCESS_CONTROL.md`) |

### 1.3 Zugriffskontrolle (Data access control)

| Measure | Status |
|---|---|
| All DB queries scoped by `user_id` (multi-tenant isolation) | ✅ |
| ORM (SQLAlchemy) prevents SQL injection | ✅ |
| No raw SQL with user input anywhere in codebase | ✅ |
| Advisor (Steuerberater) acting mode = read-only enforced by middleware | ✅ |
| Admin actions logged with user + IP | ✅ |
| Sensitive log fields auto-masked (API keys, DATABASE_URL, JWT) | ✅ |

### 1.4 Trennungskontrolle (Separation of purposes)

| Measure | Status |
|---|---|
| Multi-tenant data separation by `user_id` foreign key | ✅ |
| Test data not mixed with production (separate Stripe test mode used before) | ✅ |
| Backup data segregated by file (one dump per timestamp) | ✅ |

### 1.5 Pseudonymisierung (Pseudonymization) — Art. 32(1)(a)

| Measure | Status |
|---|---|
| Email addresses masked in application logs (`hu***@example.com`) | ✅ |
| IP addresses anonymized (last octet stripped) | ✅ |
| Passwords stored as bcrypt hashes (one-way, irreversible) | ✅ |

---

## 2. Integrität (Integrity) — Art. 32(1)(b)

### 2.1 Weitergabekontrolle (Transmission control)

| Measure | Status |
|---|---|
| All HTTP traffic forced to HTTPS via HSTS (2 years + preload) | ✅ |
| TLS 1.2+ enforced (TLS 1.3 supported) | ✅ |
| Cloudflare SSL/TLS in Full (Strict) mode (end-to-end encryption) | ✅ |
| Inbound webhooks verified with cryptographic signatures (Stripe, AI Reviewer HMAC, Telegram secret) | ✅ |
| Outbound API calls over HTTPS only | ✅ |
| Backup data uploaded to R2 over TLS only | ✅ |

### 2.2 Eingabekontrolle (Input control)

| Measure | Status |
|---|---|
| All user input validated server-side (Pydantic models + custom checks) | ✅ |
| File uploads validated by magic byte detection (not just MIME claim) | ✅ |
| File size limits enforced | ✅ |
| CSV/XLSX exports sanitized against formula injection (=CMD attacks) | ✅ |
| Input length caps on chat / feedback / AI endpoints | ✅ |

---

## 3. Verfügbarkeit + Belastbarkeit (Availability + Resilience) — Art. 32(1)(b/c)

### 3.1 Verfügbarkeitskontrolle (Availability control)

| Measure | Status |
|---|---|
| Production hosting on managed PaaS (Railway) with auto-restart on failure | ✅ |
| Cloudflare DDoS protection + WAF at edge | ✅ |
| Uptime monitoring with Telegram alerts (DOWN within minutes) | ✅ |
| Sentry error tracking + alerting | ✅ |
| Performance metrics tracked via `/health` endpoint | ✅ |

### 3.2 Schnelle Wiederherstellbarkeit (Rapid recoverability) — Art. 32(1)(c)

| Measure | Status |
|---|---|
| Weekly automated backups to off-Railway storage (Cloudflare R2 EU) | ✅ |
| 4-week rolling retention with auto-prune | ✅ |
| RPO ≤ 7 days, RTO ≤ 4 hours | ✅ |
| Restore procedure documented in `BACKUP_POLICY.md` | ✅ |
| Restore drill scheduled quarterly | ✅ (next: 2026-08-25) |
| Kill switches for instant feature isolation | ✅ |

---

## 4. Verfahren zur regelmäßigen Überprüfung — Art. 32(1)(d)

### 4.1 Regelmäßige Sicherheitsaudits

| Measure | Status |
|---|---|
| Internal security audit performed | ✅ (2026-05-26, see `SECURITY_AUDIT.md`) |
| Audit recurrence | 6-month cadence |
| Penetration test by third party | ⏳ Planned for 2026-Q4 (post 10-customer milestone) |
| Dependency vulnerability scan | ✅ pip-audit in GitHub Actions (weekly) |
| Secret leak scan | ✅ TruffleHog in GitHub Actions |

### 4.2 Datenschutz-Folgenabschätzung (DPIA)

A DPIA per Art. 35 DSGVO is **not required** at current scale and processing type (no large-scale special-category data, no public surveillance, no automated decision-making with legal effect). Will be reviewed annually.

---

## 5. Auftragsverarbeiter (Sub-processors) — Art. 28

All sub-processors listed in `VENDOR_RISK_ASSESSMENT.md` and `PRIVACY_POLICY.md`. AVV signed with each:

- Railway Inc.
- Cloudflare, Inc.
- Stripe Payments Europe Ltd.
- Anthropic PBC
- OCR.space / a9t9 Software GmbH
- Resend
- (Telegram opt-in only, not formal sub-processor for compulsory data)

International transfers governed by SCC + EU-US DPF where applicable.

---

## 6. Mitarbeiterverpflichtung (Employee commitments)

Solo operation (Hüseyin Hancer only). When team members are added, each will:

1. Sign Verpflichtungserklärung gem. Art. 28 DSGVO (confidentiality)
2. Sign data protection training acknowledgment
3. Be added to relevant access systems with least-privilege role
4. Be removed and credentials rotated upon departure

---

## 7. Compliance mapping

| DSGVO Article | Requirement | Section above |
|---|---|---|
| Art. 32(1)(a) | Pseudonymisierung + Verschlüsselung | 1.5, 2.1 |
| Art. 32(1)(b) | Vertraulichkeit, Integrität, Verfügbarkeit, Belastbarkeit | 1, 2, 3 |
| Art. 32(1)(c) | Wiederherstellbarkeit | 3.2 |
| Art. 32(1)(d) | Regelmäßige Überprüfung | 4 |
| Art. 28(3)(h) | Audit rights | Available on B2B request |
| ISO 27001 A.5–A.18 | Annex A controls | Partial coverage; full mapping in S5 sprint |

---

## 8. Updates to this document

Changes to TOMs will be:
- Communicated to B2B AVV partners with 30-day notice
- Logged in the change log below

---

## Change log

- 2026-05-28: Initial TOMs document
- 2026-05-25: Backup measure implemented (R2)
- 2026-05-26: Security headers (CSP, HSTS, COOP, CORP) deployed
- 2026-05-26: CSV formula injection prevention deployed
- 2026-05-27: Email verification + password reset email deployed
