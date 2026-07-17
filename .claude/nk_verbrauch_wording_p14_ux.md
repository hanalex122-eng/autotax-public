# Sprint P1.4 — Verbrauch: Rechnung ↔ Zähler erklären (Architecture + UX design)

**Single goal:** on a line split by **Verbrauch**, make unmistakably clear that the "Rechnung €" is the
**whole invoice** and AutoTax splits it by each flat's consumption (Ende − Anfang) — **no price per unit
is entered anywhere.** Kills the recurring "wo gebe ich den Preis (€/kWh) ein?" confusion (P1.4). One
screen, wording only. **No backend / schema / engine change.**

Only this. P1.1/P1.2/P1.5 + P2 stay in the approved backlog order after this.

## Today (evidence)
When a line's ÷ = Verbrauch, the sub-panel (`renderMeterState`, index.html:3375) shows either the meter
grid (Anfang/Ende per flat) or "Split by meter readings" — but nothing states that the amount typed in
"Rechnung €" is the TOTAL bill and that no €/unit is ever entered. The owner asked this repeatedly
("fiyatı nereye giriyorum?").

## The fix — one explanatory block at the top of the Verbrauch sub-panel

Right under the ÷-Verbrauch selection (before the meter grid / HeizkostenV split), a short info block:

**Standard Verbrauch line (Wasser, Warmwasser…):**
> ⓘ Oben die **GESAMT-Rechnung** eintragen (die ganze Jahresrechnung, z. B. 1.200 € Wasser). AutoTax
> verteilt sie nach dem **Verbrauch je Wohnung** (Ende − Anfang). Einen **Preis pro Einheit gibst du
> NICHT ein** — der ergibt sich aus der Rechnung.

**Worked example line** (concrete, dismisses the "where's the price" reflex):
> Beispiel: 1.200 € ÷ 200 m³ Gesamtverbrauch → eine Wohnung mit 40 m³ zahlt **240 €**.

**HeizkostenV line (Heizkosten/Warmwasser)** — append to the existing Grund/Verbrauch row:
> Zuerst {Grund}% nach Fläche (Grundkosten), der Rest ({100−Grund}%) nach Zähler. Auch hier: nur die
> Gesamt-Rechnung, kein Preis pro kWh.

All three languages (DE/TR/EN) via `_L(...)`, consistent wording.

## Architecture
- Pure presentational: an info `<div>` inside the `sval==="verbrauch"` block (index.html ~3538), above
  `renderMeterState(kat)`. For HeizkostenV lines the extra sentence joins the existing Grund% row.
- No new state, no API, no engine touch. The numbers in the example are static illustration text (not
  computed), so nothing depends on data being present.
- Locked/finalised view: the explanation is edit-time guidance → shown only when `!locked` (same as the
  rest of the sub-panel).

## The 7-check frame (for the pre-commit gate, same rigor as P1.3)
1. Verbrauch line shows the "GESAMT-Rechnung / kein Preis pro Einheit" block. 2. Example line present.
3. HeizkostenV line additionally explains Grund/Verbrauch + "kein Preis pro kWh". 4. DE/TR/EN all filled,
consistent. 5. Non-Verbrauch lines unchanged (no block). 6. Engine/results/PDF byte-identical (only
index.html changes). 7. Mobile: block wraps, no overflow.

## Definition of Done
Explanatory block on Verbrauch lines (standard + HeizkostenV) · worked example · trilingual · only shown
when editable · engine/schema untouched · JSX PARSE OK/BALANCED + served-HTML markers · Go/No-Go deploy ·
sprint closed. P1.1 becomes the next sprint.

## Open decision
Include the concrete **worked example** line ("1.200 € ÷ 200 m³ → 240 €")? Recommended — it's the single
sentence that most directly answers "where's the price?". Or keep only the plain explanation?
