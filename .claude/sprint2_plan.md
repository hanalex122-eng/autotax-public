# Sprint 2 — Nebenkostenabrechnung (Masterplan #8 ⭐⭐⭐)

**Goal:** a small landlord produces a legally proper annual utility-cost statement (Betriebs-/
Nebenkostenabrechnung) for each tenant — inside AutoTax, without Excel, without the Steuerberater
(80–250 €/statement).

**Scope = Faz 1 (MVP) only.** OCR auto-classification, HeizkostenV/Verbrauch keys, per-person keys,
bank matching, copy-previous-year and multi-object are explicitly **Sprint 3+** (see backlog). MVP
kills the calculation + PDF part of the Excel — the biggest time sink — with **manual** cost entry.
Prior research/design: `.claude/immo_nebenkosten_{research,mvp_plan,wow_design}.md`.

**Legal frame (grounding, not advice):** §556 BGB (12-month deadline + advance offset), §556a BGB
(**Wohnfläche is the default key** when nothing else is agreed), BetrKV §2 (which costs are
umlagefähig). The statement is a **calculation/preparation tool**, not Steuer- or Rechtsberatung —
language stays "Entwurf/Vorlage", responsibility with the landlord (AGB §3 + §4a already cover this).

---

## What already exists (reuse, do NOT rebuild)

| Piece | Where | Used for |
|---|---|---|
| Wohnfläche per unit | `ImmoUnit.wohnflaeche` | the distribution key |
| Tenancy von/bis (Zeitanteil) | `ImmoTenancy` + `immo_rules.month_proration` | mid-year move in/out |
| **NK advance already owed, pro-rated** | `immo_rules.monat_nk_soll` (Sprint 0) | Vorauszahlung offset — the SAME engine, no fourth truth |
| Expenses + categories | `ImmoExpense`, `EXPENSE_KATEGORIEN` | source of cost positions |
| Documents + storage + OCR | `ImmoDocument`, `storage`, existing OCR | receipts behind cost positions (OCR = Sprint 3) |
| PDF generation | reportlab (Mahnung/WGB/Protokoll pattern) | the per-tenant statement |
| Meter consumption per period | `immo_rules.verbrauch_zeitraum` (Sprint 1) | ready for the Verbrauch key (Sprint 3) |

## The biggest value = correctness the landlord gets wrong in Excel

The research names the top error sources; the engine must handle exactly these:
1. **Umlagefähig or not?** Verwaltungskosten, Reparatur/Instandhaltung, Rücklage are **not**
   umlagefähig. Each cost position carries an `umlagefaehig` flag; non-umlagefähige categories are
   flagged/defaulted off, so the landlord cannot silently dun the tenant for a repair.
2. **Zeitanteil** — a tenant present 7/12 months pays 7/12 of the period share. Derived, not typed.
3. **Leerstand** — a vacant unit's share is carried by the **landlord**, never redistributed to the
   other tenants. Its own line on the result.
4. **Hausmeister/Gartenpflege mixed** — only the umlagefähiger part; `umlage_pct` (default 100).
5. **12-month deadline** (§556 III) — warn if the statement is finalised later than 12 months after
   the period end (Nachforderung then barred; Guthaben still owed).

## Data model (2 new tables, additive — nothing existing is touched)

```
NkAbrechnung                one statement for one property + one period
  id, user_id, property_id, jahr, zeitraum_von, zeitraum_bis
  status  "entwurf" | "final"        ← final = locked (like the protocol)
  finalized_at, notiz, created_at, is_deleted

NkKostenposition            one cost line in a statement
  id, abrechnung_id, user_id
  kategorie   (BetrKV-style: heizung/wasser/abwasser/muell/versicherung/grundsteuer/
               hausmeister/garten/allgemeinstrom/schornsteinfeger/winterdienst/sonstige)
  betrag
  umlagefaehig  (bool)               ← default per category (repairs/management → false)
  umlage_pct    (int, default 100)   ← for the mixed Hausmeister case
  schluessel    (str, "wohnflaeche") ← MVP: one key; Person/Verbrauch = Sprint 3
  document_id   (FK ImmoDocument, nullable)   ← the receipt behind it
  beleg_datum, notiz, is_deleted
```

A finalised statement is **immutable** and freezes a per-tenant result snapshot (JSON on the
Abrechnung) — same discipline as the Übergabeprotokoll, and what makes it valid evidence.

## Pure rules — `immo_nebenkosten.py` (no DB, testable)

