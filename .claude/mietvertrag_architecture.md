# Sprint 5 — Mietvertrag Generator: ARCHITECTURE & SCOPE (approval required before any code)

**Goal.** A small German landlord produces a **legally usable Wohnraummietvertrag** in a few minutes:
the app pulls the property/unit/tenant data it already has, the landlord confirms a handful of choices,
and out comes a clean, print-ready PDF built from current, BGH-proof clauses.

This is a **template/form generator**, not legal advice. That distinction is the whole architecture.

---

## §0 — The binding legal stance (RDG / StBerG) — READ FIRST

A document generator driven by a fixed question-catalogue is **not** an unauthorised legal service.
This is settled: **BGH 2021 (Az. II ZR 209/18, "Smartlaw")** — an automated contract generator that
assembles a document from user answers is a **software product**, not Rechtsdienstleistung under the RDG,
as long as it does **not present itself as individual legal advice**. We build strictly inside that ruling.

**The law for this module (binding, verbatim):**
1. **No individual legal advice.** The app never evaluates the landlord's specific case ("in Ihrem Fall
   dürfen Sie…"). It offers a **Vorlage / Muster** the landlord fills and is responsible for.
2. **Language is neutral and non-guaranteeing.** "Muster / Vorlage / Vorschlag", never "rechtssicher
   garantiert", "wir beraten Sie", "geprüft für Ihren Fall".
3. **A prominent disclaimer** on screen and in the PDF footer: *Muster ohne Gewähr; keine Rechtsberatung;
   im Zweifel Mietrecht-Fachanwalt / Haus & Grund.*
4. **Only currently-valid clauses.** Clauses the BGH has struck down are NOT offered (see §5). We author
   our OWN clause text grounded in the BGB — no copying a copyrighted Haus&Grund/DMB form.
5. **Final responsibility is the landlord's** — the same posture as the Nebenkosten module ("Hilfe/Entwurf,
   Verantwortung beim Vermieter").

If a choice would require judging the individual case (e.g. "is my rent above the Mietpreisbremse cap?"),
the app **collects and warns**, it never rules. See §5.

---

## §1 — Data that ALREADY exists (reuse, never re-enter)

| Contract field | Source (already in DB) |
|---|---|
| Vermieter (name, Anschrift, IBAN) | `UserCompany` (company_name, address, iban) |
| Mietobjekt: Adresse, Wohnung, Wohnfläche | `ImmoProperty.adresse` + `ImmoUnit.name/wohnflaeche` |
| Mieter (Name) | `ImmoTenancy.mieter_name` (+ telefon/email) |
| Mietbeginn | `ImmoTenancy.von` |
| Kaltmiete | `ImmoTenancy.kaltmiete` (+ `miete_historie`) |
| Betriebskosten-Vorauszahlung | `ImmoTenancy.nk_voraus` |
| Kaution | `ImmoTenancy.kaution` |
| Personenzahl | `ImmoTenancy.personenzahl` |

The generator is a NEW **read** surface over this data + a small set of contract-only choices. It never
recomputes rent/debt (Architecture law: one accounting model). A generated contract may *write back* the
agreed Kaltmiete/NK/Kaution to the tenancy (one Payment-Service-safe update), or stay read-only — see §7.

## §2 — What is MISSING (added now, additive + nullable, so no future migration)

New table **`ImmoMietvertrag`** (one contract per tenancy, versioned):
- `id, user_id, tenancy_id (FK), status (entwurf|final), created_at, finalized_at, is_deleted`
- `vertrag_json (Text)` — the structured choices (type, clauses, options) that produced the document
- `pdf_snapshot / html_snapshot (Text)` — **frozen document** at finalise (Principle A: the snapshot,
  not a live re-render, is the record of truth — identical discipline to the NK Settlement snapshot)
- `vertrag_version (Int)` — the clause-set version, so a contract re-produces years later even if we
  later change the template

No change to existing tables. Boot-time `create_all` makes the new table; nothing to ALTER.

## §3 — The Wohnraummietvertrag structure (§§535 ff BGB)

Authored as a **pure template module** `mietvertrag_template.py` (DB-free, testable — same pattern as
`immo_nebenkosten.py`). Sections:

1. **Vertragsparteien** — Vermieter / Mieter (+ mehrere Mieter als Gesamtschuldner)
2. **Mietobjekt** — Anschrift, Lage, Wohnfläche, mitvermietete Räume (Keller/Stellplatz), Schlüssel
3. **Mietzeit** — unbefristet (default) / befristet (§575 with a valid Befristungsgrund) / Staffel (§557a) / Index (§557b)
4. **Miete & Betriebskosten** — Kaltmiete, Betriebskostenvorauszahlung (BetrKV), Heizkosten (HeizkostenV),
   Zahlungsweise/-termin (§556b), Bankverbindung
5. **Kaution** — max. **3 Kaltmieten (§551)**, Anlagepflicht getrennt verzinslich; the engine **caps** the
   entered Kaution at 3× Kaltmiete and warns if exceeded
