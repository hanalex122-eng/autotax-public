# Kassensystem (DSFinV-K) Import — MVP Plan

**Başlangıç:** 2026-05-30
**Hedef:** Müşteri Kassensystem'inden CSV/ZIP yükler → AutoTax CashEntry'lere dönüşür
**İlk müşteri:** Berber akraba (Türk, Saarbrücken) — Speedy Kasse
**Scope:** MVP — generic CSV + Speedy Kasse + DSFinV-K basit (full GoBD/INSIKA sonra)

---

## Müşteri sinyali

User raporu (2026-05-30): "Çok müşteri sordu, Kassensystem olmadan almıyorlar." Berber akraba Speedy Kasse kullanıyor, ilk pilot.

## DSFinV-K nedir?

**Digitale Schnittstelle der Finanzverwaltung für Kassensysteme** —
Almanya Maliye Bakanlığı'nın Kasse export standartı (2020'den beri zorunlu).
Yıllık denetimde Finanzamt bu formatta veri ister.

### Tipik DSFinV-K dosyaları (ZIP içinde)

| Dosya | İçerik |
|---|---|
| **cashpointclosing.csv** | Z-Bon (gün sonu kapanış) |
| **transactions.csv** | Her satır = bir fiş (Bon) |
| **lines.csv** | Fiş içindeki ürün satırları |
| **payment.csv** | Ödeme metodu (bar/EC/kredi) |
| **vat.csv** | KDV breakdown (7%, 19%) |
| **tse.csv** | TSE (Technische Sicherungseinrichtung) imzaları |
| **subitems.csv** | Alt-pozisyon (varsa) |
| **itemamounts.csv** | Satır tutarları |
| **references.csv** | Diğer referanslar |
| **business_cases.csv** | Geschäftsvorfall (BC) |
| **cash_register.csv** | Kasiyer cihaz metadata |

### MVP'de NE TARARIZ?

Sadece **3 dosya**:
1. **transactions.csv** — her satır = bir CashEntry candidate
2. **vat.csv** — KDV ayrımı için
3. **payment.csv** — ödeme türü için

Diğerleri bilgi için saklanır, parse edilmez.

## Speedy Kasse özelliği

Türkiye-DE pazarı için popüler küçük Kassensystem (berberler, kuaförler, küçük markets). Export formatı:
- ZIP dosyası DSFinV-K standardı
- Veya tek CSV (basit "transactions.csv" gibi)

**Speedy Kasse spesifik kolonlar** (tahmini, doğrulama bekliyor):
```
Z_KASSE_ID, Z_BUCHUNGSTAG, Z_ERSTELLUNG, BON_ID, BON_NR, 
BON_TYP, BON_NAME, TERMINAL_ID, BON_STORNO, BON_START,
BON_ENDE, BON_NOTIZ, TERMINAL_NR, BON_GESAMT_BRUTTO,
KUNDE_ID, BEDIENER_ID, UMS_BRUTTO, UMS_NETTO, UMS_USTNORM,
USTNORM_NETTO, USTNORM_BRUTTO, USTNORM_PROZ
```

## Data model

### `CashRegisterImport`

```python
class CashRegisterImport(Base):
    __tablename__ = "cash_register_imports"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    source = Column(String(20), default="generic")  # generic | speedy | dsfinvk
    file_name = Column(String, nullable=True)
    file_sha256 = Column(String(64), nullable=True, index=True)  # idempotency
    period_start = Column(Date, nullable=True)
    period_end = Column(Date, nullable=True)
    total_rows = Column(Integer, default=0)
    total_amount = Column(Float, default=0.0)
    total_vat = Column(Float, default=0.0)
    rows_imported = Column(Integer, default=0)
    rows_skipped = Column(Integer, default=0)
    status = Column(String(20), default="pending")  # pending | parsed | imported | failed
    error_message = Column(Text, nullable=True)
    raw_csv_excerpt = Column(Text, nullable=True)  # first 500 chars for debug
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
```

### CashEntry — zaten var (`autotax/models.py`)

Mevcut alanlar yeterli: date, vendor, total_amount, vat_amount, category, payment_method, note.

Auto-create sırasında:
- `vendor` = "Kassensystem-{terminal_id}" veya Kassensystem adı
- `category` = "kasse_income" (yeni kategori)
- `note` = "DSFinV-K import: BON_NR {x}"
- `source` field eklenebilir → "kasse_dsfinvk"

## Parser akışı

```
CSV/ZIP upload
    ↓
sha256 idempotency check (varsa skip)
    ↓
Detect format (Speedy/DSFinV-K/generic)
    ↓
Parse transactions.csv -> rows
    ↓
For each row:
  date = parse_date(row.Z_BUCHUNGSTAG)
  brutto = parse_money(row.UMS_BRUTTO)
  netto = parse_money(row.UMS_NETTO)
  vat = brutto - netto
  payment = lookup(row.TERMINAL_NR -> payment.csv)
  ↓
  CashEntry.create(...)
    ↓
Update CashRegisterImport.rows_imported / total_amount / status=imported
```

## API endpoints

```
POST /kasse/import          -> file upload, parse, create entries
GET  /kasse/imports         -> list (recent 50)
GET  /kasse/imports/{id}    -> detail (with entries preview)
DELETE /kasse/imports/{id}  -> rollback (delete imported entries + import record)
```

## UI komponentleri

- `KasseView` — ana sayfa
- Upload drop zone (drag-drop + click)
- Import progress + sonuç (X rows imported, Y skipped, error if any)
- Recent imports list (last 10)
- Per-import detail modal (preview of created CashEntry rows)

## Sprint plan

### Bugün (2-3 saat)
- [x] Plan (.claude/kasse_plan.md)
- [ ] CashRegisterImport model
- [ ] autotax/kasse.py parser
- [ ] 4 endpoint
- [ ] Skeleton KasseView UI
- [ ] Commit + push

### Hafta sonu / Pazartesi
- [ ] Speedy Kasse gerçek dosya testi (berber akrabadan al)
- [ ] Format-detection iyileştirme
- [ ] TSE doğrulama (opsiyonel)
- [ ] DATEV export uyumu (Konto map)

### Önümüzdeki hafta
- [ ] Full DSFinV-K (cashpointclosing.csv, payment.csv, vat.csv tam parse)
- [ ] Z-Bon hesap doğrulama
- [ ] Stripe Reader entegrasyonu (eğer Kasse Stripe kullanıyorsa)
- [ ] Pricing tier — Pro plan'a dahil mi yoksa ayrı addon mı

## RED LINE

- ❌ TSE imza üretmek (sadece TSE imzalı dosyaları kabul edip kabul)
- ❌ Full INSIKA compliance (out of scope MVP)
- ❌ Real-time Kasse sync (sadece batch CSV upload)
- ❌ Cashier hardware kontrolü
- ❌ Mevcut CashEntry'yi silme (sadece yeni ekle, duplicate detection ile)

## Pricing (öneriler)

| Plan | Kasse access |
|---|---|
| Free | ❌ Locked |
| Starter | ❌ Locked (pricing strategy: push to Pro) |
| **Pro** | ✅ Included |
| AI Steuer | ✅ Included |
| Premium | ✅ Included |

Kasse = Pro feature. Steuererklärung = Starter+. Bu **pricing differentiation** yapar — küçük müşteri Starter, kasse'li müşteri Pro/AI Steuer.

## Memory referans

- Bu plan dosyası → her session CLAUDE.md'den okunur
- `project_autotax_dsfinvk.md` — eski erteleme kararı (bugün canlanan)
- `feedback_product_principles.md` — Phase 9 + DSFinV-K binding rules
