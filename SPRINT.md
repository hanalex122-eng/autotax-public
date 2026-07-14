# SPRINT — one active sprint at a time

**Rule:** `Finish > New Features`. See CLAUDE.md → "Sprint discipline". No topic switching, no new
features proposed, until the active sprint passes the Definition of Done below.

---

## Definition of Done (all 8 must be true)

- [ ] Code complete
- [ ] Tests green
- [ ] UX checked (real user flow, not just endpoints)
- [ ] Contradicting legacy flows removed (no two screens telling different truths)
- [ ] Review done
- [ ] Deployed
- [ ] Smoke-tested on production
- [ ] No critical gap left from the user's point of view

---

## ACTIVE SPRINT — Sprint 0: "Fundament — make Mietkonto tell the truth"

**Opened:** 2026-07-14
**Serves:** `VERMIETER_MASTERPLAN.md` items #1 #2 #3 (marked ✅ there, **not actually done**) and
unblocks #8 Nebenkostenabrechnung.

**Why this one, and not straight to the masterplan's 🔴 items:** the Exception Engine sprint
(2026-06-23…26) shipped at ~80%. The new model was added but the old flows were never removed, so the
product now tells three different truths about the same money (Bu Ay vs. Mieteingang tab vs. Berichte),
and the debt figure itself is wrong (NK missing, previous months + previous years invisible).
Nebenkostenabrechnung (#8, ⭐⭐⭐) sits directly on top of this: it needs a correct Soll incl.
NK-Vorauszahlung. Building #6/#7/#8 on a Mietkonto that miscounts money would mean shipping a second
floor onto a cracked foundation — exactly what "Finish > New Features" forbids.

**Scope (evidence: code review 2026-07-14, file:line in `.claude/immo_finish_review.md`)**

### A. Truth bugs — the product currently lies about money (P0)
- [ ] A1 Arrears from *previous months* are invisible on "Bu Ay" → screen can say "✅ Alles bezahlt"
      while the tenant owes €1.200. (`index.html:2487-2492`, `immo_api.py:1488-1502`)
- [ ] A2 Arrears are year-scoped → unpaid December vanishes on 1 January and cannot be dunned.
      (`immo_api.py:1488-1502`, `190`, `1616`)
- [ ] A3 Nebenkosten not part of Soll → debt and the Mahnung amount are short by the NK every month.
      (`immo_api.py:832-838`, `1520`, `1631` vs `index.html:2685`)
- [ ] A4 Orphan delete: deleting a property/unit leaves its tenants live on Mieter + Bu Ay.
      (`immo_api.py:375-385`, `930-940`, `193-199`) — was OPEN_ITEMS P1
- [ ] A5 Mahnung letter: no tenant address, no concrete deadline date, signed "Die Hausverwaltung"
      instead of the landlord. (`immo_api.py:1627-1636`)

### B. Contradicting legacy flows — DoD condition #4 (P0)
- [ ] B1 **ONE accounting model, many UIs** (user decision 2026-07-14 — Mieteingang is NOT removed).
      Introduce a single **Payment Service**; every payment path is only a UI on top of it:
      "Bezahlt" button · partial payment · Mieteingang tab · (future) bank import.
      All of them write the **Exception Engine** model; every read surface (Bu Ay, Mietkonto, Mahnung
      amount, Berichte, Nebenkosten) derives from it and never recomputes its own truth.
      Today the Mieteingang tab writes ImmoRent rows that change no debt number → payment recorded,
      debt unchanged. (`immo_api.py:1104`, `1505-1508`; `index.html:2914-2921`)
      **Mandatory: never two parallel debt systems.** See CLAUDE.md → "Architecture law".
- [ ] B2 "📊 Berichte" contradicts itself and Bu Ay: Gewinn negative while its own detail list is
      positive, income chart always zero, "Miete Jun fehlt" for tenants Bu Ay calls ✓ sorgenfrei.
      (`immo_api.py:1155-1162`, `1213`, `1319`, `1379-1387`)
- [ ] B3 Dead columns/flags: `auto_paid` (dead, still ALTER TABLE'd every boot), `offene_monate`
      wrongly commented "(dormant)" although it stores the live exception data. (`models.py:918-919`)

### C. UX — the module is unusable/untrustworthy without these (P1)
- [ ] C1 German UI shows Turkish buttons: "✓ Ödendi" / "✗ Ödenmedi" are the primary actions.
      (`index.html:2695-2696`, `2634-2635`)
- [ ] C2 "✗ Ödenmedi" and "📨 Mahnung" fire with no confirmation; Mahnung persists a legal record
      with no way to delete it. (`index.html:2503`, `2696`, `2709`)
- [ ] C3 Error = wrong empty state ("Noch keine Immobilie" on API failure), Berichte hangs on
      "Lädt…" forever, no retry. (`index.html:2785`, `2334`, `2483`)
- [ ] C4 Mahnung is hardcoded `stufe:1` → escalation (2./3. Mahnung) unreachable; Mahnung history
      endpoint exists but has no UI. (`index.html:2486`, `2566`; `immo_api.py:1428`, `1529`)
- [ ] C5 "Dauerzahlung" is never explained *inside* the module — the app assumes rent is paid and
      shows ✓ without telling the landlord. One sentence on Bu Ay + Mieter.
- [ ] C6 Bu Ay (the app's landing screen for every user) is not mobile-aware. (`index.html:2493-2506`)
- [ ] C7 Field hints (3 languages) on Immobilien inputs — user reported the forms are "çok karışık".
- [ ] C8 Tenancy Detail: no year switcher → last year's Mietkonto unreachable. (`index.html:2579`)

**Sprint exit report goes here when closing** (completed · deferred · open risks · honest
"is it really done?").

---

## BACKLOG — parked, do NOT start before the active sprint closes

### Funnel / conversion (next sprint candidate — evidence in `.claude/immo_finish_review.md`)
- Landing CTAs point to `/app?action=register` but the SPA never reads the param → every visitor
  who clicks "Kostenlos starten" lands on the **login** form. (`index.html:492`)
- Signup screen is in English on a German funnel ("Welcome back", "John Smith"); brand flips from
  AutoTax.Cloud to AutoTax-HUB + BETA badge. (`index.html:615-630`)
- Password rules disagree in 3 places (client ≥6, hint 8+special, backend 8+upper+digit) → 400s.
  (`index.html:557`, `621`; `main.py:5470-5475`)
- Register throws away the returned token and forces a second login. (`index.html:568-569`)
- "14 Tage kostenlos" is advertised but never provisioned (`DEFAULT_REGISTRATION_PLAN=free`,
  `trial_ends_at` only set when default is `pro`). (`main.py:5484-5489`) — also a misleading-ad risk.
- Prices disagree in 4 places (landing 15/39/89 · backend PRICING 9/29 · admin 15/39/89/149 ·
  chatbot "Pro €20"). (`landing.html:872-929`; `main.py:12613-12619`, `5078`, `13157`)
- Stripe kill switch defaults ON → checkout 503 unless `STRIPE_KILL_SWITCH=0` is set. (`billing.py:61`)
- **Zero analytics anywhere** → no funnel step is measurable today.
- Landing never mentions Mahnung / Leerstand / Nebenkostenabrechnung / Kaution / Rückstand — the
  landlord module is invisible to a visitor, while the app is landlord-first for everyone
  (`_initialPage` → "bu_ay" for every user, `index.html:7214-7220`).
- Landing has zero screenshots and zero real testimonials; Impressum e-mail is on a different
  domain (autotaxhub.de) and USt-ID says "wird nachgereicht". (`main.py:2386`)

### Immobilien — deliberately out of this sprint
- Ledger Phase 1+ (backfill/apply). `IMMO_LEDGER_READ` is OFF in prod; the read path is inert.
- Untermieter feature (TDD spec exists and is skipped: `tests/test_immo_untermieter.py`).
- Nebenkostenabrechnung (NK settlement) module.
- Dead endpoints with no UI: `/immo/events` CRUD, `/immo/dashboard`, `/immo/tenancies/{tid}/mahnungen`,
  legacy flat `/immo/tenants`.

### Other
- Premium "invisible strong engine" for the first 5 documents (flag-gated design ready).
- Landing redesign (control-center language, no "AI" hype).
- Root-level one-off scripts (~75 untracked files) → `scripts/scratch/`.
