# AutoTax-Cloud — Master Roadmap

**Kaynak:** AUTOTAX – UÇTAN UCA OTOMASYON ŞEMASI (2026-05-26)
**Son güncelleme:** 2026-05-26
**Durum:** Soft launch hafta 1 — sonra Steuererklärung modülü (Phase 9) önceliği.

Bu doküman, kullanıcının hazırladığı end-to-end şemayı kaynak alır ve **delivery sırası** belirler. Her phase'in hedefi, süresi, bağımlılığı, çıktı kriteri tanımlıdır.

---

## 📊 Sistem ilerleme yüzdesi (2026-05-26 itibarıyla)

```
Phase 1  Veri Kaynakları (Input)            ████████░░  85%   (Kasa + Bank gelecek)
Phase 2  Veri İşleme Pipeline               █████████░  95%   (OCR + Parsing + AI ✓)
Phase 3  Veritabanı (PostgreSQL)            ██████████ 100%   (Tüm tablolar mevcut)
Phase 4  Çıktı & Entegrasyonlar             ███████░░░  75%   (DATEV ✓, Berater portal gelecek)
Phase 5  Arka Plan Servisleri                █████████░  95%   (Hepsi çalışıyor)
Phase 6  Dış Servisler                       █████████░  90%   (Bank API gelecek)
Phase 7  Cron Jobs                           ████████░░  80%   (Aylık raporlar kısmen)
Phase 8  Güvenlik & Operasyon                ████████░░  85%   (Sentry + Audit log)
Phase 9  VERGİ BEYANI SÜRECİ                 █░░░░░░░░░  10%   ★ Büyük boşluk
Phase 10 Kullanıcı Arayüzü                   ███░░░░░░░  33%   (Mobil + Berater gelecek)

─────────────────────────────────────────────────────────────
TOPLAM SİSTEM:                               ██████░░░░  65%
```

---

## 🎯 Sprint takvimi

| Sprint | Hafta | Hedef | Çıktı kriteri |
|---|---|---|---|
| **S0 — LIVE** | 1 (şimdi) | Soft launch | İlk müşteri kayıt + ilk €1 gerçek ödeme |
| **S1 — Hardening** | 2 | Anti-abuse complete | Email verify + CAPTCHA aktif + Sentry |
| **S2 — Steuererklärung core** | 3-4 | Anlage N + V | Lohnsteuerbescheinigung OCR + AfA hesap |
| **S3 — Steuererklärung full** | 5-6 | Anlage S/G + Vorsorge + KAP | EÜR + tam beyan PDF export |
| **S4 — DSFinV-K Kasse** | 7-8 | Berber pilot live | Türk akraba berber gerçek müşteri |
| **S5 — Berater & B2B** | 9-12 | Berater Portal v1 | Steuerberater hesabı ile mandant erişimi |
| **S6 — Mobile + ELSTER** | 13-20 | Mobile app + ELSTER XML | iOS/Android beta + ELSTER direct submit |

---

# PHASE 1 — VERİ KAYNAKLARI (INPUT)

**Hedef:** Tüm gelir/gider kaynaklarından AutoTax'a veri akışı.

| Kaynak | Durum | Son adım |
|---|---|---|
| Fiziksel Fiş & Fatura (foto/PDF/scan) | ✅ DONE | OCR pipeline tam çalışıyor |
| E-Posta Faturaları (IMAP Sync) | ✅ DONE | Background loop her 10 dk |
| Manuel Yükleme | ✅ DONE | Web upload + form |
| **Kasa Sistemleri (DSFinV-K)** | 🟡 PLANLI | **S4 — Hafta 7-8** |
| Banka Hareketleri (PSD2) | ⚪ FUTURE | S7+ (Q3 2026) |
| Diğer (Makbuz, Sözleşme) | ✅ DONE | Manuel upload yeterli |

### S4: DSFinV-K Kasse Import (1-2 hafta)
- Universal parser (Speedy, Vectron, Orderbird, Lightspeed — 100+ sistem)
- Industry presets: Friseur, Gastro, Retail, Apotheke
- ZIP upload UI + preview + confirm
- **Sales side** (kasa) + **Expense side** (AutoTax mevcut) = tam tablo

---

# PHASE 2 — VERİ İŞLEME PIPELINE

