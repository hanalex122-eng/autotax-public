# Sprint P1.1 — Mehrere Wohnungen auf einmal anlegen (Architecture + UX design)

**Single goal:** stop forcing a landlord to create an N-flat building one unit at a time (~3 clicks ×
8 = 24+). Add a "create several flats at once" action that makes N units in one form. Tenants stay
per-unit (each needs its own name/rent) — but with P0.1 the landlord then just picks each existing unit,
so the whole 8-flat setup collapses from ~40 clicks to a handful. **No backend / schema / engine change**
(reuses `POST /immo/units`, called N times).

Only this. P1.2/P1.5 + P2 stay next in the approved order.

## Today (evidence)
ImmobilienView → property detail → "➕ Einheit anlegen" (`ImmoUnitForm`, index.html:2447) creates ONE
unit; `createUnit` (3864) → one `POST /immo/units`. For 8 flats that's 8× (open form → fill → save).
The acceptance test flagged this as P1.1 ("'N daire ekle' / numara aralığı").

## The fix — a "Mehrere Wohnungen" bulk form

Next to "➕ Einheit anlegen", a second button **"➕➕ Mehrere anlegen"** opens a compact bulk form:

```
Mehrere Wohnungen anlegen
 Anzahl:            [ 8 ]
 Namensschema:      [ Whg  ] ab Nr. [ 1 ]      → Whg 1, Whg 2, … Whg 8   (live preview)
 Wohnfläche (m²):   [    ]  (optional, gilt für alle — später je Wohnung änderbar)
 Soll-Miete €:      [    ]  (optional, gilt für alle)
 [ 8 Wohnungen anlegen ]   [ Abbrechen ]
```

- **Anzahl (N):** 1–100 (guard; >50 → a confirm). 
- **Namensschema:** a text prefix (default `Whg `) + start number (default 1) → `Whg 1 … Whg N`. A live
  preview line shows the first few + last so the landlord sees exactly what will be created.
- **Wohnfläche / Soll-Miete:** optional, applied to every created unit; each is editable per unit
  afterwards (the existing edit form).
- **On save:** create N units client-side (loop `POST /immo/units`, same call as `createUnit`), then
  `refreshDetail`. A short progress/rollup ("8 Wohnungen angelegt ✓"). If one fails, stop and report how
  many were created (no partial-silent).

## Architecture
- New small component/inline `bulk` state in ImmobilienView + `createUnitsBulk(n, prefix, start, qm,
  miete)` = a loop over the existing units endpoint. Reuses `refreshDetail`, `_toast`.
- No new endpoint, no schema, no engine touch. Names collide-safe (the landlord can rename later; the
  system already allows duplicate unit names — they're just labels).
- Tenants: unchanged. With P0.1, adding a tenant lets the landlord pick the existing (vacant) unit, so
  bulk units + P0.1 = fast full setup. (True "bulk tenants" is out of scope — names/rents differ.)

## The 7-check frame (pre-commit gate, same rigor)
1. "Mehrere anlegen" creates exactly N units with the schema names. 2. Preview matches what's created.
3. Optional m²/rent applied to all. 4. Per-unit edit still works afterwards. 5. Single "Einheit anlegen"
unchanged. 6. Engine/results/PDF untouched (only index.html). 7. Mobile: form + preview wrap, no overflow.
Plus: `_L` DE/TR/EN (typografic ' only), babel ALL OK + structure BALANCED.

## Definition of Done
Bulk form (Anzahl + Namensschema + optional m²/rent + live preview) · N units created via the existing
endpoint · honest partial-failure report · single-add + per-unit edit unchanged · engine/schema untouched
· JSX both gates green · served-HTML markers · Go/No-Go deploy · sprint closed. P1.2 is next.

## Open decision
Namensschema: **prefix + start number** ("Whg " + 1 → Whg 1…N, recommended — simple + covers most), or
also offer a floor pattern (EG, 1.OG, 2.OG…)? Recommend prefix+number only for v1; floor pattern → later.
