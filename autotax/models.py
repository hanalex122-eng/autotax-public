from datetime import datetime, timezone
from sqlalchemy import UniqueConstraint
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
    has_cloud_addon = Column(Boolean, default=False, nullable=False)  # AutoTax-Cloud upsell unlock
    # Trial sistemi — yeni kayitlar otomatik 15 gun Pro deneme
    # NULL  = trial baslamadi VEYA manuel odeme aldik (kalici Pro)
    # deger = trial bitis tarihi (cron expire eder)
    trial_ends_at = Column(DateTime, nullable=True)
    # Steuer reminder'larini hangi vergiler icin alacagi (JSON list)
    # NULL = hepsi default. Kullanici muteyi ayarlayabilir.
    # ornek: '["ust","est"]' (sadece USt + ESt, GewSt'siz)
    steuer_subscriptions = Column(String, nullable=True)
    # "Alle Geraete abmelden" / Logout all sessions.
    # Bu zaman damgasindan ESKI iat'li tum JWT'ler 401 dondurur.
    # Sifre degisikligi / panik logout / cihaz kaybedilirse kullanilir.
    jwt_invalidate_before = Column(DateTime, nullable=True)


class AuditLog(Base):
    """Audit trail — wer hat wann was getan?

    DSGVO Art. 30 (Verzeichnis von Verarbeitungstätigkeiten) +
    Steuerberater-Anforderung: jede schreibende Aktion mit Zeitstempel
    nachvollziehbar. user_id NULL = anonyme Aktion (z.B. fehlgeschlagener
    Login mit unbekannter E-Mail). payload = JSON-Snapshot der Änderung,
    nie das ganze Objekt — nur die geänderten Felder + alte Werte.
    """
    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    action = Column(String(50), nullable=False, index=True)        # invoice.create, auth.login, ...
    resource_type = Column(String(30), nullable=True)              # invoice, user, cash_entry, ...
    resource_id = Column(Integer, nullable=True)
    payload = Column(Text, nullable=True)                          # JSON string
    ip = Column(String(50), nullable=True)                         # anonymized (last octet masked)
    user_agent = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False, index=True)


class SteuerReminderLog(Base):
    """Steuer deadline reminder dedup tablosu — ayni reminder ikinci kez
    gonderilmesin diye. (user_id, deadline_type, deadline_date, code)
    unique."""
    __tablename__ = "steuer_reminder_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    deadline_type = Column(String(20), nullable=False)  # ust|est|gewst|jahres
    deadline_date = Column(String(10), nullable=False)  # YYYY-MM-DD
    code = Column(String(10), nullable=False)  # 7d|3d|1d|on_day|overdue
    sent_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)


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
    # Pipeline durumu — state machine. processed (eski boolean) geriye uyumluluk
    # icin korunuyor; yeni kod status'u kullanmali.
    # Degerler: pending | ocr_running | parsing | needs_review | ready | confirmed | failed
    status = Column(String(20), default="pending", nullable=False, index=True)
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
    vendor_fax = Column(String, nullable=True)
    vendor_address = Column(String, nullable=True)
    vendor_website = Column(String, nullable=True)
    # Vendor identity fingerprint — kimlik kartı (vendor adi OCR bozulmasindan bagimsiz)
    vendor_ust_id = Column(String(20), nullable=True, index=True)  # DE143571783
    vendor_hrb = Column(String(30), nullable=True)                 # HRB 23012
    vendor_steuernr = Column(String(30), nullable=True)            # 12/345/67890 (Steuernummer != USt-IdNr)
    # Soft delete
    is_deleted = Column(Boolean, default=False, nullable=False)
    deleted_at = Column(DateTime, nullable=True)
    # Duplicate detection
    file_hash = Column(String(32), index=True, nullable=True)
    possible_duplicate = Column(Boolean, default=False, nullable=False)
    # Rechnung Reminder System — odeme takibi
    due_date = Column(String, nullable=True, index=True)  # YYYY-MM-DD format
    payment_status = Column(String(20), default="unpaid", nullable=False, index=True)  # unpaid|paid|overdue
    paid_at = Column(DateTime, nullable=True)
    # JSON array string: hangi reminder'lar gonderildi — '["7d","1d","on_day","overdue"]'
    # Ayni reminder'in tekrar gonderilmesini onler.
    reminder_sent_codes = Column(String, nullable=True)
    # Mahnung — kullanicinin musterilerine kestigi income faturalar icin
    # gecikmis odeme uyarisi seviyesi (0|1|2|3). 0 = henuz Mahnung yok.
    mahnung_level = Column(Integer, default=0, nullable=False)
    # Son Mahnung gonderim tarihi — ardisik gonderimleri 14 gunde bir sinirlamak icin
    last_mahnung_at = Column(DateTime, nullable=True)
    # Recurring invoice (abonelik tarzi tekrar eden fatura)
    # is_recurring=True ise bu kayit bir 'template'. Cron her ay/yil bir kopya
    # olusturur. Kopya kayitlarda recurring_parent_id = template.id.
    is_recurring = Column(Boolean, default=False, nullable=False, index=True)
    recurring_freq = Column(String(20), nullable=True)  # monthly|quarterly|yearly
    recurring_next_at = Column(String(10), nullable=True)  # YYYY-MM-DD next spawn
    recurring_parent_id = Column(Integer, ForeignKey("invoices.id"), nullable=True, index=True)


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


