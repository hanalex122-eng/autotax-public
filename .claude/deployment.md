# Deployment runbook

## Where it runs

- **Platform:** Railway
- **Project:** `tranquil-forgiveness` (URL contains `b0a162f8-fed5-4b3b-bbac-ecd0fd2bab90`)
- **Service:** `AutoTax-Hub` (Python app, GitHub-connected to `autotax-public` repo)
- **Domain:** `autotax.cloud` (primary), Railway-provided `*.up.railway.app` (fallback)
- **Sibling service:** `autotax-public` (separate Railway service at `ai.autotaxhub.de` — not active production)
- **Database:** `Postgres` Railway service, PostgreSQL 18, internal hostname only (public networking disabled).

## Auto-deploy

Push to `main` branch on GitHub → Railway detects → builds Docker → deploys.

Build time: ~5-7 minutes (apt-get postgresql-client-18 from PGDG repo is the slow step).

During redeploy:
- 30-60 second 502 window while new container starts and old one shuts down.
- Verify post-deploy via `/health` (uptime should be < 60s right after).

## Required env vars

See `CLAUDE.md` "Live integrations" section. Add via Railway → AutoTax-Hub → Variables.

For new env vars in code:
1. Read with `os.getenv("NAME", "default")`.
2. Default should be safe / no-op (so missing env doesn't break).
3. Add to `CLAUDE.md` env list.
4. Add Railway env var.
5. Push code → Railway picks up env var on next deploy.

## Database migrations

Currently NO formal migration system (Alembic exists but not actively used). New columns added via:
1. Add field to SQLAlchemy model.
2. Run `init_db()` on startup which calls `Base.metadata.create_all` — adds missing tables but NOT missing columns.
3. For column adds: manual `ALTER TABLE` via psql (Railway → Postgres → Connect → Query).

**Recommendation:** When time permits, add Alembic migrations for schema changes. Until then, schema additions need manual coordination.

## Backup & restore

Backups run weekly Monday 04:00 UTC (configurable via `BACKUP_INTERVAL_HOURS`).

**Manual backup:**
```
POST /admin/backup/run
Headers: Authorization: Bearer <admin-jwt>
```
Returns `{ok: true, filename, gz_size_mb, ...}`.

**Restore:**
1. Download `.dump.gz` from R2 bucket `autotax-backups-de` (Cloudflare dashboard).
2. `gunzip` to get `.dump`.
3. Connect to target DB with `psql` or use `pg_restore`:
   ```
   pg_restore -h <PUBLIC_HOST> -p <PORT> -U postgres -d railway --clean --if-exists <file>.dump
   ```
4. Restart AutoTax-Hub service after restore.

Note: Public networking on Postgres is currently disabled. To restore externally, temporarily enable public networking (Railway Postgres → Settings → Networking).

## Rollback

If a deploy breaks production:
1. Railway dashboard → AutoTax-Hub → Deployments → previous successful deploy → "Redeploy".
2. Or git revert + push: `git revert HEAD && git push`.

Rollback to a working commit takes 5-7 minutes (full Docker rebuild).

## Kill switches

Quick disables without code change:

| Env var | Set to | Effect |
|---|---|---|
| `STRIPE_SECRET_KEY` | "" (empty) | Disables all `/billing/*` endpoints (503). |
| `AI_OCR_FALLBACK` | `0` | Disables Claude OCR fallback. |
| `EMAIL_AUTO_SYNC_ENABLED` | `0` | Stops IMAP background sync. |
| `R2_BACKUP_ENABLED` | `0` | Skips backup loop (won't write to R2). |
| `DEFAULT_REGISTRATION_PLAN` | `free` | New users go to free plan (anti-abuse default). |
| `ANTHROPIC_API_KEY` | "" (empty) | Disables all AI features. |

## Common operational issues

| Symptom | Likely cause | Check |
|---|---|---|
| 502 on every request | Container crashed | Railway → Logs (look for startup error) |
| 502 intermittent | Deploy rollover | Wait 30-60s |
| `/health` `db.connected: false` | DATABASE_URL wrong | Railway → Variables → DATABASE_URL exists |
| Stripe checkout 502 | Wrong sk_live_ or price_ID | Stripe Dashboard logs → look for last failed request |
| Backup loop not firing | Container restart resets initial delay | Wait 5+ minutes after restart |
| pg_dump version mismatch | postgresql-client out of date | Update Dockerfile, redeploy |

## Domain & DNS

`autotax.cloud` DNS managed via Cloudflare. A/AAAA records point to Railway edge.

Cloudflare proxying is **disabled** for this domain (orange cloud OFF) to avoid double-proxy issues with Railway. Direct Railway TLS is used.

## SSL/TLS

Railway auto-provisions Let's Encrypt cert for `autotax.cloud`. HSTS header (`max-age=63072000; includeSubDomains; preload`) sets 2-year browser pinning.

Cert auto-renews. No action needed.

## Observability

- **Logs:** Railway dashboard → AutoTax-Hub → Deployments → Logs (live tail + history).
- **Uptime monitor:** Separate Railway service (`uptime-bot-production-7c87.up.railway.app`) sends Telegram alerts on UP/DOWN events.
- **Health checks:** `GET /health` returns JSON. Used by Railway internal checks (`HEAD /health 200`).
- **Sentry:** Not yet wired (`sentry_configured: false`). Adding `SENTRY_DSN` env var enables.
- **Backup alerts:** Telegram message on each backup completion (`✅ AutoTax DB Backup OK`).

## Scaling

Current: 1 instance, 1 vCPU, default RAM.

Vertical scaling: Railway dashboard → AutoTax-Hub → Settings → Resources.

Horizontal scaling not supported with current design (in-memory rate limit counters, in-memory session-style state). Would need:
- Redis for rate limit counters.
- Sticky sessions or shared session store.

For 1-100 customers: vertical scaling is enough.
For 1000+: revisit horizontal architecture.

## Cost expectations

- Railway Hobby plan: ~$5-15/month at current scale.
- PostgreSQL: ~$5-10/month.
- Cloudflare R2: $0/year (free tier, ~5 GB/year actual usage).
- Stripe: 1.5% + €0.25 per transaction (EU card).
- Anthropic: pay-per-token, ~€0.05-0.10 per AI OCR invoice.
- Resend: free tier 3k emails/month.
- Telegram: free.

Estimate for 10 customers: ~€30-50/month operating cost.
