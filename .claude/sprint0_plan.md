# Sprint 0 — "Mietkonto tells the truth" — implementation plan

**Architecture law (CLAUDE.md):** every payment enters exactly once · no UI calculates debt · debt is
derived only from the Exception Engine · every screen is read-only w.r.t. debt · only the Payment
Service may modify payment state.

Evidence for every defect: `.claude/immo_finish_review.md`. Task list + DoD: `SPRINT.md`.

---

## The core problem in one picture

Today there are **two books**:

```
"Bezahlt" button ──► offene_monate (exception JSON)  ──► Bu Ay, Mietkonto, Mahnung   [book 1]
Mieteingang tab  ──► immo_rent rows                  ──► Berichte, Cockpit, charts   [book 2]
                                                          (+ immo_ledger, READ=OFF)  [book 3, dormant]
```
`_tenancy_arrears` returns the exception value and ignores payments (`immo_api.py:1505-1508`);
`_accounting` overwrites `ist_total` with Soll−exceptions (`:1104`); `_portfolio`/`_cockpit` still sum
`ImmoRent` (`:1155-1162`, `:1379-1387`). Hence: pay in Mieteingang → debt unchanged; Berichte says
"Miete fehlt" for a tenant Bu Ay calls ✓.

**After Sprint 0 — one book, many doors:**

```
"Bezahlt" · partial · Mieteingang · (future) bank import
                    │
                    ▼
        immo_payments.py  ── PAYMENT SERVICE (the only writer)
                    │  writes immo_rent (the payment fact, once)
                    │  recomputes the month's exception from Soll vs. paid
                    ▼
        EXCEPTION ENGINE (offene_monate) ── the only debt truth
                    │
    ┌───────────┬───────────┬──────────┬──────────┬──────────────┐
  Bu Ay     Mietkonto    Mahnung    Berichte   Nebenkosten   (all read-only)
```

---

## 1. Schema (additive, no destructive migration)

`models.py`
- `ImmoRent.fuer_jahr : Integer(nullable)` and `ImmoRent.fuer_monat : Integer(nullable)`
  → *which month this payment settles*. Today only `datum` exists, so a payment cannot be attributed
  to a rent month at all — the Payment Service is impossible without it.
- `ImmoRent.source` values become meaningful: `manual | quick | mieteingang | bank` (future).
- Fix the lying comments at `models.py:918-919`: `auto_paid` = dead (drop from the boot ALTER list),
  `offene_monate` = **live exception storage**, not "(dormant)".

`db.py` — add the two columns to the existing boot-time ALTER TABLE block (same pattern as today).

**Backfill (one-off, idempotent, dry-run first):** for existing `immo_rent` rows set
`fuer_jahr/fuer_monat` from `datum` (the month the payment was booked in). Founder/pilot data only.

## 2. `autotax/immo_payments.py` — the Payment Service (new, ~150 lines)

The **only** module allowed to touch payment state.

```python
def record_payment(db, uid, tenancy_id, *, betrag, jahr, monat, datum=None,
                   source="manual", notiz=None) -> dict
    # 1. validate ownership + amount (> 0)
    # 2. INSERT immo_rent (the payment fact — entered exactly once)
    # 3. _reconcile_month(db, uid, t, jahr, monat)   ← derives the exception
    # 4. (shadow) immo_ledger.post_entry — behind the existing flag, still READ=OFF

def delete_payment(db, uid, rent_id) -> dict          # soft-delete + reconcile that month
def mark_paid(db, uid, tenancy_id, jahr, monat)       # "Bezahlt" button → clear exception
def mark_unpaid(db, uid, tenancy_id, jahr, monat)     # "Nicht bezahlt" → unpaid exception
def mark_partial(db, uid, tenancy_id, jahr, monat, betrag)

def _reconcile_month(db, uid, t, jahr, monat):
    """THE single rule. soll = month_soll(t,y,m) (incl. NK!).
       paid = Σ immo_rent(tenancy, fuer_jahr=y, fuer_monat=m, not deleted).
       paid >= soll - 0.01  → clear exception          (no problem)
       0 < paid  < soll     → partial(offen = soll-paid)
       paid == 0            → leave the landlord's explicit flag as-is:
                              unpaid if flagged, otherwise no exception (Dauerzahlung default)."""
```

**Dauerzahlung stays intact:** no payment row and no flag = "assumed paid". A *recorded* payment only
ever moves the month toward paid; it can never silently create debt.

## 3. Debt derivation — one function, used by everyone

`immo_api.py`
- **A3 — NK belongs in the Soll.** `_monat_soll` currently returns Kaltmiete × pro-rata
  (`immo_api.py:832-838`). Add the pro-rated `nk_voraus` → the tenant owes the *Warmmiete* he actually
  owes. This single line is also the precondition for Masterplan **#8 Nebenkostenabrechnung**
  (Vorauszahlung tracking).
  *Careful:* `erstmonat_betrag` (vereinbarte Erstmiete) is a gross agreed amount → NK is **not** added
  on top of it. Existing stored `partial.offen` values were computed against a Kalt-only Soll; the
  backfill re-derives them from the payment rows so they stay consistent.
- **A1 + A2 — arrears across ALL months, not just this month / this year.**
  New `open_debt(db, uid, t, until=None) -> {total, months:[{ym, soll, paid, offen, typ}]}`, walking
  every active month from `t.von` to today across year boundaries. `_exception_arrears(t, year)` stays
  as the per-year view (Mietkonto tab) but is no longer what "who owes me" is built from.
  → Bu Ay's problem list and Σ chip come from `open_debt`, so December-unpaid does not vanish on
  1 January and a tenant unpaid in March is not "✓ sorgenfrei" in June.
