# VALIDATION & DATA INTEGRITY AUDIT — AutoTax-Cloud

> 2026-06-12 · REPAIR MODE · production veri bütünlüğü görevi (feature DEĞİL).
> Kural: **Kanıt olmadan "düzeltildi" denmez.** Test sonuçları gerçek çalıştırıldı.
> Risk: **P0 Kritik · P1 Yüksek · P2 Orta · P3 Düşük**

---

## 1. FULL INPUT VALIDATION AUDIT (alan × katman)

Editör yazılabilir alanları PATCH/PUT `/invoices/{id}` → `InvoiceUpdate` (main.py:8941) ile kaydedilir.
**Kanıt:** `InvoiceUpdate` alanları sadece `vendor, category, total_amount, vat_amount, vat_rate, date, invoice_type, invoice_number, payment_method, processed`. IBAN/E-Mail/Tax/Website/Telefon/Adresse bu modelde YOK → editörde gösterilir ama bu PATCH'le **kaydedilmez** (OCR/oluşturmada set edilir).

| Alan | Frontend (editor.html) | Backend | DB (models.py) | Kabul edilen geçersiz veri |
|---|---|---|---|---|
| **Date** | ✅ `type=date` min=2020 + JS max=güncel yıl (186) | ✅ `_sane_invoice_date` PATCH+PUT — **GAP: takvim-geçersiz (30.02) geçiyor** | ❌ `date = Column(String)` (263) — gerçek Date değil, kısıt yok | 2026-02-30 (var olmayan gün) |
| **Amount** | ⚠️ `type=number step=0.01` ama **min yok** (179) | ❌ `total_amount: Optional[float]` doğrulayıcı yok | ❌ `Float`, CHECK yok (260) | negatif (-50), devasa (999999999), API'den NaN/Inf |
| **VAT (rate)** | ✅ `<select>` sabit (182) | ❌ `vat_rate: Optional[str]` doğrulayıcı yok | ❌ `String` (262) | API-direkt "abc%", "999%" |
| **VAT (amount)** | — (otomatik) | ❌ `vat_amount: float` doğrulayıcı yok | ❌ `Float` (261) | negatif/devasa |
| **Vendor** | ❌ düz input (160) | ❌ `vendor: str` doğrulayıcı yok | ❌ `String` (257) | her şey + `<script>` payload (bkz §5) |
| **Invoice No.** | ❌ düz input (187) | ❌ `str` doğrulayıcı yok | ❌ `String` (258) | her şey (RE- benzersizliği ayrı yerde) |
| **IBAN** | ❌ düz input, pattern yok (163) | — InvoiceUpdate'te yok (PATCH'le yazılmaz) | ❌ `String` (281) | format kontrolü hiç yok |
| **Tax-Nr/USt-ID** | ❌ düz input (164) | — InvoiceUpdate'te yok | ❌ `String(20/30)` (288/290) — sadece uzunluk | format kontrolü yok |
| **Email** | ❌ düz input (**`type=email` değil!**) (171) | — InvoiceUpdate'te yok | ❌ `String` (282) | "abc" (geçersiz email) |
| **Website** | ❌ düz input (172) | — InvoiceUpdate'te yok | ❌ `String` | her şey |

