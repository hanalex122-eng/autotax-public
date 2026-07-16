# Sprint 4 — Verbrauch / Zählerstand engine + HeizkostenV (ARCHITECTURE, approved)

**Goal:** split metered operating costs by ACTUAL consumption (Zählerstände), and make heating/hot-water
compliant with the Heizkostenverordnung (HeizkostenV) Grund/Verbrauch split. A moved-out tenant is
billed for what they really used (Zwischenablesung), not just their time-share.

## Data already in place (reuse, no new tables)
- `ImmoZaehlerstand` (Sprint 1): one meter reading — `unit_id, art (strom|wasser|warmwasser|gas|heizung),
  stand (Float), einheit (kWh|m³), datum`. A time series per unit+art (handover + interim readings).
- `NkKostenposition.verbrauch_art` — links a cost line to a meter art.
- Cold-water/Abwasser/gas → pure consumption. Heating/hot-water → HeizkostenV split.

## The two computation modes (dispatch on kategorie)

### Pure Verbrauch (wasser, abwasser, gas, allgemeinstrom-metered)
100% of the line splits by each occupant's consumption in the period.

### HeizkostenV (heizkosten, warmwasser) — §7 HeizkostenV, BINDING
A heating/hot-water line MUST split into two parts (never 100% by meter):
- **Grundkosten** = `grund_prozent` % → by **Wohnfläche × Zeitanteil** (everyone incl. vacancy carries it).
- **Verbrauchskosten** = `100 − grund_prozent` % → by **consumption**.

`grund_prozent` is stored per position, default **30** (→ 70% consumption). **Configurable per line.**
Validation (API + engine): `30 ≤ grund_prozent ≤ 50` (so Verbrauch stays 50–70%); total always 100%.

## Consumption from readings (Zwischenablesung)
For an occupant (tenant / owner) of a unit over `[start, end]` (clamped to the statement period and to
their move-in/out), consumption = `Stand(end) − Stand(start)` from the unit's series for that `art`:
- `Stand(when)` = the last reading with `datum ≤ when` (else the earliest reading).
- Need ≥ 2 readings to form a difference. A tenant who moved out has a handover (Zwischen-) reading, so
  they are billed for their true interval; the remainder of the unit's consumption goes to the next
  occupant / owner (Eigennutzung) / vacancy — exactly like the area/person buckets.
- **Missing / insufficient readings → the WHOLE line falls back to Wohnfläche WITH a named note**
  (Sprint 0/1 discipline: never a silent wrong number). HeizkostenV lines fall back entirely to area.

## Invariants & principles (unchanged)
- `Σ tenant shares + Eigennutzung + Leerstand == umlagefähige line total` — to the cent, per line.
- Vacancy consumption is the landlord's (Leerstand bucket), never redistributed to tenants.
- Immutable snapshot (Principle A): the snapshot freezes `grund_prozent`, each unit's consumption
  (Anfang/End readings) and the resulting shares, so the statement re-produces years later even if
  readings change. Finalize=Lock (Principle B), Single-Ledger (Principle C) all hold.
- `CALCULATION_VERSION 3 → 4`. Old v1/v2/v3 finalised statements keep rendering from their snapshot.

## Schema (one additive, nullable column — boot ALTER, no backfill)
`NkKostenposition.grund_prozent INTEGER NULL` — the HeizkostenV Grundkosten share (30–50). Null → the
category default (30 for heizung/warmwasser; N/A for pure-Verbrauch lines).

## StBerG/RDG
This is operating-cost allocation, not tax advice. UI language stays factual ("Verteilung/Berechnung"),
no "Steuerberatung". A HeizkostenV note explains the split; no legal advice is given.

## Scope (approved)
Both pure Verbrauch AND HeizkostenV in this sprint. Deliverables: engine + readings wiring + grund_prozent
(schema/API/UI + validation) + snapshot fidelity + the Verbrauch/consumption UI (per-line consumption
breakdown, Grund% input) + tests + Go/No-Go deploy.
