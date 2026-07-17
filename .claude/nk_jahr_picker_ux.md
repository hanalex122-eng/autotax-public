# Sprint — P0: Abrechnungsjahr-Auswahl (design, approval before code)

**Single goal:** kill the "wrong-year dead-end" — the #1 blocker. A landlord must not be able to create an
empty statement for a year with no tenants and then conclude "the program is broken."

Only this P0. P1/P2 untouched (stay in backlog).

## The problem (evidence)
`newNk` (index.html) uses a bare browser **`prompt("Abrechnungsjahr", currentYear-1)`**. Default = last
year. If the tenants moved in 2026, the default 2025 statement is empty → confusion. Even the owner (an
expert user) got stuck here for 10+ turns.

## The fix — a guided year picker (replaces the prompt)

Click "➕ Neue Abrechnung" → instead of a browser prompt, an **inline picker** opens in the Nebenkosten
list view. It shows the last ~3 years + the current year, each **annotated with its status**:

```
Neue Abrechnung — Jahr wählen:

 [ 2026 · 2 Mieter · Entwurf vorhanden ]   ← empfohlen (aktuellstes Jahr mit Mietern)
 [ 2025 · kein Mieter ⚠ ]                  ← gedimmt + Warnung
 [ 2024 · 2 Mieter ]
 [ 2023 · kein Mieter ⚠ ]
 anderes Jahr: [ ____ ]  (manuelle Eingabe für Sonderfälle)
```

**Behaviour per click:**
- **Draft exists for that year** → OPEN it (never a silent duplicate). Removes the two-drafts confusion.
- **No tenant active that year** → a clear confirm: *"In {Jahr} wohnt kein Mieter im Haus — trotzdem
  anlegen?"* (allowed but explicit — vacancy-only statements are a real case).
- **Otherwise** → create + open.

The **recommended** year (the most recent year that actually had active tenants) is highlighted first,
so the common path is one obvious click.

## Data needed (backend, read-only)
A small endpoint **GET `/immo/properties/{pid}/nk-jahre`** → for the year range (current−3 … current):
`[{ jahr, mieter_aktiv: <count of tenancies active that year>, entwurf_id: <existing draft id or null> }]`.
Computed from the property's tenancies (von/bis) + existing NkAbrechnung rows. No schema change, no new
table. (Alternative: fold the same info into the existing NK list response — decide at implementation.)

## What this sprint does NOT touch (P1/P2 — backlog)
Eigennutzung entry points · Zeitanteil explanation in the result · collapsing the 14-category grid ·
Verbrauch price/meter wording · umlagefähig rationale · tooltips. None of these are in scope.

## Scope note — duplicate-year draft
The picker's "open the existing draft instead of duplicating" is INCLUDED, because it is inherent to the
picker (the year buttons must know whether a draft exists). It was listed as a P1 edge case, but here it
is a direct property of the P0 fix, not a separate feature — flagging it so the owner can confirm.

## Definition of Done
Picker replaces the prompt · recommended year highlighted · no-tenant warning before create · existing
draft opened instead of duplicated · tests (endpoint returns correct year annotations; picker flow) ·
Go/No-Go deploy · sprint closed. Manual-year input kept for edge cases.
