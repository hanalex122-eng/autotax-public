# Sprint 2 — Final Report (v1.0) · Nebenkostenabrechnung

**Master reference document.** Read this before starting Sprint 3.
Status: **CLOSED** · deployed `0c001c4` (2026-07-15) · production Go/No-Go checklist fully green ·
suite 39/39 · smoke 12/12 · regression 9/9 · all existing business data byte-for-byte unchanged.
Masterplan #8 (⭐⭐⭐) done for its Faz-1 scope.

---

## 1. The purpose of Sprint 2

**Initial goal.** Let a small German landlord (1–20 units) produce a **legally usable annual
utility-cost statement** (Betriebs-/Nebenkostenabrechnung, §556 BGB) for each tenant — inside AutoTax,
without Excel, without paying a Steuerberater/Hausverwaltung 80–250 €/statement — and get a per-tenant
PDF with the correct share, the advance offset, and the Guthaben/Nachzahlung.

**Why it was necessary.**
- It is the highest-value landlord feature (Masterplan ⭐⭐⭐). A landlord does this once a year and it
  is the single most error-prone, time-consuming task (typically 1–3 h in Excel for 3 flats).
- The errors that invalidate a statement are exactly the ones software should prevent: passing on a
  non-umlagefähige cost (repair/management), mis-computing the Zeitanteil for a mid-year move, or
  redistributing a vacant flat's share onto the other tenants.
- It was **unblocked precisely by Sprint 0 and Sprint 1**: Sprint 0 made the NK advance
  (`monat_nk_soll`) a correct, single-source per-month value; Sprint 1 added the meter readings that
  Heizkosten/Wasser will later be split by. Building NK earlier would have meant inventing a second
  advance source — a fourth truth.
- The explicit mandate was **correctness and extensibility over speed**: the database had to support
  Heizkosten and every allocation key from day one so Sprint 3 is code-only.

---

## 2. Architecture decisions

Three of these are **binding principles** (recorded in CLAUDE.md and `.claude/nk_architecture.md`) —
they govern every future change, not just Sprint 2.

### 2.1 Immutable Settlement Snapshot (Principle A)
A finalised statement freezes **every value used in the calculation** into `NkAbrechnung.ergebnis_snapshot`
(JSON): period, property, per-unit (wohnflaeche, mea), per-tenant (name, von/bis, personenzahl,
**Zeitanteil**), each cost line, the **exact allocation ratio per tenant per line**, tenant shares,
the Vorauszahlungen (and the monat_nk_soll they came from), the Leerstand share, the final result, a
`calculation_version`, and the timestamp.
- **The snapshot — not the PDF — is the record of truth.** A final statement is read from the
  snapshot, never recomputed. The PDF is only a rendering of the snapshot.
- **Why it matters:** years later, even if rent/area/tenancy dates/categories have changed, the same
  statement re-produces identically. `calculation_version` means a future engine change can never
  silently alter an old statement. Proven in production: after finalising, a tenant's `nk_voraus` was
  changed to 999 and the finalised statement still showed the frozen 490.

### 2.2 Finalize = Lock (Principle B)
Finalise is a **legal act that locks the calculation**, not "make a PDF". After finalise, every write
is refused with **409** (add/edit/delete cost line, edit period, delete statement). The only way to
correct is an explicit **Entsperren** (final → entwurf, snapshot cleared) or a new statement.
- **Why it matters:** a statement the tenant can dispute must be stable evidence. The lock is the same
  discipline as the Übergabeprotokoll (Sprint 1) — one shared rule across the module.

### 2.3 Single-Ledger Principle (Principle C)
> An economic event is represented in exactly one place in the system.

The NK **Vorauszahlung is computed only from `immo_rules.monat_nk_soll`** (the Mietkonto). There is no
second advance field, source or table. Proven by test: `vorauszahlung() == Σ monat_nk_soll`.
- **Why it matters:** the statement and the Mietkonto can never disagree about how much advance was
  charged. This is the "one accounting model" law (Sprint 0) applied to NK. It also governs the future
  Nachzahlung: posting a Nachforderung will go through the one Payment Service, never a parallel write.

### 2.4 Umlageschlüssel design
`NkKostenposition.schluessel` is an enum with **all five methods present from day one**:
`wohnflaeche · personenzahl · wohneinheiten · verbrauch · individuell`. Sprint 2 **computes**
wohnflaeche and wohneinheiten. The others are valid, storable values that **fall back to Wohnfläche
with a visible note** until wired in Sprint 3 — never a silent wrong split. The umlagefähig knowledge
lives in the rules module (`KATEGORIEN`): repairs/management/Rücklage/financing default **OFF**; the
BetrKV operating costs **ON**; `umlage_pct` handles the mixed Hausmeister case.

