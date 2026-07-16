# Nebenkosten Verbrauch — in-place wizard UX (design, approval before code)

**The insight (product owner):** a landlord never thinks *"let me open the Zählerstände menu first."*
They think *"my water bill arrived"* → they open **Nebenkosten**. So the meter step must live **inside**
the Nebenkosten cost line — never a redirect to another screen. The user gives ONE money input (the
total invoice) and the program does the rest.

## The mental model this UX serves
1. *Su faturam geldi.* → open Nebenkosten.
2. Type the **total invoice** (567 €) on the Wasser line.
3. Pick **Verbrauch** (or it's already the smart default when the building is metered).
4. The program checks the meters:
   - **present** → uses them, splits automatically, shows the result — done.
   - **missing** → an inline *"Zählerstände eintragen"* panel opens **on the same line**; the landlord
     fills Anfang/Ende for that one meter, hits save, and the result appears — still on the Nebenkosten
     screen. No navigation.
5. The landlord **never** computes `m³ × Preis`. They enter only the total invoice; the program splits
   by the consumption ratio (Σ always equals the invoice).

## The Verbrauch line, three states (all in-place, under the cost row)

The area under a `Verbrauch` cost line (today it shows the HeizkostenV Grund% + a hint) becomes a small
**state machine**:

### State A — meters complete
Every unit that counts in the period has an Anfang **and** an Ende for this meter.
```
✓ Verbrauch erfasst · 3 Wohnungen · Σ 70 m³
   Vanelle · 30/70 m³ → 300,00 €
   YURONG  · 20/70 m³ → 200,00 €
   C       · 20/70 m³ → 200,00 €
```
Nothing to do — the result is already there (this is the current inline result, kept).

### State B — meters missing / incomplete  → inline entry (the core of this sprint)
```
⚠ 2 von 3 Wohnungen ohne Zählerstand für „Wasser" — jetzt eintragen:

   Wohnung     Anfang        Ende
   Whg 1 ·V    [ 100 ]       [ 130 ]
   Whg 2 ·Y    [     ] ⚠     [     ] ⚠
   Whg 3       [ 200 ]       [ 220 ]

   Ablesung:  01.01.2026 → 31.12.2026
   [ ✓ Speichern & verteilen ]
```
- Only THIS meter (Wasser) and only the property's units — compact, one art.
- Anfang/Ende dates default to the statement's period (editable once at the top).
- Excel keys carry over (Tab →, Enter ↓, colored ✓/⚠/✕).
- Save writes the readings (the existing bulk endpoint, scoped to this art) **and** recomputes the line
  in place → the result (State A) replaces the panel. **No page change, no menu.**

### State C — HeizkostenV (heizung / warmwasser)
Same as B/A, with the **Grundkosten % (30–50)** control shown above the meter table (already built).
The split shows both parts: `Grundkosten 30% (Fläche) + Verbrauch 70% (Zähler)`.

## What the user types vs what the program does
| The landlord types | The program does (no user math) |
|---|---|
| Total invoice € (567) | holds the amount to split |
| Meter Anfang/Ende (if asked) | consumption = Ende − Anfang, per unit |
| — | split = invoice × (unit consumption / building consumption) |
| — | Σ = invoice, to the cent; shows each tenant's € |

**Never** a price-per-unit, never `m³ × Preis`. (An optional €/unit stays out of the daily flow — a
power-user extra at most.)

## Smart default (already staged, general SaaS rule)
When the building already has readings for a category's meter, that line's default is **Verbrauch**
(else the legal area/person default). Data-driven, identical for every customer — so a metered landlord
lands in State A without touching the dropdown; an unmetered one gets State B the first time.

## The standalone Zählerstände tab — kept, repositioned
Immobilien → Objekt → 🔢 Zählerstände stays as the **bulk / annual maintenance** screen (enter all 20
flats × 5 meters at once, meter numbers, history). It is the *advanced* surface. The **daily centre of
gravity is the Nebenkosten wizard** — the inline State-B panel above. Both write the same
`ImmoZaehlerstand` rows; neither is a separate source of truth.

## Reuse (no new backend needed)
- GET `.../zaehler-matrix?jahr` → filter to the one art for the inline table (or the UI filters client-side).
- POST `.../zaehler-bulk` → save the inline entries (scoped to the one art).
- The NK response already recomputes on read; after save the line refreshes.
No schema change; no new table; no new endpoint strictly required.

## Scope (this UX sprint)
- In-place State A/B/C on every Verbrauch line inside Nebenkosten (the wizard).
- Inline meter-entry panel (State B) with save-&-recompute, no navigation.
- Keep the smart default; keep the standalone Zählerstände tab as maintenance.
- Deferred: optional €/unit price entry; per-reading custom dates beyond the period bounds.

## Decision — LOCKED (product owner, 2026-07-16)
State B inline table shows **only the units missing a reading** by default (fastest for the common
"one flat forgot" case), with a **"alle Wohnungen anzeigen / tüm daireleri göster"** link to reveal the
full list on demand. Complete when needed, minimal noise by default.
