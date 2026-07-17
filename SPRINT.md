# SPRINT — one active sprint at a time

**Rule:** `Finish > New Features`. See CLAUDE.md → "Sprint discipline". No topic switching, no new
features proposed, until the active sprint passes the Definition of Done below.

---

## Definition of Done (all 8 must be true)

- [ ] Code complete
- [ ] Tests green
- [ ] UX checked (real user flow, not just endpoints)
- [ ] Contradicting legacy flows removed (no two screens telling different truths)
- [ ] Review done
- [ ] Deployed
- [ ] Smoke-tested on production
- [ ] No critical gap left from the user's point of view

---

## NO ACTIVE SPRINT — Nebenkosten Verbrauch Wizard closed & production-verified 2026-07-17

## ✅ SPRINT — Nebenkosten Verbrauch Wizard (in-place) — CLOSED (canlı `f57ad0a`, 2026-07-17)
**Single goal:** the landlord bills consumption without leaving Nebenkosten. "My bill arrived" → enter
the total → Verbrauch → if a meter is missing, an inline panel opens ON THE LINE (missing flats +
"show all") → Anfang/Ende → "Speichern & verteilen" → recomputes in place. No menu trip. Supporting
pieces: allowed-Umlageschlüssel matrix per category (server-validated, Heizkosten locked to
HeizkostenV), data-driven smart default (metered → Verbrauch), Allgemeinstrom fixed to area, standalone
🔢 Zählerstände tab kept as bulk/annual maintenance. Design: `.claude/nk_verbrauch_wizard_ux.md`,
`.claude/nk_schluessel_matrix.md`.

**Go/No-Go (production-verified with a throwaway test building, then HARD-deleted):**
- Migration: **N/A** (no schema change — reuses ImmoZaehlerstand + existing columns).
- Production Health: **PASS** (status ok · db connected).
- Smoke: **PASS** (nk-config allowed-map · State B fallback note when no meters · forbidden key → 400 ·
  enter meters in place → NK recomputes M1 640 / M2 360, no fallback).
- Regression: **PASS** — 7 core tables byte-identical to the pre-deploy baseline; the only delta is one
  owner-created NK draft (nk_abrechnung id 29, property 10) made in the browser during the deploy window
  — real usage, not test residue (test data fully hard-deleted) and not deploy corruption.

> **Bu sprint feature-complete olarak kapatılmıştır. Sonraki değişiklikler yalnızca kritik hata
> düzeltmeleri veya kullanıcı geri bildirimleri sonucunda yapılacaktır.**

Nebenkosten module is now feature-complete. No new features; new ideas → BACKLOG only. This sprint is
not reopened (critical bugs excepted).

## ✅ SPRINT 4 — Verbrauch / Zählerstand engine + HeizkostenV (canlı `15ddc5b`, 2026-07-16)
Metered costs split by ACTUAL consumption (Zählerstände); heating/hot-water obey HeizkostenV (§7):
Grundkosten % by area + Verbrauch % by meter (default 30/70, per-line 30–50, snapshot-frozen). A
moved-out tenant is billed for their real consumption (Zwischenablesung). Missing readings → Wohnfläche
fallback + note. CALC_VERSION 3→4. Report: `.claude/heizkosten_v_architecture.md`.
- Schema: one additive+nullable column `nk_kostenposition.grund_prozent` (boot-ALTER, no backfill).
- Tests: engine 32/32 + **E2E 27/27 through the real API** (create→readings→NK→finalize→PDF). Suite 42/42.
- **Go/No-Go GREEN — production-verified with a throwaway test building (created via API, HARD-deleted):**
  Backup PASS · Migration PASS (grund_prozent added t+210s) · Health PASS · Regression PASS (8 tables
  SHA256 identical) · **Smoke PASS on prod** (Wasser 700→750/510/440 · HeizkostenV 1000→640/360, Grund
  300 + Verbrauch 700 · Finalize+Snapshot: meter 70→9999 after finalise, result stayed 640 · PDF ok) ·
  **Data clean PASS** (after HARD-delete, all 8 core tables byte-identical to the pre-deploy baseline).
- NOTE: prod has 0 Zählerstände — the owner must enter unit meter readings before their own Verbrauch
  lines compute; until then they fall back to Wohnfläche with a note.

