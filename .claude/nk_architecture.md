# Sprint 2 — Nebenkostenabrechnung: ARCHITECTURE (approval required before any code)

**The goal is NOT expense tracking.** It is a **legally usable Betriebs-/Nebenkostenabrechnung** for
a small German landlord (1–20 units), producing a per-tenant statement that survives a tenant's
objection under §556 BGB.

**Optimise for correctness and extensibility, not speed.** The database defined here must support
Heizkosten (HeizkostenV) and every allocation method **without a later redesign** — even though
Sprint 2 only *computes* Wohnfläche. Everything else is data-ready and stubbed at the rules layer.

Supersedes the MVP simplification in `immo_nebenkosten_mvp_plan.md` on exactly one point: that plan
said "no Personenzahl field, Wohnfläche only, to stay simple." We now add the full data model up
front (Personenzahl, Verbrauch linkage, Individuell) so the foundation is complete. See
§ "Comparison with existing plans" at the end.

Legal grounding (not advice): §556 BGB (12-month deadline + advance offset), §556a BGB (Wohnfläche is
the default key absent agreement), §560 (cost changes), BetrKV §2 (the 17 umlagefähige categories),
HeizkostenV (heat/hot water must be ≥50–70% consumption-based). The statement is a calculation and
preparation tool, not Steuer-/Rechtsberatung (AGB §3 + §4a already state this).

---

## Q1 — What data ALREADY exists (reuse, never re-enter)

| Concept | Where it lives | Ready for NK? |
|---|---|---|
| **Properties** (Objekt) | `ImmoProperty` (adresse, name) | ✅ the statement is per property |
| **Units** (Wohnung) | `ImmoUnit` — **`wohnflaeche`** present | ✅ the Wohnfläche key basis |
| **Tenancies** (Mietverhältnis) | `ImmoTenancy` — **`von`/`bis`** present | ✅ Zeitanteil (mid-year move in/out) |
| **Mietkonto / Payments** | `immo_rent` + `offene_monate` via the Payment Service | ✅ Nachzahlung can later post here through ONE service (law) |
| **Vorauszahlungen** | **`immo_rules.monat_nk_soll(t, y, m)`** — Sprint 0 | ✅ **the NK advance owed per month, pro-rated — the single source** |
| **Meter readings** | `ImmoZaehlerstand` + `immo_rules.verbrauch_zeitraum` — Sprint 1 | ✅ Verbrauch basis (wired in Sprint 3) |
| Receipts + OCR | `ImmoDocument` + storage + existing OCR engine | ✅ receipt behind a cost line (OCR auto-fill = Sprint 3) |
| PDF | reportlab (Mahnung/WGB/Protokoll pattern) | ✅ the per-tenant statement |

**The crucial reuse:** the Vorauszahlung is NOT recomputed. `monat_nk_soll` is what the tenant is
*charged* as NK advance each month (Sprint 0, pro-rated, Mieterhöhung-aware). Using it means the NK
statement and the Mietkonto can never disagree about how much advance was owed — no fourth truth.

## Q2 — What data is still MISSING (added now, additive + nullable, so no future migration)

| Missing | Add to | Why now (extensibility) |
|---|---|---|
| **Personenzahl** per tenancy | `ImmoTenancy.personenzahl` (int, nullable) | the Personenzahl key (Müll is often per person). Collected now, split wired in Sprint 3. Without the column now, Sprint 3 needs a migration + backfill. |
| **Umlage-Anteil / m² agreement override** | `ImmoUnit.mea` (float, nullable — Miteigentumsanteil) | WEG/Eigentümer statements and non-Wohnfläche agreed keys. Optional; nullable. |
| **Which meter type a heat/water cost is split by** | `NkKostenposition.verbrauch_art` (nullable) | links a Heizkosten line to `ImmoZaehlerstand.art`. Readings already exist. |
| **Individual per-tenant amounts** | `NkKostenposition.individuell` (JSON, nullable) `{tenancy_id: betrag}` | the "Individuell" key (e.g. a cost that concerns only one flat). |
| **The statement itself** | 2 new tables (below) | — |

Nothing is added to a table that would change existing behaviour; every new column is nullable.

