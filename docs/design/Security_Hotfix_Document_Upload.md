# Security Architecture Report — Belge Yükleme/İndirme Altyapısı

> **Belge türü:** Güvenlik mimari analizi + düzeltme tasarımı. **KOD YOK · commit/push/deploy YOK.**
> **Kapsam:** Tüm upload/download yüzeyleri salt-okuma incelendi; her iddia `dosya:satır` referanslı. Varsayım yok.
> **Amaç:** Minimum kod değişikliği · mevcut davranışı bozmamak · yeni özellik yok · yalnız güvenlik borcunu kapatmak.
> **Tarih:** 2026-07-23 · **Durum:** onay bekliyor · **Kaynak:** Sprint 13.0 R3.

---

## 1. Mevcut durum

### 1.1 Zaten var olan savunmalar (değiştirilmeyecek)
- **Global güvenlik başlıkları (middleware, TÜM yanıtlara):** `X-Content-Type-Options: nosniff`,
  `X-Frame-Options: DENY`, `X-XSS-Protection`, HSTS, CSP, `Cross-Origin-Resource-Policy: same-site`
  (`main.py:479-490`). ✅ Güçlü taban.
- **Path traversal:** `storage._resolve` `..`/mutlak yolu reddediyor, `UPLOADS_DIR` dışına çıkışı engelliyor
  (`storage.py:63-74`). ✅
- **Kullanıcı izolasyonu:** her upload/download `user_id` filtreli + sahiplik guard'ı
  (`immo_api.py:698,713`; `main.py:12440`). ✅
- **Disk (BLOB değil):** dosyalar diske, DB'de relative path (`storage.py:34-59`). ✅
- **Çoğu upload DOĞRULUYOR:** fatura/tax/kasse upload'ları hem **boyut** hem **magic-byte** kontrol ediyor
  (`main.py:7216-7220`, `:8391-8467`, `:9087`, `:3890`). Yani proje deseni sağlam — sorun **kapsam boşlukları.**

### 1.2 Upload yüzeyleri — kontrol matrisi

| Endpoint | Boyut limiti | Magic doğrulama | content_type kaynağı | Disposition | Değerlendirme |
|---|---|---|---|---|---|
| `POST /immo/documents` (`immo_api.py:691`) | ❌ **YOK** | ❌ **YOK** | ❌ kullanıcı (`:701`) | ❌ **inline** (`:722`) | 🔴 **ana açık** |
| `POST /immo/protokolle/{pid}/foto` (`immo_api.py:2387`) | 🟡 downscale öncesi limit yok | ✅ JPEG re-encode (sanitize) | türetilir | (foto, ayrı) | 🟡 küçük DoS |
| `POST /vault/.../upload` (`main.py:12436`) | ✅ (`:12444`) | ❌ **YOK** | ❌ kullanıcı (`:12452`) | 🟡 mode: attachment\|inline (`:12481`) | 🟠 orta |
| `POST /upload-invoice` (`main.py:8384`) | ✅ | ✅ (`:8467`) | doğrulanmış | attachment | ✅ |
| `POST /upload-erechnung` (`main.py:7057`) | ✅ (`:7063`) | ✅ (`:7220`) | doğrulanmış | attachment | ✅ |
| `POST /upload-batch` (`main.py:9071`) | ✅ (`:9081`) | ✅ (`:9087`) | doğrulanmış | attachment | ✅ |
| kasse/csv/xlsx/datev import (`main.py:8309,10804,...`) | ✅ | — (parse-only, diske yazmaz) | — | — | ✅ |

**Sonuç:** iki gerçek boşluk — **`POST /immo/documents` (🔴)** ve **vault upload (🟠)**. Kasse/CSV import'ları
dosyayı parse edip atıyor (diske yazmıyor), servis edilmiyor → XSS yüzeyi değil.

### 1.3 Download yüzeyleri — Content-Disposition
23 download `attachment`, **1 `inline`**: `GET /immo/documents/{did}/download` (`immo_api.py:722`).
Vault download `inline`'a düşebiliyor ama `mode` parametresiyle (`main.py:12481`).

### 1.4 Diğer bulgular
- **Filename header injection (küçük):** `Content-Disposition: inline; filename="{d.filename}"` — `d.filename`
  ham interpole (`immo_api.py:722`). Filename `"` veya CRLF içerirse header kırılabilir. Diğer PDF
  download'ları **sabit** filename kullanıyor (güvenli).
- **Uzantı kontrolü:** `storage._safe_ext` yalnız uzantıyı whitelist'liyor ve tanınmayanı `.bin`'e
  **çeviriyor** — reddetmiyor, içeriği doğrulamıyor (`storage.py:24-31`).
- **Test:** immo belge upload/storage güvenliği için **hiç test yok** (grep boş).

---

## 2. Risk analizi

