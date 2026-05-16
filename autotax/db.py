import logging
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from autotax.models import Base, Invoice, User, CashEntry, UserCompany, LlmUsage, LearningRule, Correction, PromptExample, VendorIdentity, RecurringExpense

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


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def save_invoice(data: dict, user_id: int, filename: str = None, file_data: bytes = None, file_content_type: str = None, file_hash: str = None, possible_duplicate: bool = False) -> int:
    """Persist an invoice. If file_data is provided it is written to disk
    (via autotax.storage) and only the relative path is stored in the DB.
    The file_data column is no longer populated for new rows.
    """
    from autotax import storage

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
        # Status: total_amount varsa 'ready' (kullanici onaylayabilir),
        # yoksa 'needs_review' (zayif parse). 'confirmed' yalnizca kullanici PATCH'i ile gelir.
        _has_total = bool(data.get("total_amount"))
        _initial_status = "ready" if _has_total else "needs_review"
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
