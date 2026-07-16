# Sprint 3 — Final Report (v1.0) · Allocation Engine (Personenzahl · Individuell · Eigennutzung)

**Status:** ready to close — code + tests + docs complete; single production deploy pending the
Go/No-Go run below (no deploy while the user is active on prod).
**Engine suite:** 71/71 · **Full suite:** 40/40 · **JSX:** PARSE OK / BALANCED · **Schema:** one
additive nullable column (`ImmoUnit.eigennutzung_personen`).

---

## 1. The purpose of Sprint 3

Sprint 2 shipped the Nebenkostenabrechnung with **Wohnfläche** and **Wohneinheiten** working; the other
three Umlageschlüssel were stored but fell back to Wohnfläche with a note. Sprint 3 turns the
**Allocation Engine** into a real per-tenant calculator for the keys a small landlord actually needs:

- **Personenzahl** — split water/Abwasser/Müll by persons per flat × Zeitanteil (single-meter houses).
- **Individuell** — the landlord assigns an exact euro per tenant (sub-meter readings, special deals).
- **Eigennutzung** — when the owner lives in the building, count them in the person split so the tenants
  are not over-charged — without ever turning the owner into a tenant/debtor.

The user's one-line test throughout: *"I enter the invoice total once; the program reads the data and
splits it per tenant."* That is now true for 4 of the 5 keys.

---

## 2. Architecture decisions (see nk_architecture.md → "Sprint 3 decisions")

### 2.1 Eigennutzung = model B (unit column, NOT a fake tenancy) — BINDING
`ImmoUnit.eigennutzung_personen` (INT, nullable). The owner is not a tenant, never enters Mietkonto /
Mahnung / Mieteingang / debt. Eigennutzung is **allocation master data, not an accounting event** —
which is *more* aligned with the Single-Ledger law than the rejected occupant model (that would have
created a Tenancy needing suppression in ~20 rent/debt queries — phantom-debtor risk). Rationale locked
by the product owner; behaviour locked by tests.

### 2.2 Three locked Eigennutzung behaviours
1. Owner lives in (persons > 0) → in the Personenzahl denominator; share → **Eigennutzung** bucket.
2. Owner absent (unset) → 0 persons; person-key empty flat adds no cost, no Eigennutzung share.
3. **Eigennutzung ≠ Leerstand** — separate buckets that coexist. Invariant
   `Σ tenants + Eigennutzung + Leerstand == umlagefähige total` in every case.

### 2.3 Individuell reads its stored map (no fallback)
`NkKostenposition.individuell` JSON `{tenancy_id: betrag}` now drives the split: exact euro per tenant,
unassigned rest → landlord, over-assignment → scaled to invoice + note, empty → landlord + note.

### 2.4 CALCULATION_VERSION 2 → 3
Output changed for Individuell lines. Old finalised v1/v2 statements keep rendering from their frozen
snapshot (Principle A) — the bump only affects newly finalised statements.

### 2.5 Deviation from "code-only", deliberately accepted
Sprint 3's original scope said "no schema change". Eigennutzung required **one** additive+nullable
column because an owner-occupied flat has no tenancy, so its person count had no home and cannot be
derived. Added via boot-time ALTER, no backfill. This is the only schema change in the sprint.

---

## 3. Completed commits

| # | Commit | What |
|---|--------|------|
| C1 | `16a3bb5` | Personenzahl allocation engine (rules-only, deployed in the earlier partial close) |
| C2 | `a4fb6bb` | Enter Personenzahl right in the Nebenkosten screen (in-context UI) |
| C3 | `2b1f382` | Eigennutzung — owner-occupied flats counted in the split (model B, +schema column) |
| C4 | `3217cb7` | Individuell allocation — exact amount per tenant + Schlüssel-driven dynamic form |
| C5 | `a8897a9` | Lock the three Eigennutzung behaviours as regression tests |
| C6 | this deploy | docs (this report, nk_architecture D1–D3, SPRINT.md) + production deploy |

---

## 4. Database changes

**One additive, nullable column — no backfill, no migration tool:**