class Correction(Base):
    """Kullanici duzeltmelerinin ham logu. _do_update_invoice her PATCH/PUT'ta
    degisen alanlar icin bir kayit olusturur. LearningRule ozet tutar (anahtar
    kelime + son deger); bu tablo tam diff'i + duzeltme anindaki OCR snapshot'i
    saklar — few-shot RAG ve modeli iyilestirme icin yakit."""
    __tablename__ = "corrections"

    id = Column(Integer, primary_key=True, autoincrement=True)
    invoice_id = Column(Integer, ForeignKey("invoices.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    field_name = Column(String(50), nullable=False, index=True)
    old_value = Column(Text, nullable=True)            # JSON-encoded (string olarak)
    new_value = Column(Text, nullable=True)            # JSON-encoded (string olarak)
    ocr_text_snapshot = Column(Text, nullable=True)    # ilk 4000 karakter
    vendor_at_correction = Column(String(200), nullable=True, index=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)


class VendorIdentity(Base):
    """Vendor kimlik parmak izi — manuel kayittan veya confirmed fislerden ogrenilir.
    OCR'da vendor adi bozulsa bile (LDL/L1DL), USt-IdNr/IBAN gibi sabit kimlik
    verileri ile dogru vendor'i bulmayi saglar. Beleg hinzufugen sekmesinden
    manuel kayit + PATCH'lerden otomatik ogrenme.

    source:
      - 'manual'        : kullanici Beleg hinzufugen formuyla girdi (en yuksek guven)
      - 'auto_learned'  : confirmed PATCH'ten otomatik ogrenildi
    confidence: 0.0-1.0; manuel=1.0, auto=0.7 baslangici.
    """
    __tablename__ = "vendor_identities"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    vendor_name = Column(String(200), nullable=False, index=True)

    # Kimlik anahtarlari — eslestirme onceligi: ust_id > iban > hrb > phone > email > domain
    ust_id = Column(String(20), nullable=True, index=True)   # DE143571783
    iban = Column(String(40), nullable=True, index=True)     # DE89...
    hrb = Column(String(30), nullable=True)                  # HRB 23012
    phone = Column(String(40), nullable=True)
    email = Column(String(120), nullable=True, index=True)
    domain = Column(String(120), nullable=True, index=True)  # lidl.de
    address = Column(String(300), nullable=True)

    # Default'lar — yeni fisler icin auto-fill
    default_vat_rate = Column(String(10), nullable=True)
    default_category = Column(String(50), nullable=True)
    default_payment_method = Column(String(30), nullable=True)

    source = Column(String(20), default="manual", nullable=False)  # manual | auto_learned
    confidence = Column(Float, default=1.0, nullable=False)
    use_count = Column(Integer, default=0, nullable=False)

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    last_used_at = Column(DateTime, nullable=True)


class PromptExample(Base):
    """Few-shot ornekler — LLM extraction prompt'una RAG ile enjekte edilir.
    learn_from_corrections.py job'u confirmed (status='confirmed') fislerden
    vendor basina en guvenilir ornegi seker. Kullanildikca quality_score guncellenir."""
    __tablename__ = "prompt_examples"

    id = Column(Integer, primary_key=True, autoincrement=True)
    vendor_pattern = Column(String(200), nullable=False, index=True)  # "lidl", "rewe", "shell"
    ocr_text = Column(Text, nullable=False)
    expected_json = Column(Text, nullable=False)       # JSON-encoded ParsedReceipt
    quality_score = Column(Float, default=1.0, nullable=False)
    use_count = Column(Integer, default=0, nullable=False)
    last_used_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
