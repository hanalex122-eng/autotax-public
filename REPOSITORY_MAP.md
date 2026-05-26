# Repository map

Generated 2026-05-26. Keep current after major refactors.

## Top-level

```
.claude/                      Claude Code AI memory & system notes
├── architecture.md
├── auth_flow.md
├── deployment.md
└── env_vars.md
autotax/                      Python backend package
├── __init__.py
├── ai_knowledge.py           AI Steuerberater Q&A cache
├── ai_ocr.py                 Claude Haiku OCR fallback
├── audit.py                  Audit log helpers
├── auth.py                   JWT + bcrypt
├── backup.py                 Weekly PG dump → R2
├── billing.py                Stripe wrapper
├── config.py                 Feature flags (FEATURES dict)
├── corrections.py            User correction pipeline
├── db.py                     SQLAlchemy session
├── duplicate_service.py      Duplicate receipt detection
├── email_sync.py             IMAP polling
├── jobs.py                   Background job table
├── learning.py               Learning rules engine
├── mahnung.py                Dunning letters
├── main.py                   FastAPI app — all 176 endpoints (~12k lines)
├── models.py                 SQLAlchemy ORM models
├── ocr.py                    Local OCR (tesseract + OCR.space)
├── parser.py                 Heuristic invoice parser
├── qr_reader.py              QR/Giro code reader
├── queries.py                Reused SQL helpers
├── receipt_ocr.py            Photo receipt OCR tuning
├── recurring.py              Recurring invoices
├── reminders.py              Daily reminder loop
├── steuer.py                 EÜR + tax math
├── storage.py                File save/load
└── vendor_identity.py        Vendor matching
services/                     Microservices (separate Railway services)
└── ai-reviewer/              External AI quality reviewer
tests/                        Test files
uptime-bot/                   Telegram uptime monitor (separate Railway service)
.github/                      GitHub Actions (planned)

Dockerfile                    Python 3.11-slim + tesseract + pg-client-18
Procfile                      uvicorn entrypoint for Railway
railway.json                  Railway service config
requirements.txt              Python dependencies (25 packages)
index.html                    React SPA via CDN (~5k lines)
email-settings.html           Standalone JWT-protected page
landing.html                  Marketing landing (planned)
*.md                          Documentation (CLAUDE.md, SECURITY_*, LIVE_*, NEXT_STEPS, REPOSITORY_MAP)
```

## File sizes (approximate)

| File | Lines | Size |
|---|---|---|
| `autotax/main.py` | ~12,000 | 500 KB |
| `index.html` | ~5,200 | 220 KB |
| `autotax/models.py` | ~400 | 18 KB |
| `autotax/billing.py` | ~130 | 5 KB |
| `autotax/backup.py` | ~280 | 9 KB |
| Other `autotax/*.py` | ~200-1500 each | varies |

`main.py` is intentionally monolithic to keep deploy + cognitive overhead low. Splitting tracked but not urgent.

## Conventions

- Endpoint definitions: `@app.METHOD("/path")` decorator, function name `verb_noun`.
- Auth: `Depends(get_current_user)` or `Depends(get_acting_context)`.
- Error responses: `err(status_code, message)` helper from `main.py`.
- DB sessions: `db = SessionLocal(); try: ... finally: db.close()`.
- Logging: standard `logging` module + `_SanitizeLogFilter` to mask secrets.
- Naming: `snake_case` for Python, `camelCase` for JS, German + Turkish comments mixed.

## Important entry points

| Route | Purpose |
|---|---|
| `GET /` | Marketing landing |
| `GET /app` | React SPA |
| `GET /health` | Health + config introspection |
| `POST /auth/login` | JWT issuance |
| `POST /auth/register` | New user (default plan from env) |
| `GET /invoices` | List user's invoices |
| `POST /invoices/upload` | Upload + OCR pipeline |
| `POST /billing/checkout-session` | Stripe Checkout URL |
| `POST /billing/webhook` | Stripe webhook receiver |
| `POST /chat` | AI chat (mostly hardcoded responses) |
| `POST /steuer/ask` | AI Steuerberater Q&A (paid feature) |
| `POST /admin/backup/run` | Manual backup trigger |
| `GET /impressum` | Legal — provider info |
| `GET /datenschutz` | Legal — privacy (DE) |
| `GET /privacy` | Legal — privacy (EN) |
| `GET /agb` | Legal — terms |

## Where things are NOT

- No frontend build directory (`dist/`, `build/`) — frontend is the single `index.html` file.
- No migrations directory in use (Alembic exists but inactive).
- No tests with full coverage — `tests/` exists but minimal.
- No CI workflows yet (`.github/workflows/` planned).
