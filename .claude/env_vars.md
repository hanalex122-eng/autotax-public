# Environment variables reference

All env vars used by autotax-public. Add to Railway → AutoTax-Hub → Variables.

## Required for production

| Name | Type | Purpose |
|---|---|---|
| `DATABASE_URL` | string | PostgreSQL connection string (auto-injected by Railway) |
| `JWT_SECRET` | secret | JWT signing key. **MUST be stable** across restarts (else all tokens invalidate) |
| `STRIPE_SECRET_KEY` | secret `sk_live_...` | Stripe API access |
| `STRIPE_PUBLISHABLE_KEY` | string `pk_live_...` | Stripe client-side |
| `STRIPE_WEBHOOK_SECRET` | secret `whsec_...` | Verify Stripe webhook signatures |
| `STRIPE_PRICE_STARTER` | string `price_1...` | Live Starter €15 product price ID |
| `STRIPE_PRICE_PRO` | string `price_1...` | Live Pro €39 product price ID |
| `STRIPE_PRICE_PREMIUM` | string `price_1...` | Live AI Steuer €89 product price ID |
| `PUBLIC_APP_URL` | URL | `https://autotax.cloud` — used in success/cancel URLs |

## Anti-abuse defaults

| Name | Default | Purpose |
|---|---|---|
| `DEFAULT_REGISTRATION_PLAN` | `free` | Plan assigned to new registrations. Set to `pro` to enable 15-day trial. |
| `TRIAL_DAYS` | `15` | Trial duration if `DEFAULT_REGISTRATION_PLAN=pro` |
| `AI_OCR_FALLBACK` | `1` | Enable Claude Haiku OCR fallback for difficult receipts. Set `0` to kill switch. |

## AI

| Name | Type | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | secret `sk-ant-...` | Claude API (OCR fallback + Steuerberater chat) |
| `AI_OCR_MODEL` | string | Override Claude model. Default `claude-haiku-4-5-20251001`. |
| `AI_REVIEWER_WEBHOOK_URL` | URL | External AI reviewer service callback URL |
| `AI_REVIEWER_SECRET` | secret | HMAC key for AI reviewer webhook verification |

## OCR

| Name | Type | Purpose |
|---|---|---|
| `OCR_API_KEY` | secret | OCR.space API key (cloud OCR fallback after local tesseract) |

## Email

| Name | Type | Purpose |
|---|---|---|
| `RESEND_API_KEY` | secret `re_...` | Resend (transactional email — reminders, invoices, password reset) |
| `RESEND_FROM` | string | From name (e.g., `AutoTax`) |
| `SMTP_HOST` | string | Optional fallback SMTP (Resend preferred) |
| `SMTP_PORT` | int | SMTP port |
| `SMTP_USER` | secret | SMTP username |
| `SMTP_PASS` | secret | SMTP password |
| `SMTP_FROM` | string | From address |
| `EMAIL_AUTO_SYNC_ENABLED` | `0`/`1` | Toggle IMAP background sync (default `1`) |

## Telegram

| Name | Type | Purpose |
|---|---|---|
| `TELEGRAM_TOKEN` (or `TELEGRAM_BOT_TOKEN`) | secret | Bot token for reminders + backup alerts |
| `TELEGRAM_CHAT_ID` | string | Default chat for notifications |
| `TELEGRAM_WEBHOOK_SECRET` | secret | Header secret for incoming webhook verify |

## Backups (R2)

| Name | Type | Purpose |
|---|---|---|
| `R2_BACKUP_ENABLED` | `0`/`1` | Toggle backup loop (default `0`, set `1` to enable) |
| `R2_ACCOUNT_ID` | string | Cloudflare account ID |
| `R2_ACCESS_KEY_ID` | secret | R2 S3-compatible access key |
| `R2_SECRET_ACCESS_KEY` | secret | R2 S3-compatible secret |
| `R2_BUCKET` | string | Bucket name (default `autotax-backups`) |
| `BACKUP_RETENTION_WEEKS` | int | Delete backups older than N weeks (default 4) |
| `BACKUP_INTERVAL_HOURS` | int | Interval between backups (default 168 = weekly) |
| `BACKUP_PG_DUMP_TIMEOUT` | int | pg_dump timeout seconds (default 1200) |

## CAPTCHA (planned)

| Name | Type | Purpose |
|---|---|---|
| `TURNSTILE_SITE_KEY` | string | Cloudflare Turnstile public key (frontend) |
| `TURNSTILE_SECRET_KEY` | secret | Turnstile secret (backend verify) |

## Admin

| Name | Type | Purpose |
|---|---|---|
| `ADMIN_EMAILS` | string | Comma-separated emails with admin access. **Required** for `/admin/*`. |

## CORS / Networking

| Name | Type | Purpose |
|---|---|---|
| `ALLOWED_ORIGINS` | csv | CORS allow-list (default includes Railway preview + autotaxhub.de) |
| `RAILWAY_ENVIRONMENT` | auto | Railway sets to `production` |

## Sentry (planned)

| Name | Type | Purpose |
|---|---|---|
| `SENTRY_DSN` | string | Sentry project DSN |

## Misc / feature flags

| Name | Default | Purpose |
|---|---|---|
| `FEAT_UPLOAD` | `1` | Upload view enabled |
| `FEAT_TABELLE_IMPORT` | `1` | Handwritten table import enabled |
| `FEAT_BELEG_MANUAL` | `1` | Manual receipt entry enabled |
| `FEAT_EDITOR` | `1` | Split-view editor enabled |
| `FEAT_EMAIL_IMPORT` | `1` | IMAP import enabled |
| `FEAT_AI_CHAT` | `1` | AI chat tab enabled |
| `FEAT_HANDWRITING` | `1` | Handwriting OCR mode toggle |
| `PUBLIC_NICHE` | `0` | Niche marker (changes landing/pricing copy) |
| `NICHE_NAME` | "" | Niche product name override |
| `DATA_DIR` | autotax/ dir | Where uploaded files are stored on disk |
| `NOTIFY_WEBHOOK_URL` | "" | External notify forwarder (uptime-bot Telegram relay) |

## Watcher (desktop agent)

| Name | Default | Purpose |
|---|---|---|
| `WATCHER_LATEST_VERSION` | `2.3.0` | Latest desktop agent version |
| `WATCHER_DOWNLOAD_URL` | derived | Override download URL pattern |

## Removal-safe vars (kill switches)

These can be set to empty `""` to disable a feature without code change:

- `STRIPE_SECRET_KEY=""` → All Stripe endpoints return 503.
- `ANTHROPIC_API_KEY=""` → All AI features disabled.
- `RESEND_API_KEY=""` → Email sends silently fail (log warning).
- `TELEGRAM_TOKEN=""` → No Telegram notifications.
- `OCR_API_KEY=""` → OCR.space cloud fallback disabled, only local tesseract.
- `R2_BACKUP_ENABLED="0"` → Backup loop skips entirely.
