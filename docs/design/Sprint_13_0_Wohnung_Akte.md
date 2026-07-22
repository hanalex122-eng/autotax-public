# Sprint 13.0 — Wohnung Akte (#13) · Teknik Tasarım

> **Belge türü:** Uygulama planı. Onaylanan mimariye dayanır. **Yeni hesaplama · yeni aggregate endpoint · yeni veri modeli YOK.**
> **Üst belgeler:** `VERMIETER_MASTERPLAN.md` #13 · `CLAUDE.md` (Architecture law · Git workflow) · `SPRINT.md`
> **Tarih:** 2026-07-22 · **Durum:** onaylı, uygulamaya hazır

---

## 0. Başlangıç gerçeği (ölçüldü, varsayım değil)

`VERMIETER_MASTERPLAN.md:38` #13 için "🔴 yok" diyor — **bu satır güncel değil.** Akte **Phase 1 olarak
canlı**: `index.html:4229-4356`, 8 bölüm, 4 eager çağrı, 2 accordion. Sprint 13.0 sıfırdan bir ekran
yazmaz; **var olan hub'ın yalanlarını düzeltir ve bağlanmamış modülleri bağlar.**
*(Masterplan'ın durum sütunu sprint kapanışında düzeltilecek — sıra değişmiyor.)*

---

## 1. Temel ilke (bağlayıcı)

**Akte bir COMPOSITION HUB'dır.** Veri üretmez · hesaplama yapmaz · ikinci gerçek kaynak oluşturmaz ·
mevcut modülleri tek yerde toplar. Her sayı mevcut endpoint'ten geldiği gibi gösterilir
(CLAUDE.md yasası #2/#4). Tek istisna, Sprint 3.0'da onaylanan **"Offen gesamt"**: salt-görsel toplam,
saklanmaz, endpoint'e yazılmaz, Mahnung üretmez.

**Aggregate endpoint EKLENMEZ.** Backend'e bu sprintte **hiç dokunulmaz** — tüm iş `index.html` içinde.

---

## 2. Kapsam

**Dahil (E-numaraları analizden):**
| # | İş |
|---|---|
| E1 | Hata / boş durum ayrımı (bugün hata "veri yok" gibi görünüyor) |
| E2 | Yıl senkronizasyonu (Akte cari yıla sabit, ekranın yıl seçicisini yok sayıyor) |
| E3 | Deep-link (Mietkonto/Mahnung linkleri kiracıyı taşımıyor, Akte kapanmıyor) |
| E4 | Protokolle (Übergabe/Rückgabe) + PDF |
| E5 | Wohnungsgeberbestätigung (Einzug/Auszug PDF) |
| E6 | Kiracı iletişim bilgileri + Kaution |
| E7 | Zähler geçmişi (tam seri + tüketim) |
| E13 | Mobil düzen + ESC ile kapatma |
| R5 | Legacy inline-NK temizliği (ölü kod) |

**Hariç:** Mietvertrag (#9) · Schäden (#14) · fotoğraf modülü · yeni hesaplama · aggregate endpoint ·
yeni veri modeli · belge→daire bağı (`ImmoDocument.unit_id`, şema gerektirir → 13.1) ·
N>1 tamamlama (trigger-based, Faz 3 ile) · **R3 belge yükleme güvenliği → ayrı Security Hotfix.**

---

## 3. "Done" tanımı (#13)

1. Mevcut bütün modüller Akte'de eksiksiz görünür.
2. **Hata durumu veri yokluğu gibi gösterilmez.**
3. Her modüle tek tıkla gidilir (doğru bağlamla).
4. Yeni hesaplama eklenmez.
5. İkinci gerçek kaynak oluşmaz.

Henüz var olmayan modüller (#9, #14, fotoğraf) **kendi sprintlerinde** Akte'ye kendi bölümlerini ekler.

---

## 4. Uygulama adımları (küçük, test edilebilir)

### 13.0a — Ölü kod temizliği (R5) · *bağımsız, en düşük risk*
`index.html:3974-4009` arasındaki ImmobilienView-içi inline-NK yardımcıları **ölü**: NK sekmesi
`<NkEditor propertyId={sel.id}/>` render ediyor (`4227`); bu bloktaki hiçbir tanım ImmobilienView'ın
başka hiçbir yerinde kullanılmıyor.

**Kanıt (ölçüldü):** ImmobilienView aralığı `3905-4365`; `nkList` yalnız `3976`'da · `nkOpen` yalnız
`3977-4009` arasında · `openNk/newNk/addNkPos/delNkPos/toggleNkPos/finalizeNk/unlockNk/nkPdf/nkSaveRow/
nkSaveSchl/NK_KAT/NK_SCHL/NK_STD/nkGrid/nkSchl/nkPos/nkPosOf` **yalnız kendi tanım satırlarında**.
Ayrıca `newNk` içindeki `prompt()` (`3983`), P0 sprintinde onaylanan yıl seçici akışıyla **çelişen
legacy akıştır** (`SPRINT.md` P0 kaydı bunu "dead ImmobilienView inline-NK" olarak not etmişti).

**Yapılacak:** `3974-4009` silinir + `openProp`'taki `setNkOpen(null)` ve `refreshDetail`'deki
`loadNk(pid)` çağrıları kaldırılır. **Davranış değişmez** (hiçbiri render edilmiyordu).

### 13.0b — Hata ≠ boş + yıl senkronu (E1, E2)
Üç durum ayrılır: `null` = yükleniyor · `false` = **hata** · veri = boş/dolu.
Etkilenen state'ler: `akteMk`, `akteMh`, `akteNk`, `akteNkD`, `akteZ`.
Hata durumunda bölüm "Daten konnten nicht geladen werden" + **Erneut versuchen** gösterir.
Yıl: Akte, ekranın `year` state'ini kullanır (`acctY` → `year`); yıl değişince Akte verisi tazelenir.

### 13.0c — Deep-link (E3)
`sessionStorage` deseni zaten kullanılıyor (`index.html:1098`: `atx_invoices_status` → `onNav("invoices")`).
Aynı desen: `atx_mieter_focus = tenancy_id` → `onNav("mieter")`; `MieterView` mount'ta okur, o kiracının
detayını açar ve anahtarı siler. Akte kapanır. Mahnung linki aynı kiracıya gider.

### 13.0d — Modülleri bağla (E4, E5, E6, E7)
- **Protokolle:** `GET /immo/protokolle?tenancy_id=` (aktif sözleşme başına) → liste (art · datum · status)
  + PDF `GET /immo/protokolle/{pid}/pdf`. Lazy (accordion açılınca).
- **WGB:** mevcut `dlWgb(tid, "einzug"|"auszug")` (`3973`) Akte'den çağrılır.
- **Kiracı:** telefon · e-posta · Kaution (`tFull`) · Anmeldung durumu — hepsi zaten yüklü, sadece gösterim.
- **Zähler:** `GET /immo/units/{uid}/zaehler` (tam seri + `verbrauch`) — bugünkü `zaehler-matrix`
  (yalnız Anfang/Ende) yerine. Lazy.

### 13.0e — Mobil + ESC (E13)
Detay ızgaraları (`4302`, `4330`) dar ekranda tek kolona düşer (`isMob`). ESC ile kapatma.

---

## 5. Test planı

| Katman | Kontrol |
|---|---|
| Statik | `tests/_babelcheck.js` PARSE OK · `tests/check_jsx_structure.py` BALANCED |
| Backend suite | 47/47 (backend değişmiyor — regresyon beklenmiyor, doğrulanacak) |
| Ölü kod | Silme sonrası `nkOpen/newNk/...` kimliklerinin dosyada **NkEditor dışında** kalmadığı |
| Tarayıcı (yerel harness) | Akte'nin açılması · hata durumunda "Erneut versuchen" görünmesi · Protokoll/WGB/Zähler bölümleri · N=1 görünümünün bozulmaması |
| Prod smoke | `/health` · `/app` 200 · yeni marker'lar canlıda · console error yok · Akte açılıyor |

**Bağlayıcı regresyon:** tek sözleşmeli, verisi eksiksiz gelen bir dairede Akte **bugünküyle aynı
bilgileri** göstermeli — sadece eksik bölümler eklenmiş olmalı.

---

## 6. Riskler

| # | Risk | Önlem |
|---|---|---|
| R-A | Akte dev bir bileşenin içinde → regresyon | Adımlar küçük ve ayrı commit; her adımda babel/JSX + harness |
| R-B | Ölü kod silerken canlı bir şeyin kesilmesi | §4'teki kimlik-bazlı kanıt; silme sonrası grep doğrulaması |
| R-C | Yeni çağrılar Akte'yi yavaşlatır | Protokolle ve Zähler **lazy** (accordion açılınca); eager çağrı sayısı artmaz |
| R-D | Deep-link `sessionStorage` anahtarı temizlenmezse yanlış kiracı açılır | Okuyan taraf anahtarı hemen siler |
| R-E | "Erneut versuchen" ile sonsuz istek | Tek seferlik manuel tetik, otomatik retry yok |

---

## 7. Definition of Done (Sprint 13.0)

| # | Madde |
|---|---|
| D1 | E1 · E2 · E3 · E4 · E5 · E6 · E7 · E13 · R5 tamam |
| D2 | Hiçbir bölüm hata durumunu "veri yok" gibi göstermiyor |
| D3 | Yıl seçici Akte'yi de etkiliyor |
| D4 | Mietkonto/Mahnung linkleri doğru kiracıyı açıyor, Akte kapanıyor |
| D5 | Backend'de **0 satır** değişiklik (`git diff --stat`) |
| D6 | Yeni hesaplama yok · yeni endpoint yok · yeni tablo/kolon yok |
| D7 | Suite 47/47 · babel PARSE OK · JSX BALANCED |
| D8 | Tarayıcı smoke: Akte açılıyor, yeni bölümler görünüyor, N=1 görünümü bozulmadı |
| D9 | Deploy + prod smoke (`/health`, `/app`, console error yok) |
| D10 | Çelişen legacy akış kalmadı (inline-NK ölü kodu silindi) |
| D11 | `SPRINT.md` kapanış raporu + Masterplan #13 durum sütunu düzeltildi |

---

## 8. Sprint sonrası

- **13.1 (ayrı sprint):** `ImmoDocument.unit_id` (additive/nullable) → daire bazlı belgeler + Akte'den
  yükleme. **Ön koşul: Security Hotfix (R3).**
- **Security Hotfix (bağımsız, öncelikli):** yükleme boyut limiti · MIME whitelist ·
  `Content-Disposition: attachment` · content-sniffing/XSS kapatma.
- **#9 Mietvertrag · #14 Schäden · fotoğraf:** kendi sprintlerinde Akte'ye kendi bölümlerini ekler.
- **N>1 Akte tamamlama:** Faz 3 ile birlikte trigger-based.