## Q3 — German operating-cost categories (all supported at the data layer from day 1)

The category is a **string** (not a DB enum), so adding one never needs a migration. The rules module
holds the BetrKV knowledge: the **default umlagefähig** flag and the **default Umlageschlüssel** per
category. Sprint 2 ships all categories for *entry*; the ones needing Verbrauch (heizung/warmwasser)
compute their split in Sprint 3 — until then they distribute by Wohnfläche with a visible note.

| Kategorie | umlagefähig default | default Schlüssel | notes |
|---|---|---|---|
| **heizkosten** (Heizung) | ✅ | **verbrauch** | HeizkostenV ≥50% consumption → full split in Sprint 3; Wohnfläche fallback until then |
| **warmwasser** | ✅ | verbrauch | as above |
| **wasser** (Kaltwasser) | ✅ | wohnflaeche (or verbrauch) | |
| **abwasser** | ✅ | wohnflaeche | |
| **muell** (Müllabfuhr) | ✅ | **personenzahl** (fallback wohnflaeche) | |
| **grundsteuer** | ✅ | wohnflaeche | |
| **gebaeudeversicherung** | ✅ | wohnflaeche | |
| **hausmeister** | ✅ (only the umlagefähiger part → `umlage_pct`) | wohnflaeche | Reparatur-Anteil not umlagefähig |
| **allgemeinstrom** | ✅ | wohnflaeche | |
| **gartenpflege** | ✅ | wohnflaeche | |
| **schornsteinfeger** | ✅ | wohnflaeche | |
| **winterdienst** | ✅ | wohnflaeche | |
| **strassenreinigung** | ✅ | wohnflaeche | (bonus BetrKV item) |
| **sonstige** | ✅ | wohnflaeche | free text |
| — **not umlagefähig** — | | | |
| **verwaltung** (Verwaltungskosten) | ❌ | — | flagged off by default |
| **reparatur / instandhaltung** | ❌ | — | the #1 landlord mistake |
| **ruecklage** (Instandhaltungsrücklage) | ❌ | — | |
| **finanzierung** (Zins/Tilgung) | ❌ | — | |

Sprint 2 wires the **wohnflaeche** computation. `personenzahl`, `verbrauch`, `wohneinheiten`,
`individuell` are valid stored values; the engine dispatches on them and, for the not-yet-wired ones,
falls back to Wohnfläche **with an explicit note on the result and PDF** (no silent wrong number).

## Q4 — Allocation methods (Umlageschlüssel) — the enum is complete from day 1

`NkKostenposition.schluessel` ∈ **{wohnflaeche, personenzahl, wohneinheiten, verbrauch, individuell}**
— all five are valid values in the schema *now*.

| Schlüssel | Basis | Sprint 2 | Basis data present? |
|---|---|---|---|
| **wohnflaeche** | `ImmoUnit.wohnflaeche` × Zeitanteil | ✅ **computed** | ✅ |
| **wohneinheiten** | count of units × Zeitanteil | ✅ **computed** (trivial, same engine) | ✅ |
| **personenzahl** | `ImmoTenancy.personenzahl` × Zeitanteil | 🟡 stored; computed Sprint 3 | ✅ (column added now) |
| **verbrauch** | `verbrauch_zeitraum` per meter | 🟡 stored; computed Sprint 3 | ✅ (Sprint 1) |
| **individuell** | `NkKostenposition.individuell` JSON | 🟡 stored; computed Sprint 3 | ✅ (column added now) |

Because the enum and the basis data are all present now, turning on personenzahl/verbrauch/individuell
in Sprint 3 is **rules-module code only — no schema change, no migration.**

## Q5 — How Vorauszahlungen are tracked

Per tenant, the advance paid over the period =

    vorauszahlung_i = Σ  monat_nk_soll(tenancy_i, jahr, monat)   for each month in [von, bis]

`monat_nk_soll` (Sprint 0) already returns the pro-rated NK advance owed for one month, honouring
mid-month move-in and any Mieterhöhung. **We do not add a second advance field.** This is the "one
accounting model" law applied to NK: the advance the statement offsets is exactly the advance the
Mietkonto charged. (A landlord who wants to enter actually-received advances instead of owed advances
is a Sprint 3 option — via the Payment Service, not a parallel field.)

