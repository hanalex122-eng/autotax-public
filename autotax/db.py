import logging
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from autotax.models import Base, Invoice, User, CashEntry, UserCompany, LlmUsage, LearningRule, Correction, PromptExample, VendorIdentity, RecurringExpense, AIKnowledgeEntry, SignalWeight, VendorResolutionLog, InvoiceMetadata

logger = logging.getLogger("autotax")

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///autotax.db")

if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine_args = {}
if DATABASE_URL.startswith("sqlite"):
    engine_args["connect_args"] = {"check_same_thread": False}
else:
    engine_args["pool_pre_ping"] = True
    engine_args["pool_size"] = 10
    engine_args["max_overflow"] = 20
    engine_args["pool_recycle"] = 300

engine = create_engine(DATABASE_URL, **engine_args)
SessionLocal = sessionmaker(bind=engine)


def init_db():
    db_type = "PostgreSQL" if DATABASE_URL.startswith("postgresql") else "SQLite"
    logger.info("Database: %s", db_type)
    if db_type == "SQLite":
        logger.warning("Using SQLite fallback — set DATABASE_URL for production")
    Base.metadata.create_all(bind=engine)
    # Add missing columns to existing tables (safe migration)
    from sqlalchemy import text, inspect
    # pg_trgm extension — AI knowledge cache fuzzy matching icin gerekli
    # (PostgreSQL only, SQLite'ta atlanir)
    if db_type == "PostgreSQL":
        try:
            with engine.begin() as conn:
                conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_ai_knowledge_trgm "
                                   "ON ai_knowledge USING gin (normalized_question gin_trgm_ops)"))
            logger.info("pg_trgm extension + GIN index ready (AI knowledge cache)")
        except Exception as e:
            logger.warning("pg_trgm setup skipped: %s", e)
    # Immobilien: immo_rent.tenancy_id (create_all can't ALTER existing table).
    try:
        _ii = inspect(engine)
        if "immo_rent" in _ii.get_table_names():
            _rc = [c["name"] for c in _ii.get_columns("immo_rent")]
            with engine.begin() as conn:
                if "tenancy_id" not in _rc:
                    conn.execute(text("ALTER TABLE immo_rent ADD COLUMN tenancy_id INTEGER"))
                    logger.info("Added 'tenancy_id' column to immo_rent")
                if "source" not in _rc:
                    conn.execute(text("ALTER TABLE immo_rent ADD COLUMN source VARCHAR(20)"))
                    logger.info("Added 'source' column to immo_rent")
    except Exception as e:
        logger.warning("immo_rent tenancy_id migration skipped: %s", e)
    # Immobilien tenant-centric UX: immo_tenancy status columns (additive, nullable).
    try:
        _it = inspect(engine)
        if "immo_tenancy" in _it.get_table_names():
            _tc = [c["name"] for c in _it.get_columns("immo_tenancy")]
            with engine.begin() as conn:
                if "anmeldung_done" not in _tc:
                    conn.execute(text("ALTER TABLE immo_tenancy ADD COLUMN anmeldung_done BOOLEAN DEFAULT FALSE"))
                    logger.info("Added 'anmeldung_done' column to immo_tenancy")
                if "wgb_erstellt_am" not in _tc:
                    conn.execute(text("ALTER TABLE immo_tenancy ADD COLUMN wgb_erstellt_am TIMESTAMP"))
                    logger.info("Added 'wgb_erstellt_am' column to immo_tenancy")
                if "auto_paid" not in _tc:
                    conn.execute(text("ALTER TABLE immo_tenancy ADD COLUMN auto_paid BOOLEAN DEFAULT TRUE"))
                    logger.info("Added 'auto_paid' column to immo_tenancy")
                if "offene_monate" not in _tc:
                    conn.execute(text("ALTER TABLE immo_tenancy ADD COLUMN offene_monate TEXT"))
                    logger.info("Added 'offene_monate' column to immo_tenancy")
    except Exception as e:
        logger.warning("immo_tenancy status-column migration skipped: %s", e)
    # Immobilien Ledger (Ledger-First Migration, Faz 0). The immo_ledger_entry
    # table is created by create_all; only the partial-unique indexes (backfill
    # idempotency) must be ensured explicitly. Best-effort — never block startup.
    try:
        from autotax.immo_ledger import ensure_ledger_indexes
        ensure_ledger_indexes(engine)
        logger.info("Immo ledger partial-unique indexes ready (Faz 0)")
    except Exception as e:
        logger.warning("immo_ledger index migration skipped: %s", e)
    insp = inspect(engine)
    try:
        user_cols = [c["name"] for c in insp.get_columns("users")]
        with engine.begin() as conn:
            if "plan" not in user_cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN plan VARCHAR DEFAULT 'free'"))
                logger.info("Added 'plan' column to users")
            if "stripe_customer_id" not in user_cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN stripe_customer_id VARCHAR"))
                logger.info("Added 'stripe_customer_id' column to users")
            if "registered_at" not in user_cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN registered_at TIMESTAMP"))
                logger.info("Added 'registered_at' column to users")
            if "gdpr_consent_at" not in user_cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN gdpr_consent_at TIMESTAMP"))
                logger.info("Added 'gdpr_consent_at' column to users")
            if "is_kleinunternehmer" not in user_cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN is_kleinunternehmer BOOLEAN DEFAULT FALSE"))
                logger.info("Added 'is_kleinunternehmer' column to users")
            if "has_cloud_addon" not in user_cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN has_cloud_addon BOOLEAN DEFAULT FALSE"))
                logger.info("Added 'has_cloud_addon' column to users")
            if "trial_ends_at" not in user_cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN trial_ends_at TIMESTAMP"))
                logger.info("Added 'trial_ends_at' column to users")
            if "steuer_subscriptions" not in user_cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN steuer_subscriptions VARCHAR"))
                logger.info("Added 'steuer_subscriptions' column to users")
            if "jwt_invalidate_before" not in user_cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN jwt_invalidate_before TIMESTAMP"))
                logger.info("Added 'jwt_invalidate_before' column to users")
            if "subscription_status" not in user_cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN subscription_status VARCHAR(20)"))
                logger.info("Added 'subscription_status' column to users")
            if "stripe_subscription_id" not in user_cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN stripe_subscription_id VARCHAR"))
                logger.info("Added 'stripe_subscription_id' column to users")
            if "plan_ends_at" not in user_cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN plan_ends_at TIMESTAMP"))
                logger.info("Added 'plan_ends_at' column to users")
            if "telegram_chat_id" not in user_cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN telegram_chat_id VARCHAR(50)"))
                logger.info("Added 'telegram_chat_id' column to users")
            if "telegram_username" not in user_cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN telegram_username VARCHAR(50)"))
                logger.info("Added 'telegram_username' column to users")
            if "telegram_notify_pref" not in user_cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN telegram_notify_pref TEXT"))
                logger.info("Added 'telegram_notify_pref' column to users")
            # Email verification (2026-05-27). Existing users grandfathered to True
            # so they don't get locked out. Only new registrations start False.
            if "email_verified" not in user_cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN email_verified BOOLEAN NOT NULL DEFAULT TRUE"))
                logger.info("Added 'email_verified' column to users (existing users grandfathered TRUE)")
                # New rows default to FALSE will be controlled by model default
                # (SQLAlchemy default=False overrides DDL default on inserts).
            if "email_verified_at" not in user_cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN email_verified_at TIMESTAMP"))
                logger.info("Added 'email_verified_at' column to users")
        # Invoice table — file storage columns
        inv_cols = [c["name"] for c in insp.get_columns("invoices")]
        with engine.begin() as conn:
            if "file_data" not in inv_cols:
                conn.execute(text("ALTER TABLE invoices ADD COLUMN file_data BYTEA"))
                logger.info("Added 'file_data' column to invoices")
            if "file_content_type" not in inv_cols:
                conn.execute(text("ALTER TABLE invoices ADD COLUMN file_content_type VARCHAR"))
                logger.info("Added 'file_content_type' column to invoices")
            if "file_path" not in inv_cols:
                conn.execute(text("ALTER TABLE invoices ADD COLUMN file_path VARCHAR"))
                logger.info("Added 'file_path' column to invoices")
            if "file_size" not in inv_cols:
                conn.execute(text("ALTER TABLE invoices ADD COLUMN file_size INTEGER"))
                logger.info("Added 'file_size' column to invoices")
        # --- ADDED START: soft delete columns ---
        inv_cols = [c["name"] for c in insp.get_columns("invoices")]
        with engine.begin() as conn:
            if "is_deleted" not in inv_cols:
                conn.execute(text("ALTER TABLE invoices ADD COLUMN is_deleted BOOLEAN DEFAULT FALSE"))
                logger.info("Added 'is_deleted' column to invoices")
            if "deleted_at" not in inv_cols:
                conn.execute(text("ALTER TABLE invoices ADD COLUMN deleted_at TIMESTAMP"))
                logger.info("Added 'deleted_at' column to invoices")
        ce_cols = [c["name"] for c in insp.get_columns("cash_entries")]
        with engine.begin() as conn:
            if "is_deleted" not in ce_cols:
                conn.execute(text("ALTER TABLE cash_entries ADD COLUMN is_deleted BOOLEAN DEFAULT FALSE"))
                logger.info("Added 'is_deleted' column to cash_entries")
            if "deleted_at" not in ce_cols:
                conn.execute(text("ALTER TABLE cash_entries ADD COLUMN deleted_at TIMESTAMP"))
                logger.info("Added 'deleted_at' column to cash_entries")
        # --- ADDED END ---
        # --- ADDED START: company detail columns ---
        uc_cols = [c["name"] for c in insp.get_columns("user_companies")]
        with engine.begin() as conn:
            for col in ["iban", "tax_id", "address", "phone", "fax", "email", "website"]:
                if col not in uc_cols:
                    conn.execute(text(f"ALTER TABLE user_companies ADD COLUMN {col} VARCHAR"))
                    logger.info("Added '%s' column to user_companies", col)
            if "is_default" not in uc_cols:
                conn.execute(text("ALTER TABLE user_companies ADD COLUMN is_default BOOLEAN DEFAULT FALSE"))
                logger.info("Added 'is_default' column to user_companies")
            if "logo" not in uc_cols:
                conn.execute(text("ALTER TABLE user_companies ADD COLUMN logo TEXT"))
                logger.info("Added 'logo' column to user_companies (PDF-Briefkopf)")
        # --- ADDED END ---
        # --- Vendor contact columns (extracted by parser but previously not persisted) ---
        inv_cols = [c["name"] for c in insp.get_columns("invoices")]
        with engine.begin() as conn:
            for col in ["vendor_iban", "vendor_email", "vendor_phone", "vendor_fax",
                        "vendor_address", "vendor_website", "vendor_steuernr"]:
                if col not in inv_cols:
                    conn.execute(text(f"ALTER TABLE invoices ADD COLUMN {col} VARCHAR"))
                    logger.info("Added '%s' column to invoices", col)
        # --- Rechnung Reminder System columns ---
        inv_cols = [c["name"] for c in insp.get_columns("invoices")]
        with engine.begin() as conn:
            if "due_date" not in inv_cols:
                conn.execute(text("ALTER TABLE invoices ADD COLUMN due_date VARCHAR"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_invoices_due_date ON invoices(due_date)"))
                logger.info("Added 'due_date' column to invoices")
            if "due_date_v2" not in inv_cols:
                conn.execute(text("ALTER TABLE invoices ADD COLUMN due_date_v2 DATE"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_invoices_due_date_v2 ON invoices(due_date_v2)"))
                logger.info("Added 'due_date_v2' column to invoices (Sprint 2C migration)")
            if "ai_status" not in inv_cols:
                conn.execute(text("ALTER TABLE invoices ADD COLUMN ai_status VARCHAR(20)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_invoices_ai_status ON invoices(ai_status)"))
                logger.info("Added 'ai_status' column to invoices (Sprint 4)")
            if "ai_notes" not in inv_cols:
                conn.execute(text("ALTER TABLE invoices ADD COLUMN ai_notes TEXT"))
                logger.info("Added 'ai_notes' column to invoices (Sprint 4)")
            if "ai_reviewed_at" not in inv_cols:
                conn.execute(text("ALTER TABLE invoices ADD COLUMN ai_reviewed_at TIMESTAMP"))
                logger.info("Added 'ai_reviewed_at' column to invoices (Sprint 4)")
            # Steuerlogik Engine v1 (2026-05-16) — AI vergi kategorisi + absetzbarkeit
            if "tax_category" not in inv_cols:
                conn.execute(text("ALTER TABLE invoices ADD COLUMN tax_category VARCHAR(40)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_invoices_tax_category ON invoices(tax_category)"))
                logger.info("Added 'tax_category' column to invoices (Steuerlogik v1)")
            if "absetzbar_pct" not in inv_cols:
                conn.execute(text("ALTER TABLE invoices ADD COLUMN absetzbar_pct INTEGER"))
                logger.info("Added 'absetzbar_pct' column to invoices (Steuerlogik v1)")
            if "vorsteuer_abziehbar" not in inv_cols:
                conn.execute(text("ALTER TABLE invoices ADD COLUMN vorsteuer_abziehbar BOOLEAN"))
                logger.info("Added 'vorsteuer_abziehbar' column to invoices (Steuerlogik v1)")
            if "tax_warnings" not in inv_cols:
                conn.execute(text("ALTER TABLE invoices ADD COLUMN tax_warnings TEXT"))
                logger.info("Added 'tax_warnings' column to invoices (Steuerlogik v1)")
            if "tax_missing_docs" not in inv_cols:
                conn.execute(text("ALTER TABLE invoices ADD COLUMN tax_missing_docs TEXT"))
                logger.info("Added 'tax_missing_docs' column to invoices (Steuerlogik v1)")
            # §14 UStG (2026-06-07) — eigene Rechnung: Empfänger-Adresse + Leistungsdatum
            if "recipient_address" not in inv_cols:
                conn.execute(text("ALTER TABLE invoices ADD COLUMN recipient_address VARCHAR"))
                logger.info("Added 'recipient_address' column to invoices (§14 UStG)")
            if "service_date" not in inv_cols:
                conn.execute(text("ALTER TABLE invoices ADD COLUMN service_date VARCHAR"))
                logger.info("Added 'service_date' column to invoices (§14 UStG)")
            if "service_description" not in inv_cols:
                conn.execute(text("ALTER TABLE invoices ADD COLUMN service_description VARCHAR"))
                logger.info("Added 'service_description' column to invoices (§14 UStG)")
            if "positions" not in inv_cols:
                conn.execute(text("ALTER TABLE invoices ADD COLUMN positions TEXT"))
                logger.info("Added 'positions' column to invoices (§14 Positionen)")
            if "doc_type" not in inv_cols:
                conn.execute(text("ALTER TABLE invoices ADD COLUMN doc_type VARCHAR(16) DEFAULT 'rechnung'"))
                logger.info("Added 'doc_type' column to invoices (rechnung|angebot)")
            if "valid_until" not in inv_cols:
                conn.execute(text("ALTER TABLE invoices ADD COLUMN valid_until VARCHAR"))
                logger.info("Added 'valid_until' column to invoices (Angebot Gültig bis)")
            # Steuerlogik v2 (2026-05-17) — 4-bolumlu juristisch sicher yapi
            if "ki_einschaetzung" not in inv_cols:
                conn.execute(text("ALTER TABLE invoices ADD COLUMN ki_einschaetzung TEXT"))
                logger.info("Added 'ki_einschaetzung' column to invoices (Steuerlogik v2)")
            if "ki_grund" not in inv_cols:
                conn.execute(text("ALTER TABLE invoices ADD COLUMN ki_grund TEXT"))
                logger.info("Added 'ki_grund' column to invoices (Steuerlogik v2)")
            if "ki_empfehlung" not in inv_cols:
                conn.execute(text("ALTER TABLE invoices ADD COLUMN ki_empfehlung TEXT"))
                logger.info("Added 'ki_empfehlung' column to invoices (Steuerlogik v2)")
            if "ki_confidence" not in inv_cols:
                conn.execute(text("ALTER TABLE invoices ADD COLUMN ki_confidence REAL"))
                logger.info("Added 'ki_confidence' column to invoices (Steuerlogik v2)")
            if "payment_status" not in inv_cols:
                conn.execute(text("ALTER TABLE invoices ADD COLUMN payment_status VARCHAR(20) NOT NULL DEFAULT 'unpaid'"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_invoices_payment_status ON invoices(payment_status)"))
                logger.info("Added 'payment_status' column to invoices")
            if "paid_at" not in inv_cols:
                conn.execute(text("ALTER TABLE invoices ADD COLUMN paid_at TIMESTAMP"))
                logger.info("Added 'paid_at' column to invoices")
            if "reminder_sent_codes" not in inv_cols:
                conn.execute(text("ALTER TABLE invoices ADD COLUMN reminder_sent_codes VARCHAR"))
                logger.info("Added 'reminder_sent_codes' column to invoices")
            if "mahnung_level" not in inv_cols:
                conn.execute(text("ALTER TABLE invoices ADD COLUMN mahnung_level INTEGER NOT NULL DEFAULT 0"))
                logger.info("Added 'mahnung_level' column to invoices")
            if "last_mahnung_at" not in inv_cols:
                conn.execute(text("ALTER TABLE invoices ADD COLUMN last_mahnung_at TIMESTAMP"))
                logger.info("Added 'last_mahnung_at' column to invoices")
            if "is_recurring" not in inv_cols:
                conn.execute(text("ALTER TABLE invoices ADD COLUMN is_recurring BOOLEAN NOT NULL DEFAULT FALSE"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_invoices_is_recurring ON invoices(is_recurring)"))
                logger.info("Added 'is_recurring' column to invoices")
            if "recurring_freq" not in inv_cols:
                conn.execute(text("ALTER TABLE invoices ADD COLUMN recurring_freq VARCHAR(20)"))
                logger.info("Added 'recurring_freq' column to invoices")
            if "recurring_next_at" not in inv_cols:
                conn.execute(text("ALTER TABLE invoices ADD COLUMN recurring_next_at VARCHAR(10)"))
                logger.info("Added 'recurring_next_at' column to invoices")
            if "recurring_parent_id" not in inv_cols:
                conn.execute(text("ALTER TABLE invoices ADD COLUMN recurring_parent_id INTEGER"))
                logger.info("Added 'recurring_parent_id' column to invoices")
        # §14 — eindeutige Rechnungsnummer pro Nutzer (nur nicht-leere Nummern).
        # Eigener try/with-Block: bei vorhandenen Duplikaten wird der Index
        # übersprungen (Warnung), Startup darf NICHT blockieren.
        try:
            with engine.begin() as conn:
                conn.execute(text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_invoices_user_number "
                    "ON invoices(user_id, invoice_number) "
                    "WHERE invoice_number IS NOT NULL AND invoice_number <> ''"
                ))
            logger.info("Unique index uq_invoices_user_number ready (§14 eindeutige Rechnungsnummer)")
        except Exception as _uqe:
            logger.warning("uq_invoices_user_number skipped (existing duplicates?): %s", _uqe)
        # EmailConfig — auth-fail backoff counter (auto-disable nach wiederholten IMAP-Logins)
        try:
            ec_cols = [c["name"] for c in insp.get_columns("email_configs")]
            if "auth_fail_count" not in ec_cols:
                with engine.begin() as conn:
                    conn.execute(text("ALTER TABLE email_configs ADD COLUMN auth_fail_count INTEGER NOT NULL DEFAULT 0"))
                logger.info("Added 'auth_fail_count' column to email_configs")
        except Exception as _ece:
            logger.warning("email_configs.auth_fail_count migration skipped: %s", _ece)
        # Verwaiste EmailConfigs (User existiert nicht mehr) entfernen -> stoppt den
        # Auto-Sync-Spam für früher gelöschte Accounts (alter Delete-Code räumte
        # email_configs nicht auf; z.B. user=4 mit AUTHENTICATIONFAILED jede Runde).
        try:
            with engine.begin() as conn:
                conn.execute(text(
                    "DELETE FROM email_configs WHERE user_id NOT IN (SELECT id FROM users)"
                ))
            logger.info("Cleaned orphaned email_configs (users no longer exist)")
        except Exception as _oce:
            logger.warning("orphaned email_configs cleanup skipped: %s", _oce)
        # --- Vendor identity fingerprint (USt-IdNr + HRB) ---
        inv_cols = [c["name"] for c in insp.get_columns("invoices")]
        with engine.begin() as conn:
            if "vendor_ust_id" not in inv_cols:
                conn.execute(text("ALTER TABLE invoices ADD COLUMN vendor_ust_id VARCHAR(20)"))
                logger.info("Added 'vendor_ust_id' column to invoices")
                try:
                    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_invoices_vendor_ust_id ON invoices(vendor_ust_id)"))
                except Exception as ix_e:
                    logger.warning("vendor_ust_id index skipped: %s", ix_e)
            if "vendor_hrb" not in inv_cols:
                conn.execute(text("ALTER TABLE invoices ADD COLUMN vendor_hrb VARCHAR(30)"))
                logger.info("Added 'vendor_hrb' column to invoices")
        # --- Pipeline state machine: invoices.status ---
        # Eski 'processed' boolean korunuyor; yeni kod status'u kullanmali.
        # Ilk migration'da: var olan processed=true satirlar 'confirmed' isaretlenir,
        # processed=false satirlar 'pending' kalir.
        inv_cols = [c["name"] for c in insp.get_columns("invoices")]
        with engine.begin() as conn:
            if "status" not in inv_cols:
                # Postgres ve SQLite'in ikisinde de calisan minimal sentaks
                conn.execute(text(
                    "ALTER TABLE invoices ADD COLUMN status VARCHAR(20) "
                    "NOT NULL DEFAULT 'pending'"
                ))
                logger.info("Added 'status' column to invoices")
                # Eski isenmis kayitlari geriye uyumlu sekilde isaretle
                conn.execute(text(
                    "UPDATE invoices SET status = 'confirmed' "
                    "WHERE processed = TRUE AND status = 'pending'"
                ))
                logger.info("Backfilled status='confirmed' for processed=true rows")
                # Index — status'a gore filtrelemek icin
                try:
                    conn.execute(text(
                        "CREATE INDEX IF NOT EXISTS ix_invoices_status ON invoices(status)"
                    ))
                except Exception as ix_e:
                    logger.warning("Status index skipped: %s", ix_e)

        # --- Sprint 0 PERFORMANCE INDEXES (2026-05-14 roadmap) ---
        # Her index IF NOT EXISTS — idempotent, restart safe.
        # Bu blokta hata olursa logla ve devam et; sema bozulmaz.
        with engine.begin() as conn:
            try:
                conn.execute(text(
                    "CREATE INDEX IF NOT EXISTS ix_cash_entries_user_date "
                    "ON cash_entries(user_id, date DESC)"
                ))
                logger.info("Sprint-0 idx: ix_cash_entries_user_date OK")
            except Exception as e:
                logger.warning("idx cash_entries_user_date skipped: %s", e)
            try:
                conn.execute(text(
                    "CREATE INDEX IF NOT EXISTS ix_invoices_user_active "
                    "ON invoices(user_id, is_deleted, status)"
                ))
                logger.info("Sprint-0 idx: ix_invoices_user_active OK")
            except Exception as e:
                logger.warning("idx invoices_user_active skipped: %s", e)
            try:
                conn.execute(text(
                    "CREATE INDEX IF NOT EXISTS ix_audit_user_created "
                    "ON audit_log(user_id, created_at DESC)"
                ))
                logger.info("Sprint-0 idx: ix_audit_user_created OK")
            except Exception as e:
                logger.warning("idx audit_user_created skipped: %s", e)
            try:
                conn.execute(text(
                    "CREATE INDEX IF NOT EXISTS ix_jobs_type_started "
                    "ON background_jobs(job_type, started_at DESC)"
                ))
                logger.info("Sprint-0 idx: ix_jobs_type_started OK")
            except Exception as e:
                logger.warning("idx jobs_type_started skipped: %s", e)
            try:
                conn.execute(text(
                    "CREATE INDEX IF NOT EXISTS ix_corrections_user_field_date "
                    "ON corrections(user_id, field_name, created_at DESC)"
                ))
                logger.info("Sprint-0 idx: ix_corrections_user_field_date OK")
            except Exception as e:
                logger.warning("idx corrections_user_field_date skipped: %s", e)

        # --- Sprint 2C: due_date_v2 backfill (idempotent, tek seferlik) ---
        # ISO (YYYY-MM-DD) ve DE (DD.MM.YYYY) format'larından mevcut
        # string due_date'leri parse edip Date kolonu doldur.
        # Backfill yalnızca due_date_v2 NULL olan satırlar için çalışır;
        # her startup'ta tekrar çalışsa da idempotent.
        try:
            with engine.begin() as conn:
                # Postgres syntax — TO_DATE + regex
                # ISO
                conn.execute(text("""
                    UPDATE invoices
                       SET due_date_v2 = TO_DATE(due_date, 'YYYY-MM-DD')
                     WHERE due_date_v2 IS NULL
                       AND due_date IS NOT NULL
                       AND due_date ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
                """))
                # DE (DD.MM.YYYY)
                conn.execute(text("""
                    UPDATE invoices
                       SET due_date_v2 = TO_DATE(due_date, 'DD.MM.YYYY')
                     WHERE due_date_v2 IS NULL
                       AND due_date IS NOT NULL
                       AND due_date ~ '^[0-9]{2}\\.[0-9]{2}\\.[0-9]{4}$'
                """))
                # Unparseable'ları audit_log'a düş — sadece bir kez
                # (idempotent for audit_log: aynı row birden çok kez yazılabilir
                # ama low-volume, kabul edilebilir)
                conn.execute(text("""
                    INSERT INTO audit_log (action, resource_type, resource_id, payload, created_at, user_id)
                    SELECT 'invoice.due_date_unparseable', 'invoice', id,
                           json_build_object('raw', due_date)::text,
                           NOW(), user_id
                      FROM invoices
                     WHERE due_date_v2 IS NULL
                       AND due_date IS NOT NULL
                       AND due_date != ''
                """))
            logger.info("Sprint-2C: due_date_v2 backfill complete")
        except Exception as e:
            # SQLite local dev'de TO_DATE / regex desteklemez — sessiz skip
            logger.info("Sprint-2C backfill skipped (%s)", e)
    except Exception as e:
        logger.warning("Column migration skipped: %s", e)

    # --- Kasa MVP cash_entries columns (Sprint 1/2) — BULLETPROOF, standalone ---
    # Alembic 002/003 never run on Railway (Dockerfile CMD; Procfile release
    # ignored). create_all makes new TABLES but cannot ALTER cash_entries, so
    # the new columns are added here. Runs OUTSIDE the big try above (cannot be
    # skipped) and each ALTER is isolated (one failure never blocks the others
    # or rolls back). Without these, EVERY CashEntry query 500s (incl /invoices).
    try:
        _ce = [c["name"] for c in inspect(engine).get_columns("cash_entries")]
        _kasa_cols = [
            ("category_id", "INTEGER"), ("net_amount", "DOUBLE PRECISION"),
            ("source", "VARCHAR(16)"), ("status", "VARCHAR(16)"),
            ("ocr_document_id", "INTEGER"), ("extraction_meta", "TEXT"),
        ]
        for _col, _typ in _kasa_cols:
            if _col not in _ce:
                try:
                    with engine.begin() as conn:
                        conn.execute(text(f"ALTER TABLE cash_entries ADD COLUMN {_col} {_typ}"))
                    logger.info("Kasa: added cash_entries.%s", _col)
                except Exception as _ce_e:
                    logger.warning("Kasa: add cash_entries.%s failed: %s", _col, _ce_e)
        for _ixn, _ixc in [
            ("ix_cash_entries_category_id", "category_id"),
            ("ix_cash_user_date", "user_id, date"),
            ("ix_cash_user_type_date", "user_id, entry_type, date"),
            ("ix_cash_user_status", "user_id, status"),
        ]:
            try:
                with engine.begin() as conn:
                    conn.execute(text(f"CREATE INDEX IF NOT EXISTS {_ixn} ON cash_entries({_ixc})"))
            except Exception:
                pass
        logger.info("Kasa cash_entries column-ensure done")
    except Exception as e:
        logger.warning("Kasa column-ensure skipped: %s", e)

    # --- Vendor v2 shadow log columns (Phase 1, additive) ---
    # The table is created by create_all (Phase 0), but create_all cannot ALTER
    # to add the comparison columns, so they are ensured here. Plus a UNIQUE
    # index on invoice_id => DB-level "one shadow log per invoice" guarantee.
    try:
        from sqlalchemy import text as _text, inspect as _inspect
        _vrl = [c["name"] for c in _inspect(engine).get_columns("vendor_resolution_logs")]
        for _col, _typ in [("current_vendor", "VARCHAR(200)"),
                           ("current_confidence", "DOUBLE PRECISION"),
                           ("agree", "BOOLEAN"),
                           ("source_type", "VARCHAR(16)")]:
            if _col not in _vrl:
                try:
                    with engine.begin() as conn:
                        conn.execute(_text(f"ALTER TABLE vendor_resolution_logs ADD COLUMN {_col} {_typ}"))
                    logger.info("vendor-v2: added vendor_resolution_logs.%s", _col)
                except Exception as _e:
                    logger.warning("vendor-v2: add %s failed: %s", _col, _e)
        try:
            with engine.begin() as conn:
                conn.execute(_text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_vrl_invoice "
                    "ON vendor_resolution_logs(invoice_id)"))
        except Exception as _e:
            logger.warning("vendor-v2: uq_vrl_invoice skipped: %s", _e)
    except Exception as e:
        logger.warning("vendor-v2 column-ensure skipped: %s", e)

    # Vendor Intelligence v2, Phase 0 — seed calibratable signal weights.
    ensure_signal_weights()


def ensure_signal_weights():
    """Idempotently seed SignalWeight defaults (Confidence Engine v2, Phase 0).

    Inserts only signal_types that are MISSING; never overwrites admin-tuned
    rows (so production tuning survives restarts/redeploys). Best-effort — a
    failure here must not block startup, and nothing reads these weights yet,
    so a skip changes no behavior.
    """
    from autotax.models import SIGNAL_WEIGHT_DEFAULTS, SignalWeight
    db = SessionLocal()
    try:
        existing = {r[0] for r in db.query(SignalWeight.signal_type).all()}
        added = 0
        for sig, w, pen, fam, note in SIGNAL_WEIGHT_DEFAULTS:
            if sig in existing:
                continue
            db.add(SignalWeight(
                signal_type=sig, weight=w, collision_penalty=pen,
                family=fam, notes=note, enabled=True,
            ))
            added += 1
        if added:
            db.commit()
            logger.info("SignalWeight: seeded %d default(s)", added)
    except Exception as e:
        db.rollback()
        logger.warning("SignalWeight seed skipped: %s", e)
    finally:
        db.close()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _smart_filename(parsed: dict, original: str | None) -> str | None:
    """AI Filename: 'IMG_001.pdf' -> '2026-05-17_AUCHAN_3.77EUR.pdf'.

    Strategy:
    - If original looks generic (IMG_xxx, scan_xxx, untitled, foto_xxx, vb.)
      AND parsed has good data -> generate smart name.
    - Otherwise keep original (user named it intentionally).
    """
    if not original:
        return original
    import os as _os
    import re as _re
    base, ext = _os.path.splitext(original)
    base_lower = base.lower()
    GENERIC = ("img_", "img-", "image", "scan", "scan_", "scan-",
               "untitled", "neue", "neu_", "photo", "foto_", "foto-",
               "document", "doc_", "screenshot", "page", "kopie")
    is_generic = any(base_lower.startswith(p) for p in GENERIC) or len(base_lower) <= 4
    if not is_generic:
        return original  # user named it on purpose
    # Need vendor + (amount OR date) to build smart name
    vendor = (parsed.get("vendor") or "").strip()
    if not vendor or vendor.lower() in ("unbekannt", "manual entry", ""):
        return original
    # Clean vendor: uppercase, strip special, max 20 chars
    v = _re.sub(r"[^A-Za-z0-9 ]", "", vendor)
    v = _re.sub(r"\s+", "_", v.strip()).upper()[:20]
    if not v:
        return original
    parts = []
    # Date
    date = (parsed.get("date") or "").strip()
    if date and _re.match(r"^\d{4}-\d{2}-\d{2}", date):
        parts.append(date[:10])
    parts.append(v)
    # Amount
    amt = parsed.get("total_amount")
    try:
        amt = float(amt) if amt is not None else None
        if amt and amt > 0:
            parts.append(f"{amt:.2f}EUR")
    except (TypeError, ValueError):
        pass
    if len(parts) < 2:
        return original  # not enough info
    new_name = "_".join(parts) + (ext or ".pdf")
    return new_name


def _strip_null_bytes(v):
    """Postgres TEXT/VARCHAR cannot store NUL (0x00) bytes — they raise
    'A string literal cannot contain NUL (0x00) characters.' on insert.
    OCR output from PDFs with broken encodings sometimes contains them.
    Recursively strip from str values; pass through everything else."""
    if isinstance(v, str):
        return v.replace("\x00", "") if "\x00" in v else v
    return v


def _sanitize_invoice_data(data: dict) -> dict:
    """Return a shallow copy of `data` with all string values stripped of
    NUL bytes. Applied at the DB boundary so the entire upstream pipeline
    (OCR/parser/email-import) can stay simple."""
    if not isinstance(data, dict):
        return data
    return {k: _strip_null_bytes(v) for k, v in data.items()}


def save_invoice(data: dict, user_id: int, filename: str = None, file_data: bytes = None, file_content_type: str = None, file_hash: str = None, possible_duplicate: bool = False) -> int:
    """Persist an invoice. If file_data is provided it is written to disk
    (via autotax.storage) and only the relative path is stored in the DB.
    The file_data column is no longer populated for new rows.
    """
    from autotax import storage

    # Strip Postgres-fatal NUL bytes from all string fields. OCR'd Anthropic
    # receipts and some scanned PDFs slip 0x00 into the extracted text.
    data = _sanitize_invoice_data(data)
    filename = _strip_null_bytes(filename) if filename else filename

    # AI Filename: 'IMG_001.pdf' -> '2026-05-17_AUCHAN_3.77EUR.pdf'
    # Sadece generic filename varsa devreye girer, kullanici adlandirmasi korunur.
    try:
        smart_name = _smart_filename(data, filename)
        if smart_name and smart_name != filename:
            logger.info("AI filename: %r -> %r", filename, smart_name)
            filename = smart_name
    except Exception:
        logger.exception("smart filename failed (continuing with original)")

    file_path = None
    file_size = None
    if file_data:
        try:
            file_path = storage.save_file(user_id, file_data, filename)
            file_size = len(file_data)
        except Exception:
            logger.exception("Failed to write invoice file to disk")
            raise

    db = SessionLocal()
    try:
        # SELF-PROTECTION GUARD: reject an IMPLAUSIBLE total so a bad OCR/QR/parser
        # result can't pollute production (e.g. QR=8.9e19). Single choke-point for
        # ALL upload paths. Rejected -> 0.0 -> status='needs_review' (below) and the
        # dashboard already excludes total<=0, so it never reaches the figures.
        try:
            _t = data.get("total_amount")
            _tv = float(_t) if _t not in (None, "") else 0.0
            if _tv != _tv or _tv in (float("inf"), float("-inf")) or not (0 <= _tv < 1_000_000):
                if _tv != 0:
                    logger.warning("NEEDS_REVIEW reason=implausible_total value=%r vendor=%s", _t, data.get("vendor"))
                data["total_amount"] = 0.0
        except (TypeError, ValueError):
            logger.warning("NEEDS_REVIEW reason=total_parse_error value=%r", data.get("total_amount"))
            data["total_amount"] = 0.0
        # Status: total_amount varsa 'ready' (kullanici onaylayabilir),
        # yoksa 'needs_review' (zayif parse). 'confirmed' yalnizca kullanici PATCH'i ile gelir.
        # Vendor sanity: a nonsense/empty vendor (confidence 0 -> 'Unbekannt', e.g. a
        # logo-OCR garble rejected by the parser) must NOT be silently 'ready' just
        # because a total exists — flag it for review so noise isn't trusted as a
        # valid vendor. (vendor-only gate; total/date logic unchanged.)
        _has_total = bool(data.get("total_amount"))
        _v = (data.get("vendor") or "").strip()
        _vc = data.get("vendor_confidence")
        _vendor_unknown = _v in ("", "Unbekannt", "Processing...") or _vc == 0
        _initial_status = "ready" if (_has_total and not _vendor_unknown) else "needs_review"
        invoice = Invoice(
            user_id=user_id,
            filename=filename,
            vendor=data.get("vendor") or "Unbekannt",
            total_amount=data.get("total_amount") or 0.0,
            vat_amount=data.get("vat_amount") or 0.0,
            vat_rate=data.get("vat_rate") or "0%",
            date=data.get("date") or "",
            raw_text=data.get("raw_text", ""),
            invoice_type=data.get("invoice_type") or "expense",
            invoice_number=data.get("invoice_number") or "",
            payment_method=data.get("payment_method") or "",
            category=data.get("category") or "other",
            processed=_has_total,
            status=_initial_status,
            file_path=file_path,
            file_size=file_size,
            file_content_type=file_content_type,
            # Vendor contact info (previously extracted but discarded)
            vendor_iban=data.get("vendor_iban") or "",
            vendor_email=data.get("vendor_email") or "",
            vendor_phone=data.get("vendor_phone") or "",
            vendor_fax=data.get("vendor_fax") or "",
            vendor_address=data.get("vendor_address") or "",
            vendor_website=data.get("vendor_website") or data.get("vendor_domain") or "",
            due_date=data.get("due_date") or None,
            # Identity fingerprint
            vendor_ust_id=data.get("vendor_ust_id") or None,
            vendor_hrb=data.get("vendor_hrb") or None,
            vendor_steuernr=data.get("vendor_steuernr") or None,
            file_hash=file_hash,
            possible_duplicate=possible_duplicate,
        )
        db.add(invoice)
        db.commit()
        db.refresh(invoice)
        return invoice.id
    except Exception:
        db.rollback()
        # Best-effort cleanup of the file we just wrote
        if file_path:
            from autotax import storage as _s
            _s.delete_file(file_path)
        raise
    finally:
        db.close()
