# Authentication flow

## Token model

- **Access token (JWT, 60 min):** signed with `JWT_SECRET`, claim `sub` = user.id, `email`, `exp`.
- **Refresh token (JWT, 7 days):** longer-lived, used to mint new access tokens.
- **Cookie storage:** `atx_token` (access) + `atx_refresh` (refresh), both `HttpOnly + Secure + SameSite=Strict`.
- **Header storage:** `Authorization: Bearer <access_token>` — primary today (localStorage in frontend).

## Register flow

1. POST `/auth/register` with `{email, password, full_name, gdpr_consent: true}`.
2. Validate: password >= 8, uppercase + digit; GDPR consent required.
3. Check duplicate email → 400 if exists.
4. Determine default plan from `DEFAULT_REGISTRATION_PLAN` env (defaults to `free`).
5. `bcrypt` hash password, insert User row.
6. Auto-create default UserCompany.
7. Optional: send welcome email (Resend, when implemented).
8. Issue access + refresh tokens, set HttpOnly cookies, return body with token (legacy compat).

Rate limit: 3/minute per IP (slowapi).

## Login flow

1. POST `/auth/login` with `{email, password}`.
2. Lookup user, `bcrypt.verify(password, hash)`.
3. On fail: log + audit + 401 generic message (no enumeration).
4. On success: issue tokens, set cookies, return body.

Rate limit: 5/minute per IP (slowapi `@limiter.limit("5/minute")` + manual sliding window).

## Refresh flow

1. POST `/auth/refresh` with refresh token (cookie or body).
2. Validate JWT signature + exp.
3. Issue new access token (refresh stays same).
4. Set cookie.

Rate limit: 10/minute per IP.

## Logout flow

1. POST `/auth/logout`.
2. Clear cookies via `response.delete_cookie`.
3. No server-side session — JWT is stateless, tokens expire naturally.

For paranoid logout (revoke before expiry), would need a JWT blacklist table — not implemented; acceptable for current scale.

## Per-request auth

```python
def get_current_user(request: Request) -> dict:
    # Reads Authorization: Bearer header first, then atx_token cookie.
    # Decodes JWT with JWT_SECRET, returns {"sub": user_id, "email": ...}.
    # Raises 401 if missing/invalid/expired.
```

`get_acting_context(...)` wraps `get_current_user` and additionally handles advisor-mode `X-Acting-Client-Id` header — advisor with mandate sees mandant's data, but writes are blocked by security middleware.

## Admin auth

`/admin/*` paths are gated by middleware at `main.py:188+`:

```python
if path.startswith("/admin/"):
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return 403
    payload = decode_token(token)
    if payload.email not in ADMIN_EMAILS:
        return 403
```

`ADMIN_EMAILS` env var = comma-separated list. Default empty (no admin access until set).

## Password reset (partial)

- `/auth/forgot-password` exists but email delivery not verified in audit. To verify end-to-end:
  1. Request `/auth/forgot-password` with email.
  2. Check Resend dashboard for delivered email.
  3. Use token from email at `/auth/reset-password`.

If broken, fix is small — wire Resend.send() into the existing token generation.

## CSRF

Not needed — Bearer token in Authorization header is not auto-attached by browser (unlike cookies). The HttpOnly cookie path would need CSRF protection but:
- SameSite=Strict mitigates CSRF for cookies in our context.
- Frontend explicitly attaches Bearer; if it switches to cookie-only, add CSRF token on state-changing endpoints.

## XSS surface

CSP allows `'unsafe-inline'` for scripts (Babel requirement). This means any HTML injection vulnerability becomes XSS-exploitable.

Mitigations:
- All user content rendered via React (auto-escapes).
- `dangerouslySetInnerHTML` usage: search codebase before use; no current legitimate uses.
- HttpOnly cookies for tokens (XSS can't read them).
- localStorage tokens ARE readable by XSS — known L-2 risk in SECURITY_AUDIT.

## Token lifetime decisions

- 60 min access: short enough to limit abuse if token leaks.
- 7 days refresh: balance between user convenience (no daily login) and theft window.
- No rolling refresh: refresh token doesn't change on use. For higher security, rotate on each use.

## Sensitive operations beyond JWT

- Stripe Checkout: validated by Stripe-side session (not just our JWT).
- Stripe Customer Portal: validated by Stripe Customer ID lookup.
- Admin backup trigger: requires ADMIN_EMAILS match in addition to JWT.
- Webhook callbacks: NO JWT — instead HMAC or Stripe signature.

## Recommended hardening (deferred)

- Move primary token to HttpOnly cookie (already supported by `_set_auth_cookies`), drop localStorage usage in frontend.
- JWT blacklist or rotation on logout for paranoid scenarios (B2B contracts may require).
- 2FA / WebAuthn / passkeys — future, low priority for current customer profile.
