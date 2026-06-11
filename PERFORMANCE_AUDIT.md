# PERFORMANCE AUDIT — AutoTax-Cloud

> Son güncelleme: 2026-06-11 · Yöntem: canlı ölçüm (curl) + kod incelemesi (file:line).
> Kural: **Varsayım yok, kanıt var.** Ölçülemeyen yerler açıkça "ÖLÇÜLMEDİ" diye işaretlendi.
> Öncelik etiketleri: **P0 = Kritik · P1 = Yüksek · P2 = Orta · P3 = Düşük**

---

## 0. Özet — "Uygulama neden yavaş hissediliyor?"

| Katman | Yavaş mı? | Kanıt |
|---|---|---|
| **Frontend ilk yükleme** | 🔴 **EVET — en büyük sorun** | Tarayıcı her açılışta **2.85 MB Babel** indirip **620 KB JSX'i tarayıcıda transpile ediyor** |
| **Railway / network** | 🟢 HAYIR | `/health` TTFB: min 0.13s, medyan **0.19s**, max 0.31s (10 istek). Cold-start gözlenmedi |
| **API yanıt sıkıştırma** | 🟢 OK | Yanıtlar edge'de **brotli** ile sıkıştırılıyor (`Content-Encoding: br`) — GZip eklemeye gerek yok |
| **OCR upload hattı** | 🔴 **EVET** | Tüm hat `async def` içinde **bloklayıcı/sync** çalışıyor → bir upload tüm istekleri dondurur |
| **Backend okuma uçları** | 🟡 KISMEN | Dashboard/summary/chat her seferinde TÜM invoice'ları çekip Python'da topluyor |

**Sonuç:** Yavaşlık hissi %80 **frontend (Babel in-browser)** + OCR upload hattının bloklayıcı olması. Railway/sunucu suçlu değil — bu kanıtlandı.

---

## P0 — KRİTİK

### P0-1 · Babel tarayıcıda çalışıyor (frontend ilk yükleme)
- **Sebep:** `index.html` tek dosya **620 KB**, içinde ~6800 satır JSX. Tarayıcı her açılışta `babel-standalone` (**2.849.480 byte = 2.85 MB**) indirip JSX'i **runtime'da** transpile ediyor. İlk boyama (first paint) bu transpile bitene kadar beklemek zorunda.
- **Kanıt:** `index.html:18` `<script src=".../babel-standalone/7.23.9/babel.min.js">`; `index.html:149` `<script type="text/babel">`. CDN ölçümü: react 10 KB + react-dom 131 KB + **babel 2.85 MB** + jszip 97 KB. HTML `Cache-Control: no-cache, no-store` → 620 KB her açılışta yeniden iner.
- **Etki:** Mobilde/zayıf bağlantıda saniyelerce beyaz ekran. CPU'su zayıf telefonda transpile tek başına 1–3 sn. "20 yıl geriden" hissinin teknik kaynağı kısmen bu.
- **Çözüm (P0):** Deploy anında JSX'i **bir kez** sade JS'e derle (esbuild/babel CLI build step) → `babel-standalone`'u tamamen kaldır, derlenmiş `app.js`'i **cache'lenebilir** statik dosya olarak sun. Mimariyi değiştirmez (hâlâ React CDN), sadece transpile'ı build zamanına alır. Beklenen kazanç: ilk yükleme **−2.85 MB indirme + −transpile CPU**.

