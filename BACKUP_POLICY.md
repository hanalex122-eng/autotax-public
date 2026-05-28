# Backup & Disaster Recovery Policy

**Last updated:** 2026-05-28
**Owner:** Hüseyin Hancer (Diensteanbieter)
**Scope:** AutoTax-Cloud production database + uploaded customer files

---

## Backup objectives

| Metric | Target | Current |
|---|---|---|
| **RPO** (Recovery Point Objective) | ≤ 7 days | 7 days (weekly backup) |
| **RTO** (Recovery Time Objective) | ≤ 4 hours | ~30 minutes (single dump restore) |
| **Retention** | 4 weeks rolling | 4 weeks (auto-prune) |
| **Off-site** | Required (different provider from primary) | ✅ Cloudflare R2 (EU/Frankfurt) |

GDPR Art. 32(1)(c) requires the ability to restore availability and access to personal data in a timely manner — this policy satisfies that.

---

## Backup architecture

```
Railway PostgreSQL 18 (production DB)
    │
    │ Weekly Monday 04:00 UTC
    ▼
AutoTax-Hub backend (autotax/backup.py)
    │
    │ pg_dump --format=custom
    ▼
Local /tmp (transient)
    │
    │ gzip -6 compression
    ▼
Cloudflare R2 bucket: autotax-backups-de
    │
    │ S3 PutObject (boto3, EU/Frankfurt region)
    ▼
Telegram notification (success or failure)
```

### Schedule

- **Automatic:** Weekly, configurable via `BACKUP_INTERVAL_HOURS` env (default 168 hours = 7 days)
- **First backup after deploy:** 5 minutes after container startup
- **Manual trigger:** `POST /admin/backup/run` (admin email + Bearer token)

### Retention

- **4 weeks rolling** (configurable via `BACKUP_RETENTION_WEEKS` env, default 4)
- Older backups are auto-pruned by `_prune_old_backups()` at the end of each successful run
- No manual deletion required

### Encryption

- **In transit:** TLS to R2 (HTTPS only)
- **At rest:** Cloudflare R2 default encryption (AES-256)
- **Dump file:** Not separately encrypted — relies on R2 at-rest encryption + IAM access control
  - Future enhancement: Client-side encryption with PGP/age (S2 sprint)

---

## Access control

Only the following identities can read/write backups:

| Identity | Permissions |
|---|---|
| AutoTax-Hub backend (R2 API token) | Object Read & Write on `autotax-backups-de` bucket only |
| Owner (Hüseyin Hancer) | Full R2 admin via Cloudflare account |
| External auditor on request | Time-limited read-only token, max 7 days |

R2 API token scope is **bucket-restricted** (not account-wide), per least-privilege.

---

## Restore procedure

### Quick restore (last good backup)

1. List backups in R2:
   ```
   aws s3 ls s3://autotax-backups-de/ --endpoint-url=https://<ACCOUNT_ID>.r2.cloudflarestorage.com
   ```

2. Download desired dump:
   ```
   aws s3 cp s3://autotax-backups-de/autotax_db_YYYY-MM-DD_HHMMSS.dump.gz . \
       --endpoint-url=https://<ACCOUNT_ID>.r2.cloudflarestorage.com
   ```

3. Decompress:
   ```
   gunzip autotax_db_YYYY-MM-DD_HHMMSS.dump.gz
   ```

4. Restore to Railway PostgreSQL (requires temporary public networking on the database service):
   ```
   pg_restore \
       --host=<RAILWAY_PROXY_HOST> --port=<PORT> \
       --username=postgres --dbname=railway \
       --clean --if-exists \
       autotax_db_YYYY-MM-DD_HHMMSS.dump
   ```

5. Restart AutoTax-Hub service from Railway dashboard.

6. Verify via `/health` and a sample data check (recent invoices visible).

### Point-in-time restore (alternative)

Not supported by current setup. If required:
- Migrate to Neon (free tier includes 7-day PITR) or
- Upgrade to Railway Pro plan (built-in PITR)

---

## Testing

### Restore drill schedule

- **Quarterly** (every 3 months) — restore latest dump to a temporary DB, verify integrity
- **Before any major deploy** — confirm backup from previous day is restorable

### Last drill

| Date | Result | Notes |
|---|---|---|
| 2026-05-25 | ✅ First production backup verified | 415 KB compressed, contains all expected tables |

---

## Failure handling

If the weekly backup loop fails:

1. **Detection:** Telegram receives `❌ AutoTax DB Backup FAILED` with the underlying error.
2. **First response (≤24 h):**
   - Check Railway logs for `Backup: FAILED` lines
   - Common causes: R2 token expired, disk full, pg_dump version mismatch
3. **Fix:** Apply fix → manually trigger `/admin/backup/run` → verify success
4. **Escalation if 3 consecutive failures:** Open incident per `INCIDENT_RESPONSE.md`

---

## Compliance mapping

| Standard | Section | Satisfied by |
|---|---|---|
| GDPR Art. 32(1)(c) | Ability to restore availability + access | Weekly backups, RPO ≤ 7 days |
| GoBD §4 | Datensicherheit + Aufbewahrung | 10-year retention plan + immutable R2 |
| ISO 27001 A.12.3 | Backup | This policy + automated schedule |
| SOC 2 CC6.7 | System backup | This policy + restore drill log |

---

## Long-term archive (10-year retention)

GoBD requires 10-year retention for bookkeeping records. The 4-week rolling backup is for **operational disaster recovery** only.

For long-term legal retention:

- **Customer-side:** Each user's data is exportable via DATEV / CSV / XML. Customers retain their own 10-year archive (legal responsibility is theirs as bookkeeping owner).
- **Provider-side:** Yearly cold-archive snapshot stored in R2 with object lock, encrypted, separate retention policy. **Implementation planned for S5 sprint.**

---

## Change log

- 2026-05-25: Initial weekly R2 backup deployed (commit `e246f59`)
- 2026-05-28: Policy document created