6. **Betriebskosten-Umlage** — which BetrKV items are passed on (ties into the Nebenkosten module keys)
7. **Schönheitsreparaturen** — only a **BGH-valid** variant (no rigid Fristenplan, no "besenrein"+quota;
   an unrenovated flat handed over → clause left to the landlord's explicit choice, default: keine Abwälzung)
8. **Kleinreparaturen** — valid only with a per-case cap (~100 €) AND a yearly cap (~8 % of Jahresmiete)
9. **Tierhaltung** — Kleintiere frei; Hunde/Katzen "Zustimmung, die nicht unbillig verweigert wird" (BGH)
10. **Untervermietung** (§553), **bauliche Veränderungen**, **Hausordnung** (Anlage)
11. **Kündigung** — statutory notice, no clauses that undercut the tenant's §573c rights
12. **Schlussbestimmungen** — Schriftform, salvatorische Klausel, Anlagenverzeichnis
13. **Unterschriften** — Ort/Datum + signature blocks

## §4 — Configurable vs fixed

- **Auto-filled from data (§1):** parties, object, rent, deposit, start date.
- **Landlord chooses (guided):** Mietzeit-Typ, Kleinreparatur-Caps on/off, Schönheitsreparatur variant,
  Tierhaltung, Stellplatz/Keller mitvermietet, Betriebskosten-Umlage list, Zahlungstermin.
- **Fixed (statutory, not editable):** Kaution cap 3×, Kündigungsfristen, tenant-protective clauses.
  The user cannot generate an *invalid* clause — the invalid options simply don't exist in the picker.

## §5 — Legal safety rails (what the engine refuses / warns)

- **Kaution > 3 Kaltmieten** → capped + warning.
- **Mietpreisbremse (§556d):** we CANNOT know the local Mietspiegel cap → we **do not rule**; a neutral
  note collects the landlord's attention ("In Gebieten mit Mietpreisbremse gilt eine Obergrenze — bitte
  prüfen"). No cap is asserted.
- **Struck-down clauses are absent**, not toggled off — a landlord can't opt into an invalid Schönheits-
  reparatur/Kleinreparatur clause.
- **Disclaimer** on screen + PDF footer (§0.3).

## §6 — Document lifecycle (mirror the NK principles)

- **Immutable snapshot (A):** at "Fertigstellen" the HTML/PDF + `vertrag_json` freeze; the finalised
  contract renders from the snapshot, never a live re-render.
- **Finalize = Lock (B):** a final contract is read-only; a change means a **new Revision** (v2), the old
  one is kept. (A signed paper contract shouldn't silently mutate.)
- **PDF** via the existing reportlab path (reuse `immo_api` PDF infra + the Wohnungsgeberbestätigung/
  Protokoll styling). **Signature:** print-and-sign in v1; the finger-signature from Sprint 1
  (Übergabeprotokoll) can be grafted later — see §7.

## §7 — Scope: v1 (this sprint) vs deferred — LOCKED (product owner, 2026-07-16)

**In v1 (approved):**
- Wohnraummietvertrag, **unbefristet + Staffelmiete (§557a)** — the two commonest for small landlords.
- Auto-fill from property/unit/tenant; guided clause choices; legal rails (§5).
- Immutable snapshot + finalize-lock + **print-and-sign PDF** (Schriftform §550 — wet signature, the
  legally safest for a Mietvertrag; no digital signature in v1).
- **Write-back ON:** the agreed Kaltmiete / NK-Vorauszahlung / Kaution are written onto the tenancy at
  finalise, through the same safe update path, so the Mietkonto and Nebenkosten stay one source of truth.
  (For Staffelmiete the steps also seed `miete_historie` so future rents match the contract.)

**Deferred (Sprint 5.x / later):**
- Indexmiete (§557b), befristeter Vertrag with Befristungsgrund, Gewerbe/Stellplatz-only contracts.
- Digital finger-signature inside the app + tenant self-sign link.
- Anlagen auto-bundle (Hausordnung + Übergabeprotokoll + Wohnungsgeberbestätigung as one packet).
- Mietspiegel/Mietpreisbremse lookup.

## §8 — Fit with the platform

Natural extension of the Vermieter module: the contract is the *start* of a tenancy, the
Übergabeprotokoll/WGB/Nebenkostenabrechnung are its lifecycle. `VERMIETER_MASTERPLAN.md`'s remaining
"Wohnung Akte" (property file) can later collect the contract + protocol + statements into one dossier —
this sprint delivers the contract piece.

---

## Open decisions for the product owner (approve before code)

1. **v1 Mietzeit-Umfang:** unbefristet + Staffelmiete (önerilen) — yoksa sadece unbefristet (daha hızlı),
   ya da +Indexmiete/befristet (daha geniş, daha yavaş)?
2. **İmza akışı v1:** yazdır-imzala PDF (önerilen, hızlı) — yoksa Sprint 1 parmak-imzasını hemen entegre et?
3. **Write-back:** sözleşmedeki Kaltmiete/NK/Kaution otomatik tenancy'ye yazılsın mı (Mietkonto uyumlu) —
   yoksa sözleşme salt-okunur kalsın, ev sahibi Mieter ekranından ayrı mı girsin?
