# Code review 2026-07-14 — user's-eye review of the shipped Immobilien module + funnel

Reviewed state: `main` @ `fe93c98` (pre-holiday stabilization). Working tree clean — this is a review
of what is **live**, not of a pending diff. Every claim below is code-cited.

**Verdict:** the *concept* (Dauerzahlung / exception model — "only mark what was NOT paid") is right.
The *implementation* is at ~80% and currently damages trust: the same product tells three different
truths about the same money. Not a feature problem — a finishing problem.

---

## 1. Truth bugs — the product lies about money

| # | Finding | Evidence |
|---|---|---|
| A1 | "✅ Alles bezahlt — nichts zu tun" while the tenant owes for earlier months. Bu Ay only reads the *current month's* exception; a tenant unpaid in Mar/Apr/May counts as ✓ sorgenfrei and is never listed. Σ chip excludes it too. | `index.html:2487-2492` + `immo_api.py:1488-1502` |
| A2 | Arrears are year-scoped: `_exception_arrears(t, year)` iterates one year, `/mieter` defaults to `now.year`, Mahnung likewise → unpaid December is invisible and undunnable on 1 January. | `immo_api.py:1488-1502`, `190`, `1616-1617` |
| A3 | `_monat_soll` = Kaltmiete × pro-rata only; `nk_voraus` is never added. Tenant card says "Gesamt €470", Bu Ay says "❌ €400", **and the Mahnung duns for €400**. | `immo_api.py:832-838`, `1520`, `1631` vs `index.html:2685` |
| A4 | Orphan delete. `delete_property` soft-deletes only the property row; `/mieter` selects tenancies by `user_id` alone → deleted building's tenants stay on Mieter + Bu Ay with a blank address, still accruing debt, still offering Mahnung. Same for `delete_unit` (cascades the ledger, never sets `t.is_deleted`). | `immo_api.py:375-385`, `930-940`, `193-199` |
| A5 | Mahnung letter has no tenant address, no concrete deadline date ("innerhalb von 14 Tagen"), and is signed **"Die Hausverwaltung"** — not the landlord. German-only regardless of UI language. | `immo_api.py:1627-1636` |
| — | Partial-failure hole: the one-page "Neuer Mieter" flow fires 3 sequential POSTs with no rollback; if the tenancy POST fails, property+unit are orphaned. | `index.html:2550-2561` |
| — | API error renders as an empty portfolio (`.catch(()=>setLoading(false))`). | `index.html:2483`, `2542` |

## 2. Contradicting legacy flows (the reason the sprint is not "done")

- **B1 Two payment systems.** Mark "Ödenmedi" (debt €400) → record €400 in the "📈 Mieteingang" tab →
  green toast, row appears — **debt stays €400**. `_tenancy_arrears` returns `_exception_arrears` and
  ignores payments; `_accounting` overwrites `ist_total` with Soll−exceptions.
  `immo_api.py:1104`, `1505-1508`; UI `index.html:2914-2921`
- **B2 Berichte contradicts itself and Bu Ay.** `_portfolio` still computes income from `ImmoRent` rows,
  which the exception engine never creates:
  - "💰 Gewinn" KPI is negative (0 income − expenses) while the *same card's* detail list (from
    per-property `_accounting`) is positive. `immo_api.py:1155-1162`, `1213`, `1345`
  - "Mieteingang/Monat" chart is all zeros forever. `index.html:2391`
  - Score component `inkasso = ist/soll*100` = 0 → portfolio score red. `immo_api.py:1319`
  - "⚠ Heute wichtig" shows `missing_rent` for every active tenant every month — including the ones
    Bu Ay calls ✓ sorgenfrei. `immo_api.py:1379-1387`
- **B3 Dead state.** `auto_paid` is dead but still ALTER TABLE'd on every boot; `offene_monate` is
  commented "(dormant)" although it *is* the exception engine's live storage. `models.py:918-919`,
  `db.py:72-74`. `IMMO_LEDGER_MAHNUNG` flag referenced nowhere (`config.py:60-67`).

