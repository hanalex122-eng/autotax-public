# AutoTax-Cloud — Master Roadmap

**Kaynak:** AUTOTAX – UÇTAN UCA OTOMASYON ŞEMASI (2026-05-26)
**Son güncelleme:** 2026-05-31 (prod v5.5.5)
**Durum:** Soft launch CANLI (Stripe LIVE, ilk €15 gerçek ödeme alındı 2026-05-30). Aktif öncelik: **Phase 9 Steuererklärung Form Engine** — tam spec yazıldı (`.claude/steuererklaerung_form_engine_complete.md`, 8 haftalık plan), MVP %45 hazır.

Bu doküman, kullanıcının hazırladığı end-to-end şemayı kaynak alır ve **delivery sırası** belirler. Her phase'in hedefi, süresi, bağımlılığı, çıktı kriteri tanımlıdır.

---

## 📊 Sistem ilerleme yüzdesi (2026-05-31 itibarıyla)

```
Phase 1  Veri Kaynakları (Input)            █████████░  90%   (Kasse MVP canlı, Bank API gelecek)
Phase 2  Veri İşleme Pipeline               █████████░  95%   (OCR + Parsing + AI ✓)
Phase 3  Veritabanı (PostgreSQL)            ██████████ 100%   (Tüm tablolar mevcut)
Phase 4  Çıktı & Entegrasyonlar             ███████░░░  75%   (DATEV ✓, Berater portal gelecek)
Phase 5  Arka Plan Servisleri                █████████░  95%   (Hepsi çalışıyor)
Phase 6  Dış Servisler                       █████████░  90%   (Bank API gelecek)
Phase 7  Cron Jobs                           ████████░░  80%   (Aylık raporlar kısmen)
Phase 8  Güvenlik & Operasyon                █████████░  92%   (CAPTCHA/Email-verify/Sentry/Stripe LIVE ✓; Audit-log tablosu gelecek)
Phase 9  VERGİ BEYANI SÜRECİ                 ████░░░░░░  45%   ★ MVP canlı (75 field/11 section), Form Engine tam spec yazıldı
Phase 10 Kullanıcı Arayüzü                   ████░░░░░░  40%   (Web ✓ + Steuer/Kasse view; Mobil + Berater gelecek)

─────────────────────────────────────────────────────────────
TOPLAM SİSTEM:                               ███████░░░  72%
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
| **CAPTCHA (Cloudflare Turnstile)** | ✅ DONE | Canlı + test edildi (2026-05-30) |
| **Email Verification** | ✅ DONE | Resend token akışı canlı |
| **Sentry DSN** | ✅ DONE | `/health` → `sentry_configured: true` |
| **Stripe LIVE (kill switch)** | ✅ DONE | İlk €15 gerçek ödeme alındı (2026-05-30) |
| **Audit Logs (structured table)** | ⚪ FUTURE | S2 |
| **pip-audit (CI)** | ⏳ TODO | S1 (30 dk) |
| Postgres password rotation | ⏳ TODO | S1 hijyen (2 dk Railway dashboard) |

---

# PHASE 9 — VERGİ BEYANI SÜRECİ (★ Büyük boşluk)

**Hedef:** Müşterinin yıllık Steuererklärung'unu otomatize et — AI auto-fill, Steuerberater'a hazır paket.

**Bu Phase: AI Steuer planının (€89/ay) gerçek değer önermesi.**

### Mevcut durum: ~%45 (2026-05-30/31 sprint sonrası)
- **MVP canlı:** Steuererklärung 2025, 75 field / 11 section, Zeile numaralı, live tax estimator, LSB OCR (Claude Vision), Behindertenpauschbetrag, Anlage Kind dinamik liste, ELSTER XML skeleton, ESt 1 A formuna yakın PDF (`autotax/declaration.py`)
- **Tam Form Engine spec yazıldı:** `.claude/steuererklaerung_form_engine_complete.md` — 29 form × field-level (Zeile/ELSTER-Kennzahl/validation/Hilfetext), 10-adım engine (Finanzamt lookup, Form detection, Dynamic questionnaire, Validation 60+, Optimization 50+, Document AI, QC, Output, Self-learning), DB şema + API katalog + 8-haftalık plan + Definition of Done. **Phase 9'un otoritatif kaynağı budur.**
- **Eksik kritik 5:** Finanzamt lookup, Form detection engine, Dynamic questionnaire, 12 eksik form (Anlage G/EÜR/AUS/SO/AV/Haushaltsnahe/Energetisch/KAP-BET/KAP-INV/R-AUS/USt/GewSt), Validation/Optimization motoru

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

# 🧭 Çalışma prensipleri (2026-05-27 user direktifi)

Bu prensipler her sprint'te bağlayıcıdır:

1. **Küçük güvenli commit'ler** — Bir commit = bir değişiklik. Rollback kolay.
2. **Her değişiklik sonrası test** — Manual veya CI (test workflow var). En azından `/health` doğrula.
3. **main.py'ı modüllere böl** — ~12k satır, parça parça (file-by-file). Hiçbir commit'te tek seferde 1000+ satır taşıma.
4. **Mobile UX iyileştir** — Responsive iyileştirmeler, PWA service worker (S6+).
5. **Berber/dönerci workflow optimize** — DSFinV-K import + industry preset (S4'te).
6. **AI tax advisor geliştir** — `/steuer/ask` + ai_knowledge cache iyileştirme.
7. **WISO benzeri tax filing system** — Phase 9 (Steuererklärung) ana hedef.
8. **Soft launch'a zarar verecek büyük refactor YAPMA** — KIRMIZI çizgi.

### Karar matrisi her değişiklik öncesi

- **GO:** Backward compat + <30 dk + rollback path net + production-safe.
- **ASK:** >30 dk veya production-breaking riski var.
- **STOP:** Soft launch'ı geciktirir.

### Berber pilot — şimdilik kapalı
Berber sadece Kasse ile ilgileniyor, AutoTax Kasse sistemi yok. DSFinV-K
parser (Phase 1 / S4) bitince yeniden konuşulacak. Şimdilik **Phase 9
Steuererklärung modülü** öncelikli — AI Steuer €89/ay planının gerçek
satış argümanı.

---

# 🎯 Sprint S0 — LIVE ✅ TAMAMLANDI (2026-05-30)

Bu sprint **soft launch** için gerekli minimumdu. **Bitti:** CAPTCHA + email verify + Sentry + Stripe LIVE + ilk €15 gerçek ödeme alındı. Aşağıdaki liste geçmiş referans olarak tutuluyor.

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

# PHASE 11 — ENTERPRISE GROWTH & CERTIFICATION

**Hedef:** Tekil müşteriden enterprise B2B + Steuerberater pazarına çıkış.
**Süre:** S0-S6 bitince başlar (Ay 4+). Mali yatırım gerekir.

Bu phase, Phase 1-10 (ürün) bittikten sonra **ürün operasyonel olgunluk** + **resmi sertifikasyon** yolu.

---

## 11.1 — İlk 10 gerçek müşteri (Ay 1-6)

**Hedef:** Pilot → para ödeyen müşteri → 10 müşteri.

| Adım | Süre |
|---|---|
| Türk akraba berber pilot (DSFinV-K Speedy) | S4 sonu |
| Network referansı 4-5 berber/esnaf | S5-S6 |
| Cold outreach (LinkedIn, Steuerberater partnerlik) | S5+ |
| **10 paying customer milestone** | Ay 4-6 |

Bu süreçte:
- Customer feedback toplama (Notion / Linear board)
- Usage analytics (PostHog veya kendi Sentry ile)
- NPS / CSAT anketleri ay sonu
- **Churn izle** — eğer ay sonu cancel > %15 ise feature/UX'te sorun var

**Gelir hedefi:** 10 × €89 (AI Steuer) = €890/ay → tüm operasyon maliyetini karşılar + €500/ay kâr.

---

## 11.2 — Sistem stabilite (Ay 3-6)

**Hedef:** %99.5 uptime, sıfır data loss, %1 altı error rate.

| Konu | Hedef |
|---|---|
| Uptime | 99.5%+ (1 ay max 3.5 saat down) |
| P95 response time | < 500ms |
| Error rate (Sentry) | < 1% |
| Backup restore drill | 3 ayda 1 manuel test |
| Customer support response | < 24 saat |

Yapılacaklar:
- **Sentry + Better Stack / Uptime Robot** (zaten Telegram bot var, formal SLA)
- **Status page** (status.autotax.cloud — Cloudflare ile bedava)
- **Runbook** her major incident için (.claude/runbooks/)
- **Postmortem template** — büyük incident sonrası

---

## 11.3 — Güvenlik dokümantasyonu (Ay 5-7)

**Hedef:** B2B sales için "Security & Compliance" sayfası + resmi belgeler.

Hazırlanacak dokümanlar:
- ✅ `SECURITY_AUDIT.md` (zaten var, periyodik güncelle)
- ⚪ **GoBD Verfahrensdokumentation** — BMF zorunlu (5-10 sayfa)
- ⚪ **Auftragsverarbeitungsvertrag (AVV)** — DSGVO Art. 28, B2B müşteri zorunlu ister
- ⚪ **TOMs (Technische und Organisatorische Maßnahmen)** — DSGVO ekli, 5-15 sayfa
- ⚪ **Information Security Policy** (genel politika, 5 sayfa)
- ⚪ **Data Processing Inventory** — hangi data hangi processor'da
- ⚪ **Incident Response Plan** — log → triage → notify → fix → postmortem
- ⚪ **Backup & Disaster Recovery Plan** — RPO/RTO tanımları, R2 restore drill
- ⚪ **Vendor Risk Assessment** — Stripe, Cloudflare, Anthropic, Resend için
- ⚪ **Access Control Policy** — ADMIN_EMAILS, JWT lifetime, password policy
- ⚪ **Security Awareness Training** — bir başka geliştirici eklenirse

**Maliyet:** Solo dev kendisi yazabilir, opsiyonel danışman €1-3k.

---

## 11.4 — Penetration Test (Ay 7-8)

**Hedef:** Bağımsız 3rd party güvenlik testi → bulgular fix → certificate.

| Alanlar | Test edilir |
|---|---|
| OWASP Top 10 web app | SQL injection, XSS, CSRF, auth bypass, IDOR |
| API endpoints | 176 endpoint, rate limit, auth, input validation |
| Infrastructure | TLS, headers, DNS, hosting config |
| Social engineering | Email phishing simulation (opsiyonel) |
| Source code review | Statik analiz (Semgrep, Bandit) |

Önerilen firma (Almanya'da):
- **SySS GmbH** (Tübingen) — €5-15k, 1-2 hafta
- **redteam.pl** veya Almanya pentestcİları
- **HackerOne / Bugcrowd** crowdsourced (alternatif, %0.5-2% bug bounty per critical)

Çıktı: Pentest raporu (CVSS scoring + recommendations) → fix → re-test → certificate of completion.

**Maliyet:** €5-15k tek seferlik + €3-5k yearly re-test.

---

## 11.5 — ISO 27001 light süreç (Ay 9-14)

**Hedef:** Information Security Management System (ISMS) kurulumu.

ISO 27001 "light" = küçük şirketler için TISAX-benzeri uyumluluk, tam sertifikasyon değil.

| Adım | Süre |
|---|---|
| Gap analysis (mevcut TOMs vs ISO 27001 Annex A) | 1-2 hafta |
| ISMS scope tanımı (sadece SaaS prod) | 1 hafta |
| Risk assessment + treatment plan | 2-3 hafta |
| Policies + procedures (114 Annex A controls) | 4-6 hafta |
| Internal audit (kendisi veya danışman) | 1 hafta |
| Management review + action items | 1 hafta |
| Sertifikasyon: opsiyonel (sertifika için DEKRA/TÜV harici audit) | 4-8 hafta |

**Light versiyonda** sertifika yerine: "ISO 27001-aligned" claim + dokümantasyon — B2B sales için yeterli.

**Tam sertifika** istersen DEKRA/TÜV Süd vs. ile audit yapılır.

**Maliyet:**
- Light (claim only): €5-15k danışman + kendi zaman
- Tam sertifika: +€10-20k audit + €5k/yıl re-audit

---

## 11.6 — BSI Grundschutz / Enterprise tier (Yıl 2+)

**Hedef:** Almanya kamu sektörü ve büyük enterprise müşterilere açılma.

BSI = Bundesamt für Sicherheit in der Informationstechnik (Almanya federal güvenlik kurumu).

| Sertifika | Müşteri profili | Maliyet |
|---|---|---|
| **BSI IT-Grundschutz** | Almanya orta-büyük şirketler, kamu | €30-80k |
| **C5 (Cloud Computing Compliance Criteria Catalogue)** | Cloud provider müşterileri, BSI requested | €20-50k |
| **Auftragsverarbeitung** | B2B SaaS müşterileri (DSGVO Art. 28 plus) | €5-15k |

**Ön şartlar (ISO 27001 light bittikten sonra):**
- ISMS olgunluk en az 12 ay
- Pentest geçmişi (yıllık)
- Audit log infrastructure (Phase 8'den)
- Detailed asset inventory
- Vendor risk management
- BCMS (Business Continuity Management System)
- Incident response capability

**Iş etkisi:**
- Enterprise customer için ZORUNLU
- 1 enterprise müşteri = 50-200 SMB customer kadar gelir
- Steuerberater büyük firmalar (HLB, Mazars, RSM Ebner) için referans

**Maliyet vs. Getiri (gerçekçi):**
- Bir BSI sertifikası 2 yılda alınır, €50-100k yatırım
- İlk enterprise müşteri 6 ay içinde gelirse yatırımı karşılar
- Solo dev sınırına ulaşırsan: 2-3 kişilik ekip büyütme + danışmanlık

---

## Phase 11 zaman çizelgesi (özet)

```
Ay 1-6:    İlk 10 müşteri, ürün stabilite, customer feedback
Ay 5-7:    Güvenlik dokümantasyonu (paralel, kendi yazar)
Ay 7-8:    Penetration test (external — SySS veya benzer)
Ay 9-14:   ISO 27001 light implementation
Ay 12+:    Enterprise sales konuşmaları (ISMS belgelerle)
Yıl 2:     BSI / C5 sertifikasyon planlaması
Yıl 2-3:   BSI sertifika alımı
Yıl 3+:    Kamu sektörü + büyük enterprise satış
```

**Hesaplı yol:** Ay 6 sonunda 10 müşteri + €890/ay gelir → Pentest yatırımı için cash flow var → ISO 27001 light + B2B sales açılır → enterprise tier'a köprü.

---

## Phase 11 stratejik notlar

1. **Sertifikasyon → satış değil**, sertifikasyon **satış engellerini kaldırır**. Büyük müşteri "DSGVO + ISO 27001 var mı?" diye sorar, "yok" cevabı satışı öldürür.

2. **Bootstrap'ta sertifikasyon erken yapma** — ürün-pazar uyumu (product-market fit) yokken €30k harcama riski.

3. **B2B-first değil B2C-first kal** — 10 SMB müşteri toplamak 1 enterprise sözleşme açmaktan kolay. Önce SMB'de kazan, sonra enterprise.

4. **Steuerberater partnerlik 1. öncelik** (S5 Berater Portal sonrası) — bir Steuerberater = potansiyel 50-200 mandant. ISO sertifikası gerekmez, sadece DATEV export ve veri güvenliği yeter.

5. **Solo dev sınırı** — Tek başına ISO 27001 + BSI yürütemezsin. 5+ müşteri sonrası yarı zamanlı danışman + Yıl 2'de junior dev/ops kiralama planı.

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
- Claude Opus 4.8 (engineering plan + delivery), 2026-05-31 güncelleme

2026-05-26