### 2.5 Extensibility (Heizkosten, Personenzahl, …)
The database is complete now so Sprint 3 needs **no migration/redesign**:
- `kategorie` is a **string**, not a DB enum → a new category never needs a migration.
- the full Schlüssel enum is in place.
- the **basis data for every future key exists**: `ImmoTenancy.personenzahl` (Personenzahl),
  `ImmoUnit.mea` (agreed key / WEG), `NkKostenposition.verbrauch_art` (links a Heizkosten line to a
  meter type — the readings already exist from Sprint 1), `NkKostenposition.individuell` (JSON).
- Turning on personenzahl/verbrauch/individuell in Sprint 3 is **rules-module code only.**

---

## 3. Completed commits

### C1 — `6ca8983` · foundation (schema + rules, no endpoint/UI)
- **Purpose:** lay the complete, extensible data model and the pure calculation core.
- **What changed:** 2 new tables (`nk_abrechnung`, `nk_kostenposition`) + `ImmoTenancy.personenzahl`
  + `ImmoUnit.mea`; boot-time ALTER in `db.py`; `autotax/immo_nebenkosten.py` — the pure rules
  (umlagefähig knowledge, `verteile`, `zeitanteil`, Leerstand bucket, `ergebnis`, `vorauszahlung`,
  `build_snapshot`, `frist_ueberschritten`). Test: `test_immo_nk_rules.py` (57 assertions).
- **Why it matters:** the correctness and extensibility of the whole sprint is set here. The rules are
  DB-free (a test enforces no sqlalchemy/SessionLocal/ORM), so they are testable and re-usable.

### C2 — `ea2e6ad` · endpoints + PDF (API only)
- **Purpose:** expose the rules as a thin API and produce the deliverable PDF.
- **What changed:** 11 endpoints (`/immo/nk` CRUD, `/position` CRUD, `/finalisieren`, `/entsperren`,
  `/pdf`); a FINAL statement is served from the snapshot, a draft is computed live; per-tenant and
  overview PDF (§556 formell ordnungsgemäß). Test: `test_immo_nk_api.py` (27→31 assertions).
- **Why it matters:** this is where Principles A + B are enforced at the boundary — 409 on every write
  to a final statement, snapshot immutability proven end-to-end (change master data → statement does
  not move), Entsperren the only correction path.

### C3 — `437c5db` · Nebenkosten tab (first visible UI)
- **Purpose:** the landlord-facing surface.
- **What changed:** a new "📑 Nebenkosten" tab on the property detail (Immobilien → Details): list of
  statements, cost-line entry with the BetrKV umlagefähig default applied, a "umlegen" toggle, the
  non-umlagefähige lines shown dimmed, result cards per tenant (Guthaben green / Nachzahlung red), the
  Leerstand line, Hinweise + the 12-month warning, Übersicht/per-tenant PDF, Abschließen/Entsperren.
- **Why it matters:** the value becomes usable. The frontend computes nothing — every number is
  backend-derived (Single-Ledger holds at the UI too).

### C4 — `0c001c4` · collect Personenzahl + Umlageschlüssel/% picker + polish
- **Purpose:** start collecting the data the Sprint-3 keys need, and expose the mixed-cost controls.
- **What changed:** `TenancyPatch.personenzahl` + a "👤 Personen" field in the tenant edit (with the
  hint "for the utility-cost split"); an Umlageschlüssel picker and an "umlegen %" input per cost line.
  Test: +4 assertions (personenzahl accepted + returned; personenzahl key stored + Wohnfläche fallback
  note). (Docs commit `7f69253` recorded the Single-Main-Meter scenario in the architecture.)
- **Why it matters:** landlords can enter Personenzahl now; Sprint 3 flips the compute switch with no
  data backfill needed.

### C5 — production deploy (this report)
- Deployed all of the above (`885d44f → 0c001c4`, 7 commits incl. the pending Hilfe/AGB docs
  `b6da075`). Go/No-Go checklist executed and fully green (see §6).

---

## 4. Database changes

**New tables (from `create_all`, empty on deploy):**
- `nk_abrechnung` — one statement per property+period. Columns: `status` (entwurf|final),
  `ergebnis_snapshot` (JSON), `calculation_version`, `finalized_at`, period, notiz, soft-delete.
- `nk_kostenposition` — one cost line. Columns: `kategorie` (**string**), `betrag`, `umlagefaehig`,
  `umlage_pct`, `schluessel`, `verbrauch_art` (S3), `individuell` (S3, JSON), `document_id`,
  `beleg_datum`, notiz, soft-delete.

