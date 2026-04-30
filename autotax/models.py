from datetime import datetime, timezone
from sqlalchemy import Column, Integer, Float, Text, String, Boolean, DateTime, ForeignKey, LargeBinary
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String, unique=True, nullable=False, index=True)
    hashed_password = Column(String, nullable=False)
    full_name = Column(String, nullable=True)
    plan = Column(String, default="free")  # free, early, pro
    stripe_customer_id = Column(String, nullable=True)
    registered_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    gdpr_consent_at = Column(DateTime, nullable=True)  # Art. 7(1) DSGVO — proof of consent
    is_kleinunternehmer = Column(Boolean, default=False, nullable=False)


class Invoice(Base):
    __tablename__ = "invoices"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    filename = Column(String, nullable=True)
    vendor = Column(String, nullable=True)
    invoice_number = Column(String, nullable=True)
    invoice_type = Column(String, default="expense")
    total_amount = Column(Float, nullable=True)
    vat_amount = Column(Float, nullable=True)
    vat_rate = Column(String, nullable=True)
    date = Column(String, nullable=True)
    payment_method = Column(String, nullable=True)
    raw_text = Column(Text, nullable=False)
    category = Column(String, nullable=True)
    processed = Column(Boolean, default=False, nullable=False)
    # New (preferred): files live on disk, only the relative path is stored.
    file_path = Column(String, nullable=True)
    file_size = Column(Integer, nullable=True)
    file_content_type = Column(String, nullable=True)
    # Legacy: kept temporarily for backwards compatibility with old rows.
    # Will be dropped after migrate_blobs_to_disk has run in production.
    file_data = Column(LargeBinary, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    # Vendor contact info (extracted from OCR by parser.extract_entities)
    vendor_iban = Column(String, nullable=True)
    vendor_email = Column(String, nullable=True)
    vendor_phone = Column(String, nullable=True)
    vendor_address = Column(String, nullable=True)
    # Soft delete
    is_deleted = Column(Boolean, default=False, nullable=False)
    deleted_at = Column(DateTime, nullable=True)
    # Duplicate detection
    file_hash = Column(String(32), index=True, nullable=True)
    possible_duplicate = Column(Boolean, default=False, nullable=False)


class CashEntry(Base):
    __tablename__ = "cash_entries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    description = Column(String, nullable=False)
    vendor = Column(String, nullable=True)
    gross_amount = Column(Float, nullable=True)
    vat_amount = Column(Float, nullable=True)
    vat_rate = Column(String, nullable=True)
    entry_type = Column(String, nullable=False)
    category = Column(String, nullable=True)
    payment_method = Column(String, nullable=True)
    reference = Column(String, nullable=True)
    notes = Column(Text, nullable=True)
    is_reconciled = Column(Boolean, default=False)
    invoice_id = Column(Integer, nullable=True)
    date = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    # --- ADDED: soft delete ---
    is_deleted = Column(Boolean, default=False, nullable=False)
    deleted_at = Column(DateTime, nullable=True)


class LlmUsage(Base):
    __tablename__ = "llm_usage"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, nullable=False, index=True)
    date = Column(String, nullable=False, index=True)
    count = Column(Integer, default=1)


class UserCompany(Base):
    __tablename__ = "user_companies"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    company_name = Column(String, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    # --- ADDED: company details ---
    iban = Column(String, nullable=True)
    tax_id = Column(String, nullable=True)
    address = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    fax = Column(String, nullable=True)
    email = Column(String, nullable=True)
    website = Column(String, nullable=True)
    is_default = Column(Boolean, default=False, nullable=False)


class EmailConfig(Base):
    """Per-user IMAP inbox credentials for auto-importing invoices from email."""
    __tablename__ = "email_configs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, unique=True, index=True)
    provider = Column(String(20), nullable=False)  # "gmail", "outlook", "imap"
    email = Column(String, nullable=False)
    host = Column(String, nullable=True)   # only for provider="imap"
    port = Column(Integer, nullable=True)  # only for provider="imap"
    encrypted_password = Column(Text, nullable=False)  # Fernet ciphertext
    last_sync = Column(DateTime, nullable=True)
    enabled = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class LearningRule(Base):
    """Per-user field correction memory. When a user edits a vendor name,
    VAT rate, or category on an invoice, a rule is created that auto-fills
    the same correction on future uploads containing the same keyword."""
    __tablename__ = "learning_rules"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    match_text = Column(String(200), nullable=False, index=True)  # "lidl", "bereket"
    field_name = Column(String(50), nullable=False)               # "vendor", "vat_rate", "category"
    value = Column(String(200), nullable=False)                   # "Lidl GmbH", "19%", "food"
    use_count = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
