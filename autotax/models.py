from datetime import datetime, timezone
from sqlalchemy import UniqueConstraint, Index
from sqlalchemy import Column, Integer, Float, Text, String, Boolean, DateTime, Date, ForeignKey, LargeBinary
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
    # Email verification (anti-abuse + DSGVO opt-in proof).
    # False = newly registered, hasn't clicked verification link yet.
    # True  = verified (clicked link OR grandfathered existing user).
    # Existing users (registered before 2026-05-27) -> backfilled to True via init_db migration.
    email_verified = Column(Boolean, default=False, nullable=False)
    email_verified_at = Column(DateTime, nullable=True)
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
    # Stripe subscription state. status:
    #   active | trialing | past_due | unpaid | canceled | incomplete | None
    # plan_ends_at = current period end (also used after cancellation for
    # the grace window). stripe_subscription_id = active sub object.
    subscription_status = Column(String(20), nullable=True)
    stripe_subscription_id = Column(String, nullable=True)
    plan_ends_at = Column(DateTime, nullable=True)
    # Per-user Telegram bot binding (Sprint 2B)
    # NULL = bağlı değil (global admin chat fallback). Bot /start <token>
    # ile bind edilir. Kullanıcı dilediği zaman disconnect edebilir.
    telegram_chat_id = Column(String(50), nullable=True)
    telegram_username = Column(String(50), nullable=True)
    # JSON list: ["mahnung","summary","steuer","reminders","advisor"]
    # NULL = hepsi açık (default). Kullanıcı PATCH ile kapatabilir.
    telegram_notify_pref = Column(Text, nullable=True)


class TelegramLinkToken(Base):
    """One-time token Telegram bot binding'i için.

    Flow:
      1. User /telegram/link/start çağırır → token üretilir, deeplink döner
         (https://t.me/<bot>?start=<token>)
      2. User Telegram'da botu açar → bot /start <token> mesajı bizim
         /telegram/webhook'a gelir
      3. Token doğrulanır, User.telegram_chat_id set edilir, used_at yazılır
      4. User'a "✓ Bağlandı" mesajı

    15 dk geçerli, tek kullanımlık (used_at NULL olmayan token reddedilir)."""
    __tablename__ = "telegram_link_tokens"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    token = Column(String(64), unique=True, nullable=False, index=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    expires_at = Column(DateTime, nullable=False)
    used_at = Column(DateTime, nullable=True)


class SentNotificationLog(Base):
    """Tüm dış bildirim gönderimleri (Telegram, email, webhook) için
    audit + dedup tablosu. Eski reminder_sent_codes JSON string'i bunu
    kapsamlı şekilde yerine alır.

    Dedup: aynı (user, kind, ref_type, ref_id) bir gün içinde tekrar
    gönderilmesin diye filter kullanır."""
    __tablename__ = "sent_notifications"
    __table_args__ = (
        Index("ix_sent_user_kind_ref", "user_id", "kind", "ref_type", "ref_id"),
        Index("ix_sent_sent_at", "sent_at"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    channel = Column(String(20), nullable=False)   # telegram | email | webhook
    kind = Column(String(50), nullable=False)      # mahnung_l1 | invoice_overdue_7d | ...
    target = Column(String(200), nullable=True)    # chat_id veya email
    ref_type = Column(String(30), nullable=True)   # invoice | steuer_reminder | ...
    ref_id = Column(Integer, nullable=True)
    status = Column(String(20), nullable=False, default="sent")  # sent | failed
    error = Column(Text, nullable=True)
    sent_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)


class StripeEventLog(Base):
    """Stripe webhook idempotency — aynı event ikinci kez gelirse 'duplicate'
    dönüp atlanır. Stripe at-least-once teslimat verir; bu tablo bizim
    'tam olarak bir kez işleme' garantimiz.
    90 günden eski kayıtlar cron tarafından silinir (event teslimi
    Stripe'da en fazla 3 gün retry yapar)."""
    __tablename__ = "stripe_event_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(String, unique=True, nullable=False, index=True)
    event_type = Column(String, nullable=False)
    processed_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)


class BackgroundJob(Base):
    """Hintergrund-Job-Tracking — fuer Email-Sync, Reminder, Mahnung,
    Recurring, async OCR und alle anderen async Loops. Eine Zeile pro
    Job-Lauf; spaeter koennen wir Admin-Dashboard zeigen ('Letzter
    Email-Sync vor 2 Min, Dauer 4s, OK') und failing Jobs alarmieren.

    status: running | success | failed
    """
    __tablename__ = "background_jobs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_type = Column(String(50), nullable=False, index=True)   # email_sync, reminder, mahnung, ocr_async, ...
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    status = Column(String(20), nullable=False, default="running")
    started_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False, index=True)
    finished_at = Column(DateTime, nullable=True)
    duration_ms = Column(Integer, nullable=True)
    error = Column(Text, nullable=True)
    payload = Column(Text, nullable=True)  # JSON — work item info