**New columns (nullable, on existing tables via boot-time ALTER):**
- `immo_tenancy.personenzahl` (INTEGER) — Personenzahl key basis.
- `immo_unit.mea` (DOUBLE PRECISION) — Miteigentumsanteil / agreed key override.

**Migration strategy.** Boot-time in `db.py`: `create_all` for new tables (never touches existing
tables) + guarded `ALTER TABLE … ADD COLUMN` (`if col not in existing_columns`) for the two columns.
Additive and nullable throughout — no data is read, written or transformed. Verified in three
scenarios (fresh install / existing production data / idempotent on repeat) and confirmed in
production: new tables created empty, columns added, **11/11 business tables SHA256-identical
before and after**.

**Why no future migration will be needed.** `kategorie` is a string (new categories = no migration);
the Schlüssel enum already contains all five methods; the basis columns for every future key
(personenzahl, mea, verbrauch_art, individuell) are already present. Sprint 3 (Personenzahl/Verbrauch/
Heizkosten engines) is **rules-module code only**.

---

## 5. Test summary

**Unit (pure rules) — `test_immo_nk_rules.py`, 57 assertions.** umlagefähig defaults; Zeitanteil for
mid-year move in/out; distribution by Wohnfläche/Wohneinheiten; **the invariant**; the Leerstand
bucket; `vorauszahlung == Σ monat_nk_soll`; Guthaben/Nachzahlung; honesty fallbacks (missing area →
flagged, not-yet-wired key → note); the 12-month rule; immutability guard; snapshot completeness;
persistence-free architecture (asserts no sqlalchemy/SessionLocal/ORM in the module).

**API (endpoints + PDF) — `test_immo_nk_api.py`, 31 assertions.** create → cost lines → live result →
finalise → snapshot → **409 on every write to a final statement** → **snapshot immutable when master
data changes afterwards** → PDF from snapshot → Entsperren → live recompute; empty statement refused;
Personenzahl collectable + fallback note.

**Full suite:** 39/39 files green.

**Smoke (production, 12 steps):** create → cost → compute (invariant 1800, Vorauszahlung 840) →
finalise → snapshot → PDF → **409 locked** → change master data → **snapshot unchanged (490 not
999×7)** → **2nd PDF calculation values identical** (core sha `159e489f…`; byte diff is only the PDF
timestamp) → unlock → cleanup. 12/12.

**Regression (production, 9 checks):** Bu Ay/Mieter+summe, Mietkonto, Mahnung+escalation, Berichte
(Rückstand == card, no third book), Dashboard, Übergabe, Zählerstände, **Mieteingang settles the debt
(470→0)**, Immobilien+Accounting. 9/9.

**Invariants proven and held (unit + production):**
- `Σ tenant shares + Leerstand == umlagefähige total`, to the cent. The vacant share is never
  redistributed to the other tenants.
- `Vorauszahlung == Σ monat_nk_soll` (Single-Ledger).
- A finalised statement's numbers == its snapshot, regardless of later master-data changes.

---

## 6. Production verification

**Deploy.** `885d44f → 0c001c4` pushed; Railway auto-deploy; new instance healthy (`/health` `/`
`/app` `/agb` = 200, db connected).

**SHA256 verification.** A pre-deploy fingerprint of 11 business tables (combined `8bbb8b68…`) was
taken. After deploy: new tables present and empty, `personenzahl`/`mea` added, and **every one of the
11 business tables hashes identically** to before. Re-confirmed after all smoke/regression test data
was deleted.

**Rollback plan (ready).** Last safe version `885d44f`. Roll back via Railway "Redeploy" of that
deployment (~1–2 min) or `git revert 885d44f..0c001c4 && push`. **No DB rollback needed** — the new
tables/columns are additive+nullable, ignored by the old code, no data loss.

**Result.** Migration PASS · Smoke PASS · Regression PASS · Rollback YES · **GO**. Deploy complete.

---

## 7. What the system can do now (after Sprint 2)

- Create an annual Nebenkostenabrechnung per property for a chosen year/period.
- Enter cost lines by category, with the correct umlagefähig default applied automatically
  (repairs/management/Rücklage/financing excluded — the landlord is protected from an invalid pass-on).
- Choose the allocation key per line (Wohnfläche / Wohneinheiten compute; the others store + note) and
  split a mixed cost with an "umlegen %".
- Distribute umlagefähige costs across tenants by **Wohnfläche × Zeitanteil**, correctly handling
  mid-year move in/out.
- Carry a **vacant unit's share on the landlord** (never on the other tenants) — shown as a Leerstand
  line, with the exact-total invariant preserved.