## 3. UX gaps

- **C1** German UI renders Turkish primary buttons: `_L("Ödendi","Ödendi","Paid")` → "✓ Ödendi" /
  "✗ Ödenmedi". `index.html:2695-2696`, `2634-2635`
- **C2** "✗ Ödenmedi" has no confirmation and sits 6px from "✓ Ödendi". "📨 Mahnung" has no
  confirmation yet persists an `ImmoMahnung` record with no delete UI. `index.html:2503`, `2696`, `2709`
- **C3** `ImmobilienView` has no loading state → a landlord with 3 properties sees "Noch keine
  Immobilie" on every visit, permanently if the fetch fails. `Berichte` sticks on "Lädt…" forever on
  error, no retry. `index.html:2785`, `2334`
- **C4** Mahnung hardcoded `stufe:1` at both call sites → 2./3. Mahnung unreachable although the
  backend supports them; `/tenancies/{tid}/mahnungen` has no UI. `index.html:2486`, `2566`;
  `immo_api.py:1428`, `1529`
- **C5** "Dauerzahlung" is explained only in the separate Help center (`index.html:5356`) — never in
  the module. The app asserts money it never saw.
- **C6** Bu Ay — the landing screen for *every* user (`index.html:7214-7220`) — has no `useIsMobile`;
  the Σ chip (`fontSize:26`, `minWidth:140`) clips on a 360px phone. `index.html:2493-2506`
- **C7** Jargon with no explanation: Soll/Ist, Stammdaten, Kaltmiete, Zahlungsausfall, WGB, Mietkonto,
  Erstmiete. `index.html:2615-2616`, `2876`, `2882-2884`
- **C8** Tenancy Detail: one action (WGB PDF), no year switcher → last year's Mietkonto unreachable.
  `index.html:2579`, `2604-2642`
- Mixed i18n both ways: hardcoded German for TR/EN users (`Stammdaten`, `Einzug`, `Soll`/`Ist`), and
  backend errors are always German, surfaced raw via `alert(e.message)`. `immo_api.py:64`, `259`, `1565`
- "○ Anmeldung" chip can never be ticked — backend accepts `anmeldung_done`, no control sends it.
  `index.html:2612`, `2688`; `immo_api.py:883`, `981`

## 4. Funnel (parked in SPRINT.md backlog — evidence kept here)

- Every landing CTA → `/app?action=register`, but the SPA never reads `action` → the visitor lands on
  the **login** form. `landing.html:400`, `418`, `649`, `883`; `index.html:492`
- Auth screen is English inside a German funnel; brand flips AutoTax.Cloud → AutoTax-HUB + BETA.
  `index.html:615-630`
- Password rules disagree in 3 places → avoidable 400s. `index.html:557`, `621`; `main.py:5470-5475`
- Register returns a token, the SPA discards it and forces a second login. `index.html:568-569`
- "14 Tage kostenlos testen" is advertised but never provisioned (`DEFAULT_REGISTRATION_PLAN=free`;
  `trial_ends_at` only set when the default is `pro`; `TRIAL_DAYS`=15). `landing.html:870`, `973-974`;
  `main.py:5484-5489`
- Prices disagree in 4 places. `landing.html:872-929`; `main.py:12613-12619`, `5078`, `13157`
- Stripe kill switch defaults ON → checkout 503 unless `STRIPE_KILL_SWITCH=0`. `billing.py:61-77`
- **No analytics of any kind** (grep: gtag/plausible/posthog/matomo/pixel/dataLayer → 0 hits). No
  register audit event. The funnel is unmeasurable today.
- The landing never says Mahnung / Leerstand / Nebenkostenabrechnung / Kaution / Mieterhöhung /
  Rückstand — the landlord work of the last 10 commits is invisible to a visitor. Demo is a REWE
  grocery receipt. `landing.html:588-604`, `610-668`
- No screenshots, no named testimonials; Impressum e-mail on autotaxhub.de, USt-ID "wird nachgereicht".
  `landing.html:427-469`; `main.py:2386`
