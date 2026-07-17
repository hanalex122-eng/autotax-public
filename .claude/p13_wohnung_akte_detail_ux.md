# #13 Wohnung Akte — detailed screen UX (Option C: composition hub, 8 aspects, 2 deferred)

DESIGN ONLY. Chosen: **C — composition hub** (embeds existing components, no new data model, reads the
Exception Engine, never computes debt) · Mietvertrag + Reparaturen **deferred** (placeholders). Nothing is
coded until you approve; implementation will be phased in small sprints (one section at a time: tests →
deploy → close).

## Keying — the Akte belongs to the WOHNUNG (unit), not the tenant
A flat outlives its tenants. The Akte is opened for a **unit**; the tenant-scoped parts (Mietkonto,
Mahnung, NK share) resolve through the unit's **current tenancy** (and show history where relevant). This
keeps the flat stable across tenant changes.

## Entry point
From **Immobilien → Objekt → Einheiten**, each unit card gets one clear **"📂 Akte öffnen"** button. (No
new top-level menu — honors the no-new-screens rule in spirit; the Akte is a detail view reached from the
unit you already see.) Optional secondary entry later: Mieter → tenant → "zur Wohnung-Akte".

## Layout — one flat, sticky header + collapsible sections
```
┌─ 📂 Whg 3 · Wiesenstr. 10 ────────────── [✕ schließen] ─┐
│  Mieter: Ahmet Yılmaz · seit 01.01.2026                 │
│  Status: ● 2 Monate offen · Saldo 940 € (aus Mietkonto) │   ← READ from Exception Engine, not computed
├─────────────────────────────────────────────────────────┤
│ ▸ 🏠 Stammdaten          (m², Soll-Miete, Eigennutzung)  │
│ ▸ 👤 Kiracı              (aktuell + Verlauf, +wechseln)  │
│ ▸ 📄 Mietvertrag         → bald                          │
│ ▸ 💰 Mietkonto           (eingebettet, Monatsraster)     │
│ ▸ 📬 Mahnung             (Stufe + PDF, eingebettet)      │
│ ▸ 📑 Nebenkosten         (Anteil dieser Wohnung + Link)  │
│ ▸ ⚡ Zählerstände        (nur diese Wohnung, eingebettet)│
│ ▸ 🛠 Reparaturen         → bald                          │
│ ▸ 📷 Fotos               (Übergabeprotokoll-Fotos)       │
│ ▸ 📁 Belege              (Gebäude-Dokumente)             │
└─────────────────────────────────────────────────────────┘
```
Sections are collapsible; the header stays sticky. Default-open the 2–3 that matter most (Status/Mietkonto,
Mahnung if offen).

## Per-section composition source (all READ / reuse — no new debt logic)
| Section | Source component / data | New endpoint? |
|---|---|---|
| 🏠 Stammdaten | `ImmoUnitForm` (view/edit) on the unit | no |
| 👤 Kiracı | unit's tenancies (current + history); reuse add/change-tenant | no |
| 💰 Mietkonto | embed existing **Mietkonto** (fetchMk) for the current tenancy | no |
| 📬 Mahnung | embed existing Mahnung view/PDF for the current tenancy | no |
| 📑 Nebenkosten | this unit's row from the building statement `erg.tenants` (anteil_betrag) + link to the full NkEditor | no (reads existing) |
| ⚡ Zählerstände | `ZaehlerMatrix` rows filtered to this unit (Verbrauch je Wohnung) | no |
| 📷 Fotos | Übergabeprotokoll photos for the unit/tenancy | no |
| 📁 Belege | property Dokumente (building-level; note: not yet unit-scoped) | no |
| 📄 Mietvertrag / 🛠 Reparaturen | placeholder "→ bald" | later |

Status/Saldo in the header come from the **debt-derivation helper** the other screens already use — the
Akte never sums rows itself (Architecture law).

## Cross-cutting
- **One accounting model:** every money figure is read from the Exception Engine / derivation helper. The
  Akte is a UI, not a second book. No new `ImmoRent`/ledger writes.
- **No second Nebenkosten path:** the NK section shows the existing statement's result and links into the
  existing NkEditor for edits — it does not recompute.
- **Backward compat:** composition only → no schema change. Deferred features = additive later.
- **Mobile:** single column, sticky flat header, collapsible sections — replaces today's hop between
  Immobilien and Mieter, the worst mobile pain.

## Suggested implementation phasing (each a small sprint, only after approval)
1. Akte shell: entry button + header (flat + tenant + Status/Saldo read) + collapsible section frame with
   Stammdaten + Kiracı. (Highest value, lowest risk.)
2. Embed Mietkonto + Mahnung.
3. Embed Nebenkosten-Anteil + Zählerstände (this unit).
4. Fotos + Belege + "bald" placeholders → close #13 (masterplan capstone).

## Open UX decision
Entry point: **"📂 Akte öffnen" on each Einheiten unit-card** (recommended, no new menu), or also add a
top-level "Wohnungen"/Akte list? Recommend starting from the unit-card only.