class AdvisorInvite(Base):
    """Steuerberater-Einladung — Token-basiert.

    Kunde erstellt einen Invite, der Berater bekommt einen Link per E-Mail.
    Klick → /advisor/invite/accept → wenn Berater eingeloggt ist, wird
    sofort eine AdvisorRelationship erzeugt; wenn nicht, muss er sich erst
    registrieren (selbe E-Mail), dann accept erneut aufrufen.
    """
    __tablename__ = "advisor_invites"

    id = Column(Integer, primary_key=True, autoincrement=True)
    inviter_user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    advisor_email = Column(String, nullable=False, index=True)
    token = Column(String(64), nullable=False, unique=True, index=True)
    scope = Column(String(30), default="read", nullable=False)   # read | read_export
    status = Column(String(20), default="pending", nullable=False, index=True)  # pending|accepted|revoked|expired
    note = Column(String, nullable=True)  # Müşterinin not'u (örn. "Steuerberater Müller")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    expires_at = Column(DateTime, nullable=False)  # 14 gün
    accepted_at = Column(DateTime, nullable=True)
    accepted_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)


class AdvisorRelationship(Base):
    """Aktive Berater-Kunde-Beziehung. Berater darf Kunden-Daten read-only
    sehen + (optional) DATEV-Export ziehen. Beziehung kann von beiden
    Seiten gekündigt werden — soft delete via revoked_at."""
    __tablename__ = "advisor_relationships"
    __table_args__ = (UniqueConstraint("client_user_id", "advisor_user_id", name="uq_client_advisor"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    client_user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    advisor_user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    scope = Column(String(30), default="read", nullable=False)
    note = Column(String, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    revoked_at = Column(DateTime, nullable=True)
    revoked_by = Column(String(20), nullable=True)  # 'client' veya 'advisor'


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


class SteuerReminder(Base):
    """Aktif vergi vadeleri + kullanıcı durumu.

    SteuerReminderLog (dedup) ile birlikte çalışır:
      - SteuerReminder: vadenin tanımı (due_date, label, status, user notes)
      - SteuerReminderLog: hangi bildirim kodu (7d/3d/1d/on_day/overdue)
        kaç kez gönderildi (anti-dup)

    Cron her ayın 1'inde gelecek 12 ay slot'larını UPSERT eder
    (idempotent — UNIQUE constraint sayesinde duplicate yaratmaz).

    User snooze/done/dismiss yapabilir. 'Custom' tipi user'ın elle
    eklediği kendi vergi/ödeme vadeleridir (örn. quartal/yıllık özel
    deadline'lar)."""
    __tablename__ = "steuer_reminders"
    __table_args__ = (
        UniqueConstraint("user_id", "type", "due_date", name="uq_steuer_user_type_due"),
        Index("ix_steuer_user_status_due", "user_id", "status", "due_date"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    # ust | est | gewst | jahres | custom
    type = Column(String(20), nullable=False)
    due_date = Column(Date, nullable=False)          # gerçek vade
    reminder_date = Column(Date, nullable=True)      # bildirim tetik tarihi (due_date - 7d default)
    # active | snoozed | done | dismissed
    status = Column(String(20), default="active", nullable=False, index=True)
    label = Column(String(200), nullable=True)       # "USt-Voranmeldung Q3 2026"
    notes = Column(Text, nullable=True)              # kullanıcı notu
    snoozed_until = Column(Date, nullable=True)
    last_notified_at = Column(DateTime, nullable=True)
    notify_count = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)


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
    # NOT (Sprint 2C migration, 2026-05-14): due_date string format'tan
    # native Date'e geçiliyor. due_date_v2 yeni native kolon — okuma için.
    # due_date hala yazılıyor (dual write window, 2 hafta sonra drop).
    due_date = Column(String, nullable=True, index=True)  # YYYY-MM-DD (legacy)
    due_date_v2 = Column(Date, nullable=True, index=True) # native Date — okuma için
    # Sprint 4: external AI reviewer feedback. Async webhook'tan gelir.
    # ai_status: None (henüz değerlendirilmedi) | ok | warning | error
    # ai_notes: AI'ın insan-okunabilir notu (uyumsuzluk, eksik bilgi, vs.)
    # ai_reviewed_at: en son AI değerlendirmesi zamanı
    ai_status = Column(String(20), nullable=True, index=True)
    ai_notes = Column(Text, nullable=True)
    ai_reviewed_at = Column(DateTime, nullable=True)
    # Steuerlogik Engine v1 — AI'in cikardigi vergi kategorisi + absetzbarkeit.
    # tax_category: Bewirtung / Geschenk / Miete / Homeoffice / KFZ / Reise /
    #               Lohn / Sozialabgaben / AfA / Buero / Versicherung /
    #               Software / Material / Andere
    # absetzbar_pct: 0-100 yuzde (Bewirtung=70, Geschenk>50€=0, normal=100)
    # vorsteuer_abziehbar: bool (USt indirim hakki)
    # tax_warnings / tax_missing_docs: JSON-serialized list (Privatanteil
    # prüfen, Bewirtungsbeleg fehlt, Aktivierung notig, vs.)
    tax_category = Column(String(40), nullable=True, index=True)
    absetzbar_pct = Column(Integer, nullable=True)
    vorsteuer_abziehbar = Column(Boolean, nullable=True)
    tax_warnings = Column(Text, nullable=True)
    tax_missing_docs = Column(Text, nullable=True)
    # Steuerlogik v2 — 4-bolumlu juristisch sicheres yapi
    ki_einschaetzung = Column(Text, nullable=True)  # "Wahrscheinlich privat veranlasst"
    ki_grund = Column(Text, nullable=True)          # "Beleg enthaelt ueberwiegend Lebensmittel"
    ki_empfehlung = Column(Text, nullable=True)     # "Falls betrieblich, Anlass dokumentieren"
    ki_confidence = Column(Float, nullable=True)    # 0.0-1.0
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
    # §14 UStG — eigene (income) Rechnung: Leistungsempfänger-Adresse + Leistungsdatum.
    # Additive, nullable (safe migration). Nur für selbst erstellte Rechnungen relevant.
    recipient_address = Column(String, nullable=True)   # Kunde/Leistungsempfänger Anschrift
    service_date = Column(String, nullable=True)        # Leistungsdatum YYYY-MM-DD (default=Rechnungsdatum)
    service_description = Column(String, nullable=True) # §14 — Leistungsbeschreibung (was wurde geleistet)
    positions = Column(Text, nullable=True)             # §14 — Positionen JSON: [{description, amount}] (mehrzeilig)
    doc_type = Column(String(16), nullable=True, default="rechnung")  # rechnung | angebot (Angebot zählt NICHT als Umsatz)
    valid_until = Column(String, nullable=True)         # Angebot: "Gültig bis" YYYY-MM-DD


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
    # --- Kasa MVP (Sprint 1) — additive, all nullable (safe migration) ---
    category_id = Column(Integer, ForeignKey("cash_categories.id"), nullable=True, index=True)
    net_amount = Column(Float, nullable=True)                # gross - vat (denormalized for report speed)
    source = Column(String(16), nullable=True, default="manual")      # manual | ocr | import
    status = Column(String(16), nullable=True, default="confirmed")   # confirmed | pending_review
    ocr_document_id = Column(Integer, nullable=True)         # logical link to tax_document (no hard FK; additive)
    extraction_meta = Column(Text, nullable=True)            # JSON-as-text: {confidence, model, template_id, raw_fields}
    __table_args__ = (
        Index("ix_cash_user_date", "user_id", "date"),
        Index("ix_cash_user_type_date", "user_id", "entry_type", "date"),
        Index("ix_cash_user_status", "user_id", "status"),
    )


class CashCategory(Base):
    """Kasa MVP — structured income/expense categories (Sprint 1).

    user_id NULL = system/global seed category (visible to everyone).
    Legacy free-form CashEntry.category string is kept for back-compat.
    """
    __tablename__ = "cash_categories"
    __table_args__ = (
        Index("ix_cashcat_user_kind", "user_id", "kind"),
        UniqueConstraint("user_id", "name", name="uq_cashcat_user_name"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)  # NULL = system
    name = Column(String(80), nullable=False)
    kind = Column(String(16), nullable=False)            # income | expense | both
    datev_konto = Column(String(10), nullable=True)      # SKR03/04 (Tax mapping, S3)
    euer_line = Column(String(40), nullable=True)        # forms.json anlage_euer key (S3)
    default_vat_rate = Column(String(4), nullable=True)  # "19" | "7" | "0"
    color = Column(String(16), nullable=True)
    icon = Column(String(40), nullable=True)
    sort_order = Column(Integer, default=0)
    is_system = Column(Boolean, default=False, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class KasseDocument(Base):
    """Kasa MVP (Sprint 2) — original uploaded image/PDF audit trail.

    Stored in R2 (key) for auditability, support, dispute handling and OCR/
    learning. sha256 enables per-user dedup. Linked from CashEntry.ocr_document_id.
    """
    __tablename__ = "kasse_documents"
    __table_args__ = (
        UniqueConstraint("user_id", "sha256", name="uq_kassedoc_user_sha"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    r2_key = Column(String(255), nullable=True)        # object key (or local rel-path fallback)
    content_type = Column(String(40), nullable=True)   # image/jpeg | application/pdf
    sha256 = Column(String(64), nullable=True, index=True)
    doc_kind = Column(String(16), nullable=True)       # expense | pos
    business_type = Column(String(24), nullable=True)  # doener/restaurant/... (pos)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class CashReport(Base):
    """Kasa MVP (Sprint 2) — generated PDF report metadata (PDF bytes in R2)."""
    __tablename__ = "cash_reports"
    __table_args__ = (
        Index("ix_cashreport_user_created", "user_id", "created_at"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    report_type = Column(String(16), nullable=False)   # daily | weekly | monthly
    period_start = Column(Date, nullable=True)
    period_end = Column(Date, nullable=True)
    r2_key = Column(String(255), nullable=True)
    total_income = Column(Float, nullable=True)
    total_expense = Column(Float, nullable=True)
    profit = Column(Float, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


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
    logo = Column(Text, nullable=True)  # data-URL (base64 PNG/JPG) für PDF-Briefkopf (Rechnung+Angebot)


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
    # Auth-Fail-Backoff: aufeinanderfolgende IMAP-Login-Fehler. Bei Erreichen des
    # Limits wird enabled=False gesetzt (Gmail-Sperre + Log-Spam vermeiden). Reset
    # bei erfolgreichem Sync oder beim erneuten Speichern der Zugangsdaten.
    auth_fail_count = Column(Integer, default=0, nullable=False)
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


class AIKnowledgeEntry(Base):
    """AI Tax Knowledge Cache — Claude'a sorulan vergi sorularinin cevaplari.

    Amac: ayni/benzer soru tekrar gelirse cache'ten dondur, Claude'u
    cagirma. Maliyet azalir, yanit anlik olur.

    Match logic: normalized_question uzerinde
      - pg_trgm similarity (PostgreSQL extension)
      - keywords Jaccard intersection
      - Combined score > 0.55 -> hit
    """
    __tablename__ = "ai_knowledge"

    id = Column(Integer, primary_key=True, autoincrement=True)
    # Orijinal kullanici sorusu (UI'da goster)
    original_question = Column(Text, nullable=False)
    # Normalize edilmis hali (lowercase, stopword cikartilmis, sirali)
    normalized_question = Column(String(500), nullable=False, index=True)
    # AI cevabi
    answer = Column(Text, nullable=False)
    # Otomatik kategori (Bewirtung/KFZ/Miete/Software/Versicherung/...)
    category = Column(String(40), nullable=True, index=True)
    # Anahtar kelimeler (JSON string list)
    keywords = Column(Text, nullable=True)
    # Dil — DE/EN/TR (default DE)
    language = Column(String(5), default="de", nullable=False, index=True)
    # Hangi model uretti (claude-opus-4-7, sonnet-4-6, ...)
    source_model = Column(String(40), nullable=True)
    # AI'in kendi degerlendirdigi guven (0.0-1.0)
    confidence = Column(Float, default=0.9, nullable=False)
    # Vector embedding placeholder (vector DB ileride) — JSON list[float]
    embedding = Column(Text, nullable=True)
    # Kac kez kullanildi (cache hit sayisi)
    usage_count = Column(Integer, default=0, nullable=False, index=True)
    last_used_at = Column(DateTime, nullable=True, index=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                         onupdate=lambda: datetime.now(timezone.utc))
    # Versiyonlama
    tax_year = Column(Integer, nullable=True)  # ornek 2026 — bu cevap hangi vergi yili icin gecerli
    is_deprecated = Column(Boolean, default=False, nullable=False, index=True)
    manually_verified = Column(Boolean, default=False, nullable=False)  # admin onayladi
    # Soruyu kim sordu (analytics — opsiyonel, NULL = anonim)
    first_asked_by = Column(Integer, ForeignKey("users.id"), nullable=True)

    __table_args__ = (
        Index("ix_ai_knowledge_active", "is_deprecated", "language"),
    )


class RecurringExpense(Base):
    """Periyodik giderler — kira, sigorta, Rentenversicherung, GEZ vb.
    Kullanici bir kez tanimlar, her ay/yil otomatik Steuer-Ubersicht'e dahil olur.
    Fatura olarak DB'ye yazilmaz — sadece template + yillik toplam icin sayilir.

    period:
      monthly  = ayda 1 kez (amount × 12 = yillik)
      quarterly= 3 ayda 1 (amount × 4)
      yearly   = yilda 1 (amount)
      once     = tek seferlik (sadece o yil sayilir, start_date alinir)

    tax_treatment:
      betriebsausgabe  = Betriebsausgabe (100% abzugsfahig)
      sonderausgabe    = Sonderausgaben (private Versicherung, KV, RV, vs.)
      bewirtung_70     = 70% abzugsfahig (Bewirtung)
      privat_anteil    = kismi (absetzbar_pct ile)
      nicht_absetzbar  = sifir
    """
    __tablename__ = "recurring_expenses"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"),
                     nullable=False, index=True)
    label = Column(String(200), nullable=False)
    category = Column(String(40), nullable=True, index=True)  # Miete/Versicherung/Rentenversicherung/Krankenkasse/GEZ/Telefon/Internet/...
    amount = Column(Float, nullable=False)  # tek period basina (monthly/quarterly/yearly)
    vat_rate = Column(String(10), nullable=True)   # "19%", "7%", "0%"
    period = Column(String(20), default="monthly", nullable=False)  # monthly|quarterly|yearly|once
    tax_treatment = Column(String(30), default="betriebsausgabe", nullable=False)
    absetzbar_pct = Column(Integer, nullable=True)  # opsiyonel manuel override
    vendor = Column(String(200), nullable=True)    # Vermieter, Versicherer, vb.
    notes = Column(Text, nullable=True)
    start_date = Column(Date, nullable=True)  # ilk gecerli ay/yil
    end_date = Column(Date, nullable=True)    # iptal edildi/sona erdi
    active = Column(Boolean, default=True, nullable=False, index=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        Index("ix_recurring_user_active", "user_id", "active"),
    )


class TaxDeclaration(Base):
    """Steuererklärung (annual tax return) per user per year.

    Stores form fields as JSON in `data`. PDF generated on finalize.
    No ELSTER integration yet — user prints PDF and uploads manually.
    See .claude/steuererklaerung_plan.md for scope + field schema.
    """
    __tablename__ = "tax_declarations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    year = Column(Integer, nullable=False)
    status = Column(String(20), default="draft", nullable=False)  # draft | finalized
    data = Column(Text, nullable=True)  # JSON-serialized form fields
    pdf_path = Column(String, nullable=True)
    pdf_generated_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        UniqueConstraint("user_id", "year", name="uq_tax_decl_user_year"),
        Index("ix_tax_decl_user_year", "user_id", "year"),
    )


class CashRegisterImport(Base):
    """One DSFinV-K / Speedy Kasse / generic CSV upload from a customer's
    cash register. Each upload spawns N CashEntry rows.

    Idempotency via sha256 of the raw file: re-uploading same file is a no-op.
    Source field flags parser used (generic | speedy | dsfinvk). See
    autotax/kasse.py for parsing logic + .claude/kasse_plan.md for scope.
    """
    __tablename__ = "cash_register_imports"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    source = Column(String(20), default="generic", nullable=False)
    file_name = Column(String, nullable=True)
    file_sha256 = Column(String(64), nullable=True, index=True)
    period_start = Column(Date, nullable=True)
    period_end = Column(Date, nullable=True)
    total_rows = Column(Integer, default=0)
    total_amount = Column(Float, default=0.0)
    total_vat = Column(Float, default=0.0)
    rows_imported = Column(Integer, default=0)
    rows_skipped = Column(Integer, default=0)
    status = Column(String(20), default="pending", nullable=False)
    error_message = Column(Text, nullable=True)
    raw_csv_excerpt = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        Index("ix_cri_user_created", "user_id", "created_at"),
        UniqueConstraint("user_id", "file_sha256", name="uq_cri_user_sha"),
    )


# ═══════════════════════════════════════════════════════════════════
# Vendor Intelligence System v2 — Evidence-Based Confidence Engine
# Phase 0: additive infrastructure only. NOTHING reads these yet, so
# adding them cannot change any existing behavior (zero-risk migration).
# ═══════════════════════════════════════════════════════════════════

class SignalWeight(Base):
    """Calibratable per-signal evidence weights for the v2 vendor confidence
    engine. Lets the log-odds weights be TUNED in production WITHOUT a code
    deploy (operability). `weight` is in log-odds (nats); the engine combines
    matching signals as L = L0 + Σ(weight − collision_penalty), grouped by
    `family` for the correlation discount. Seeded with calibrated defaults
    (see SIGNAL_WEIGHT_DEFAULTS); admin can override later.
    """
    __tablename__ = "signal_weights"

    id = Column(Integer, primary_key=True, autoincrement=True)
    signal_type = Column(String(40), nullable=False, unique=True, index=True)
    weight = Column(Float, nullable=False, default=0.0)             # log-odds (nats)
    collision_penalty = Column(Float, nullable=False, default=0.0)  # subtracted from weight
    family = Column(String(20), nullable=False, default="other")    # identity|location|device|brand|text|hint
    enabled = Column(Boolean, nullable=False, default=True)
    notes = Column(String(200), nullable=True)
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class VendorResolutionLog(Base):
    """Audit + offline-calibration log for the v2 vendor confidence engine.
    One row per vendor resolution: the evidence that fired, the candidate
    vendors with their log-odds/confidence, and the final decision.

    Read-only audit — it NEVER drives behavior. Written best-effort (must
    not block the upload path). No hard FK on purpose: a deleted invoice must
    not cascade-delete its audit trail, and logging must never fail on FK.
    """
    __tablename__ = "vendor_resolution_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, nullable=True, index=True)
    invoice_id = Column(Integer, nullable=True, index=True)
    evidence = Column(Text, nullable=True)     # JSON: [{signal_type,value,vendor,weight,family,validated}]
    candidates = Column(Text, nullable=True)   # JSON: [{vendor,log_odds,confidence}]
    current_vendor = Column(String(200), nullable=True)     # old-engine vendor (comparison)
    current_confidence = Column(Float, nullable=True)
    final_vendor = Column(String(200), nullable=True)       # v2 vendor
    final_confidence = Column(Float, nullable=True)
    agree = Column(Boolean, nullable=True, index=True)      # normalized(current) == normalized(v2)?
    status = Column(String(20), nullable=True, index=True)  # locked|accepted|provisional|unknown|conflict
    engine_version = Column(String(20), nullable=True)
    source_type = Column(String(16), nullable=True, index=True)  # ocr|manual_entry|import
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)

    __table_args__ = (
        # One shadow log per invoice. invoice_id NULL is allowed (NULLs are
        # distinct in both PostgreSQL and SQLite unique indexes).
        Index("uq_vrl_invoice", "invoice_id", unique=True),
    )


# Calibrated default signal weights (log-odds / nats). Reliability r → weight
# w = ln(r/(1-r)); single signal under a neutral prior recovers ~r. Tuned in
# the Confidence Engine v2 technical design. Seeded idempotently in init_db.
# Order: identity > device/brand > location > text > hint. The scanner-default
# filename is a HARD VETO (handled in engine code, not as a weight).
SIGNAL_WEIGHT_DEFAULTS = [
    # (signal_type, weight, collision_penalty, family, notes)
    ("ust_id",          3.9, 0.0, "identity", "USt-IdNr (validated)"),
    ("iban",            3.2, 0.0, "identity", "IBAN (validated)"),
    ("hrb",             2.2, 0.0, "identity", "Handelsregister HRB"),
    ("tse_serial",      3.0, 0.0, "device",   "TSE KassenSichV serial"),
    ("kasse_prefix",    2.0, 0.0, "device",   "Kassen-ID prefix (e.g. LDL-)"),
    ("barcode_prefix",  2.5, 0.0, "brand",    "Receipt barcode prefix (e.g. 0888)"),
    ("legal_name",      2.2, 0.0, "brand",    "Legal-name fingerprint"),
    ("address",         1.8, 0.2, "location", "Street + PLZ"),
    ("email",           1.4, 0.0, "text",     "Vendor email / domain"),
    ("phone",           0.8, 0.2, "location", "Phone (OCR-fragile)"),
    ("known_name",      0.5, 0.0, "text",     "Known-vendor token in OCR head"),
    ("filename_brand",  0.2, 0.0, "hint",     "Known brand token in filename (capped)"),
    ("filename_scanner",0.0, 0.0, "hint",     "Scanner-default filename — HARD VETO, never vendor"),
]


# ═══════════════════════════════════════════════════════════════════
# Metadata Extraction V1 — structured identifiers pulled from OCR text,
# INDEPENDENT of vendor resolution. Phase 0: additive infrastructure only.
# Nothing here feeds vendor/total/date/import — pure metadata store.
# ═══════════════════════════════════════════════════════════════════

class InvoiceMetadata(Base):
    """One row per invoice holding identifiers extracted from raw_text:
    USt-IdNr, IBAN, TSE serial, Kassen-ID, Belegnummer. Written best-effort by
    a flag-gated, fire-and-forget hook AFTER save_invoice — it never touches the
    parsed result, the vendor_* columns, or the upload flow. Kept in its own
    table so vendor logic stays completely independent of it.
    """
    __tablename__ = "invoice_metadata"

    id = Column(Integer, primary_key=True, autoincrement=True)
    invoice_id = Column(Integer, nullable=True, index=True)
    user_id = Column(Integer, nullable=True, index=True)
    ust_id = Column(String(20), nullable=True, index=True)
    iban = Column(String(40), nullable=True, index=True)
    tse_serial = Column(String(120), nullable=True)
    kasse_id = Column(String(60), nullable=True, index=True)
    beleg_nr = Column(String(40), nullable=True)
    raw_snippets = Column(Text, nullable=True)        # JSON: where each was found
    validation = Column(Text, nullable=True)          # JSON: per-field validity
    extraction_version = Column(String(16), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)

    __table_args__ = (
        # One metadata row per invoice (NULL invoice_id allowed: NULLs distinct).
        Index("uq_invoice_metadata_invoice", "invoice_id", unique=True),
    )


# ============================================================
# IMMOBILIEN PRO MVP — küçük ev sahibi (1-20 daire). Additive + izole:
# create_all bu 5 tabloyu otomatik oluşturur, mevcut tablolara dokunmaz.
# OCR/Vision/Parser/VAT/Kassenbuch/Rechnungen ile ALAKASI YOK.
# ============================================================
class ImmoProperty(Base):
    __tablename__ = "immo_property"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    name = Column(String(200), nullable=False)
    adresse = Column(String(400), nullable=True)
    einheiten = Column(Integer, nullable=False, default=1)   # number of units (for belegt/leer)
    kaufdatum = Column(Date, nullable=True)
    kaufpreis = Column(Float, nullable=True)
    notiz = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    is_deleted = Column(Boolean, default=False, nullable=False)
    deleted_at = Column(DateTime, nullable=True)


class ImmoUnit(Base):
    __tablename__ = "immo_unit"
    id = Column(Integer, primary_key=True, autoincrement=True)
    property_id = Column(Integer, ForeignKey("immo_property.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    name = Column(String(100), nullable=True)        # z.B. "Whg 1", "EG links"
    wohnflaeche = Column(Float, nullable=True)
    soll_miete = Column(Float, nullable=True)         # Ziel-/Marktmiete (für Leerstand-Bewertung)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    is_deleted = Column(Boolean, default=False, nullable=False)
    deleted_at = Column(DateTime, nullable=True)


class ImmoTenancy(Base):
    __tablename__ = "immo_tenancy"
    id = Column(Integer, primary_key=True, autoincrement=True)
    unit_id = Column(Integer, ForeignKey("immo_unit.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    mieter_name = Column(String(200), nullable=False)
    von = Column(Date, nullable=True)                 # Einzug
    bis = Column(Date, nullable=True)                 # Auszug (null = laufend)
    kaltmiete = Column(Float, nullable=True)
    kaution = Column(Float, nullable=True)
    nk_voraus = Column(Float, nullable=True)          # NK-Vorauszahlung pro Monat
    anmeldung_done = Column(Boolean, nullable=True, default=False)  # Anmeldung beim Amt erledigt (UI status)
    wgb_erstellt_am = Column(DateTime, nullable=True)  # Wohnungsgeberbestätigung zuletzt erzeugt (UI status)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    is_deleted = Column(Boolean, default=False, nullable=False)
    deleted_at = Column(DateTime, nullable=True)


# immo_tenant (legacy, flat) — kept for back-compat; PRO engine uses unit+tenancy.
class ImmoTenant(Base):
    __tablename__ = "immo_tenant"
    id = Column(Integer, primary_key=True, autoincrement=True)
    property_id = Column(Integer, ForeignKey("immo_property.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    name = Column(String(200), nullable=False)
    einzug_datum = Column(Date, nullable=True)
    auszug_datum = Column(Date, nullable=True)
    kaltmiete = Column(Float, nullable=True)
    kaution = Column(Float, nullable=True)
    status = Column(String(10), nullable=False, default="active")   # active | inactive
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    is_deleted = Column(Boolean, default=False, nullable=False)
    deleted_at = Column(DateTime, nullable=True)


class ImmoRent(Base):
    __tablename__ = "immo_rent"
    id = Column(Integer, primary_key=True, autoincrement=True)
    property_id = Column(Integer, ForeignKey("immo_property.id"), nullable=False, index=True)
    tenant_id = Column(Integer, ForeignKey("immo_tenant.id"), nullable=True, index=True)
    tenancy_id = Column(Integer, ForeignKey("immo_tenancy.id"), nullable=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    datum = Column(Date, nullable=True)
    betrag = Column(Float, nullable=False, default=0.0)
    notiz = Column(String(300), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    is_deleted = Column(Boolean, default=False, nullable=False)
    deleted_at = Column(DateTime, nullable=True)


class ImmoExpense(Base):
    __tablename__ = "immo_expense"
    id = Column(Integer, primary_key=True, autoincrement=True)
    property_id = Column(Integer, ForeignKey("immo_property.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    datum = Column(Date, nullable=True)
    kategorie = Column(String(20), nullable=False)   # utilities|repairs|insurance|property_tax|interest|management|other
    betrag = Column(Float, nullable=False, default=0.0)
    beschreibung = Column(String(300), nullable=True)
    document_id = Column(Integer, nullable=True)      # optional link to immo_document (no hard FK; additive)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    is_deleted = Column(Boolean, default=False, nullable=False)
    deleted_at = Column(DateTime, nullable=True)


class ImmoDocument(Base):
    __tablename__ = "immo_document"
    id = Column(Integer, primary_key=True, autoincrement=True)
    property_id = Column(Integer, ForeignKey("immo_property.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    typ = Column(String(20), nullable=True)          # contract|utility|insurance|tax|repair|other
    filename = Column(String(300), nullable=True)
    file_path = Column(String(400), nullable=True)
    file_content_type = Column(String(100), nullable=True)
    uploaded_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    is_deleted = Column(Boolean, default=False, nullable=False)
    deleted_at = Column(DateTime, nullable=True)


# ── IMMOBILIEN P2: Mahnung history + Erinnerungen/Events (additive) ──
class ImmoMahnung(Base):
    __tablename__ = "immo_mahnung"
    id = Column(Integer, primary_key=True, autoincrement=True)
    tenancy_id = Column(Integer, ForeignKey("immo_tenancy.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    datum = Column(Date, nullable=True)
    betrag = Column(Float, nullable=True)             # offener Betrag bei Mahnung
    stufe = Column(Integer, nullable=False, default=1)  # 1 Erinnerung · 2 1.Mahnung · 3 2.Mahnung
    notiz = Column(String(300), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    is_deleted = Column(Boolean, default=False, nullable=False)
    deleted_at = Column(DateTime, nullable=True)


class ImmoEvent(Base):
    __tablename__ = "immo_event"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    property_id = Column(Integer, ForeignKey("immo_property.id"), nullable=True, index=True)
    datum = Column(Date, nullable=True)
    typ = Column(String(20), nullable=True)          # wartung|versicherung|grundsteuer|mieterhoehung|sonstige
    titel = Column(String(200), nullable=False)
    done = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    is_deleted = Column(Boolean, default=False, nullable=False)
    deleted_at = Column(DateTime, nullable=True)


# ── IMMOBILIEN LEDGER (Ledger-First Migration, Faz 0) ─────────────────
class ImmoLedgerEntry(Base):
    """Mietkonto-Buchung — unified, event-based ledger.

    Single source of truth for all Konto movements. The amount is SIGNED and the
    sign is ENFORCED by the posting service (autotax.immo_ledger.post_entry) so a
    wrong-signed row can never be persisted:
        sollbuchung / mahngebuehr  ->  betrag > 0   (Forderung)
        zahlung / teilzahlung      ->  betrag < 0   (Tilgung)
        korrektur                  ->  betrag != 0  (any sign)
    Konto-Saldo = SUM(betrag). Positive saldo = open arrears (Rückstand).

    ADDITIVE & ISOLATED: does NOT touch immo_rent (kept as source/backup during
    dual-write), OCR, VAT, Kassenbuch or Rechnungen. konto_art prepares the same
    base for future Leerstand-/Nebenkosten-/Anlage-V-Konten.
    """
    __tablename__ = "immo_ledger_entry"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    konto_art = Column(String(20), nullable=False, default="miete")   # miete|leerstand|nebenkosten|anlage_v
    property_id = Column(Integer, ForeignKey("immo_property.id"), nullable=True, index=True)
    unit_id = Column(Integer, ForeignKey("immo_unit.id"), nullable=True, index=True)
    tenancy_id = Column(Integer, ForeignKey("immo_tenancy.id"), nullable=True, index=True)
    typ = Column(String(20), nullable=False)          # sollbuchung|zahlung|teilzahlung|korrektur|mahngebuehr
    betrag = Column(Float, nullable=False, default=0.0)  # SIGNED (see class docstring)
    jahr = Column(Integer, nullable=False, index=True)
    monat = Column(Integer, nullable=True)            # 1-12 (sollbuchung: required; payments: mahsup ayı)
    buchungsdatum = Column(Date, nullable=True)       # event date (payment date / Sollstellung date)
    faellig_am = Column(Date, nullable=True)          # sollbuchung Fälligkeit (aging basis)
    beleg = Column(String(300), nullable=True)        # free description / reference
    source = Column(String(20), nullable=True)        # auto|import_rent|manual|mahnung
    source_rent_id = Column(Integer, nullable=True, index=True)   # backfill idempotency: which immo_rent
    mahnung_id = Column(Integer, nullable=True, index=True)       # mahngebuehr <-> immo_mahnung link
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    is_deleted = Column(Boolean, default=False, nullable=False)
    deleted_at = Column(DateTime, nullable=True)
