# Sprint 1 — Move-in / Move-out Package  (Masterplan #6 + #7 + #5)

**Goal (user's words):** *"A landlord must complete an entire tenant handover inside AutoTax."*
No Word. No Excel. No paper. No PDF hunting.

**Success test (the only one that matters):** the landlord stands in the empty flat with his
**phone**, the tenant next to him, and 5 minutes later both have signed and the PDF is in the
tenant's inbox — without opening any other app.

---

## What exists today (reuse, don't rebuild)

| Piece | Status | File |
|---|---|---|
| Wohnungsgeberbestätigung PDF (§19 BMG) | ✅ works | `immo_api.py` `wohnungsgeber_pdf()` |
| `anmeldung_done` flag | ⚠️ exists, **no UI can ever set it** | `models.py:914`, read-only chips |
| Document upload + storage | ✅ works (property-scoped) | `upload_document()`, `storage.save_file()` |
| PDF generation (reportlab) | ✅ used by Mahnung / WGB / report | `immo_api.py` |
| Mieter / Tenancy detail screen | ✅ the natural home for a handover | `index.html` MieterView |
| Übergabeprotokoll · Zählerstände · signatures | ❌ **nothing** | — |

---

## Data model (additive, nothing existing is touched)

```
ImmoProtokoll                 one handover (Einzug or Auszug)
  id, user_id, tenancy_id, unit_id
  art            "einzug" | "auszug"
  datum          date of the handover
  status         "entwurf" | "abgeschlossen"      ← locked after signing
  raeume         JSON  [{name, elemente:[{was, zustand, notiz}], notiz}]
  schluessel     JSON  [{typ:"Haustür", anzahl:2}, …]
  personen       JSON  {vermieter, mieter, zeugen[]}
  unterschrift_vermieter   Text (PNG data-URL)
  unterschrift_mieter      Text (PNG data-URL)
  unterschrift_datum       date
  notiz, created_at, is_deleted

ImmoZaehlerstand             one meter reading (also usable WITHOUT a protocol)
  id, user_id, unit_id, protokoll_id (nullable)
  art            "strom" | "wasser" | "warmwasser" | "gas" | "heizung"
  zaehler_nr, stand (float), einheit ("kWh"|"m³")
  datum, foto_document_id (nullable), notiz

ImmoDocument   + protokoll_id (nullable), + raum (nullable)   ← photos reuse the existing table
```

**Zählerstände is deliberately its OWN table, not JSON inside the protocol** — Masterplan #7
wants *history + chart*, and Sprint 2 (Nebenkostenabrechnung) needs Heizkosten/Wasser
consumption **per period**. A reading taken at a handover and a reading taken in January must
live in the same series.

## Rules (pure, testable — `immo_protokoll.py`)

- A protocol belongs to a tenancy; Einzug defaults to `tenancy.von`, Auszug to `tenancy.bis`.
- Default room list is generated from the unit (Wohnzimmer, Schlafzimmer, Küche, Bad, Flur…),
  each with the standard elements: **Wände · Boden · Decke · Türen · Fenster · Heizkörper**
  (+ Küche: Herd/Spüle/Schränke · Bad: WC/Dusche/Wanne/Waschbecken).
- Condition scale, 4 steps: **neu · gut · gebraucht · beschädigt** (+ free note + photo).
- **`abgeschlossen` = immutable.** After both signatures the protocol can no longer be edited —
  that is the whole point of a handover document. A correction = a new protocol (`Nachtrag`).
- Consumption between two readings of the same meter = `stand_neu − stand_alt` (never negative;
  a lower reading flags a meter change → `zaehler_nr` differs).

## Endpoints (thin — logic lives in the rules module)

```
POST   /immo/protokolle                     {tenancy_id, art}  → draft with pre-filled rooms
GET    /immo/protokolle?tenancy_id=         list (for the tenant screen)
GET    /immo/protokolle/{id}                full protocol
PATCH  /immo/protokolle/{id}                rooms / keys / notes / persons   (only while draft)
POST   /immo/protokolle/{id}/foto           multipart, {raum}                (only while draft)
DELETE /immo/protokolle/{id}/foto/{doc_id}
POST   /immo/protokolle/{id}/unterschrift   {rolle:"vermieter"|"mieter", png}
POST   /immo/protokolle/{id}/abschliessen   both signatures required → status=abgeschlossen (LOCK)
GET    /immo/protokolle/{id}/pdf            the document

POST   /immo/zaehler                        {unit_id, art, stand, datum, zaehler_nr, protokoll_id?}
GET    /immo/units/{id}/zaehler             history per meter type + consumption + chart series
DELETE /immo/zaehler/{id}
```

## PDF (the deliverable the landlord actually hands over)

Letterhead (landlord's Firmen data) · Objekt + Wohnung · Einzug/Auszug + date · parties ·
**room-by-room table** (element · condition · note) · **meter table** (type · number · reading ·
date) · **keys** (type · count) · **photos** (thumbnails, grouped by room, max ~12) ·
**both signatures** as images + name + date · footer "Erstellt mit AutoTax".

## UI — a 5-step wizard, phone first (this is used *standing in the flat*)

Entry point: Mieter → tenant → **🔑 Übergabe** (Einzug or Auszug).

1. **Start** — Art (Einzug/Auszug), date, who is present.
2. **Räume** — accordion per room; 4-button condition selector (big tap targets), note, 📷 photo
   (uses the phone camera directly: `<input type="file" accept="image/*" capture="environment">`).
3. **Zähler** — one card per meter type; number + reading + 📷 photo of the meter.
4. **Schlüssel** — key type + count (+/−).
5. **Unterschriften** — two signature canvases (finger), then **Abschließen** → PDF.

After an **Einzug** protocol is completed, the app offers **"Wohnungsgeberbestätigung erstellen"**
(the PDF already exists) and finally lets the landlord **tick `anmeldung_done`** — the chip that
has been permanently "○" until now. That closes Masterplan **#5**.

## Commits

| # | What | Visible? |
|---|---|---|
| **C1** | Schema (3 additive tables/columns) + `immo_protokoll.py` rules + unit tests. **No endpoint, no UI, no behaviour change.** | no |
| **C2** | Endpoints + PDF + tests (incl. the immutability rule) | API only |
| **C3** | The wizard UI (mobile-first) + photo capture + signature canvas | **yes** |
| **C4** | Zählerstände history + consumption chart on the unit + WGB/`anmeldung_done` closing step | **yes** |
| **C5** | Deploy + production smoke (a real handover, end to end) + sprint close report | — |

Every visible change gets a BEFORE/AFTER line and a test that proves it. No migration of
existing data is needed (all three tables are new).

## Risks / decisions to confirm

1. **Photo storage.** Photos go to the Railway disk via `storage.save_file()` (like receipts).
   A handover with 15 phone photos ≈ 30–60 MB. Disk shows 821 GB free → fine. Should photos be
   **downscaled server-side** (e.g. max 1600px) to keep the PDF small and the disk sane? *I
   recommend yes.*
2. **Signature = PNG data-URL** drawn on a canvas. It is a *document* signature (like a scanned
   one), **not** a qualified electronic signature (QES). Legally that is what a paper
   Übergabeprotokoll is too — but the UI must not claim more than it is.
3. **Immutability.** After `abgeschlossen` nothing can be edited. Confirm you want that hard lock
   (I think it is exactly the point of the document).
4. Sprint 1 does **not** include e-mailing the PDF to the tenant (that is Sprint 3, together with
   the Mahnung e-mail path). The landlord downloads/shares the PDF from the phone.