**Hedef:** Her belge için: Alım → OCR → Parse → AI Classify → DB Save.

| Adım | Durum | Notlar |
|---|---|---|
| 2.1 ALIM (Dosya/Email/API/Upload) | ✅ DONE | |
| 2.2 OCR (Tesseract + OCR.space + Claude Haiku) | ✅ DONE | 3 katmanlı fallback |
| 2.3 PARSING (parser.py) | ✅ DONE | Heuristik + öğrenen kurallar |
| 2.4 AI SINIFLANDIRMA (Claude AI Reviewer) | ✅ DONE | External async worker |
| 2.5 KAYDET (DB) | ✅ DONE | |

### Pre-S0 polish (kalan ufak işler)
- ⚪ E-Rechnung (XRechnung/ZUGFeRD) parser — XML invoices (var ama test gerekli)
- ⚪ Handschrift OCR mode improvements
- ⚪ Multi-page PDF chunking (uzun belgeler için)

---

# PHASE 3 — VERİTABANI (POSTGRESQL)

**Hedef:** Tüm tablolar GoBD-uyumlu, user-scoped, soft-delete.

| Tablo | Durum |
|---|---|
| users | ✅ |
| invoices | ✅ |
| cash_entries | ✅ |
| files (Invoice.file_data) | ✅ |
| ai_cache (ai_knowledge_cache) | ✅ |
| settings (per-user) | ✅ |
| logs (audit) | ✅ |
| stripe_event_log | ✅ |
| corrections | ✅ |
| learning_rules | ✅ |

### S1: Schema hardening
- ⏳ Yapısal **audit_log** tablosu (GDPR data-access trail)
- ⏳ `users.email_verified` kolonu (S1)
- ⏳ Alembic migrations devreye sok (yeni kolonlar için)

---

# PHASE 4 — ÇIKTI & ENTEGRASYONLAR

**Hedef:** Müşteri AutoTax'tan başka sistemlere data aktarımı.

| Entegrasyon | Durum | Notlar |
|---|---|---|
| DATEV Export (CSV) | ✅ DONE | /export/datev, /export/excel |
| **Berater Portal** | 🟡 PLANLI | **S5 — Hafta 9-12** |
| E-Posta Bildirimleri (Resend) | ✅ DONE | Reminders, invoices |
| Rechnung Reminder (vadesi geçen) | ✅ DONE | Daily cron |
| Raporlar & Dashboard | ✅ DONE | Frontend + backend |
| API & Webhook (3rd party) | 🟡 PARTIAL | Stripe webhook ✓, public API yok |

### S5: Berater Portal (3-4 hafta)
- Advisor authentication + mandate management
- X-Acting-Client-Id mantığı zaten var (sadece UI yok)
- Mandant'a write yetkisi kontrolü middleware'de mevcut
- Steuerberater dashboard view (1 advisor → N mandant)
- Bulk export + comment + flag mechanism

---

# PHASE 5 — ARKA PLAN SERVİSLERİ

**Hedef:** Otomatik çalışan worker'lar (kullanıcı tetiklemesiz).

| Servis | Durum |
|---|---|
| Email Sync (IMAP) | ✅ DONE |
| AI OCR Fallback (Claude Haiku) | ✅ DONE |
| AI Knowledge (Steuerberater cache, pg_trgm) | ✅ DONE |
| Reminders (Rechnung overdue) | ✅ DONE |
| Steuer Hesaplama (KDV, EÜR, Gewinn) | ✅ DONE |
| **Storage** (Local + R2) | ✅ DONE | R2 backup, file storage gelecek |
| Billing (Stripe) | ✅ DONE | LIVE keys + webhook |

---

# PHASE 6 — DIŞ SERVİSLER

| Servis | Durum | Kullanım |
|---|---|---|
| Anthropic Claude API | ✅ | OCR fallback + Steuerberater chat |
| Stripe | ✅ | LIVE, kill switch ile yönetilebilir |
| Resend | ✅ | Transactional email |
| R2 (Cloudflare) | ✅ | Haftalık backup |
| Telegram | ✅ | Operations notify + uptime |
| **Bank API (PSD2)** | ⚪ FUTURE | S7+ — DKB, Comdirect, Sparkasse FinTS |

---

# PHASE 7 — CRON JOBS

