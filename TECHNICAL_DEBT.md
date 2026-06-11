# TECHNICAL DEBT — AutoTax-Cloud

> Son güncelleme: 2026-06-11 · Kanıt: kod incelemesi (file:line).
> Etiketler: **P0 Kritik · P1 Yüksek · P2 Orta · P3 Düşük**
> Bu dosya performans değil, **yapısal borç** içindir. Performans için → `PERFORMANCE_AUDIT.md`.

---

## 1. `main.py` — monolit

| # | Borç | Kanıt | Öncelik |
|---|---|---|---|
| 1.1 | **Tek dosyada 14.244 satır, 209 endpoint** | `wc -l autotax/main.py` = 14244; `grep @app.(get/post/...)` = 209 | P1 |
| 1.2 | İş mantığı + endpoint + heuristik iç içe (örn. upload içinde ~200 satır inline vendor/dosya-adı heuristiği) | `main.py:8200-8512` | P1 |
| 1.3 | Aynı metrik hesabı 3 endpoint'te tekrar (dashboard/summary/chat) | `main.py:4946 / 8874 / 12399` | P1 |

**Sebep:** Solo + AI ile hızlı feature-first geliştirme. **Etki:** Her değişiklik regresyon riski; "küçük commit" zor; test yüzeyi büyük. **Çözüm:** Yeni feature DURDU; modülarizasyon (router'lara böl: `invoices`, `steuer`, `kasse`, `billing`, `admin`). RED LINE: tek seferde büyük refactor YOK — endpoint endpoint taşı, her adımda test.

---

## 2. OCR pipeline

| # | Borç | Kanıt | Öncelik |
|---|---|---|---|
| 2.1 | Tüm hat `async def` içinde **sync/bloklayıcı** | `main.py:8022, 8127, 8150, 8195`; sync DB `db.py:23-24` | **P0** |
| 2.2 | Ana yolda **downscale yok** (sadece <1500px upscale) | `ocr.py:789-790` | **P0** |
| 2.3 | **Hiç timing enstrümantasyonu yok** → kör nokta | `grep perf_counter ocr.py` = 0 | **P0** (ilk iş) |
| 2.4 | Tesseract düşük metinde **4× tam tur** | `ocr.py:805-823` | P1 |
| 2.5 | OCR.space **3 ardışık** 30s çağrı | `ocr.py:264/274/283` | P1 |
| 2.6 | QR decode upload başına **3×**, çift geçiş | `qr_reader.py:39/52`, `main.py:8135/8157/8175` | P1 |
| 2.7 | Hiç cache yok (OCR/parser/QR sonucu) | path geneli | P2 |
| 2.8 | Upload başına **5+ ayrı DB session** | `main.py:8095/8546/8560/8582/8603` | P2 |

**Not:** Parser (`parser.py` 3143 satır) upload başına **1 kez** çağrılıyor (`main.py:8195`) — tekrar yok, ama ağır (~15 alt-extractor). Şimdilik kabul edilebilir.

---

## 3. API katmanı

| # | Borç | Kanıt | Öncelik |
|---|---|---|---|
| 3.1 | `/vault` sayfalama yok + BLOB yüklüyor | `main.py:11837/11848` | **P0** |
| 3.2 | dashboard/summary/chat tam-tablo Python aggregation | `main.py:4946 / 8874 / 12399` | P1 |
| 3.3 | `email_invoices_bulk` async'te bloklayıcı PDF döngüsü | `main.py:4422` | P1 |
| 3.4 | Export/GDPR uçlarında sınırsız `.all()` | `main.py:7469/11983/3405` | P2 |

**🟢 İyi olanlar (borç DEĞİL):** `/invoices` ve `/bookkeeping` zaten sayfalı (skip/limit, default 50, max 500); `/bookkeeping` SQL aggregation kullanıyor; hot list uçları `def` (threadpool'da çalışır, event-loop'u bloklamaz); OCR.space + AI-reviewer webhook async httpx.

---

## 4. Database

| # | Borç | Kanıt | Öncelik |
|---|---|---|---|
| 4.1 | **`Invoice.date` index yok** (her yıl/aralık filtresi bunu kullanıyor) | `models.py:263`; filtre `main.py:8797/13577/3405` | P1 |
| 4.2 | `Invoice.invoice_type`, `Invoice.category` indexsiz | `models.py:259/266` | P2 |
| 4.3 | **Sync SQLAlchemy** (`create_engine`, async değil) → commit'ler event-loop'u blokluyor (async uçlarda) | `db.py:23` | P1 |
| 4.4 | Eski `Invoice.file_data` (LargeBinary) hâlâ yükleniyor (defer yok) | `main.py:11848` | P1 |

**🟢 İyi:** `ix_invoices_user_active (user_id,is_deleted,status)`, `due_date/status/payment_status/vendor_ust_id` index'leri ve `CashEntry` composite index'leri zaten var (`db.py:346`, `models.py:388`). En yüksek değerli eksik: **`(user_id, date)` invoices**.

---

## 5. Frontend

| # | Borç | Kanıt | Öncelik |
|---|---|---|---|
| 5.1 | **Babel tarayıcıda transpile** (2.85 MB + 620 KB JSX her açılış) | `index.html:18/149` | **P0** |
| 5.2 | Tek dosya 620 KB / ~6800 satır / 45 component | `wc -c index.html`; `grep function [A-Z]` = 45 | P1 |
| 5.3 | HTML `no-cache` → 620 KB her açılış yeniden iner | `Cache-Control` header ölçüldü | P1 |
| 5.4 | **2009 inline `style={{}}`** objesi → her render'da yeni obje (reconciliation maliyeti) | `grep style={{` = 2009 | P2 |
| 5.5 | **İki tasarım dili**: Kasse (`css.card`, `theme.*`) vs Steuer/genel (`var(--*)`) → tutarsız "yarım bitmiş" his | `index.html` KasseDashboardView vs DeclarationView | P1 (UX) |

**Sebep:** "By design" denmiş (CLAUDE.md anti-pattern: "Babel in-browser by design") — ama bu performansı en çok yiyen karar. **Çözüm:** Build step (esbuild) ile Babel'i kaldır; uzun vadede component'leri dosyalara böl (gerekirse). RED LINE: TypeScript/Next.js rewrite YOK.

---

## Borç kapatma sırası (özet)
1. **P0** Frontend build step (Babel kaldır) — `index.html:18`
2. **P0** OCR'ı threadpool'a al + downscale cap — `main.py:8022`, `ocr.py:789`
3. **P0** OCR timing enstrümantasyonu — `ocr.py`/`main.py`
4. **P0/P1** `/vault` sayfalama + defer — `main.py:11837`
5. **P1** dashboard/summary/chat SQL aggregation — `main.py:4946`
6. **P1** `(user_id, date)` index — `models.py:263`
7. **P1** Tek tasarım dili (Kasse↔Steuer birleştir)
8. **P1** `main.py` router'lara modülarizasyon (kademeli)
