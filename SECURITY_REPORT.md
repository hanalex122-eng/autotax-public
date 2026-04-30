# AutoTax-HUB Security Audit Report
**Datum:** 13.04.2026  
**Version:** v5.2  
**Auditor:** Automated Security Analysis  

---

## Executive Summary

| Severity | Count | Status |
|----------|-------|--------|
| CRITICAL | 1 | FIX REQUIRED |
| HIGH | 3 | FIX RECOMMENDED |
| MEDIUM | 4 | IMPROVE |
| LOW | 5 | ACCEPTABLE |
| POSITIVE | 12 | OK |

**Overall Rating: 7/10** — Strong data isolation, weak on admin endpoints and CSP.

---

## CRITICAL (1)

### C-1: /admin/reset-password — No Authentication
**File:** `main.py:735`  
**Risk:** Anyone can reset any user's password by knowing their email.  
**Impact:** Complete account takeover.  
**Status:** MUST FIX IMMEDIATELY  

---

## HIGH (3)

### H-1: CSP allows unsafe-inline + unsafe-eval
**File:** `main.py:57`  
**Risk:** XSS attacks can execute arbitrary JavaScript. Defeats CSP purpose.  
**Note:** Required for React/Babel inline compilation — acceptable for current architecture but should be addressed when migrating to build system.

### H-2: JWT_SECRET not enforced at startup
**File:** `auth.py:11-15`  
**Risk:** Random secret on every restart = all tokens invalidated. In multi-instance setup, tokens incompatible between instances.

### H-3: /admin/reparse lacks admin role check
**File:** `main.py:753`  
**Risk:** Any authenticated user can trigger expensive re-parse of all their invoices.

---

## MEDIUM (4)

### M-1: Missing rate limiting on some endpoints
- `/auth/change-password` — brute force risk
- `/bookkeeping/import-*` — DoS via large files
- `/invoices/upload` — DoS via repeated uploads

### M-2: CSV/XLSX formula injection not sanitized
**File:** `main.py:2698+`  
**Risk:** Excel files with `=CMD()` formulas could execute on user's machine when opened.

### M-3: No max row limit on imports
**Risk:** DoS via million-row CSV/XLSX files consuming server memory.

### M-4: Inconsistent file size checks
`/bookkeeping/import-xlsx` doesn't explicitly check MAX_FILE_SIZE.

---

## LOW (5)

### L-1: console.log() debug statements in frontend
**File:** `index.html:307-310` — Exposes auth flow details in browser console.

### L-2: Token in localStorage
Standard SPA pattern, acceptable with HTTPS. Would be stronger with httpOnly cookies.

### L-3: No audit logging table
Basic logging exists but no structured audit trail for GDPR.

### L-4: No file_data encryption at rest
Relies on database-level encryption (Railway PostgreSQL).

### L-5: Password reset flow incomplete
Token generated but no email sending implemented.

---

## POSITIVE FINDINGS (What's Working Well)

| # | Area | Detail |
|---|------|--------|
| 1 | **Data Isolation** | ALL 6 tables have user_id, ALL queries filter by it |
| 2 | **Password Hashing** | bcrypt with salt (industry standard) |
| 3 | **JWT Implementation** | Separate access (60min) + refresh (7d) tokens |
| 4 | **SQL Injection** | SQLAlchemy ORM used everywhere — no raw user input in SQL |
| 5 | **Auth on Endpoints** | Every data endpoint requires get_current_user |
| 6 | **File Validation** | Magic byte checking + size limits + type whitelist |
| 7 | **Security Headers** | HSTS, X-Frame-Options, X-Content-Type-Options |
| 8 | **Soft Delete** | GDPR-compliant data retention |
| 9 | **CORS** | Properly configured, credentials=false (correct for Bearer) |
| 10 | **CSRF** | Not needed — Bearer token auth, not cookies |
| 11 | **Vendor Sanitization** | safe_vendor() strips non-printable chars |
| 12 | **Log Sanitization** | API keys masked, tokens not logged (DSGVO) |

---

## Database Isolation Map

```
User A (id=1)
  ├── invoices       WHERE user_id=1  ✓
  ├── cash_entries   WHERE user_id=1  ✓
  ├── learning_rules WHERE user_id=1  ✓
  ├── user_companies WHERE user_id=1  ✓
  └── llm_usage      WHERE user_id=1  ✓

User B (id=2)
  ├── invoices       WHERE user_id=2  ✓
  ├── cash_entries   WHERE user_id=2  ✓
  ├── learning_rules WHERE user_id=2  ✓
  ├── user_companies WHERE user_id=2  ✓
  └── llm_usage      WHERE user_id=2  ✓

  → No cross-user data access possible ✓
```

---

## Authentication Flow

```
Register → bcrypt hash → DB
Login → verify bcrypt → JWT access (60min) + refresh (7d)
Request → Bearer token → decode_token() → user["sub"]
Refresh → validate refresh JWT → new access token
```

---

## Action Plan

| Priority | Action | Effort |
|----------|--------|--------|
| NOW | Fix /admin/reset-password auth | 5 min |
| NOW | Add admin check to /admin/reparse | 5 min |
| SOON | Add rate limiting to import endpoints | 30 min |
| SOON | Add max row limits to CSV/XLSX imports | 15 min |
| LATER | Migrate to build system (remove unsafe-eval) | Days |
| LATER | Implement email-based password reset | Hours |
| LATER | Add audit logging table | Hours |
