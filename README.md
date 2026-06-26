# AutoTax-Cloud

Turn receipts, invoices, and rent payments into clean, tax-ready bookkeeping —
built for German freelancers, small businesses, and small landlords who don't
have (or don't want) a full accounting setup.

You photograph a receipt, send an invoice, or log a rent payment; AutoTax keeps
the VAT, the cash book, and the tax-relevant records in order for you.

- **Production:** https://autotax.cloud

## What it does

- **Belege** — photograph a receipt; VAT and amounts are read out and booked
  into your EÜR.
- **Rechnungen** — write §14-compliant invoices with automatic numbering and
  one-click reminders (Mahnung).
- **Kassenbuch** — import a handwritten or photographed cash book into a clean,
  ordered ledger.
- **Steuererklärung (Entwurf)** — prepare a tax-return draft from your booked
  data.
- **Immobilien** — manage rentals for a small landlord (1–20 units): tenants,
  Mietkonto, a default-paid (Dauerzahlung) model so you only flag what's
  *unpaid*, and one-click Mahnung.

## For developers

- **Stack:** FastAPI + SQLAlchemy + PostgreSQL + React (CDN, Babel in-browser) +
  Uvicorn. Single monolithic FastAPI app; frontend is one `index.html`.
- **Hosting:** Railway (project `tranquil-forgiveness`, service `AutoTax-Hub`),
  auto-deploy from `origin/main`.
- **Payments:** Stripe (LIVE).
- **Storage:** Railway disk for invoice files; Cloudflare R2 for weekly DB
  backups.
- **Infrastructure detail:** receipt OCR falls back to a hosted model, and the
  tax-question chat is model-backed (Anthropic Claude). These are implementation
  details, not the product.

### Verify production

```bash
curl -s https://autotax.cloud/health | python -m json.tool
```

Expected: `status:"ok"`, `db.connected:true`, `stripe_configured:true`,
`backup_r2.pg_dump_available:true`.

### Tests

```bash
PYTHONIOENCODING=utf-8 PYTHONPATH=. python tests/test_immo_exception_engine.py
# run any tests/test_*.py the same way
```

### Documentation

See `CLAUDE.md` and `.claude/*.md` for architecture, conventions, and the
deployment runbook. `CHANGELOG.md` tracks notable changes; `OPEN_ITEMS.md` and
`NEXT_STEPS.md` hold the backlog.

## Compliance note

This is **bookkeeping and preparation software, not tax advice** (StBerG/RDG).
In-product suggestions use "Vorschlag/Empfehlung" — never prescriptive tax
advice.
