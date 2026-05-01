import logging
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from autotax.models import Base, Invoice, User, CashEntry, UserCompany, LlmUsage, LearningRule, Correction, PromptExample

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
            for col in ["vendor_iban", "vendor_email", "vendor_phone", "vendor_address"]:
                if col not in inv_cols:
                    conn.execute(text(f"ALTER TABLE invoices ADD COLUMN {col} VARCHAR"))
                    logger.info("Added '%s' column to invoices", col)
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
            vendor_address=data.get("vendor_address") or "",
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
