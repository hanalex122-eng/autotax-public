# Sprint 2.1 — Teknik Tasarım · Flexible Mietmodelle Faz 2 (Untermieter)

> ⚠️ **SUPERSEDED (2026-07-21).** Bu, kodlama başlamadan önce yazılmış ilk taslaktır ve tarihsel
> kayıt olarak durur. **Geçerli belge: [`Sprint_2_1_Untermieter.md`](Sprint_2_1_Untermieter.md)** —
> uygulanan hâli, uygulama durumu tablosunu ve çıkış kriterlerini o içerir. İkisi çeliştiğinde
> geçerli olan diğeridir. (Tek fark etiket: buradaki "Karar 1 = A", orada "Seçenek B" adıyla geçer —
> içerik aynı: Untermieter ayrı Unit'te.)

> **Belge türü:** Teknik tasarım (KOD DEĞİL). **Commit/deploy YOK.**
> **Ön koşul:** Faz 1 CANLI + kısa stabilizasyon. Kapsam kararı: **Karar 1 = A (ayrı Unit).**
> **Üst belge:** `docs/roadmap/Flexible_Mietmodelle_Phase1.md` · Ürün prensibi: `CONTRIBUTING.md`.
> **Onay sonrası** kodlamaya geçilir (Çalışma Sırası).

---

## 1. Sprint Amacı

Bir kiracının **Untermieter (alt kiracı)** olduğunu ve **hangi Hauptmieter'e** bağlı olduğunu kaydedebilmek. Böylece ev sahibi ilişkiyi (kim kimin alt kiracısı) izler; belgeler/PDF ve gelecek fazlar bu bağı kullanır.

**Bu sprintte (Karar 1 = A):** Untermieter **AYRI bir Unit'te** oturur → aynı-daire NK m²-payı sorunu **YOK.** Dar, güvenli, additive.

**Çözmediği (bilinçli):**
- ❌ Aynı dairede Hauptmieter + Untermieter (NK m²-paylaşımı) → Faz 3/4.
- ❌ WG / Zimmervermietung → Faz 3.
- ❌ Muhasebe/borç mantığı değişikliği → `monat_soll` ve NK motoru **DOKUNULMAZ.**

---

## 2. Kapsam Kararları (onaylı)

- **Karar 1 = A:** Untermieter ayrı Unit'te (paylaşımlı daire yok). NK/m² sorunu doğmaz.
- **Karar 2 = ayrı:** Untermieter'in **kendi Mietkonto/Mahnung**'u var (tenancy başına — zaten böyle çalışıyor). Hauptmieter'e borç bağlanmaz.

> Sonuç: Untermieter = kendi Unit'inde **normal bir tenancy** + iki yeni bilgi alanı (**etiket + Hauptmieter bağı**). Kalt/NK/Heiz/Zahler (Sprint 1.1) ve Mietkonto/Mahnung/NK zaten çalışır; bu sprint **sadece ilişkiyi** ekler.

---

## 3. Veri Modeli

`ImmoTenancy` (`models.py:911`) tablosuna **2 additive, nullable** kolon:

| İsim | Tip (SQL) | Nullable | Default | Neden |
|---|---|---|---|---|
| `typ` | `VARCHAR(10)` | ✅ | `NULL` (→ `haupt` gibi) | `haupt` \| `unter` — kiracı türü |
| `parent_tenancy_id` | `INTEGER` (self-FK, soft) | ✅ | `NULL` | Untermieter → hangi Hauptmieter (immo_tenancy.id) |

- `typ = NULL` → **`haupt` (mevcut kiracılar birebir aynı).**
- `parent_tenancy_id` sadece `typ='unter'` iken anlamlı; hard FK **değil** (mevcut desen — `immo_rent.tenancy_id` gibi soft), silme cascade karmaşası yok.

### Migration (Sprint 1.1 deseniyle aynı)
`db.py` startup idempotent `ALTER TABLE immo_tenancy ADD COLUMN` döngüsüne 2 satır:
```
if "typ" not in _tc:               ADD COLUMN typ VARCHAR(10)
if "parent_tenancy_id" not in _tc: ADD COLUMN parent_tenancy_id INTEGER
```
Try/except sarılı; eski satırlar `NULL` → davranış aynı.

### Geriye dönük uyumluluk
- Hepsi nullable/defaultsuz → eski kayıtlar `typ=NULL=haupt`, `parent=NULL`.
- **Mietkonto, Mahnung, NK, soll, API çıktıları birebir aynı** (yeni alanlar sadece ilişki bilgisi).

---

## 4. İş Kuralları (muhasebe DEĞİŞMEZ)

- `typ`/`parent_tenancy_id` **hiçbir hesaba girmez** — `monat_soll`, `monat_nk_soll`, Mahnung, NK motoru **dokunulmaz.**
- **Doğrulama:** `parent_tenancy_id` verilirse → (a) aynı user'a ait geçerli bir tenancy olmalı, (b) **kendine bağlanamaz**, (c) hedef `typ='haupt'` olmalı (Untermieter'e Untermieter bağlanmaz — Faz 2'de tek seviye), (d) **farklı Unit** (Karar 1=A güvencesi; aynı Unit'e bağlama Faz 3/4).
- `typ='unter'` ama `parent_tenancy_id` boş → izin ver ama "Hauptmieter seçilmedi" uyarısı (UI).
- Single-Ledger korunur: her tenancy kendi soll/borç/NK'sını türetir; ilişki sadece **görsel/belge** amaçlı.