## ✅ SPRINT 3 — Allocation Engine (Personenzahl · Individuell · Eigennutzung)
**Engine-only part deployed `16a3bb5` (2026-07-15).** Extension (in-screen UI + Individuell +
Eigennutzung) code+tests+docs complete — closing with ONE production deploy (Go/No-Go below).
Full report: `.claude/sprint3_final_report.md`. Arch decisions: `.claude/nk_architecture.md` → D1–D3.

**4 of 5 Umlageschlüssel now fully automatic** (Wohnfläche · Wohneinheiten · Personenzahl · Individuell):
enter the invoice total once → the engine reads the data and splits per tenant × Zeitanteil.
- **Personenzahl** — persons per flat; vacant flat = 0; missing count → honest Wohnfläche fallback
  naming the tenant. `a4fb6bb` adds the in-screen person entry.
- **Individuell** (`3217cb7`) — exact euro per tenant; rest→landlord; over-assignment scaled+note;
  reads `NkKostenposition.individuell` (no schema change). Schlüssel-driven **dynamic cost form**.
- **Eigennutzung** (`2b1f382`, model B) — owner-occupied flat carries `ImmoUnit.eigennutzung_personen`;
  counted in the person split, borne by the owner, never a tenant/debtor. Eigennutzung ≠ Leerstand.
- Invariant `Σ tenants + Eigennutzung + Leerstand == total` holds for all keys. CALC_VERSION 2 → 3.
- Tests: engine 71/71, full suite 40/40, JSX OK. `a8897a9` locks the 3 Eigennutzung behaviours.
- **Schema:** one additive+nullable column (`immo_unit.eigennutzung_personen`) — the only deviation
  from the original "code-only" scope, deliberately accepted (see report §2.5).
- **Deferred → Sprint 4:** Verbrauch engine + HeizkostenV (separate legal design).

---

## CLOSED — Sprint 3: "Personenzahl Allocation Engine"

**Opened:** 2026-07-15
**Scope (approved):** switch on the Personenzahl allocation key ONLY. Verbrauch = next; HeizkostenV =
a separate later sprint with its own legal/architecture design (no HeizkostenV rules added here).
**Constraints (binding):** NO DB change (use the existing `immo_tenancy.personenzahl`) · keep the
Zeitanteil logic · Leerstand stays with the landlord · the invariant Σ(tenant shares)+Leerstand ==
umlagefähige total holds · Snapshot/Finalize behaviour unchanged · Single-Ledger preserved · all new
computation in the rules layer (`immo_nebenkosten.py`).
**Key design (person-based):** a vacant unit has 0 persons → contributes 0 weight (no invented head
count); the cost is split among the actual occupants by personenzahl × Zeitanteil. If any active
tenant lacks personenzahl, the position falls back to Wohnfläche WITH a note (no silent wrong split).

- [ ] C1 Rules: personenzahl computed in `basis_weight`/`verteile`; bump CALCULATION_VERSION. Unit +
      invariant + regression tests. No DB, no UI change (picker+field already exist from Sprint 2 C4).
- [ ] C2 Deploy + production smoke (single-water-meter statement split by persons) + sprint close.

---

## CLOSED — Sprint 2 and earlier below

## ✅ SPRINT 2 CLOSED (2026-07-15) — full report: `.claude/sprint2_final_report.md`
Deployed `0c001c4` · Go/No-Go fully green (migration/smoke 12-12/regression 9-9/rollback ready) ·
suite 39/39 · all business data SHA256-identical. A landlord can now produce a legally usable
Nebenkostenabrechnung per tenant (Wohnfläche×Zeitanteil + Leerstand → landlord, Vorauszahlung from
`monat_nk_soll`, Guthaben/Nachzahlung, immutable snapshot, finalise=lock, per-tenant + overview PDF).
Personenzahl/Verbrauch/HeizkostenV/OCR are data-ready and deferred to Sprint 3 (code-only, no
migration). Masterplan #8 done for Faz-1.

---

## CLOSED — Sprint 2: "Nebenkostenabrechnung" (Masterplan #8 ⭐⭐⭐)

**Opened:** 2026-07-15
**Goal:** a small landlord produces a legally usable annual utility-cost statement (§556 BGB) per
tenant — inside AutoTax, no Excel, no Steuerberater. NOT expense tracking.
**Architecture (approved):** `.claude/nk_architecture.md` — 3 binding principles: (A) immutable
settlement snapshot is the record of truth, not the PDF; (B) finalise = legal lock; (C) Single-Ledger
— Vorauszahlung only from `monat_nk_soll`. Full DB now; Sprint 2 computes Wohnfläche/Wohneinheiten,
Heizkosten/Personenzahl/Verbrauch/Individuell are data-ready and stubbed (Sprint 3, code-only).