## Q6 — Nachzahlung / Guthaben

Per tenant:

    umlage_i   = Σ over all umlagefähige positions of  position.betrag × (umlage_pct/100) × anteil_i(schlüssel)
    saldo_i    = vorauszahlung_i − umlage_i
    saldo_i > 0  → **Guthaben** (landlord owes the tenant)
    saldo_i < 0  → **Nachzahlung** (tenant owes the landlord)

**Vacancy:** for the months a unit is empty, its share is NOT redistributed to the other tenants; it
is accumulated into a **landlord bucket** (Leerstandskostenanteil). Invariant, proven by test:

    Σ umlage_i (all tenants)  +  leerstand_bucket  ==  Σ umlagefähige position amounts   (to the cent)

**Does the Nachzahlung post to the debt system?** MVP: **NO** — the statement is its own document.
The result snapshot is frozen on finalise. A later, explicit opt-in ("Nachzahlung als Forderung
buchen") can push it through the **Payment Service** (Sprint 3), never as a direct write — so the law
holds. This keeps NK from creating a fourth truth in the Mietkonto.

## Q7 — The PDF (per tenant, formell ordnungsgemäß — what makes it hold up)

A §556-proper statement shows, unambiguously:
1. Vermieter + Mieter + Objekt + Wohnung + **Abrechnungszeitraum**.
2. **Gesamtkosten** table: each cost line — Kategorie, Gesamtbetrag, Umlageschlüssel, (umlagefähiger
   %). Non-umlagefähige costs are **not** on the tenant's statement.
3. **Verteilung**: the tenant's share per line = Gesamt × key-fraction × Zeitanteil, with the fraction
   shown (e.g. "57 m² / 228 m² × 7/12 Monate").
4. **Ergebnis**: Summe Umlage − geleistete Vorauszahlungen = **Guthaben / Nachzahlung** (bold).
5. Zeitanteil note if the tenancy did not cover the full period; Leerstand note if applicable.
6. Footer: "Erstellt mit AutoTax · Vorlage, kein Ersatz für rechtliche Prüfung. Einwendungen §556 III
   BGB." Zahlungsziel/IBAN from the landlord's Firmen data.

An **overview PDF** (no tenancy_id) lists all tenants + the landlord's vacancy share + the invariant
check, for the landlord's own file.

## Q8 — Sprint 2 vs. intentionally postponed

**Sprint 2 ships (Faz 1 — the correct calculation + PDF that kills the Excel):**
- The 2 tables + the missing columns (Personenzahl, mea, verbrauch_art, individuell) — **full model**.
- Manual cost entry with per-category umlagefähig defaults + the mixed `umlage_pct`.
- Distribution engine: **Wohnfläche and Wohneinheiten**, with **Zeitanteil** and **Leerstand → landlord**.
- Vorauszahlung offset from `monat_nk_soll`; Guthaben/Nachzahlung; the Σ invariant.
- Per-tenant + overview PDF. Finalise → immutable snapshot. 12-month-deadline warning.

**Postponed to Sprint 3+ (data-ready, rules-stubbed — NO DB redesign needed):**
- **Heizkosten/Warmwasser by Verbrauch** (HeizkostenV 50–70% split) — the meter data exists.
- **Personenzahl** and **Individuell** computation. ⭐ **Personenzahl unlocks the Single-Main-Meter
  scenario** (single water meter split by persons for water/Abwasser/Müll) — see "Real World German
  Landlord Scenarios → Scenario 1". Code-only; the column and enum already exist.
- **OCR auto-classification** ("drop 20 PDFs, we sort them") — the Wow moment.
- Nachzahlung → Mietkonto via the Payment Service (opt-in).
- Copy-previous-year, multi-object batch, Techem/ista import, bank matching.

---

## 🔒 BINDING ARCHITECTURE PRINCIPLES (approved 2026-07-15 — all implementation must obey)

### Principle A — Immutable Settlement Snapshot
Every **finalised** Nebenkostenabrechnung is immutable. At finalisation, **all data used in the
calculation is frozen into a snapshot** (`ergebnis_snapshot`, JSON). The snapshot — not the PDF — is
the record of truth. The PDF is only a rendering of the snapshot and must be re-derivable from it.

The snapshot MUST contain at least:
`settlement_id · abrechnungsperiode (von/bis) · property (id + adresse) · per unit (id + wohnflaeche +
mea) · per tenant (tenancy_id + name + von/bis) · allocation_method per cost line · allocation_ratios
(the exact fraction used per tenant per line) · cost_lines (kategorie, betrag, umlagefaehig,
umlage_pct, schluessel) · tenant_shares · vorauszahlungen (per tenant, and the monat_nk_soll values
they came from) · leerstand_share · final_result (per tenant saldo + typ) · calculation_version ·
finalized_timestamp`.

**Goal:** years later, even if the master data (rent, area, tenancy dates, categories) has changed,
the same settlement re-produces **byte-identically** from its snapshot. Every read surface and the PDF
of a *final* settlement derive from the snapshot, never from live master data. `calculation_version`
is stamped so a future engine change never silently alters an old statement.

### Principle B — Finalize = Lock (legal lock, not just "make a PDF")
A finalised settlement cannot be changed in the normal flow. After finalise:
no cost line may be added, edited or deleted · no allocation may be changed · no tenant share may be
changed · the calculation may not be re-run. Every write endpoint calls `require_editable(status)`
(returns 409, same discipline as the Übergabeprotokoll).

A correction requires an **explicit** path, never an in-place edit:
- **Unlock** (an authorised action that reverts `final → entwurf`, recorded), or
- a **new Revision / new Settlement** (the old snapshot stays as evidence).

Finalise is a legal act that locks the calculation — it is not merely PDF generation.

### Principle C — Single-Ledger Principle (one economic event, one representation)
> **An economic event is represented in exactly one place in the system.**

The NK **Vorauszahlung is computed only from the Mietkonto via `monat_nk_soll`**. No second
Vorauszahlung source, field or table is created. This is the "one accounting model" law (CLAUDE.md)
applied to NK. It also governs the future Nachzahlung: posting a Nachforderung goes through the one
Payment Service, never a parallel write.

---

## Data model (final — additive, nothing existing changes)

```
-- new columns (nullable) on existing tables, so Sprint 3 needs no migration:
ImmoTenancy.personenzahl   INTEGER   NULL      -- Personenzahl key basis
ImmoUnit.mea               FLOAT     NULL      -- Miteigentumsanteil / agreed key override

NkAbrechnung
  id, user_id, property_id (FK ImmoProperty)
  jahr, zeitraum_von, zeitraum_bis
  status            'entwurf' | 'final'         -- final = locked
  ergebnis_snapshot TEXT (JSON)                 -- frozen per-tenant result at finalise (GoBD)
  finalized_at, notiz, created_at, is_deleted

NkKostenposition
  id, abrechnung_id (FK NkAbrechnung), user_id
  kategorie      VARCHAR        -- string, not an enum → new categories need no migration
  betrag         FLOAT
  umlagefaehig   BOOLEAN        -- default per category (rules)
  umlage_pct     INTEGER  100   -- mixed Hausmeister etc.
  schluessel     VARCHAR        -- wohnflaeche|personenzahl|wohneinheiten|verbrauch|individuell
  verbrauch_art  VARCHAR NULL   -- links to ImmoZaehlerstand.art (Sprint 3 compute)
  individuell    TEXT NULL      -- JSON {tenancy_id: betrag} for the Individuell key
  document_id    INTEGER NULL   -- receipt (ImmoDocument)
  beleg_datum, notiz, is_deleted
```

## Rules module — `immo_nebenkosten.py` (pure, no DB, testable — the law)

```
umlagefaehig_default(kategorie) -> bool
default_schluessel(kategorie)   -> str
zeitanteil(tenancy, von, bis)   -> float          # months present / months in period (via immo_rules)
anteil(position, unit, tenancy, alle_units, alle_tenancies, zeitraum) -> float
    # dispatch on position.schluessel:
    #   wohnflaeche   -> wohnflaeche_i·zeitanteil_i / Σ(wohnflaeche·zeitanteil)   [Sprint 2]
    #   wohneinheiten -> zeitanteil_i / Σ(zeitanteil)                             [Sprint 2]
    #   personenzahl  -> NotYetComputed (fallback wohnflaeche + note)             [Sprint 3]
    #   verbrauch     -> NotYetComputed (fallback wohnflaeche + note)             [Sprint 3]
    #   individuell   -> position.individuell[tenancy]                            [Sprint 3]
verteile(abrechnung, units, tenancies) -> {per_tenant, leerstand_bucket, umlagefaehige_summe}
    # asserts Σ per_tenant + leerstand == umlagefaehige_summe   (the invariant)
ergebnis(verteile_result, vorauszahlungen) -> per_tenant {umlage, voraus, saldo, typ}
```

Honesty rules (Sprint 0/1 spirit): a unit with no `wohnflaeche` cannot be split by area → the line is
flagged, not divided by zero. A not-yet-wired Schlüssel falls back to Wohnfläche **with a visible
note**, never a silent wrong split.

## Commit plan

| # | What | Visible |
|---|---|---|
| C1 | Full schema (2 tables + 4 nullable columns) + `immo_nebenkosten.py` rules + unit tests (Wohnfläche/Wohneinheiten split, Zeitanteil, Leerstand, Σ-invariant, Vorauszahlung from `monat_nk_soll`, division-by-zero honesty). No endpoint, no UI. | no |
| C2 | Endpoints + per-tenant & overview PDF + tests (final=immutable, umlagefähig defaults, fallback note). | API |
| C3 | Nebenkosten tab: cost entry (category → default umlagefähig), result cards, Leerstand card. | **yes** |
| C4 | Finalise + PDF + 12-month warning + polish. | **yes** |
| C5 | Deploy + production smoke (a real 3-flat statement) + sprint close. | — |

---

## Real World German Landlord Scenarios

Concrete situations the module must ultimately serve. Recorded here so the roadmap never drifts from
how small German landlords actually bill.

### Scenario 1 — Single main meter (Sammelzähler / ein Hauptzähler)
In German buildings of **2–20 units** it is very common that the building has **one single water
meter** for the whole house (a Sammelzähler), not one per flat. There is then **no per-flat Verbrauch
reading** to split water by — the total water bill must be distributed by another key.

Real need: for **water, sewage (Abwasser), waste (Müll)** and similar, the total is very often split
by **Personenzahl** (number of people per flat). This is a core use case for small landlords and, for
these categories, frequently the fairest and the agreed key.

The system must therefore support these Umlageschlüssel (all present in the enum since Sprint 2):
`Personenzahl · Wohnfläche · Wohneinheiten · Verbrauch · Individuell`.

**Roadmap (this scenario):**
- **Sprint 2 (shipped):** the `personenzahl` data model exists (`ImmoTenancy.personenzahl`, nullable);
  the `personenzahl` Umlageschlüssel is a valid, storable value; **it is NOT yet computed** — a
  position set to `personenzahl` falls back to Wohnfläche with a visible note.
- **Sprint 3:** the **Personenzahl Allocation Engine** is switched on. A building with a single water
  meter then distributes its total water (and Müll etc.) automatically by the number of persons per
  flat × Zeitanteil. **Code-only** — the column and the enum are already in place, no DB change.

The invariant (Σ tenant shares + Leerstand == total) and the honesty rules (missing basis → flagged,
never divided) apply to the Personenzahl key exactly as to Wohnfläche.

---

## Comparison with the existing Nebenkosten plans

| Existing plan | What we KEEP | What we CHANGE / ADD |
|---|---|---|
| `immo_nebenkosten_research.md` | The whole legal frame (§556/§556a/BetrKV/HeizkostenV), the 7 top error sources, the competitor gaps. This architecture implements exactly those error-guards. | — (research stands) |
| `immo_nebenkosten_mvp_plan.md` | The 2-table core, Wohnfläche×Zeitanteil+Leerstand engine, Vorauszahlung offset, per-tenant PDF, 12-month warning, "reuse existing data" principle. | **Deviate on extensibility:** that plan dropped Personenzahl and kept a single key "to stay simple". We ADD the full model now (Personenzahl, verbrauch_art, individuell, mea, complete Schlüssel enum) so Sprint 3 needs no DB redesign — per the explicit Sprint 2 mandate. We still only *compute* Wohnfläche/Wohneinheiten. |
| `immo_nebenkosten_wow_design.md` | The 3-step workflow vision and the OCR→classify→container Wow. | OCR classification is explicitly **Sprint 3** here; the data linkage (document_id, verbrauch_art) is laid now so the Wow drops in without redesign. |

## Decisions to confirm before C1

1. **Ship Wohnfläche + Wohneinheiten computation in Sprint 2; store (not compute) Personenzahl,
   Verbrauch, Individuell.** Full DB now, staged rules. — confirm.
2. **Add `ImmoTenancy.personenzahl` and `ImmoUnit.mea` now** (nullable), so Sprint 3 is code-only. — confirm.
3. **NK Nachzahlung is a standalone document in MVP** (no auto-post to the Mietkonto); posting via the
   Payment Service is a later opt-in. — confirm.
4. **Umlagefähig default split** as tabled in Q3 (repairs/management/Rücklage/financing OFF; the BetrKV
   operating costs ON). — confirm.

---

# Sprint 3 — allocation-engine architecture decisions (BINDING)

Recorded when the Personenzahl/Individuell/Eigennutzung allocation work was finalised. These lock the
model so it cannot silently regress.

## D1 — Eigennutzung is modelled on the UNIT, not as a Tenancy (chosen: model B)

**Decision:** an owner-occupied flat carries `ImmoUnit.eigennutzung_personen` (INT, nullable). It is
NOT modelled as a fake `ImmoTenancy` (the rejected "occupant model" A).

**Rationale (product owner, binding):**
- The owner is *not a tenant*. No fake record in `ImmoTenancy`.
- The owner must NEVER appear in Mietkonto, Mahnung, Mieteingang or any debt calculation.
- Eigennutzung is **not an accounting event** — it is *master data for allocation only*.
- This is MORE aligned with the Single-Ledger law: the owner never becomes a payment-bearing entity,
  so there is nothing to filter out of ~20 rent/debt queries and no phantom-tenant / phantom-debtor
  risk. (Model A would have created a Tenancy that must be suppressed everywhere — fragile.)

**Behaviour (locked by tests `[Eig]`, `[Eig-2]`, `[Eig-3]` in test_immo_nk_personenzahl.py):**
1. Owner lives in the building (`eigennutzung_personen` > 0) → counted in the Personenzahl denominator;
   the owner bears that share, reported as the **Eigennutzung** bucket (not billed to tenants).
2. Owner does not live there (`eigennutzung_personen` unset) → 0 persons; a person-key empty flat adds
   no cost and produces no Eigennutzung share.
3. **Eigennutzung ≠ Leerstand** — two separate buckets that coexist in one building. Leerstand is a true
   vacancy the landlord carries as a loss; Eigennutzung is the landlord's own consumption.
Invariant, all keys: `Σ tenant shares + Eigennutzung + Leerstand == umlagefähige total`.

**Schema note (deviation from the original "Sprint 3 = code-only" scope, deliberately accepted):**
`eigennutzung_personen` is genuinely new information (person counts previously lived only on tenancies;
an owner-occupied flat has no tenancy, so the datum had no home and cannot be derived). Added as a
single additive + nullable column via a boot-time ALTER — no backfill, no migration tool.

## D2 — Individuell reads its stored map (no fallback)

`NkKostenposition.individuell` (JSON `{tenancy_id: betrag}`) is now consumed by the engine: each tenant
is billed the EXACT entered euro (no weighting, no Zeitanteil). Unassigned rest → landlord (Leerstand
bucket); over-assignment → scaled to the invoice + a note; empty → whole line to the landlord + a note.
No schema change (the column pre-existed). `CALCULATION_VERSION` 2 → 3.

## D3 — What is deliberately still deferred

**Verbrauch** stays a Wohnfläche fallback WITH a visible note — the metered split belongs to the
separate **Sprint 4 / HeizkostenV** legal design (≥50% consumption rule, Zählerstände integration). Not
a bug; a scoped deferral.