---

## 5. API Etkisi

| Endpoint | Değişiklik |
|---|---|
| `POST /immo/tenancies` · `PATCH /immo/tenancies/{tid}` | `TenancyIn`/`TenancyPatch`'e `typ` + `parent_tenancy_id` (opsiyonel) + doğrulama |
| `_tenancy_dict` · tenant-feed (`/immo/mieter`) · `/units/{uid}/tenancies` | yanıta `typ`, `parent_tenancy_id`, (opsiyonel) `parent_name` eklenir |

**Eski istemciler:** alanlar opsiyonel/additive → kırılmaz. `typ` yoksa `haupt` kabul edilir.

---

## 6. UI Etkisi

- **ImmoTenancyForm + satır-içi edit** (Sprint 1.2'deki iki form): "**Untermieter (☑)**" seçeneği; işaretlenince **Hauptmieter seç** (aynı property'deki `typ=haupt` kiracılar dropdown'ı, farklı Unit).
- Kiracı kartında rozet: `🔗 Untermieter → [Hauptmieter adı]`.
- **Varsayılan:** işaretsiz = Hauptmieter (eski davranış). Yeni ekran YOK.
- Neuer Mieter sihirbazı: bu sprintte **kapsam dışı** (Sprint 1.2'deki gibi).

---

## 7. Regresyon / Test Planı

| Kontrol | Beklenen |
|---|---|
| Eski kiracı (`typ=NULL`) | `haupt` gibi; Mietkonto/Mahnung/NK **birebir aynı** |
| `soll` / `monat_nk_soll` | **değişmez** (birim testi: typ eklenince soll aynı) |
| NK-Abrechnung | **değişmez** (motor dokunulmadı) |
| Untermieter oluştur (ayrı Unit) | kendi Mietkonto/Mahnung; ilişki API'de görünür |
| Doğrulama | kendine bağlama / aynı-Unit / unter'e bağlama reddedilir |
| babel + structure (UI) | yeşil (tipografik `'`) |
| Backend suite | 44/44 + yeni Faz 2 testleri |

---

## 8. Risk Analizi

| # | Risk | Seviye | Önleme |
|---|---|---|---|
| R1 | Yeni alan muhasebeyi etkiler | 🟢 Düşük | `typ`/`parent` hiçbir hesaba girmez; regresyon testi |
| R2 | Geçersiz parent bağı (döngü/kendine) | 🟡 Orta | Sunucu doğrulaması (self/unter/aynı-Unit yasak) |
| R3 | Aynı-daire NK çift-sayımı | 🟢 (kapsam dışı) | Karar 1=A: farklı Unit zorunlu → sorun doğmaz |
| R4 | Migration | 🟢 | Idempotent ALTER (Sprint 1.1 deseni) |

---

## 9. Rollback

- Kod revert: `typ`/`parent` sadece bilgi → revert davranışı eskiye döndürür.
- Kolonlar additive/nullable → DB'de kalması zararsız, DROP gerekmez.
- Frontend + backend ayrı commit'lenir → parça parça geri alınabilir.

---

## 10. Sprint Planı (onaylanırsa)

- **2.1a — Şema + Model + doğrulama** (backend): `typ`+`parent_tenancy_id`, API + validation. Test: soll/NK değişmez.
- **2.1b — UI:** Untermieter toggle + Hauptmieter seçimi + rozet (iki form). Test: babel/structure.

---

## Onay

Bu **yalnızca tasarımdır.** İnceleme + onay sonrası kodlamaya geçilir. Kod/commit/deploy bu aşamada YOK.