| Table | Column | Type | Purpose |
|-------|--------|------|---------|
| `immo_unit` | `eigennutzung_personen` | INTEGER NULL | persons in an owner-occupied flat (Eigennutzung) |

Applied at boot in `db.py` under an `if col not in existing_columns` guard (idempotent). `mea`,
`personenzahl`, `individuell`, `verbrauch_art` all already existed from Sprint 2's forward-looking
schema — Personenzahl and Individuell needed **no** schema change.

Rollback: dropping the column is safe (nullable, only read by the NK engine); no data rollback needed.

---

## 5. Test summary

- **Allocation engine** (`test_immo_nk_personenzahl.py`) — **71/71**. Covers: Personenzahl core split,
  Zeitanteil, missing-person fallback naming the tenant, mixed statements, the three Eigennutzung
  behaviours `[Eig]/[Eig-2]/[Eig-3]`, and Individuell `[10]–[14]` (exact / remainder→landlord /
  over-assignment scaling+note / empty+note / snapshot fidelity / no-fallback proof).
- **NK API** (`test_immo_nk_api.py`) — 30/30 (+ version bump to 3).
- **Full suite** — **40/40 test files green.**
- **JSX** — `_babelcheck.js` PARSE OK, `check_jsx_structure.py` BALANCED.
- **API round-trip** — `_dump_individuell` → `_parse_individuell` → `verteile` verified end-to-end
  (int keys, floats, zero/empty dropped); `_pos_dict` and the snapshot expose/freeze the map.

**The 5 Umlageschlüssel after Sprint 3:**

| Key | Reads | Computes | Fallback | Status |
|-----|-------|----------|----------|--------|
| Wohnfläche | `ImmoUnit.wohnflaeche` (mea override) | ✅ | — | ✅ done |
| Wohneinheiten | equal per occupied unit × Zeitanteil | ✅ | — | ✅ done |
| Personenzahl | `ImmoTenancy.personenzahl` (+ Eigennutzung) | ✅ | — | ✅ done |
| Individuell | `NkKostenposition.individuell` JSON | ✅ | — | ✅ done |
| Verbrauch | (no meter data yet) | ❌ | Wohnfläche + note | ⏭ Sprint 4 / HeizkostenV |

**4 of 5 fully automatic; Verbrauch consciously deferred.**

---

## 6. UX delivered

- Nebenkosten moved out of the property Details tab into its own **sidebar menu** with a name-first
  property picker.
- The cost grid is now an **open, Schlüssel-driven dynamic form**: all categories visible at once;
  choosing *Individuell* on a line opens a per-tenant amount table (live "distributed / invoice" sum);
  choosing *Verbrauch* shows the Sprint-4 deferral note; the *Personen* section opens only when a line
  uses *Personenzahl*; owner-occupied flats appear there as "🏠 Vermieter (Eigennutzung)".
- The result card shows the **Eigennutzung** share and the **Leerstand** share as separate lines.

---

## 7. Deliberately NOT done (→ Sprint 4)

- **Verbrauch engine** — metered consumption split (Zählerstände already stored since Sprint 1) under
  the HeizkostenV ≥50%-consumption rule. A separate legal/architecture design.
- **OCR auto-fill** of cost lines from receipts.
- Consolidating the user's own building data (two properties at one address → one property + 3 units)
  — a data operation on production, to be done separately with explicit confirmation.

---

## 8. Go / No-Go — to be run at deploy (schema change present)

1. **Backup** — SHA256 fingerprint of the core business tables (pre-deploy).
2. **Migration verify** — after restart, `eigennutzung_personen` exists on `immo_unit`; core tables
   SHA256-identical (only the additive column added).
3. **Rollback ready** — previous commit noted; column drop is safe.
4. **Smoke** — the 4-persons-owner + 2-tenants water scenario returns 211,17 / 211,17 / Eig 844,67;
   an Individuell line bills the exact entered amounts.
5. **Regression** — Sprint 0/1/2 + Wohnfläche/Wohneinheiten NK unchanged; owner absent from Mietkonto /
   Mahnung / Mieteingang.
6. Do NOT touch the owner's real production NK drafts (user_id = 1).