| Sıklık | İş | Durum |
|---|---|---|
| **Günlük** | Email Sync, Reminder Kontrol, Vade Bildirim, Trial Downgrade | ✅ DONE |
| **Haftalık** | Backup pg_dump → R2, AI Cache cleanup, Log cleanup | ✅ DONE (backup), 🟡 cleanup'lar opsiyonel |
| **Aylık** | Rapor Üretimi, KDV Raporu | 🟡 PARTIAL (manual rapor var, auto-send yok) |
| **Yıllık** | Yıllık Kapanış, Arşivleme | ⚪ FUTURE (S3 ile gelir — Steuererklärung modülü) |

---

# PHASE 8 — GÜVENLİK & OPERASYON

| Madde | Durum | Sprint |
|---|---|---|
| Haftalık Backup (pg_dump → R2) | ✅ | DONE |
| JWT / Hash / HTTPS | ✅ | DONE |
| CSP + secure headers (HSTS, COOP) | ✅ | DONE |
| Rate Limit (slowapi + manual) | ✅ | DONE |
| Webhook güvenliği (Stripe + AI HMAC + Telegram secret) | ✅ | DONE |
| Default plan = free (anti-abuse) | ✅ | DONE 2026-05-26 |
| Input length caps | ✅ | DONE 2026-05-26 |
| CSV/XLSX formula injection prevention | ✅ | DONE 2026-05-26 |
| **CAPTCHA (Cloudflare Turnstile)** | 🟡 CODE READY | **S1** — env eklenince aktif |
| **Email Verification** | ⏳ TODO | **S1** — Resend ile (2-3 saat) |
| **Sentry DSN** | ⏳ TODO | **S1** — env ekle (5 dk) |
| **Audit Logs (structured table)** | ⚪ FUTURE | S2 |
| **pip-audit (CI)** | ⏳ TODO | S1 (30 dk) |
| Postgres password rotation | ⏳ TODO | S1 hijyen (2 dk Railway dashboard) |

---

# PHASE 9 — VERGİ BEYANI SÜRECİ (★ Büyük boşluk)

**Hedef:** Müşterinin yıllık Steuererklärung'unu otomatize et — AI auto-fill, Steuerberater'a hazır paket.

**Bu Phase: AI Steuer planının (€89/ay) gerçek değer önermesi.**

### Mevcut durum: %10
- Sadece EÜR raporu var (manuel rapor)
- Anlage form yapısı yok

### S2 — Hafta 3-4: Anlage N + Anlage V (core)
- **Anlage N (Maaş)**
  - Lohnsteuerbescheinigung PDF/foto upload
  - Claude Vision ile yapılandırılmış parse (alanlar: Bruttolohn, Steuer, Soli, SV)
  - Form UI ile preview + manuel düzeltme
  - Çıktı: Anlage N PDF (ELSTER format)
- **Anlage V (Kira)**
  - Daire ekleme (adres, m², yapım yılı)
  - Banka extresinden kira gelirleri match
  - Gider faturaları → Werbungskosten
  - **AfA hesaplayıcı** (binanın amortismanı, 2% genelde)
  - Sonuç: Gewinn/Verlust V+V

### S3 — Hafta 5-6: Anlage S/G + Vorsorge + KAP
- **Anlage S/G (Selbständig/Gewerbe)**
  - AutoTax mevcut verisinden **otomatik dolar** (manuel iş sıfır)
  - Einnahmen toplamı, Ausgaben kategori bazlı
  - Gewinn = Einnahmen − Ausgaben
- **Anlage Vorsorgeaufwand**
  - Sigorta + BAV upload
- **Anlage KAP**
  - Banka faiz raporu upload + parse
- **PDF Export**
  - ELSTER-uyumlu format
  - Tüm Anlage'ler tek paket

### S6 — Hafta 13-16: ELSTER direct integration (opsiyonel)
- ELSTER ERiC SDK entegrasyonu
- BSI certificate gerekir
- XML signed submission
- 2-3 hafta iş + 2-3 hafta sertifikasyon süreci
- **Risk:** zor, opsiyonel — başta sadece PDF export, kullanıcı ELSTER'a manuel yükler

### Çıktı kriteri (S3 sonu)
- Hüseyin kendi 2025 vergisini AutoTax ile yapabilir
- Berbere demo: tam Steuererklärung iş akışı

---