- `_tenancy_arrears`, `_mahnung_betrag` → thin wrappers over `open_debt` (no second formula).

## 4. Read surfaces stop computing their own truth (B2)

- `_accounting` (`:1048-1119`): `ist_total` = Σ payments *derived through the service view*, `offen` =
  `open_debt`. Remove the `ist_total = ist_sum` overwrite at `:1104`.
- `_portfolio` (`:1134-1235`): stop summing `ImmoRent` independently — take income and arrears from the
  same derivation. Fixes: negative Gewinn vs. positive detail list, always-zero income chart, `inkasso = 0`
  score, red portfolio score.
- `_cockpit` (`:1310-1414`): the `missing_rent` action must be raised from the **exception engine**,
  not from "no ImmoRent row this month" (`:1379-1387`) — otherwise it fires for every tenant, forever.
- Result: Bu Ay, Mietkonto, Mahnung, Berichte and (later) NK all answer the same number.

## 5. Endpoints — thin, no logic

- `POST /immo/rent` (Mieteingang, `:469`) → `immo_payments.record_payment(...)` (+ `fuer_jahr/monat` in
  `RentIn`, defaulting to the month of `datum`). **The tab stays** — it is now a real door into the
  same book. UI gains a "Für Monat" selector.
- `DELETE /immo/rent/{rid}` (`:500`) → `delete_payment` (reconcile after removal).
- `POST/DELETE /immo/tenancies/{tid}/monat-bezahlt` (`:248`, `:271`) → `mark_paid` / `mark_unpaid`
  (same service, unchanged UX).
- `PATCH /immo/rent/{rid}` (`:482`, no UI today) → route through the service or drop it.

## 6. A4 — orphan delete (trust bug)

`delete_property` (`:375-385`) and `delete_unit` (`:930-940`) must cascade to their tenancies
(soft-delete), and `/mieter` (`:193`) must join through unit→property instead of selecting by
`user_id` alone. Today a deleted building's tenants keep accruing debt with a blank address.

## 7. A5 + C4 — Mahnung becomes a real letter

- Amount comes from `open_debt` (incl. NK) — today it duns Kalt-only (`:1520` → `:1631`).
- Letter (`:1627-1636`): tenant address block, concrete deadline **date** (not "innerhalb von 14
  Tagen"), landlord's name/company from Firmen instead of the hardcoded **"Die Hausverwaltung"**.
- Escalation: UI sends the real `stufe` (today hardcoded `stufe:1` at `index.html:2486`, `2566`);
  next stufe is suggested from the Mahnung history. Wire up the existing, never-called
  `GET /tenancies/{tid}/mahnungen` (`:1529`) as a small history list on the tenant card.
- Confirmation dialog before creating a Mahnung (it persists a legal record).

## 8. Frontend (`index.html`)

- **C1** Turkish buttons in the German UI → proper `_L("Bezahlt","Ödendi","Paid")` /
  `("Nicht bezahlt","Ödenmedi","Unpaid")` (`:2695-2696`, `:2634-2635`).
- **C2** Confirm dialogs for "Nicht bezahlt" and "Mahnung"; both are consequential.
- **C3** Real loading / error / retry states; an API failure must never render "Noch keine Immobilie"
  (`:2785`, `:2334`, `:2483`).
- **C5** One sentence explaining Dauerzahlung *inside* Bu Ay + Mieter: "Miete gilt als bezahlt — du
  markierst nur, was NICHT bezahlt wurde." (Today only in the separate Help center, `:5356`.)
- **C6** Bu Ay mobile: it is the landing screen for every user and has no `useIsMobile` (`:2493-2506`).
- **C7** 3-language field hints on all Immobilien inputs (user: "çok karışık").
- **C8** Year switcher on Tenancy Detail (`:2579`) — last year's Mietkonto is unreachable today.
- Mieteingang tab: add the "Für Monat" selector + show the effect on the debt ("Rückstand: 400 → 0").

## 9. Tests

- `tests/test_immo_payment_service.py` (new): pay-in-full clears the exception · partial → `offen` =
  Soll−paid · **Mieteingang payment reduces the debt shown by Bu Ay/Mahnung** (the bug that opened this
  sprint) · payment deletion restores the debt · NK is part of Soll · Erstmiete overrides NK+Kalt ·
  arrears cross the year boundary (Dec unpaid still owed on 2 Jan) · no payment + no flag = paid
  (Dauerzahlung) · delete property → tenants disappear from `/mieter`.
- Parity test: `open_debt` == what Bu Ay, Mietkonto, Mahnung and Berichte each report (one number).
- Existing suite (31 files) must stay green.

## 10. Rollout

Backfill dry-run → apply on production data (founder + VANELLE pilot) → deploy → smoke: create tenant,
mark unpaid, pay via Mieteingang, confirm Bu Ay/Mahnung/Berichte all show 0 → sprint report in
`SPRINT.md` (completed · deferred · risks · "is it really done?").

## Risks

- **Numbers will change for existing data** (NK now counted, previous years now counted). That is the
  point, but it must be announced, not silently applied: pilot landlord may see a higher Rückstand.
- `immo_ledger` (Faz 0) stays a **shadow/audit** domain, READ still OFF. Sprint 0 does not migrate to
  it — but the Payment Service becomes the single choke point through which a later ledger cutover can
  happen without touching any UI. (Ledger backfill/apply stays in the backlog.)
- `index.html` is a 737 KB single file — frontend edits are surgical, no refactor.
