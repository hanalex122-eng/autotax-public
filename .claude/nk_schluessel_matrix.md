# Allowed-Umlageschlüssel matrix per Betriebskosten category (design — approval before code)

**Product rule:** every cost category declares which Umlageschlüssel it may use. The UI shows ONLY those.
Unsupported methods never appear → no invalid combinations, legally safer, cleaner.

Keys: **WF** Wohnfläche · **WE** Wohneinheiten · **PZ** Personenzahl · **VB** Verbrauch · **IN** Individuell.
For **Heizkosten/Warmwasser**, VB = **HeizkostenV** mode (Grundkosten by area + Verbrauch by meter, §7).

Legend: ✅ = you specified it · 🔵 = my proposal (please confirm) · • default (first allowed).

| Kategorie | WF | WE | PZ | VB | IN | Erlaubt (Reihenfolge = Default zuerst) |
|---|:--:|:--:|:--:|:--:|:--:|---|
| **Heizkosten** | — | — | — | ✅• | — | **VB (HeizkostenV)** — gesetzlich Pflicht (§7 HeizkostenV) |
| **Warmwasser** | — | — | — | ✅• | — | **VB (HeizkostenV)** |
| **Wasser (kalt)** | ✅ | — | ✅ | ✅• | 🔵 | **VB** • PZ · WF · (IN) |
| **Abwasser** | 🔵 | — | 🔵 | 🔵• | 🔵 | **VB** • PZ · WF · (IN) — folgt dem Frischwasser |
| **Müllabfuhr** | — | ✅ | ✅• | — | — | **PZ** • WE |
| **Grundsteuer** | ✅• | — | — | — | — | **WF** |
| **Gebäudeversicherung** | ✅• | — | — | — | — | **WF** |
| **Gartenpflege** | ✅• | — | — | — | — | **WF** |
| **Winterdienst** | ✅• | — | — | — | — | **WF** |
| **Allgemeinstrom** | ✅• | ✅ | — | — | — | **WF** • WE |
| **Hausmeister** | 🔵• | 🔵 | — | — | — | **WF** • WE |
| **Schornsteinfeger** | 🔵• | 🔵 | — | — | — | **WF** • WE |
| **Straßenreinigung** | 🔵• | 🔵 | — | — | — | **WF** • WE |
| **Sonstige** | 🔵• | 🔵 | 🔵 | 🔵 | 🔵 | **WF** • WE · PZ · VB · IN (Sammelkategorie → alle erlaubt) |

**Not umlagefähig (never billed, no key picker):** Verwaltung · Reparatur/Instandhaltung ·
Instandhaltungsrücklage · Finanzierung. These stay OFF; no Umlageschlüssel is offered.

## Legal notes (the safety this buys)
- **Heizkosten/Warmwasser locked to HeizkostenV** — the landlord cannot pick pure Wohnfläche (the #1
  invalid heating clause). *Exception:* a building with ≤ 2 units where the owner lives in one may split
  heating freely (§ 2 HeizkostenV). → handle later as an explicit opt-in; default stays HeizkostenV.
- **Grundsteuer/Versicherung/Garten/Winterdienst → Wohnfläche only** (as you specified). No consumption
  key offered (they have none).
- **Individuell (IN)** is offered only where a per-tenant exact amount is meaningful (metered/measurable:
  Wasser, Abwasser, Sonstige). Not on pure area costs (Grundsteuer etc.).

## UI behaviour
- The `÷ Verteilung` dropdown lists ONLY the category's allowed keys; the first is the default.
- Heizkosten/Warmwasser show a single option **„Verbrauch (HeizkostenV)"** → no wrong choice possible.
- The existing **smart default** still applies within the allowed set (a water line auto-picks VB when
  the building is metered, else its first allowed non-VB key).

## Implementation approach (when approved)
- Engine: add `allowed` (list) to each `KATEGORIEN` entry + `allowed_schluessel(kategorie) -> [..]`;
  `default_schluessel` returns `allowed[0]` (kept consistent). Validation: a position's schluessel must
  be in the category's allowed set (else 400) — server-side guard, not just UI.
- API: expose the allowed map (small `GET /immo/nk/config` or embed per position) so the cost grid can
  restrict the dropdown even before a position exists.
- UI: filter `NK_SCHL` per row to the allowed set; hide the rest. No new table, no schema change.

## Open items to confirm
1. The 🔵 rows (Abwasser, Hausmeister, Schornsteinfeger, Straßenreinigung, Sonstige) — ok as proposed?
2. **Individuell** only on Wasser/Abwasser/Sonstige — or also on Warmwasser/Heizkosten (sub-meter deals)?
3. The ≤2-unit heating exception — build now, or defer (default HeizkostenV for everyone for now)?