# PHASE 10 — KULLANICI ARAYÜZÜ

| Arayüz | Durum | Sprint |
|---|---|---|
| Web (React CDN + Babel) | ✅ DONE | Production live |
| **Mobile App (iOS/Android)** | ⚪ FUTURE | S6+ (Q3 2026) |
| **Berater Portal** | 🟡 PLANLI | S5 (Hafta 9-12) |

### S6+ Mobile (React Native veya PWA)
- Üzerinde durulacaklar:
  - **PWA** (React Native değil) — şu anki web app zaten responsive; service worker ile offline
  - **React Native** — native UX ama 2-3 ay iş
- **Öneri:** PWA önce, gerçek native sonra (müşteri talebine göre)

---

# 🎯 Sprint S0 — LIVE (BUGÜN/YARIN, 4-6 saat kalan)

Bu sprint **soft launch** için gerekli minimum. Şu an %85 bitik.

### S0 kalan iş listesi (sıralı)

1. **Email verification flow** (2-3 saat)
   - User model: `email_verified: bool` kolon ekle
   - Register sonrası Resend ile mail yolla (token link)
   - `/auth/verify-email?token=` endpoint
   - Frontend "Email doğrula" UI banner

2. **Sentry DSN ekle** (5 dk)
   - Sentry hesap aç (varsa atla)
   - Proje oluştur, DSN al
   - Railway env: `SENTRY_DSN=https://...`
   - /health → `sentry_configured: true` doğrula

3. **CAPTCHA env aktive et** (1 dk)
   - Railway env:
     ```
     TURNSTILE_SITE_KEY=<from Cloudflare>
     TURNSTILE_SECRET_KEY=<from Cloudflare>
     ```
   - Register sayfasında Turnstile widget görünür

4. **Stripe LIVE aç** (1 dk)
   - Railway env: `STRIPE_KILL_SWITCH=0` (zaten 0 muhtemelen)
   - /health → `stripe_configured: true`

5. **€1 gerçek test** (5 dk)
   - Kendi kartınla Starter €15 ödeme
   - Stripe Dashboard → ödeme görünmeli
   - Kontist'e 2 iş günü içinde havale
   - Test sonrası refund

6. **pip-audit GitHub Actions** (30 dk) — opsiyonel ama önerilen
   - `.github/workflows/security.yml`
   - Weekly + on PR

### S0 GO kriteri
✅ Yeni kullanıcı kayıt olabilir (email verify ile)
✅ Stripe Checkout açılır, gerçek ödeme alır
✅ Webhook çalışır, plan aktive olur
✅ Sentry error capture aktif
✅ Backup geçen hafta düzgün çalıştı

---

# 🚦 Karar matrisi (her sprint için)

Yeni feature kabul kriterleri:
- [ ] Backward compatible mi? (existing users etkilenmez)
- [ ] Rollback planı net mi? (env veya code revert)
- [ ] Test edildi mi? (manuel veya otomatik)
- [ ] Documentation güncel mi? (.claude/, NEXT_STEPS, ROADMAP)
- [ ] Memory'ye not düşüldü mü?

---

# 📐 Mimari prensipler (tüm sprint'lerde uy)

1. **Backend monolith** (main.py 12k lines) — split etmeyiz, sadece sınırlı şekilde refactor
2. **Frontend CDN React + Babel** — Vite migration sadece S2+ değerlendirilir
3. **PostgreSQL** — Neon/Supabase migration sadece maliyet > €30/ay olunca
4. **R2 sadece backup** — file storage migration ancak disk %70 dolunca
5. **Solo dev** — 1-2 hafta ötesi planlama gerçekçi değil, esnek kal
6. **StBerG compliance** — AI önerir, KESİN tavsiye etmez (Vorschlag/Empfehlung)
7. **GoBD compliance** — audit_log, immutability, 10-yıl arşiv (S2 hedefli)

---

# 📦 Schema'nın PDF kaynak görseli

User tarafından 2026-05-26'da paylaşıldı: `AUTOTAX – UÇTAN UCA OTOMASYON ŞEMASI`.

Bu doküman her sprint'te güncellenir, schema ile fark varsa schema-ROADMAP eşitleme yapılır.

İmza:
- Hüseyin Hancer (vizyon + ürün)
- Claude Opus 4.7 (engineering plan + delivery)

2026-05-26