**Özet:** Frontend doğrulama çoğu alanda **yok** (sadece select'ler + date + amount-number). Backend doğrulama **sadece date** (yeni). DB **hiçbir** CHECK constraint'i yok; tarih **String**.

---

## 2. DATE FIELD HARDENING — GERÇEK TEST SONUÇLARI

`_sane_invoice_date` mantığı birebir kopyalanıp çalıştırıldı (2026, max=2026):

| INPUT | SONUÇ | Beklenen | ✓/✗ |
|---|---|---|---|
| `abc` | REJECT-400 (Format) | ETMEMELİ | ✅ |
| `123` | REJECT-400 (Format) | ETMEMELİ | ✅ |
| `999999` | REJECT-400 (Format) | ETMEMELİ | ✅ |
| `31.12.275760` | REJECT-400 (Format) | ETMEMELİ | ✅ |
| `99.99.9999` | REJECT-400 (Format) | ETMEMELİ | ✅ |
| `<script>alert(1)</script>` | REJECT-400 (Format) | ETMEMELİ | ✅ |
| `2026-99-99` | REJECT-400 (Jahr/Monat) | ETMEMELİ | ✅ |
| `0000-00-00` | REJECT-400 (Jahr 2020..2026) | ETMEMELİ | ✅ |
| `275760-12-31` | REJECT-400 (Format) | ETMEMELİ | ✅ |
| `2026-12-31` | **ACCEPT** | KABUL | ✅ |
| **`2026-02-30`** | **ACCEPT** ❌ | ETMEMELİ (30 Şubat yok) | ❌ **GAP** |
| `2019-05-01` | REJECT (min 2020) | (tasarım: 2020+) | ⚠️ eski fiş riski |

**Sonuç:** İstenen 8 senaryonun **8'i de reddediliyor** ✅. AMA audit **2 gap** buldu:
- **GAP-1 (P1):** Takvim-geçersiz gün kabul ediliyor (`2026-02-30`, `2026-04-31`). Sebep: gün 1–31 kontrolü ay'a bakmıyor.
- **GAP-2 (P2):** min=2020 → meşru 2019 ve öncesi fiş düzenlenince reddedilir (geç girilen eski belge riski).

---

## 3. BACKEND PROTECTION
- **PATCH** `/invoices/{id}` (main.py:9093) + **PUT** (9233) → `_sane_invoice_date` ile tarih **API-direkt çağrıda da** reddediliyor (frontend bypass edilemez). ✅
- Diğer alanlar (amount/vat/vendor/...) için **pydantic doğrulayıcı YOK** → API'den negatif tutar, "999%" KDV, `<script>` vendor kabul edilir. ❌
- **Fix planı:** `InvoiceUpdate`'e `field_validator`'lar: amount/vat_amount ≥ 0 ve < 10.000.000; vat_rate whitelist; vendor/invoice_number uzunluk + kontrol-karakter temizliği.

## 4. DATABASE PROTECTION
- `Invoice.date = Column(String, nullable=True)` (models.py:263) — **gerçek DATE tipi değil**, geçersiz string saklayabilir. (Karşılaştırma: `due_date`/`reminder_date` bazı modellerde `Column(Date)` — tutarsız.)
- **Hiçbir `CheckConstraint` yok** (grep=0). Amount `Float` — işaret/aralık kısıtı yok.
- **Öneri:** (a) Kısa vade: app-katmanı doğrulama (yeterli ve düşük risk). (b) Orta vade: `Invoice.date`'i `Date` tipine migration — mevcut "YYYY-MM-DD" string'leri cast gerektirir, **riskli migration** (ayrı sprint, yedekli).

## 5. SECURITY REVIEW — XSS / Injection (editor.html)
| # | Yer | Durum | Risk |
|---|---|---|---|
| **XSS-1** | `srcRef.innerHTML = ... + fn + ...` (339) | **filename escape EDİLMEMİŞ** → stored XSS. Advisor modunda müvekkilin dosya adı advisor tarayıcısında çalışır (cross-user) | **P1 / Orta-Yüksek** |
| **XSS-2** | `row.innerHTML` line-item (760) | `date` değeri attribute'da escape edilmemiş (`desc` `&quot;` ile edilmiş) → attribute-breakout | **P2 / Orta** |
| OCR | `el.innerHTML = html` (715) | `_fullOcrText` önce `&<>` escape ediliyor | ✅ **Güvenli** |
| Diğer | navCounter/badge/ocrLines vs. | `.textContent` kullanıyor | ✅ Güvenli |
| Backend | vendor/`<script>` kaydı | DB'ye string olarak girer; React (index.html) render'da **otomatik escape** eder; tehlike sadece editör innerHTML sink'lerinde | — |

---

## 6. ÇÖZÜM PLANI (onaydan sonra kod)

| # | İş | Dosya | Risk | Öncelik |
|---|---|---|---|---|
| F1 | `_sane_invoice_date`: `datetime(y,mo,d)` ile gerçek takvim kontrolü → 30.02 reddet (GAP-1) | main.py | düşük | **P1** |
| F2 | XSS-1: `fn`'i escape et (escapeHtml helper veya textContent) | editor.html | düşük | **P1** |
| F3 | `InvoiceUpdate` validator'ları: amount/vat ≥0 & üst sınır, vat_rate whitelist | main.py | orta (API davranışı) | **P1** |
| F4 | XSS-2: line-item `date` attribute escape | editor.html | düşük | P2 |
| F5 | Email/IBAN/Website yazılabilir olursa format doğrulama (şu an PATCH'le yazılmıyor) | main.py | düşük | P2 |
| F6 | GAP-2: min yıl 2020→2015 (eski fiş) ya da yapılandırılabilir | main.py/editor | düşük | P3 |
| F7 | DB: `Invoice.date`→`Date` migration (yedekli, ayrı sprint) | models.py | **yüksek** | P3 |

**Etkilenen dosyalar:** `autotax/main.py` (InvoiceUpdate, _sane_invoice_date), `editor.html` (XSS escape), `autotax/models.py` (DB, uzun vade).

**Bu rapor onaylanınca F1–F3'ten başlanır (P1, güvenlik+integrity).**
