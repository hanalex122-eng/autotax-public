# Open Items — P1 / P2 / P3

**Updated:** 2026-06-26 (pre-holiday stabilization sprint)
**State:** production stable, full test suite (31 files) green, health 200,
backup R2 enabled + pg_dump available, working tree clean & pushed.

For the broader roadmap see `NEXT_STEPS.md`. This file tracks the *currently
open* concrete items only.

---

## 🔴 P1 — do first after the holiday (correctness / trust)

- **Orphan-delete bug (Immobilien).** When a unit is deleted, its tenant
  (tenancy) is left orphaned → tenant "sometimes shows, sometimes not"
  (VANELLE reproduced this on 2026-06-25). Deleting a unit must cascade to /
  handle its tenancies. Small, trust-critical. *Not done in this sprint:
  involves production data logic + behaviour change — out of scope for a
  no-feature stabilization pass.*

- **Phase 3 ledger migration APPLY.** Design + dry-run are ready (no-op on the
  founder/pilot data). Must run before onboarding a real landlord with existing
  arrears. Writes to production data → run only while present, not on holiday.

## 🟡 P2 — valuable, low risk (UX clarity)

- **"Bu Ay" should also show tenants who paid** (currently lists only problem
  cases → a new/paid tenant looks missing, "where is Ahmet?").
- **Add-tenant / mark-unpaid entry point** directly from the "Bu Ay" screen.
- **Partial-payment label** on Mietkonto (Teilzahlung indicator).

## 🟢 P3 — cleanup / deferred

- **Legacy Immobilien tabs.** Old "Kira girişi / Gider" tabs confuse the
  exception model (caused the empty-dropdown confusion). Hide / simplify toward
  the houses-vs-tenants split.
- **Untermieter (subtenant) feature.** Model lacks `typ` /
  `parent_tenancy_id`; TDD spec exists (`tests/test_immo_untermieter.py`,
  currently SKIPPED). Implement model + endpoint when prioritized, then remove
  the skip guard.
- **Root-level one-off scripts** (`backfill_*.py`, `dedup_*.py`,
  `aral_check.py`, etc., ~75 untracked files). Harmless local clutter, not in
  git. Move to a `scripts/scratch/` folder or gitignore when convenient.

---

## Rollback / safety reference

- **Production deploy:** Railway auto-deploys `origin/main`. Rollback = redeploy
  a previous deployment from the Railway dashboard, or `git revert <sha>` +
  push.
- **DB backup:** Cloudflare R2 weekly pg_dump, bucket `autotax-backups-de`,
  4-week retention, 168h interval. `pg_dump_available: true` confirmed
  2026-06-26 via `/health`.
- **DB restore drill:** download a `.dump.gz` from R2 → `pg_restore` into a temp
  DB → verify (drill still pending — see `NEXT_STEPS.md` go-criteria #8).
- **Last shipped commit:** `ec1db10` (BuAyView `_L` scope fix). Suite green at
  this commit.