- [x] C1 Schema (2 tables + personenzahl/mea) + `immo_nebenkosten.py` rules + tests (57). No endpoint/UI.
- [ ] C2 Endpoints + per-tenant & overview PDF + tests (final=immutable, umlagefähig defaults, snapshot)
- [ ] C3 Nebenkosten tab: cost entry + result cards + Leerstand card
- [ ] C4 Finalise (freeze snapshot) + PDF + 12-month warning + polish
- [ ] C5 Deploy + production smoke (a real 3-flat statement) + sprint close

**Sprint exit report goes here when closing.**

---

## CLOSED — earlier sprints below

---

## ✅ SPRINT 1 EXIT REPORT — closed 2026-07-15

**Deployed:** `45fa928` · production `/health` ok · **production smoke 17/17 + regression 11/11** ·
suite **37/37** · **all existing business data byte-for-byte unchanged (sha256 before == after)**.

### Completed — a landlord can now do an entire handover inside AutoTax
| Masterplan | What is live | Proof (production) |
|---|---|---|
| **#6 Übergabeprotokoll** ⭐ | 5-step wizard on the tenant screen (Start · Räume · Zähler · Schlüssel · Unterschrift). Rooms pre-filled with their elements, 4-step condition scale, notes, defects derived automatically. | smoke ①②: 5 rooms pre-filled, Mängel derived from a "beschädigt" floor |
| **Fotos** | 📷 opens the phone camera directly; photos are attached per room and downscaled server-side | smoke ③: 186 KB → **11 KB**, EXIF rotation honoured |
| **#7 Zählerstände** ⭐ | Strom/Wasser/Warmwasser/Gas/Heizung with meter number, unit and photo — during the handover AND standalone. History + consumption + bar chart on the tenant screen. | smoke ④⑪: 12345,5 → 13000 kWh = **654,5 kWh derived** |
| **Digitale Unterschriften** | Two canvases signed with the finger. A typed name or an empty canvas is refused. | smoke ⑥ |
| **Lock** | Both signatures → `abgeschlossen`. Every write is refused with **409**: edit, re-sign, add a meter, add a photo, delete. A correction is a new Nachtrag. | smoke ⑨: **5/5 refused** |
| **PDF** | Letterhead · flat + parties · room-by-room table (defects in red) · Mängel list · meter table · keys · photos by room · **both signatures as images** + date | smoke ⑧: 9.4 KB PDF with photo + signatures |
| **#5 Wohnungsgeberbestätigung** | §19 BMG PDF next to a real **"Anmeldung erledigt"** checkbox — the chip existed since the module was written and **no UI could ever tick it** | smoke ⑩: WGB 200 + chip ticked and it sticks |

### Found by the production smoke test (fixed before closing)
- **Mahnung history read backwards** for letters written on the same day (`datum.desc()` had no
  id tiebreak). The dunned amounts were always right; only the order was wrong. Fixed in
  `45fa928`, verified live: 1. Mahnung → Zahlungserinnerung → … newest first.
- (A false alarm worth recording: a smoke assertion marked a FUTURE month unpaid and expected
  debt. The product was right — a month that is not due yet is not debt. The test was wrong.)

### Regression — every existing landlord function still works (rule 5)
Bu Ay/Mieter (+`summe`) · Mietkonto (12 rows) · Mahnung (amount = the card, escalation) ·
Berichte + Dashboard (Rückstand == the card — no third book) · Immobilien · Accounting ·
and the Sprint-0 core: **NK in the Soll (470, not 400)**, previous-month arrears, and a
Mieteingang payment settling the debt (470 → 0). **11/11 green.**

### Deliberately deferred
- E-mailing the protocol/WGB to the tenant → **Sprint 3** (together with the Mahnung e-mail).
- Nachtrag flow (a "correction of" link between two protocols) — the rule is enforced, the
  convenience link is not built.
- Übergabe from the Immobilien screen (today it lives on the tenant, where the landlord looks).

### Open risks
1. Photos live on the Railway disk (830 GB free). A landlord with many handovers will grow it;
   no retention policy exists yet.
