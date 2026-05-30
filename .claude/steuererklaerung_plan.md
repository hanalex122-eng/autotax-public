# Steuererklärung 2025 — MVP Plan

**Başlangıç:** 2026-05-30 (akşam, 2 saat scaffold)
**Hedef:** User kendi 2025 Steuererklärung'ünü AutoTax üzerinden yapsın
**Scope:** B (MVP) — Form fields collection + PDF, ELSTER YOK (sonra)

---

## Müşteri sinyali

User raporu (2026-05-30): "Bu olmadan müşteri almıyor; çok kişi vergi beyanname formu dolduruyor mu diye sordu (WISO/Lexoffice gibi)."

## Stratejik karar

**Yapmadıklarımız (bilinçli):**
- ❌ Tam ELSTER XBRL/XML integration (80-120 saat — aylar)
- ❌ Anlage KAP / Anlage R / Anlage V (komplike, niş)
- ❌ Çocuk allowances, Behindertenpauschbetrag, vb. özel durumlar

**Yapacaklarımız (MVP):**
- ✅ ESt 1 A (Mantelbogen) — kişisel bilgi + banka + Anlage tikleri
- ✅ Anlage S — Selbständige (gewinn from EÜR)
- ✅ Anlage EÜR — zaten var, link
- ✅ Anlage Vorsorgeaufwand — Krankenkasse + Rentenversicherung (basit)
- ✅ Final PDF — kullanıcı yazdırıp ELSTER'e elle yükler

## Sprint plan

### Bu gece (2 saat scaffold)
- [x] `.claude/steuererklaerung_plan.md` (bu dosya)
- [ ] `autotax/models.py` — `TaxDeclaration` modeli (user_id, year, status, data JSON)
- [ ] `autotax/db.py` — migration (CREATE TABLE IF NOT EXISTS via Base.metadata.create_all)
- [ ] `autotax/declaration.py` — yeni modül, field schema + helpers
- [ ] `autotax/main.py` — `GET/POST/PATCH /steuer/declaration/{year}` endpoints
- [ ] `index.html` — yeni `DeclarationView` skeleton, dashboard nav link "🧾 Steuererklärung 2025"
- [ ] Commit + push

### Yarın Pazar (4-5 saat, eğer çalışırsa)
- [ ] ESt 1 A field schema tam — 12-15 field (kişisel + banka + tikler)
- [ ] Anlage S field schema — 8-10 field
- [ ] Anlage Vorsorge — 5-6 field
- [ ] EÜR otomatik link (mevcut data'dan çek)
- [ ] Form UI tam (5 ana section, mobile-friendly)

### Pazartesi-Salı (8-10 saat)
- [ ] PDF generation (ReportLab) — tax-office layout'a yakın
- [ ] Auto-fill from User + UserCompany + Invoice (EÜR data)
- [ ] Validation rules (zorunlu alanlar, format kontrolleri)
- [ ] Preview modal
- [ ] Status flow: draft → review → finalized (PDF üret)

### Çarşamba (3-4 saat) — kullanıcı test
- [ ] User kendi 2025 beyanını gir
- [ ] PDF'i kontrol et, ELSTER'e elle yükle, çalışıp çalışmadığını gör
- [ ] Bug fix + iyileştirme

### Perşembe-Cuma (4-6 saat) — public launch
- [ ] Pricing: "Steuererklärung 2025 ekstra €29 / einmalig" (free plan dahil değil)
- [ ] Landing'de "🧾 Vergi beyanname formu" feature highlight
- [ ] Help docs (Türkçe + Almanca)

**Toplam:** 1 hafta tam zamanlı.

## Field şeması — özet

### Mantelbogen (ESt 1 A) ~15 field
```
- Steuer-ID (11 hane)
- Steuernummer (10-13 hane, opsiyonel — Steuer-ID yeterli)
- Vorname, Nachname
- Geburtsdatum
- Religion (none/ev/rk/jd/...)
- Adresse (Strasse, PLZ, Ort)
- Familienstand (ledig/verheiratet/...)
- Bankverbindung: IBAN, Kontoinhaber
- Anlage tikleri: ✓ Anlage S, ✓ Anlage EÜR, ✓ Anlage Vorsorgeaufwand
```

### Anlage S ~8 field
```
- Selbständige Tätigkeit Beschreibung (z.B. "IT-Consulting", "Friseur")
- Gewinn aus EÜR (auto-fill from app data)
- Veräußerungsgewinn (default 0)
- Steuerermäßigung §35 EStG (Gewerbesteuer Anrechnung — auto)
- Pauschalbetrag für Selbständige (yok, default 0)
```

### Anlage EÜR — already in app, just link

### Anlage Vorsorgeaufwand ~6 field
```
- Krankenversicherung Basisabsicherung (€)
- Krankenversicherung Zusatz (€)
- Pflegeversicherung (€)
- Rentenversicherung (Rürup / gesetzlich)
- Berufsunfähigkeitsversicherung (€)
```

## Data model

```python
class TaxDeclaration(Base):
    __tablename__ = "tax_declarations"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    year = Column(Integer, nullable=False)  # 2024, 2025, 2026
    status = Column(String(20), default="draft")  # draft | finalized
    data = Column(JSON, default=dict)  # Tüm form fields JSON
    pdf_generated_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        UniqueConstraint("user_id", "year", name="uq_tax_declaration_user_year"),
    )
```

## API endpoints

```
GET    /steuer/declaration/{year}          -> draft veya finalized data
POST   /steuer/declaration/{year}          -> yeni draft oluştur (otomatik user+EÜR data)
PATCH  /steuer/declaration/{year}          -> field güncelle
POST   /steuer/declaration/{year}/finalize -> PDF üret, status=finalized
GET    /steuer/declaration/{year}/pdf      -> PDF download
```

## UI komponentleri (SPA)

- `DeclarationView` — ana sayfa (varsa açar, yoksa "Neu erstellen" buton)
- `DeclarationFormSection` — her bölüm için (Mantelbogen / Anlage S / Vorsorge)
- `DeclarationPreviewModal` — final öncesi tam görünüm
- `DeclarationStatus` — draft / finalized badge

## RED LINE

- ❌ Birden fazla yılı paralel çalıştırma (sadece tek yıl aktif)
- ❌ ELSTER XML/XBRL (out of scope)
- ❌ Otomatik gönderim (sadece PDF)
- ❌ Steuerberater workflow (separate sprint)
- ❌ Refund / Vorauszahlung hesabı (separate)

## Pricing (sonra)

- Free plan: yok (görünür, "Premium feature")
- Starter (€15): yıllık 1 Steuererklärung dahil
- Pro (€39): 1 dahil + tekrar oluşturma free
- AI Steuer (€89): AI yardımı (her field için "ne girmeli" smart hint)

## Memory referans

- Bu plan dosyası repo'da → her session başında okunur (CLAUDE.md zaten gösteriyor)
- `feedback_product_principles.md` — small commits + test + module
- `project_autotax_2026_05_30_close.md` — bu plan'ı tetikleyen müşteri sinyali