| Sev. | # | Bulgu | Neden |
|---|---|---|---|
| 🔴 **Critical** | R-1 | **Stored XSS** — `/immo/documents` kullanıcı-`content_type`'ı `inline` sunuyor (`immo_api.py:701,722`) | `text/html`/SVG+script yüklenip origin'de render → **çalışır**. `nosniff` deklare edilmiş text/html'i durdurmaz; CSP `script-src 'unsafe-inline' 'unsafe-eval'` (`main.py:459`) içerdiği için inline script **engellenmez** |
| 🟠 **High** | R-2 | **Magic doğrulaması yok** (`/immo/documents`) — sahte içerik | R-1'i besler; `.pdf` uzantısıyla HTML/yürütülebilir yüklenebilir |
| 🟠 **High** | R-3 | **Boyut limiti yok** (`/immo/documents`) (`immo_api.py:693`) | Tek büyük dosya → disk/DoS. `MAX_FILE_SIZE=10MB` var ama uygulanmıyor |
| 🟡 **Medium** | R-4 | **Vault upload magic yok** + kullanıcı content_type (`main.py:12452`) | R-1'in hafif sürümü (download mode'a bağlı) |
| 🟡 **Medium** | R-5 | **Filename header injection** (`immo_api.py:722`) | Bozuk filename → header manipülasyonu |
| 🟢 **Low** | R-6 | Protokoll foto downscale öncesi boyut limiti yok (`immo_api.py:2387`) | JPEG re-encode sanitize ediyor; yalnız kaynak DoS |
| 🟢 **Low** | R-7 | immo belge güvenlik testi yok | Regresyon güvencesi eksik |

---

## 3. Tehdit modeli

