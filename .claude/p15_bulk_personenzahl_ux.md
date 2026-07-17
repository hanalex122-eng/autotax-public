# Sprint P1.5 — Personenzahl schnell für alle Mieter (Architecture + UX design)

**Single goal:** entering head counts for a Personenzahl split (Wasser/Müll) must be as fast as the meter
matrix — type, Enter-down, one save — instead of a per-field save that reloads the whole statement each
time. Last P1 from the acceptance test. **No backend/schema/engine change.**

Only this. After it, P2 backlog; #13 Wohnung Akte = design-only.

## Today (evidence)
The "Personenzahl-Verteilung" panel (NkEditor, index.html:3608) ALREADY lists every tenant (+ Eigennutzung
units) with an input each — so it is not literally one-screen-per-tenant. But:
- Each input **auto-saves on blur** via `nkSavePers` (3340), which PATCHes that tenancy AND reloads the
  entire statement (`setNkOpen(await api(...))`). 8 tenants = 8 network round-trips + 8 full recomputes →
  slow, flickery, focus can jump.
- **Enter just blurs** (3624); it does not move to the next tenant. No Excel-style ↓ flow, so the landlord
  clicks each field.

## The fix — meter-matrix ergonomics for the person panel
- **Excel keyboard:** Enter / ↓ moves focus to the next person field (tenants, then Eigennutzung units);
  ↑ moves back. Type-Enter-type-Enter through all N without touching the mouse. (Same pattern already
  proven in `ZaehlerMatrix`.)
- **One batch save:** a single **"✓ Speichern & verteilen"** button saves all changed counts (loop the
  existing `PATCH /immo/tenancies/{id}` / Eigennutzung update, then reload the statement **once**). Typing
  stays local until then — no per-keystroke reload.
- **Live total while typing:** "Personen gesamt" and each tenant's share preview update from the local
  input values (not only the saved ones), so the landlord sees the split form up before saving.
- **Unsaved-guard:** if there are unsaved edits, the button reads "✓ N Änderungen speichern" and a subtle
  "ungespeicherte Änderungen" hint shows — so nothing is silently lost (the current autosave never lost
  data; batch must not regress that).

## Architecture (minimal)
- Reuse the existing panel + `nkPers` / `nkEig` local state. Replace the blur-autosave with: keep edits in
  `nkPers`/`nkEig`, add `onKeyDown` ↑/↓/Enter focus movement over an ordered list of field ids, and a
  `saveAllPers()` that loops the existing PATCH calls for changed rows then reloads `nkOpen` once.
- `persTotal` and the per-row share preview compute from `nkPers`/`nkEig` (fallback to saved value) so the
  preview is live.
- No new endpoint, no schema, no engine touch. Same `personenzahl` field.

## The 7-check frame (pre-commit gate)
1. Enter/↓ advances through all person fields. 2. One "Speichern & verteilen" saves all changed. 3. Live
"Personen gesamt" + share preview update while typing. 4. Unsaved-edits hint (no silent loss). 5. Non-
Personenzahl statements unchanged (panel only shows when a position uses Personenzahl). 6. Engine/results/
PDF untouched (only index.html). 7. Mobile: numeric keyboard, panel wraps, one Save button.
Plus: `_L` DE/TR/EN (typographic apostrophe only), babel ALL OK + structure BALANCED.

## Definition of Done
Excel-keyboard + single batch save + live total + unsaved-guard in the Personenzahl panel · tenants and
Eigennutzung both covered · reuses existing PATCH (no backend) · engine/schema untouched · JSX both gates
green · served-HTML markers · Go/No-Go deploy · sprint closed. P1 backlog complete → P2 / #13 design next.

## Open decision
Save model: **batch on a button** (recommended — matches the meter matrix, kills the per-field reload
flicker; add the unsaved-edits hint so nothing is lost), or **keep autosave-on-blur** but only add Excel-
keys + drop the full-statement reload (save the single field silently, recompute lighter)? Recommend the
batch button for consistency with Zählerstände.