2. The signature is a **document signature** (like a scanned one), not a qualified electronic
   signature (QES). The UI does not claim otherwise — keep it that way.
3. Still open from Sprint 0: the ledger's Soll is Kalt-only (audit domain only, no user sees it)
   · the Railway *Postgres* service variables hold an outdated password · the acquisition funnel
   is still broken (landing CTA opens login, not registration).

### Is this sprint really finished?  **YES.**
All eight DoD conditions: code complete · 37/37 tests · UX checked (the wizard is the screen a
landlord uses standing in a flat) · no contradicting legacy flow (the handover is new ground;
the lock makes the document unambiguous) · reviewed commit by commit · deployed · smoke-tested
on production with a complete real workflow · no critical gap in the handover.

**Next: Sprint 2 = Nebenkostenabrechnung** — now genuinely unblocked: NK is tracked as owed
(Sprint 0) and the meter readings that Heizkosten/Wasser must be split by exist (Sprint 1,
`verbrauch_zeitraum()` is already written and tested).

---

## CLOSED — Sprint 1: "Move-in / Move-out Package"

**Opened:** 2026-07-14 (right after Sprint 0 closed)
**Serves:** `VERMIETER_MASTERPLAN.md` #6 Übergabeprotokoll ⭐ · #7 Zählerstände ⭐ · #5 WGB
**Goal (user):** *a landlord must complete an entire tenant handover inside AutoTax* — no Word,
no Excel, no paper, no PDF hunting.
**Scope:** Übergabeprotokoll · Zählerstände · Fotos · digitale Unterschriften · PDF.
**Plan + design:** `.claude/sprint1_plan.md`. **Not in scope:** e-mailing the PDF (Sprint 3).

Next: **Sprint 2 = Nebenkostenabrechnung** · **Sprint 3 = Mahnung improvements + e-mail sending.**
Customer value first, automation second.

- [ ] C1 Schema (immo_protokoll, immo_zaehlerstand, ImmoDocument.protokoll_id/raum) + pure rules
      module + unit tests. No endpoint, no UI, no behaviour change.
- [ ] C2 Endpoints + PDF + tests (incl. "abgeschlossen = immutable")
- [ ] C3 The 5-step wizard UI, phone-first (rooms · meters · keys · signatures)
- [ ] C4 Zählerstände history + consumption chart + WGB step that finally ticks `anmeldung_done`
- [ ] C5 Deploy + production smoke (a real end-to-end handover) + sprint close report

---

## CLOSED — Sprint 0: "Fundament — make Mietkonto tell the truth"

**Opened:** 2026-07-14
**Serves:** `VERMIETER_MASTERPLAN.md` items #1 #2 #3 (marked ✅ there, **not actually done**) and
unblocks #8 Nebenkostenabrechnung.

