# Sprint P1.3 — NK-Kostenraster entschlacken (Architecture + UX design)

**Single goal:** the Nebenkosten cost grid must not open all 14 BetrKV categories as empty rows on every
statement. Show a small starter set + a clear "add cost type" control, and make explicit that anything
not listed is simply 0. One screen. **No backend, no schema, no engine change** — pure frontend
visibility over the exact same positions/data model.

Only this. P1.4 (Verbrauch invoice↔meter wording) stays next in the UX backlog.

## Today (evidence)
`NkEditor` renders `NK_STD.map(...)` (index.html:3478) → all 14 categories as rows regardless of value.
~9 empty rows on a typical building. Friction: "which do I fill? is blank = 0?"

---

## The 7 questions — answered

### 1. Kullanıcı ekranı nasıl görecek? (What the screen looks like)
The grid keeps its 4 columns (Kostenart · Rechnung € · ÷ Verteilung · = Ergebnis) and every per-row
mechanic (Betrag, Schlüssel restriction, inline result, Individuell/Verbrauch/HeizkostenV wizard). What
changes: **only relevant rows are shown**, each with a small ✕ to remove it, and below them a single
**➕ Kostenart hinzufügen** control. A one-line note kills the "blank = 0?" doubt.

```
 Kostenart              Rechnung €   ÷ Verteilung        = Ergebnis
 Heizkosten        ✕      [ 1.200 ]  [Verbrauch ▾]          480 €
 Wasser (kalt)     ✕      [   360 ]  [Verbrauch ▾]          360 €
 Müllabfuhr        ✕      [   600 ]  [Personenzahl ▾]       600 €
 Grundsteuer       ✕      [       ]  [Wohnfläche ▾]           —
 Gebäudeversicher. ✕      [       ]  [Wohnfläche ▾]           —
 Allgemeinstrom    ✕      [       ]  [Wohnfläche ▾]           —
 ───────────────────────────────────────────────────────────────
 ➕ Kostenart hinzufügen ▾
 Typisch, noch nicht erfasst: (—)                                  [×]
 ⓘ Nur die Kosten eintragen, die es wirklich gibt — was nicht in der Liste steht, wird mit 0 gerechnet.
 ───────────────────────────────────────────────────────────────
 Summe umlagefähig                                              1.440 €
```

### 2. İlk açılışta hangi 6 kategori görünecek? (The 6 seeded on first open)
A brand-new statement (0 positions) opens with the **6 most common** BetrKV costs as empty rows — a
practical checklist, not 14:

1. **Heizkosten** · 2. **Wasser (kalt)** · 3. **Müllabfuhr** · 4. **Grundsteuer** ·
5. **Gebäudeversicherung** · 6. **Allgemeinstrom**

(Warmwasser, Abwasser, Hausmeister, Gartenpflege, Schornsteinfeger, Winterdienst, Straßenreinigung,
Sonstige → available via "hinzufügen".) The landlord fills what applies, removes the rest, adds any of
the other 8. Rationale: these 6 appear in almost every German Abrechnung; showing them keeps the old
grid's guidance while dropping 8 rarely-used rows.

### 3. "Kalem ekle" nasıl çalışacak? (How "add cost type" works)
A dropdown listing only the not-yet-shown categories, grouped so nothing legal is buried:
- **Häufig:** the common set (whichever of the 6 were removed) + Warmwasser
- **Weitere:** Abwasser · Hausmeister · Gartenpflege · Schornsteinfeger · Winterdienst · Straßenreinigung · Sonstige

Pick one → its row appears empty and the Betrag input takes focus. (Local `nkShown` list; no server call
until a Betrag is entered — exactly as today.)

### 4. Kullanıcı eklediği kategoriyi silebilecek mi? (Can a row be removed?)
Yes — a small **✕** on each row:
- Row has **no saved Betrag** → just hide it (drop from the visible list). No server call.
- Row **already has a value** (a saved position) → a confirm (*"Kostenart „…“ entfernen?"*) then delete
  the position via the existing `DELETE /immo/nk/{aid}/position/{pid}` (finalisiert → 409, unchanged).
Nothing new on the backend.

### 5. Daha önce eklenmiş kategoriler nasıl görüntülenecek? (Existing/previously-added categories)
When the landlord reopens a **draft that already has positions**, the grid shows **exactly those
categories** (derived from `nkOpen.positionen`) — the 6-seed applies **only** to a statement with 0
positions. So a returning draft never loses or hides an entered cost, and never re-injects unwanted
defaults. Any category the user adds this session is shown too.

### 6. Eski kayıtlarla uyumluluk nasıl korunacak? (Backward compatibility)
**Fully — because nothing about the data changes.** Positions are stored exactly as before; the change
is purely which rows the frontend *renders*. Concretely:
- **Finalisierte Abrechnungen:** the locked view already shows only the positions in the frozen
  `ergebnis_snapshot` — untouched. The immutable-snapshot principle is not affected.
- **Existing drafts:** their positions render as rows (Q5). A draft that happens to have all 14 filled
  still shows all 14.
- **Engine / CALCULATION_VERSION / schema:** no change. No migration.

### 7. Mobil görünüm nasıl olacak? (Mobile)
Fewer rows is a direct mobile win (the 4-column grid is tightest on phones). Specifics:
- The grid keeps its current responsive width; with 6 rows instead of 14 there's far less vertical
  scrolling.
- ✕ is a touch target at the start of each row; the "hinzufügen" dropdown is a full-width native
  `<select>` (native mobile picker — thumb-friendly, no custom menu).
- The clarity note wraps; the "typisch, noch nicht erfasst" hint wraps to its own line.
- No new horizontal overflow: we only remove rows, we don't widen columns.

---

## Definition of Done
New statement seeds the 6 common rows · existing statements show their own positions · grouped
"Kostenart hinzufügen" · ✕ remove (reuses delete endpoint) · clarity line · "typisch, noch nicht
erfasst" hint (dismissable) · locked view + engine + schema untouched · JSX PARSE OK/BALANCED +
render/logic check + served-HTML markers · Go/No-Go deploy · sprint closed. P1.4 stays backlog.

## Open decision
The default-6 set on first open: confirm **Heizkosten · Wasser · Müllabfuhr · Grundsteuer ·
Gebäudeversicherung · Allgemeinstrom**, or adjust (e.g. swap Allgemeinstrom ↔ Warmwasser)?
