# Sprint P0.1 — "Neuer Mieter" writes to the RIGHT building & unit (design, approval before code)

**Single goal:** the one-page "Neuer Mieter" (Erfassung) must NOT create a new property for every tenant.
For a multi-flat building the landlord picks the existing building and a unit inside it — so 8 tenants
land in ONE building with 8 units, and Nebenkosten can split building costs. This is the P0 that makes
the product unusable via its most visible "add tenant" path.

Nothing else. P1/P2 untouched. (Backlog moves: P1.3/P1.4 → next UX sprint; P1.1/P1.2/P1.5 + all P2 stay.)

## The bug (evidence)
`saveErf` (index.html ~2872-2874) ALWAYS does: POST /immo/properties (new, from the typed address) →
POST /immo/units (new) → POST /immo/tenancies. No building/unit selector. 8 tenants → 8 properties at
the same address → NK can't split. Exactly the failure the owner hit (VANELLE + YURONG = two properties).

## The fix — a building + unit selector in the Erfassung (no backend change)

The Erfassung form gains two selectors above the tenant fields:

**1. Gebäude**
- If the landlord already has ≥1 property: default to **"Bestehendes Gebäude"** — a dropdown of their
  buildings (pre-selected to the most recent). A second option **"➕ Neues Gebäude"** reveals the address
  field (today's behaviour).
- If they have no property yet: just the address field (new building) — unchanged.

**2. Wohnung** (shown once a building is chosen)
- **➕ Neue Wohnung** (default): name (Whg …) + m² — the common case while building up (each new tenant =
  a new flat).
- **Bestehende Wohnung**: a dropdown of that building's units (vacant ones marked) — for tenant turnover
  (a new tenant in an existing flat).

**3. Mieter**: name, Einzug, Kaltmiete, NK-Vorauszahlung — unchanged.

**saveErf becomes:**
- `property_id` = the chosen existing building, ELSE create a new property from the address.
- `unit_id` = the chosen existing unit, ELSE create a new unit (name + m²) in that property.
- create the tenancy on `unit_id` (unchanged).

Data it needs: the landlord's properties (GET /immo/properties — already loaded in MieterView context or
one call) and, for a chosen building, its units (GET /immo/properties/{pid}/units — exists). **No new
endpoint, no schema change.** The structured Immobilien → Objekt → add-unit/add-tenant path already does
this correctly and is left as-is.

## Safety guard (part of the P0, prevents the same bug via the "new building" path)
When the landlord chooses "Neues Gebäude" and types an address that **matches an existing building**, warn:
*"Du hast bereits ein Gebäude an dieser Adresse — dort hinzufügen?"* with a one-click "zum bestehenden
Gebäude". This closes the loophole of re-creating the same building by typing the address again.

## Definition of Done
Erfassung has building (existing/new) + unit (existing/new) selectors · adding 8 tenants to one building
yields ONE property with 8 units · duplicate-address warning · tests (the save path picks the right
property_id/unit_id; multi-tenant → one property) · Go/No-Go deploy · sprint closed. The structured
Immobilien path is untouched.

## Open decisions for the product owner
1. Existing building → unit: default to **"Neue Wohnung"** (setup case) with a toggle to pick an existing
   (vacant) unit? (Recommended.)
2. Duplicate-address warning on "Neues Gebäude": include it in this P0 (recommended, same bug) or leave
   for backlog?