**Why this one, and not straight to the masterplan's 🔴 items:** the Exception Engine sprint
(2026-06-23…26) shipped at ~80%. The new model was added but the old flows were never removed, so the
product now tells three different truths about the same money (Bu Ay vs. Mieteingang tab vs. Berichte),
and the debt figure itself is wrong (NK missing, previous months + previous years invisible).
Nebenkostenabrechnung (#8, ⭐⭐⭐) sits directly on top of this: it needs a correct Soll incl.
NK-Vorauszahlung. Building #6/#7/#8 on a Mietkonto that miscounts money would mean shipping a second
floor onto a cracked foundation — exactly what "Finish > New Features" forbids.

**Scope (evidence: code review 2026-07-14, file:line in `.claude/immo_finish_review.md`)**

### A. Truth bugs — the product currently lies about money (P0)
- [ ] A1 Arrears from *previous months* are invisible on "Bu Ay" → screen can say "✅ Alles bezahlt"
      while the tenant owes €1.200. (`index.html:2487-2492`, `immo_api.py:1488-1502`)
- [ ] A2 Arrears are year-scoped → unpaid December vanishes on 1 January and cannot be dunned.
      (`immo_api.py:1488-1502`, `190`, `1616`)
- [ ] A3 Nebenkosten not part of Soll → debt and the Mahnung amount are short by the NK every month.
      (`immo_api.py:832-838`, `1520`, `1631` vs `index.html:2685`)
- [ ] A4 Orphan delete: deleting a property/unit leaves its tenants live on Mieter + Bu Ay.
      (`immo_api.py:375-385`, `930-940`, `193-199`) — was OPEN_ITEMS P1
- [ ] A5 Mahnung letter: no tenant address, no concrete deadline date, signed "Die Hausverwaltung"
      instead of the landlord. (`immo_api.py:1627-1636`)

### B. Contradicting legacy flows — DoD condition #4 (P0)
- [ ] B1 **ONE accounting model, many UIs** (user decision 2026-07-14 — Mieteingang is NOT removed).
      Introduce a single **Payment Service**; every payment path is only a UI on top of it:
      "Bezahlt" button · partial payment · Mieteingang tab · (future) bank import.
      All of them write the **Exception Engine** model; every read surface (Bu Ay, Mietkonto, Mahnung
      amount, Berichte, Nebenkosten) derives from it and never recomputes its own truth.
      Today the Mieteingang tab writes ImmoRent rows that change no debt number → payment recorded,
      debt unchanged. (`immo_api.py:1104`, `1505-1508`; `index.html:2914-2921`)
      **Mandatory: never two parallel debt systems.** See CLAUDE.md → "Architecture law".
- [ ] B2 "📊 Berichte" contradicts itself and Bu Ay: Gewinn negative while its own detail list is
      positive, income chart always zero, "Miete Jun fehlt" for tenants Bu Ay calls ✓ sorgenfrei.
      (`immo_api.py:1155-1162`, `1213`, `1319`, `1379-1387`)
- [ ] B3 Dead columns/flags: `auto_paid` (dead, still ALTER TABLE'd every boot), `offene_monate`
      wrongly commented "(dormant)" although it stores the live exception data. (`models.py:918-919`)

### C. UX — the module is unusable/untrustworthy without these (P1)
- [ ] C1 German UI shows Turkish buttons: "✓ Ödendi" / "✗ Ödenmedi" are the primary actions.
      (`index.html:2695-2696`, `2634-2635`)
- [ ] C2 "✗ Ödenmedi" and "📨 Mahnung" fire with no confirmation; Mahnung persists a legal record
      with no way to delete it. (`index.html:2503`, `2696`, `2709`)
- [ ] C3 Error = wrong empty state ("Noch keine Immobilie" on API failure), Berichte hangs on
      "Lädt…" forever, no retry. (`index.html:2785`, `2334`, `2483`)
- [ ] C4 Mahnung is hardcoded `stufe:1` → escalation (2./3. Mahnung) unreachable; Mahnung history
      endpoint exists but has no UI. (`index.html:2486`, `2566`; `immo_api.py:1428`, `1529`)
- [ ] C5 "Dauerzahlung" is never explained *inside* the module — the app assumes rent is paid and
      shows ✓ without telling the landlord. One sentence on Bu Ay + Mieter.
- [ ] C6 Bu Ay (the app's landing screen for every user) is not mobile-aware. (`index.html:2493-2506`)
- [ ] C7 Field hints (3 languages) on Immobilien inputs — user reported the forms are "çok karışık".
- [ ] C8 Tenancy Detail: no year switcher → last year's Mietkonto unreachable. (`index.html:2579`)

---

## ✅ SPRINT 0 EXIT REPORT — closed 2026-07-14

**Deployed:** `32ace6f` · production `/health` ok · **production smoke test 9/9 green** ·
suite **35/35 green** (incl. the ledger flag forced ON).

### Completed
| | What | Proof |
|---|---|---|
| A1 | Arrears from previous months surface — "✅ alles bezahlt" can no longer hide 940 € | smoke 4+5 |
| A2 | Arrears cross the year boundary — unpaid December survives 1 January | test_immo_payment_service |
| A3 | **Nebenkosten are part of the Soll.** Debt + Mahnung = Warmmiete (470, not 400) | smoke 4 |
| A4 | Deleting a property/unit deletes its tenants — no orphans accruing debt | smoke 10 |
| A5 | The Mahnung is a real letter: recipient address, itemised months, concrete deadline date, landlord's IBAN + signature (no more "Die Hausverwaltung") | test_immo_delete_mahnung |
| B1 | **The sprint bug:** a Mieteingang payment now reduces the debt (940 → 470); deleting it restores it | smoke 6+7 |
| B2 | Reports derive from the Exception Engine: no negative Gewinn, no flat-zero income chart, no false "Miete fehlt" | smoke 9 |
| B3 | Dead `auto_paid` documented; `offene_monate` correctly marked as the live debt store | models.py |
| C1–C8 | German buttons, confirm dialogs, loading/error/retry, Dauerzahlung explained in-module, mobile Bu Ay, year selector, 3-language field hints, Mahnung escalation + history | commits 3B/4 |
| — | **Architecture:** Payment Service is the only writer; `PaymentRepository` port (immo_rent today, ledger tomorrow); no frontend computes debt | test_immo_no_third_book |

### Found by the production smoke test (would have shipped otherwise)
**The third book was LIVE.** `IMMO_LEDGER_READ=1` is set in production, and `portfolio_view()`
overwrote the debt fields with the ledger's Kalt-only arrears: the Berichte screen said
**2.800 €** while the Mieter card, Bu Ay and the Mahnung all said **940 €**. Every unit test
passed because they ran with the flag OFF. Fixed in code (`32ace6f`) — the ledger can no
longer be a debt source for any user-facing screen, whatever the environment says. New
regression test forces the flag ON.

### Deliberately deferred
- **Historical Payment Backfill** — dry-run proved 0 HIGH rows and no debt change → skipped (see backlog).
- `auto_paid` column drop (destructive migration).
- Untermieter (TDD spec still skipped).
- Ledger Phase 1+ / cutover.

### Open risks
1. **The ledger's Soll is still Kalt-only** and knows nothing about the exception engine. It
   is now a pure audit domain (`/immo/_ledger/*`), so no user sees it — but it MUST be
   aligned before any ledger cutover, or the third book returns.
2. `IMMO_LEDGER_READ=1` is still set in production. It is now inert for user-facing debt,
   but the variable is misleading — consider removing it.
3. The Railway *Postgres* service variables hold an **outdated password** (the working one is
   in AutoTax-Hub's `DATABASE_URL`) → backup/restore scripts reading them fail silently.
4. The screens were verified through the API and the JSX compiler, **not** by a human looking
   at the rendered UI on a phone. First real landlord session may still surface layout nits.
5. The acquisition funnel is still broken (the landing CTA opens the login form, not
   registration) — out of this sprint's scope, parked in the backlog.

### Is this sprint really finished?  **YES.**
The eight DoD conditions are met: code complete · 35/35 tests green · UX checked · the
contradicting legacy flows are gone (two payment books AND the ledger third book) · reviewed
commit by commit with BEFORE/AFTER evidence · deployed · smoke-tested on production · no
critical gap left in the landlord accounting flow. The residual items above are named, owned
and parked — none of them makes the product tell a landlord a wrong number.

Masterplan #1 #2 #3 are now genuinely ✅. #8 (Nebenkostenabrechnung) is unblocked: the
NK-Vorauszahlung is finally tracked as owed.

---

## BACKLOG — parked, do NOT start before the active sprint closes

### Allgemeinstrom single (building-level) meter field  (user feedback 2026-07-17 — parked)
The landlord asked for an Allgemeinstrom meter field. It would NOT change the NK split (common
electricity has no per-flat measurement → split by Wohnfläche/Wohneinheiten from the total invoice), so
it's a tracking-only building-level reading. Parked to keep the current sprint single-goal; revisit if
the tracking value is confirmed.

### Optional €/Einheit price on a Verbrauch line  (idea 2026-07-17 — NOT this sprint)
Some landlords know only the unit price (e.g. 4 €/m³), not the total invoice. An optional "€/Einheit"
field could compute total = consumption × price. Standard German NK splits the TOTAL by ratio (no price
needed), which is what we ship. Park as a power-user extra; do not add to the daily flow.

### HeizkostenV Exceptions  (deferred 2026-07-16 — needs separate legal design)
The ≤2-unit building where the owner occupies one flat may split heating/hot water FREELY (§2
HeizkostenV) — i.e. Wohnfläche is allowed instead of the mandatory Grund/Verbrauch split. Deliberately
NOT built now: Sprint 4's goal was the general, safe HeizkostenV engine; this is a legal special case.
Standard scenarios must be flawless first. To be handled later under "HeizkostenV Exceptions" with its
own design + legal review. Until then Heizkosten/Warmwasser are locked to Verbrauch (HeizkostenV) for
everyone (safest default). See `.claude/nk_schluessel_matrix.md`.

### Historical Payment Backfill  (decided 2026-07-14: SKIPPED for Sprint 0)
Fill `immo_rent.fuer_jahr` / `fuer_monat` on the 10 pre-Sprint-0 payment rows so that old
payments are attributed to the rent month they settle.

**Why it was skipped:** it delivers no user-visible value today and adds deployment risk.
The read-only dry-run (`scripts/immo_backfill_dryrun_standalone.py`, run against production
2026-07-14) proved it: **0 rows classified HIGH** (the only class that may ever be migrated
automatically), 8 MEDIUM, 2 LOW — and **no tenant's debt would change** (both live tenants
carry no reported exception, so Dauerzahlung already counts those months as paid: 0,00 → 0,00).
Sprint 0's goal is the accounting foundation, not perfect historical metadata.

**When it is picked up** it must be a standalone migration with its own tests:
- classification rule to revisit: a payment booked on day 1–3 is, in German practice, THAT
  month's rent (due by the 3rd working day) — not a late payment for the previous month.
  With that fixed, YURONG's Jan–May rows (400,00 = exact Warmmiete) become HIGH.
- rows that need a human decision regardless:
  - VANELLE id 37: 540,00 paid on 2026-06-25 while June's Soll is 270,00 (vereinbarte
    Erstmiete) → covers more than one month, or includes the deposit.
  - YURONG ids 30 + 32: two identical 400,00 payments on 2026-06-01 → instalments or a
    duplicate row.
  - ids 14 + 31: payments with **no tenancy_id** at all (270,00 / 460,00).
- decide only after real pilot users exist — it may never be worth it.

**Ops finding while running the dry-run (separate small task):** the Railway *Postgres*
service's `PGPASSWORD` / `DATABASE_PUBLIC_URL` hold an OUTDATED password; the working one is
in the *AutoTax-Hub* service's `DATABASE_URL`. Backup/restore scripts that read the Postgres
service vars would fail silently.


### Funnel / conversion (next sprint candidate — evidence in `.claude/immo_finish_review.md`)
- Landing CTAs point to `/app?action=register` but the SPA never reads the param → every visitor
  who clicks "Kostenlos starten" lands on the **login** form. (`index.html:492`)
- Signup screen is in English on a German funnel ("Welcome back", "John Smith"); brand flips from
  AutoTax.Cloud to AutoTax-HUB + BETA badge. (`index.html:615-630`)
- Password rules disagree in 3 places (client ≥6, hint 8+special, backend 8+upper+digit) → 400s.
  (`index.html:557`, `621`; `main.py:5470-5475`)
- Register throws away the returned token and forces a second login. (`index.html:568-569`)
- "14 Tage kostenlos" is advertised but never provisioned (`DEFAULT_REGISTRATION_PLAN=free`,
  `trial_ends_at` only set when default is `pro`). (`main.py:5484-5489`) — also a misleading-ad risk.
- Prices disagree in 4 places (landing 15/39/89 · backend PRICING 9/29 · admin 15/39/89/149 ·
  chatbot "Pro €20"). (`landing.html:872-929`; `main.py:12613-12619`, `5078`, `13157`)
- Stripe kill switch defaults ON → checkout 503 unless `STRIPE_KILL_SWITCH=0` is set. (`billing.py:61`)
- **Zero analytics anywhere** → no funnel step is measurable today.
- Landing never mentions Mahnung / Leerstand / Nebenkostenabrechnung / Kaution / Rückstand — the
  landlord module is invisible to a visitor, while the app is landlord-first for everyone
  (`_initialPage` → "bu_ay" for every user, `index.html:7214-7220`).
- Landing has zero screenshots and zero real testimonials; Impressum e-mail is on a different
  domain (autotaxhub.de) and USt-ID says "wird nachgereicht". (`main.py:2386`)

### Immobilien — deliberately out of this sprint
- Ledger Phase 1+ (backfill/apply). `IMMO_LEDGER_READ` is OFF in prod; the read path is inert.
- Untermieter feature (TDD spec exists and is skipped: `tests/test_immo_untermieter.py`).
- Nebenkostenabrechnung (NK settlement) module.
- Dead endpoints with no UI: `/immo/events` CRUD, `/immo/dashboard`, `/immo/tenancies/{tid}/mahnungen`,
  legacy flat `/immo/tenants`.

### Other
- Premium "invisible strong engine" for the first 5 documents (flag-gated design ready).
- Landing redesign (control-center language, no "AI" hype).
- Root-level one-off scripts (~75 untracked files) → `scripts/scratch/`.