```
umlagefaehig_default(kategorie) -> bool         # BetrKV knowledge, the correctness core
verteile(positionen, einheiten, mietverhaeltnisse, zeitraum) -> Verteilung
    # per umlagefähige position:
    #   basis = Σ (wohnflaeche_i) over units, weighted by Zeitanteil of the tenancy in the period
    #   tenant_share = betrag * umlage_pct/100 * (wohnflaeche_i * zeitanteil_i / basis_time_weighted)
    #   VACANCY months of a unit → their share stays with the landlord (own bucket)
ergebnis(verteilung, vorauszahlungen) -> [{tenancy, umlage, voraus, saldo(+Guthaben/−Nachzahlung)}]
    # vorauszahlung_i = Σ monat_nk_soll(tenancy_i, month) over the period  ← Sprint-0 engine
```

Honesty rules (same spirit as Sprint 0/1): if a unit has no `wohnflaeche`, the position cannot be
distributed by area → the statement flags it instead of dividing by zero. The sum of all tenant
shares + the landlord's vacancy share == the umlagefähige total, exactly (proven by test).

## Endpoints (thin)

```
POST   /immo/nk                          {property_id, jahr}  → draft, period defaults to the year
GET    /immo/nk?property_id=             list
GET    /immo/nk/{id}                     full statement incl. live Verteilung + Ergebnis
PATCH  /immo/nk/{id}                     period / notiz            (draft only)
POST   /immo/nk/{id}/position            add a cost line           (draft only)
PATCH  /immo/nk/{id}/position/{pid}      edit / toggle umlagefähig  (draft only)
DELETE /immo/nk/{id}/position/{pid}
POST   /immo/nk/{id}/finalisieren        freeze the snapshot → status=final (LOCK)
GET    /immo/nk/{id}/pdf?tenancy_id=     the per-tenant statement (or an overview without tenancy_id)
```

## UI — on the property (Immobilien → Details → new "📑 Nebenkosten" tab)

1. **Zeitraum** — year, adjustable von/bis.
2. **Kosten** — add each cost line: category (with its umlagefähig default), amount, ☑ umlagefähig,
   optional % for mixed, optional receipt. A running "umlagefähige Summe" and a clear list of the
   **non**-umlagefähige lines (so the landlord sees what he is NOT passing on).
3. **Ergebnis** — one card per tenant: Umlage · Vorauszahlung · **Guthaben (green) / Nachzahlung
   (red)** + a Leerstand card (what the landlord carries). A 12-month-deadline warning if late.
4. **Finalisieren → PDF** — per-tenant PDF: property, period, total costs, key, the tenant's share,
   his advance, the result, and the itemised cost table. Footer "Erstellt mit AutoTax · kein
   Ersatz für rechtliche Prüfung".

## Commits

| # | What | Visible? |
|---|---|---|
| **C1** | Schema (2 tables) + `immo_nebenkosten.py` rules + unit tests (distribution, Zeitanteil, Leerstand, Σ==total, Vorauszahlung from the Sprint-0 engine). No endpoint, no UI. | no |
| **C2** | Endpoints + per-tenant PDF + tests (incl. "final = immutable", umlagefähig defaults) | API only |
| **C3** | The Nebenkosten tab (cost entry + result cards) | **yes** |
| **C4** | Finalise + PDF + 12-month warning + polish | **yes** |
| **C5** | Deploy + production smoke (a real 3-flat statement) + sprint close | — |

Every visible change gets a BEFORE/AFTER line + a test. No migration of existing data (2 new tables).

## Decisions to confirm before C1

1. **MVP key = Wohnfläche only** (§556a legal default). Per-person (Müll) and Verbrauch/Heizung
   (HeizkostenV) keys are Sprint 3. This avoids adding a "number of persons" field now and keeps the
   engine correct-by-default. *Confirm this scope.*
2. **Does the Nachzahlung feed the debt system?** Per the "one accounting model" law I recommend
   **NO for MVP**: the NK statement is its own document (PDF). Auto-injecting a Nachforderung into the
   Mietkonto would risk a fourth truth. Pushing "create a Mahnung from this Nachzahlung" can be an
   explicit, later, opt-in button. *Confirm: standalone statement for MVP.*
3. **Umlagefähig defaults** — I will default OFF for: reparaturen, schoenheitsrep, finanzierung
   (Zins/Tilgung), management/Verwaltung; ON for: heizung, wasser, abwasser, muell, versicherung,
   grundsteuer, hausmeister, garten, allgemeinstrom, schornsteinfeger, winterdienst. The landlord
   can override each line. *Confirm the default split.*