- Offset each tenant's advance using the **exact amount the Mietkonto charged** (`monat_nk_soll`), and
  show **Guthaben / Nachzahlung** per tenant.
- Warn when the **§556 III 12-month deadline** is exceeded.
- **Finalise** a statement → freeze an immutable snapshot + lock it; every later write is refused
  (409); the record of truth is the snapshot, not the PDF.
- **Entsperren** a finalised statement (the only correction path) → back to draft, recomputes live.
- Produce a **per-tenant PDF** (share per line, advance, result) and a **landlord overview PDF** (all
  tenants + Leerstand), formell ordnungsgemäß (§556), from the landlord's Firmen letterhead + IBAN.
- **Collect Personenzahl** per tenant (data ready for Sprint 3's per-person split).

---

## 8. Deliberately NOT done (Sprint 3)

Each is data-ready and rules-stubbed; **none requires a DB redesign.**
- **Personenzahl allocation engine** — the per-person split (esp. the Single-Main-Meter scenario:
  one water meter split by persons for Wasser/Abwasser/Müll). Column + enum already exist.
- **Verbrauch allocation** — split by metered consumption (`verbrauch_zeitraum` from Sprint 1 exists;
  `verbrauch_art` links the line to the meter).
- **HeizkostenV** — the ≥50–70% consumption-based split for Heizung/Warmwasser.
- **OCR auto-classification** — "drop 20 PDFs, we sort them" (`document_id` linkage in place).
- **Techem/ista import** — external Heizkostenabrechnung ingestion.
- **Nachzahlung → Mietkonto** — posting a Nachforderung, **only via the Payment Service** (opt-in),
  never a parallel write.
- Copy-previous-year, multi-object batch, bank matching.

---

## 9. Infrastructure ready for Sprint 3

- **Database:** `nk_abrechnung` / `nk_kostenposition` + `personenzahl`, `mea`, `verbrauch_art`,
  `individuell` — the full model. No migration needed to turn on the deferred keys.
- **Rules:** `immo_nebenkosten.py` already dispatches on `schluessel` in `basis_weight`; the deferred
  branches (personenzahl/verbrauch/individuell) fall back with a note today — Sprint 3 replaces the
  fallback with the real computation, and the invariant/honesty rules already apply to them.
- **Enums:** all five Umlageschlüssel are valid values now.
- **Snapshot:** `build_snapshot` + `calculation_version` are in place. When the engine changes in
  Sprint 3, bump `CALCULATION_VERSION` so old finalised statements keep rendering from their frozen
  snapshot unchanged.
- **Meter data:** `ImmoZaehlerstand` + `verbrauch_zeitraum` (Sprint 1) already provide per-period
  consumption for the Verbrauch/Heizkosten keys.

---

## 10. Lessons learned (principles to preserve)

1. **Snapshot, not PDF, is the record of truth.** Any document with legal weight (statement,
   protocol, dunning) must freeze the data it was computed from. The rendering is disposable; the
   frozen calculation is not. Carry a `calculation_version` so engine changes never rewrite history.
2. **Finalise is a legal lock, not a file export.** A locked document refuses every write (409) and is
   corrected only through an explicit, recorded Unlock or a new revision. Applied identically to the
   Übergabeprotokoll and the NK statement — one rule across the module.
3. **Single-Ledger: one economic event, one representation.** The NK advance is `monat_nk_soll` and
   nothing else. Every time a new surface needs a value that already exists, derive it — never create a
   second source. This is what kept Sprint 2 from adding a fourth truth (Sprint 0 killed the third).
4. **Build the full data model up front; stage the computation.** When the mandate is extensibility,
   pay the schema cost once (all keys, all basis columns) so later sprints are code-only. A nullable
   column added now is free; a migration + backfill later is not.
5. **Never a silent wrong number.** A not-yet-wired key falls back to Wohnfläche **with a visible
   note**; a missing basis (no Wohnfläche) is flagged and carried by the landlord, never divided by
   zero. Honesty over a plausible-but-wrong figure — the same discipline that Sprint 0 spent itself
   establishing.
6. **Correctness is an invariant you can test.** `Σ shares + Leerstand == total` is asserted in the
   unit tests and re-checked in production smoke. Encode the legal correctness (umlagefähig defaults,
   Leerstand → landlord, Zeitanteil) as rules with tests, not as UI hints.
7. **Prove it against production, not just units.** Unit tests run with defaults; production had a
   surprise before (the ledger third book in Sprint 0). The SHA256 before/after fingerprint and the
   full smoke+regression on the live system are non-negotiable gates. The Go/No-Go checklist
   (backup → migration → rollback → smoke → regression) is now the standard for every deploy.
