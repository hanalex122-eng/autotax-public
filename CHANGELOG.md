# Changelog

Notable changes to AutoTax-Cloud. Newest first.

## [Unreleased]

### Immobilien — Exception Engine sprint (2026-06)

#### Added (newest first)

- **"Bu Ay" (This Month)** landing view for Immobilien, with **one-click
  Mahnung** for overdue tenants. (`4a15f4e`)
- **Exception Engine** — default-paid (Dauerzahlung) debt model: rent counts as
  paid unless explicitly marked unpaid, so no more false debt/loss. Includes a
  clean split between the audit ledger and the exception domain.
  (`eff3217`, supersedes the earlier AUTO-PAID default `8ba02a9`)
- **Vereinbarte Erstmiete** — negotiated first-month rent override. (`27b1c5d`)
- **Mieter-Info** — tenant phone / e-mail / Kaution, plus dated Mieterhöhung.
  (`756a428`)
- **Edit tenant** (✎ Bearbeiten) on the Mieter card — correct von/bis/rent.
  (`7433c85`)
- **Create / delete tenant** as a one-page Erfassung on the Mieter screen.
  (`e78f2d0`, `125c3f3`)
- **Anteilige Miete** — pro-rata rent for partial move-in / move-out months.
  (`50d41b7`)
- **Tenancy Detail** screen — monthly Mietkonto. (`31e3c2e`)

#### Changed

- **Single source of truth** = Soll − Ist across all surfaces. (`b7554be`)

#### Fixed (newest first)

- `BuAyView` crashed the landing screen — `_L` was out of scope. (`ec1db10`)
- Mieter filters overlap: "Aktiv" no longer hides tenants with debt. (`3e06a0c`)
- Reliable payment/expense entry (controlled inputs) + removed dead buttons.
  (`8fc95dd`)

#### Tests

- Immobilien suite: 24 files green.
- Full suite (31 files: immo + Kasse + OCR + VAT) green.
- `test_immo_untermieter.py` guarded to **SKIP** while the Untermieter
  (subtenant) feature is unimplemented — the spec was written ahead of the model.

---

_Earlier history: see `git log`, `NEXT_STEPS.md`, and `OPEN_ITEMS.md`._