### P0-2 · OCR upload hattının tamamı event-loop'u blokluyor
- **Sebep:** `POST /invoices/upload` → `upload_invoice()` `async def` ama içindeki tüm ağır iş **sync/bloklayıcı**: Tesseract (subprocess), pdfplumber, PIL/numpy ön-işleme, parser, sync SQLAlchemy commit. Hiçbiri threadpool'a alınmamış (tüm `autotax` paketinde `to_thread`/`run_in_executor` sadece `backup.py:301`'de var).
- **Kanıt:** `main.py:8022` `async def upload_invoice`; bloklayan çağrılar `main.py:8127` (tesseract), `8150` (pdf), `8195` (parser); DB sync `db.py:24` `SessionLocal` / `db.py:23` `create_engine` (async değil).
- **Etki:** Tek bir büyük foto/PDF upload'u, OCR süresi boyunca (memory notlarına göre ~60 sn'ye kadar) **aynı worker'daki TÜM eşzamanlı istekleri** dondurur. Çok kullanıcıda uygulama "takılıyor" hissi.
- **Çözüm (P0):** Bloklayan blokları `await asyncio.to_thread(...)` ile threadpool'a al (OCR.space `httpx` yolu zaten async — örnek mevcut). Alternatif: endpoint'i `def` yap (Starlette threadpool'da çalıştırır).

### P0-3 · OCR ana yolunda görüntü küçültme (downscale) yok
- **Sebep:** Ana Tesseract yolu görüntüyü **küçültmüyor**; sadece <1500px ise 2× büyütüyor. Memory'deki "12MP→2000px cap" yalnızca PDF→image ve AI-vision yollarına konmuş, ana foto yoluna **konmamış**.
- **Kanıt:** `ocr.py:789-790` (sadece upscale); 2000px cap `ocr.py:172-174` ve `ai_ocr.py:100` (farklı yollar). Tesseract config `--oem 3 --psm 6`, `deu+eng` `ocr.py:795-796`.
- **Etki:** 4000×3000 (12MP) telefon fotoğrafı Tesseract'a tam çözünürlükte gidiyor → OCR süresi katlanıyor. Düşük metinde **3 ek tam tur** (90/180/270 rotasyon) `ocr.py:805-823` → **4× Tesseract**.
- **Çözüm (P0):** OCR'dan önce en uzun kenarı ~2000px'e indir. Tek başına en büyük OCR hız kazancı.

### P0-4 · `/vault` tüm invoice tablosunu + BLOB ile çekiyor
- **Sebep:** `list_vault` sayfalama yok, ve eski `file_data` (LargeBinary) kolonunu satır başına yüklüyor.
- **Kanıt:** `main.py:11837` `.all()` (limit yok); `main.py:11848` `inv.file_data` okuması (defer yok).
- **Etki:** Çok fişi olan kullanıcıda her satırın MB'larca eski blob'u belleğe yüklenir → yavaş + bellek patlaması.
- **Çözüm (P1→P0 eğer çok fişli kullanıcı varsa):** `.options(defer(Invoice.file_data))` + `skip/limit`; `has_original`'ı `file_path`'tan türet.

---

## P1 — YÜKSEK

### P1-1 · Dashboard / summary / chat her seferinde TÜM invoice'ları Python'da topluyor
- **Sebep:** Üç ayrı uç (`calculate_dashboard_metrics`, `/invoices/summary`, `/chat`) her istekte tüm invoice setini `SELECT *` çekip toplamı/MwSt/kategori/aylık dökümü **Python döngüsünde** hesaplıyor. `/chat` ayrıca `raw_text`'i de taşıyor (defer yok).
- **Kanıt:** `main.py:4946-5026` (dashboard), `main.py:8874` (summary), `main.py:12399` (chat). Doğru örnek zaten var: `_list_bookkeeping` SQL aggregation `main.py:9584-9589`.
- **Etki:** En çok vurulan 3 okuma ucunun yanıt süresi ve belleği **invoice sayısıyla doğrusal** büyüyor; aynı hesap 3 yerde tekrar.
- **Çözüm:** Python toplamlarını SQL'e taşı (`func.sum`, `case`, `group_by`). `/chat`'te `defer(raw_text)`.

### P1-2 · OCR.space ardışık 3 ağ çağrısı
- **Sebep:** Tesseract çıktısı zayıfsa OCR.space'e **ardışık 3** çağrı (Engine 1 → Engine 2 → orijinal görüntü), her biri 30s timeout.
- **Kanıt:** `ocr.py:264, 274, 283`.
- **Etki:** Kötü senaryoda 90 sn'ye kadar bekleme.
- **Çözüm:** Tek çağrı + en iyi engine; 3. denemeyi kaldır; timeout düşür.

### P1-3 · QR decode upload başına 3 kez + çift pyzbar geçişi
- **Sebep:** QR okuma 3 farklı dalda çağrılıyor, her çağrı renkli + gri 2 geçiş yapıyor (pyzbar bloklayıcı C lib).
- **Kanıt:** `qr_reader.py:39, 52`; çağrı yerleri `main.py:8135, 8157, 8175`.
- **Çözüm:** QR'ı orijinal byte'larda **bir kez** çöz, sonucu tekrar kullan; 1. geçiş başardıysa 2.'yi atla.

### P1-4 · `email_invoices_bulk` — async içinde döngüde bloklayıcı PDF üretimi
- **Sebep:** `async def` içinde her fatura için sync reportlab PDF render + disk okuma.
- **Kanıt:** `main.py:4422` (`_fetch_invoice_pdf_bytes` döngüde), helper `main.py:4269-4298`.
- **Çözüm:** Döngü gövdesini `await asyncio.to_thread(...)` ile threadpool'a al.

---

## P2 — ORTA

### P2-1 · `Invoice.date` üzerinde index yok
- **Kanıt:** `models.py:263` (String, index yok). Filtre/sıralama: `main.py:8797-8800`, `13577-13578`, `ORDER BY date` `3405`. EÜR/dashboard/yıl filtreleri hep bu kolonu kullanıyor.
- **Çözüm:** `Index("ix_invoices_user_date", "user_id", "date")` ekle. En yüksek değerli index. (`invoice_type`, `category` de indexsiz ama daha az kritik.)

### P2-2 · `sync_invoices_to_bookkeeping` O(invoice × entry) Python eşleştirme
- **Kanıt:** `main.py:9939` dış döngü, `9948` iç tarama.
- **Çözüm:** `(vendor, amount, date) → entry` sözlüğü kur, O(1) bak.

### P2-3 · `admin_list_users` N+1
- **Kanıt:** `main.py:2394-2399` (kullanıcı başına `.count()` + `UserCompany.all()`). Admin-only → blast radius düşük.
- **Çözüm:** `group_by(user_id)` ile tek sorguda say.

### P2-4 · Sınırsız `.all()` export/GDPR uçları (user_id ile filtreli ama limit yok)
- **Kanıt:** `main.py:7469-7476` (GDPR), `11983/11995/11999` (admin dump), `3405/3410` (DATEV).
- **Çözüm:** Makul cap / büyük export'larda stream.

---

## P3 — DÜŞÜK / NOT
- **GZipMiddleware yok** — ama **eklemeye gerek YOK**, edge brotli yapıyor (kanıt: `main.py:132` sadece CORS; `Content-Encoding: br` ölçüldü). Sadece edge'siz büyük JSON sunarsan değerlendir.
- **Veri izolasyonu:** Tüm sorgular `user_id` ile filtreli — **ihlal bulunmadı.** 🟢

---

## EKSİK ÖLÇÜM — yapılacak ilk iş (P0)
**OCR adım-adım gerçek ms süreleri ÖLÇÜLMEDİ.** `ocr.py`/`parser.py`'de timing log'u yok (`grep time.time|perf_counter` = 0). Önce enstrümantasyon:

Şu noktalara `t=perf_counter()` … `logger.info("[TIMING] <stage> %.0fms", ...)` ekle:
1. Dosya okuma `main.py:8028`
2. Tesseract `ocr.py:796` + rotasyon döngüsü `ocr.py:814` + çağrı `main.py:8127`
3. PDF metin `main.py:8150`, `ocr.py:152`
4. OCR.space `ocr.py:184/206`, çağrı `main.py:8165`
5. QR `qr_reader.py:273` / `23`, çağrılar `main.py:8135/8157/8175`
6. Parser `main.py:8195` (+ alt: `parser.py:1867/2080/2606`)
7. DB `main.py:8095/8546/8560/8582/8603`

Kaba ilk adım: 3 faz etrafına sarmal — (a) metin alma `8122-8169`, (b) parser+heuristik `8181-8512`, (c) DB+post `8544-8660` — hangi üçte-bir baskın hemen görünür.
