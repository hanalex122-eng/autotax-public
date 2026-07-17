# Sprint P1.2 — Zählerstände ohne Abrechnungs-Zwang (Architecture + UX design)

**Single goal:** remove the ordering dependency "you must first create/open a Nebenkosten statement
before you can enter meter readings." A landlord who wants to enter meters first should find the entry
point in the Nebenkosten area — without creating a statement. Honors the earlier feedback (meters live in
Nebenkosten, NOT back in the Objekt-Details tab) and adds NO new screen. **No backend/schema/engine
change.**

Only this. P1.5 + P2 stay next.

## The 7 questions — answered

### 1. Mevcut kullanıcı problemi nedir? (Current problem)
The full meter matrix (`ZaehlerMatrix`, index.html:3679) is self-contained — it loads by property + year
(`zaehler-matrix` endpoint), independent of any statement. But its ONLY entry point is a button rendered
*inside an open statement* (NkEditor, line 3454, shown when `!locked`). At the Nebenkosten **list** view
(`if(!nkOpen)`, line 3400) there is no meter button. So a landlord who thinks "let me enter my meter
readings first" (before creating an Abrechnung) finds no way in — the acceptance test's step-5-before-
step-9 dead end (P1.2). (Per-tenant meters via Mieter→Mietkonto exist but are one-at-a-time, not the bulk
matrix.)

### 2. En basit kullanıcı akışı nasıl olmalı? (Simplest flow)
Nebenkosten → **🔢 Zählerstände eingeben** (visible even with no statement) → year selector (current year
default) → the same full matrix (Excel-keyboard, 5 meters) → Speichern. Done — no Abrechnung needed. When
a statement later needs those meters, they are already there.

### 3. Kaç ekran değişecek? (How many screens change)
**One** — the Nebenkosten view. We add the meter button to its **list header** (next to "Neue
Abrechnung", line 3401-3405) and render the existing `ZaehlerMatrix` modal from there too. The in-
statement button (3454) stays. Nothing else changes.

### 4. Yeni ekran açılacak mı? (New screen?)
**No.** It reuses the existing `ZaehlerMatrix` modal and the existing Nebenkosten view. No Details tab is
re-added (that was removed on purpose per earlier feedback — we keep meters in Nebenkosten). Just a second
entry point to a component that already exists.

### 5. Backend değişecek mi? (Backend change?)
**No.** `ZaehlerMatrix` already calls the property+year endpoints (`GET zaehler-matrix`,
`POST zaehler-bulk`) with no dependency on a statement id. Opening it from the list uses the same calls.
No new endpoint, no schema, no engine.

### 6. Eski kayıtlarla uyumluluk? (Backward compatibility)
**Fully preserved.** No data/schema/engine change. Existing meter readings and statements are untouched;
meters entered standalone land in the same `zaehler` records the in-statement matrix already writes, so a
later Abrechnung picks them up exactly as today. The in-statement flow is unchanged.

### 7. Mobil kullanım? (Mobile)
The `ZaehlerMatrix` modal is already the mobile meter UI (full-screen overlay, Excel keys). We only add
one more button in the list header (wraps with the existing "Neue Abrechnung" via the header's flex-wrap).
No new layout, no new overflow. The standalone year selector is a small native `<select>`.

## Architecture (minimal)
- Lift the `🔢 Zählerstände` button + the `nkZaehlerOpen` modal so they also render in the `if(!nkOpen)`
  list view. In the list context there is no `a.jahr`, so `initialJahr` = current year; the matrix's own
  year state lets the landlord switch year (add a small year `<select>` in the standalone header if the
  matrix doesn't already expose one).
- Reuses `ZaehlerMatrix`, `setNkZaehlerOpen`, `closeZaehler` (guard its `nkOpen` refresh so it no-ops when
  no statement is open).

## Definition of Done
"🔢 Zählerstände eingeben" reachable from the Nebenkosten list (no statement needed) · opens the existing
matrix for a selectable year · saves via the existing endpoints · in-statement button unchanged · no new
screen · no Details tab · engine/schema untouched · JSX both gates green (typographic apostrophe only) ·
served-HTML markers · Go/No-Go deploy · sprint closed. P1.5 is next.

## Open decision
Standalone year default: **current year** with a year `<select>` (recommended), or reuse the guided
`nk-jahre` picker (tenant-aware) also for the meter entry? Recommend a plain year select here — meters
aren't tenant-bound, so the tenant-aware picker would be over-constrained.
