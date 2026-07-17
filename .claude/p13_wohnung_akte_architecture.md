# #13 Wohnung Akte — Architecture + UX (DESIGN ONLY — no code, decide together)

Masterplan's last mandatory item: "each flat's single screen." This is a **design + a decision**, not
an implementation. The binding tension is explicit and unresolved on purpose:
- **VERMIETER_MASTERPLAN #13** says: build the consolidated Wohnung-Akte (one screen per flat).
- **Working rule `feedback_no_new_screens_taxfix`** says: don't build new screens, perfect existing ones.
- **Architecture law `feedback_one_accounting_model`**: any new surface READS debt from the Exception
  Engine; it never computes debt itself.
These three must be reconciled by *your* choice below — I do not pick unilaterally.

## 1. Where one flat's info lives TODAY (evidence)
| Aspect | Built? | Today's home |
|---|---|---|
| 🏠 Stammdaten | ✅ | Immobilien → Objekt → **Einheiten** (ImmoUnitForm, index.html:2447) |
| 👤 Kiracı | ✅ | Immobilien → Einheiten (tenant/unit) **+** Mieter-Liste |
| 📄 Mietvertrag | ❌ **not built** | plan only (`.claude/mietvertrag_architecture.md`) |
| 💰 Mietkonto | ✅ | **Mieter** → Mieter → Mietkonto |
| 📬 Mahnung | ✅ | **Mieter** → Mieter → Mahnung |
| 📑 Nebenkosten | ✅ | Immobilien → Objekt → **Nebenkosten** (Gebäude-Ebene) |
| ⚡ Sayaçlar | ✅ | Nebenkosten → Zählerstände (P1.2) + je Mieter |
| 🛠 Reparaturen | ❌ **not built** | — |
| 📷 Fotos | ⚠ teilweise | nur Übergabeprotokoll-Fotos (protokolle/…/foto) |
| 📁 Belege | ✅ | Immobilien → Objekt → **Dokumente** (Gebäude-Ebene) |

**Fragmentation:** to handle ONE flat, the landlord hops between **two top-level areas** — *Immobilien*
(Stammdaten, NK, Dokumente, Einnahmen) and *Mieter* (Mietkonto, Mahnung, Zähler, Protokoll). 2 of the 10
aspects (Mietvertrag, Reparaturen) don't exist yet, so "consolidating" partly means *building new
features*, not only linking.

## 2. The problem
There is no "open flat 3 → see and do everything for flat 3" view. Info is split across areas and levels
(some per-tenant, some per-building). New/occasional landlords lose the thread.

## 3. Three directions (pick one)

### Option A — Enhance existing (no new screen; obeys no-new-screens rule)
Make the existing unit/tenant detail the *de-facto* hub by adding **cross-links** and folding the missing
pieces in:
- Each Einheiten unit-card links straight to that tenant's Mietkonto / Mahnung / Zähler (today you must
  leave to Mieter).
- Add Mietvertrag + Reparaturen as small sections inside the existing unit/tenant detail.
- *Screens changed:* existing ones only. *New screen:* No. *Backend:* additive only if the 2 missing
  features are built. *Compat:* full. *Effort:* small–medium, low risk. *Win:* partial (still two homes,
  stitched by links).

### Option B — New consolidated "Wohnung Akte" screen (obeys masterplan)
Pick a flat → one screen with sections/tabs: Stammdaten · Kiracı · Mietvertrag · Mietkonto · Mahnung ·
Nebenkosten · Sayaçlar · Reparaturen · Fotos · Belege.
- *New screen:* Yes → **conflicts with the no-new-screens rule** unless we frame it as pure composition
  (below). *Effort:* medium–large. *Win:* full single-pane. *Risk:* a third surface that could drift from
  the single-accounting-law if it computes anything itself.

### Option C — Composition hub (recommended to weigh) — reconciles all three constraints
Build the Akte as a **thin composition** that EMBEDS the existing components under one flat header —
`Mietkonto`, `Mahnung`, an `NkEditor` slice, `ZaehlerMatrix`, `Dokumente` — reusing them, not
duplicating. It introduces **no new data model and no new debt logic**: the Akte only READS the
Exception-Engine/derivation helpers (obeys `feedback_one_accounting_model`). Missing aspects (Mietvertrag,
Reparaturen) are added once, here, as additive sections. This delivers the masterplan's single-pane while
staying "one accounting model, many UIs" — the Akte is just another UI over the same ledger.
- *New screen:* technically yes, but it owns no data — it's a view. *Effort:* medium. *Compat:* full.
  *Win:* full, rule-aligned in spirit.

## 4. Cross-cutting (must hold in ANY option)
- **ONE accounting model:** the Akte reads debt/derivation; never sums its own totals (Architecture law).
- **No second Nebenkosten path:** the Akte embeds the existing NkEditor, it doesn't reimplement it.
- **Backward compat:** composition needs no schema change; Mietvertrag/Reparaturen = new additive tables
  if we choose to build them.
- **Mobile:** a single-flat, section-collapsible page is a big mobile win over hopping between areas.

## 5. Missing-feature scope (second decision)
Mietvertrag and Reparaturen aren't built. Either: **(i)** build them now as part of #13, or **(ii)** defer
— the Akte ships with the 8 existing aspects and shows "Mietvertrag/Reparaturen — bald" placeholders.

## 6. Decisions for you (nothing is coded until you choose)
1. **Direction:** A (enhance existing) · B (new screen) · C (composition hub — recommended).
2. **Missing features:** build Mietvertrag + Reparaturen now, or defer to a later sprint.
After you choose, I prepare the detailed screen-level UX for that direction (still design), then — only on
your approval — implement in small sprints (each: one aspect, tests, deploy, close).