**Saldırgan:** kimliği doğrulanmış (kötü niyetli veya ele geçirilmiş) bir hesap. (Anonim yükleme yok —
tüm endpoint'ler `Depends(get_current_user)`.)

| # | Senaryo | Yol | Bugünkü sonuç | Sınır |
|---|---|---|---|---|
| T1 | **Stored XSS** | `content_type: text/html` + `<script>` yükle → `/immo/documents/{id}/download` bağlantısını hedefe aç | Script **origin'de çalışır** (R-1) — token/oturum çalınabilir | CSP `frame-ancestors 'none'` framing'i durdurur ama **direkt navigasyon**u durdurmaz |
| T2 | **Content-sniffing** | zararlı içeriği masum MIME ile | `nosniff` (`main.py:481`) sniffing'i **durdurur** → T2 mitigate | — |
| T3 | **DoS / disk** | çok büyük dosya `/immo/documents` | Limit yok → yazılır (R-3) | R2 backup diski etkilenmez (ayrı) |
| T4 | **Path traversal** | `../../etc` | `storage._resolve` **reddeder** (`storage.py:63`) → **kapalı** | — |
| T5 | **Cross-user erişim** | başka user'ın belgesi | `user_id` filtresi → **kapalı** | — |

**Öncelik:** T1 (Critical, aktif) → T3 (High) → T2 zaten mitigate.

---

## 4. Önerilen değişiklikler (minimum, davranış korur)

### D-1 (Critical → kapatır): Download sertleştirme — `/immo/documents/{did}/download`
- `Content-Disposition: **attachment**` (inline değil) — belge indirilir, origin'de render edilmez.
- **media_type güvenli:** kullanıcı-content_type yerine `application/octet-stream` (veya magic'ten türetilmiş).
- Filename **sanitize** (`"`/CRLF temizle) — R-5.
- **Retroaktif:** eski belgeler de bu yolla indirilir → mevcut R-1 riskleri de kapanır. *(nosniff zaten var.)*

### D-2 (High): Upload sertleştirme — `POST /immo/documents`
- **Boyut limiti:** `len(content) > MAX_FILE_SIZE` → 400 (mevcut sabit).
- **Magic doğrulama:** `_validate_file_magic(content, claimed)` (`validators.py:105`) — eşleşmezse 400.
- **content_type türet:** saklanan değer kullanıcıdan değil, doğrulanmış magic'ten.

### D-3 (Medium): Vault upload — `main.py:12436`
- Aynı magic doğrulaması + türetilmiş content_type. (Boyut limiti zaten var.)

> **Not:** D-1 tek başına Critical'i kapatır ve **hiçbir meşru akışı bozmaz** → önce o.

---

## 5. Regresyon riski

| Değişiklik | Regresyon yüzeyi | Seviye | Önlem |
|---|---|---|---|
| D-1 download `attachment` | Akte "Zu Dokumenten"/liste indirme | 🟢 | İndirme zaten indirme amaçlı; kullanıcı akışı değişmez (dosya kaydedilir, sekmede açılmaz) |
| D-2 upload magic/limit | Meşru non-PDF/non-image belge | 🟡 | Whitelist PDF+jpg+png+tiff+webp+heic (`validators.py:94`); XML/gif/bmp → §karar |
| D-2 content_type türetme | Liste/gösterimde MIME | 🟢 | Liste yalnız ad/tip gösteriyor; MIME UI mantığını etkilemiyor |
| D-3 vault | Fatura orijinali indirme/önizleme | 🟡 | Vault download `mode` koruyor; yalnız upload doğrulaması eklenir |

**Muhasebe / iş mantığı regresyonu YOK** — hiçbir değişiklik Mietkonto/NK/ledger'a dokunmaz.

---

## 6. Etkilenecek dosyalar

| Dosya | Değişiklik | Boyut |
|---|---|---|
| `autotax/immo_api.py` | `upload_document` (magic+limit+türet) · `download_document` (attachment+güvenli MIME+filename sanit) | küçük, 2 fonksiyon |
| `autotax/main.py` | `upload_vault_file` (magic+türet) — **opsiyonel, D-3** | küçük, 1 fonksiyon |
| `tests/test_immo_document_security.py` | **yeni** — güvenlik testleri | yeni dosya |
| `autotax/validators.py` | (yalnız okuma — `_validate_file_magic` yeniden kullanılır) | 0 satır |
| `autotax/storage.py` | muhtemelen 0 (magic API katmanında; istenirse `_safe_ext` sıkılaştırılır) | 0 / minimal |

---

## 7. Dokunulmaması gereken modüller

- `autotax/immo_rules.py` · `immo_payments.py` · `immo_payment_*.py` · `immo_nebenkosten.py` ·
  `immo_ledger.py` — **muhasebe/tek defter.**
- `autotax/mietvertrag_template.py` · `mietvertrag_api` bölümü — Sprint 9 (ayrı).
- `index.html` — **UI değişmez** (backend-only hotfix; indirme akışı aynı).
- Fatura upload doğrulama yolları (`upload_invoice/erechnung/batch`) — **zaten güvenli**, dokunulmaz.
- Global güvenlik middleware (`main.py:479-490`) — **çalışıyor**, dokunulmaz.

---

## 8. Deployment riski

- **Şema/migration YOK.** `ImmoDocument` alanları değişmez (yalnız yeni upload'larda `file_content_type`'a
  *güvenli* değer yazılır).
- **Geriye dönük uyumlu:** eski belgeler indirmede otomatik güvenli hale gelir; hiçbir kayıt silinmez/yeniden
  yazılmaz.
- **Kullanıcı-görünür değişiklik:** yalnız (a) yeni upload'da geçersiz dosya reddi, (b) indirmenin "aç" yerine
  "kaydet" olması. İkincisi bir davranış değişimidir ama belge indirme için **beklenen** davranış.
- **Deploy dönüşü kolay:** backend commit revert; veri etkilenmez.
- **Aciliyet:** R-1 Critical → deploy önceliği yüksek; ama Sprint 9 gibi ayrı push/deploy onayına tabi.

---

## 9. Test stratejisi

- **Birim (validators):** magic PDF/PNG kabul; boş → False; kısa/sahte → False.
- **Integration (TestClient):**
  - upload: sahte `.pdf` (HTML içerik) → **400**; >limit → **400**; boş → **400**; geçerli PDF → **200**.
  - download: yanıt header'ları `Content-Disposition: attachment`, güvenli `media_type`, filename sanitize;
    `nosniff` (middleware zaten ekliyor — doğrula).
- **Güvenlik senaryosu (T1):** `content_type: text/html` + `<script>` upload denemesi → 400 (D-2) VE eski bir
  HTML kayıt indirilse bile `attachment` (D-1) → origin'de çalışmaz.
- **Regresyon:** mevcut belge list/delete + Akte "Zu Dokumenten" davranışı aynı; suite yeşil.
- (Opsiyonel) `security-review` skill'i pending diff üzerinde.

---

## 10. Küçük implementasyon fazları

Tek küçük sprint, üç minik adım (her biri ayrı commit; risk artan sırada):

- **SH-1a — Download sertleştirme (Critical'i kapatır, en düşük risk):** `/immo/documents/{did}/download`
  → `attachment` + güvenli media_type + filename sanitize. Retroaktif. **Tek fonksiyon.**
  *DoD:* header'lar doğru; eski HTML kayıt origin'de çalışmıyor; list/delete değişmedi.
- **SH-1b — Upload sertleştirme:** `POST /immo/documents` → boyut limiti + magic + türetilmiş content_type.
  *DoD:* sahte/oversize reddedilir; geçerli PDF/görsel geçer; MIME türetilir.
- **SH-1c (opsiyonel) — Vault upload:** aynı magic+türetme (`main.py:12436`).
  *DoD:* vault upload doğrular; fatura indirme akışı bozulmadı.

**Ortak DoD:** şema/migration yok · muhasebe 0 satır · UI değişmez · suite yeşil + yeni güvenlik testleri ·
mevcut belge akışı regresyonsuz.

---

## Kodlamadan önce 2 karar (product owner)
1. **İzin verilen tipler:** yalnız **PDF + görsel** (magic-validated) mi, yoksa XML (Energieausweis/GAEB) da
   gerekli mi? XML'in magic'i yok (düz metin) — kabul edilecekse ayrı, güvenli bir kural gerekir.
2. **Vault (D-3/SH-1c) bu hotfixe dahil mi**, yoksa yalnız immo (`/immo/documents`) ile mi sınırlı kalsın?

---

## Onay
Bu belge **analiz + tasarımdır**; kod/commit yoktur. Onay ve yukarıdaki 2 kararla birlikte **SH-1a → SH-1b
(→ SH-1c)** kodlamasına geçilir — her adım ayrı commit, push/deploy ayrı onayla.
