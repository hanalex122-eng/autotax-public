# Sprint 2.1 — Untermieter (Flexible Mietmodelle Faz 2)

> **Belge türü:** Teknik tasarım. **Bu belge kapsamında kod/commit/deploy YOK.**
> **Mimari karar:** **Seçenek B** — Untermieter yalnızca **ayrı bir Unit** üzerinde.
> **Üst belgeler:** `docs/roadmap/Flexible_Mietmodelle_Phase1.md` · `CLAUDE.md` (Architecture law) ·
> önceki taslak: `docs/design/Sprint_2_1_Flexible_Mietmodelle.md` (bu belge onun yerine geçer).

---

## 0. Uygulama durumu — ✅ TAMAMLANDI (canlı, 2026-07-21)

| Commit | İçerik | Durum |
|---|---|---|
| `3bbdf40` | `typ` + `parent_tenancy_id` — model + idempotent migration | ✅ canlı |
| `c92f49e` | API: `TenancyIn/Patch`, `_norm_typ`, `_validate_parent`, `_tenancy_dict` + feed | ✅ canlı |
| `d833120` | **Form A** (`ImmoTenancyForm`) — Untermieter toggle + Hauptmieter dropdown | ✅ canlı |
| `28175c5` | **Form B** (`MieterView` satır-içi düzenleme) + kiracı kartı rozeti | ✅ canlı |
| `b3e7223` | Form A'nın bu belgeden sapan 3 noktası (typ filtresi · K3 uyarısı · `unit_id` fallback) | ✅ canlı |
| `70cd732` | E2E regresyon testi + görsel doğrulama harness'i | ✅ canlı |

Suite 46/46 · prod smoke 11/11 PASS · Sprint 2.1 kapandı. Kapanış raporu: `SPRINT.md`.

---

## 1. Amaç

Ev sahibinin, bir kiracının **Untermieter (alt kiracı)** olduğunu ve **hangi Hauptmieter'e** bağlı
olduğunu sisteme kaydedebilmesi. Bu bilgi ilişkiseldir: ekranlarda ve belgelerde "kim kimin alt
kiracısı" görünür; ileriki fazlar (WG, aynı-daire NK payı) bu bağı temel alır.

Muhasebe hedefi **yoktur**: bu sprint hiçbir borcu, hiçbir Soll'u, hiçbir Mahnung'u değiştirmez.

---

## 2. Kapsam

1. `ImmoTenancy` üzerinde iki **additive, nullable** alan: `typ`, `parent_tenancy_id`.
2. Bu alanların `POST /immo/tenancies` ve `PATCH /immo/tenancies/{tid}` üzerinden yazılabilmesi,
   sunucu tarafında doğrulanması.
3. Bu alanların okuma yüzeylerinde dönmesi: `_tenancy_dict` ve kiracı feed'i (`GET /immo/mieter`).
4. UI: **iki mevcut formda** (Form A = `ImmoTenancyForm`, Form B = `MieterView` satır-içi düzenleme)
   "Untermieter" onay kutusu + Hauptmieter seçimi.
5. UI: kiracı kartında salt-okunur rozet `🔗 Untermieter → [Hauptmieter adı]`.
6. Regresyon testleri: yeni alanların muhasebeye **etki etmediğinin** kanıtı.

---

## 3. Kapsam dışı (kesin)

- ❌ **Aynı Unit içinde Untermieter** (paylaşımlı daire) — Faz 4.
- ❌ WG / Zimmervermietung — Faz 3.
- ❌ Parent tenancy'nin davranışının değişmesi (Hauptmieter'in borcuna alt kiracı eklenmesi vb.).
- ❌ Nebenkosten motoru, Heizkostenabrechnung, `monat_soll` / `monat_nk_soll`.
- ❌ Mahnung mantığı, Mietkonto mantığı, Payment Service.
- ❌ Çok seviyeli zincir (Untermieter'in Untermieter'i).
- ❌ Yeni ekran, yeni endpoint, yeni muhasebe modeli, sihirbaz (`Neuer Mieter`) değişikliği.

---

## 4. Veri modeli

`ImmoTenancy` (`autotax/models.py`) — iki kolon:

| Alan | SQL tipi | Nullable | Default | Anlam |
|---|---|---|---|---|
| `typ` | `VARCHAR(10)` | ✅ | `NULL` | `haupt` \| `unter`. **`NULL` = `haupt`** |
| `parent_tenancy_id` | `INTEGER` (soft self-FK) | ✅ | `NULL` | Untermieter → Hauptmieter `immo_tenancy.id` |

- **Hard FK yok** (mevcut desen: `immo_rent.tenancy_id` de soft'tur) → cascade/silme karmaşası yok.
- Migration: `db.py` startup'ındaki idempotent `ALTER TABLE ... ADD COLUMN` döngüsüne iki satır,
  try/except sarmalı (Sprint 1.1 deseniyle birebir aynı).
- **Geriye dönük uyumluluk:** mevcut satırlar `NULL/NULL` kalır → `haupt`, davranış birebir aynı.

---

## 5. İş kuralları

**K1 — Muhasebe dokunulmaz.** `typ` ve `parent_tenancy_id` hiçbir hesaplamaya girmez. Her tenancy
kendi Mietkonto / borç / ödeme / Mahnung akışını korur. Single-Ledger prensibi değişmez.

**K2 — Doğrulama (sunucu tarafı, `_validate_parent`).** `parent_tenancy_id` verildiğinde:

| # | Kural | Reddetme sebebi |
|---|---|---|
| a | parent aynı kullanıcıya ait, silinmemiş bir tenancy olmalı | "nicht gefunden" |
| b | kendine bağlanamaz (`parent == self`) | döngü |
| c | parent `typ='unter'` olamaz | tek seviye |
| d | parent **farklı Unit**'te olmalı | **Seçenek B güvencesi** |

**K3 — Boş bağ serbest.** `typ='unter'` ama Hauptmieter seçilmemişse kayıt kabul edilir; UI "Hauptmieter
seçilmedi" uyarısını gösterir. (Ev sahibi bilgiyi sonra tamamlayabilir.)

**K4 — `typ` geri alınırsa bağ silinir.** `typ` `haupt`'a çekildiğinde `parent_tenancy_id = NULL`.

**K5 — Silme sentinel'i.** `PATCH` içinde `parent_tenancy_id = -1` → bağı temizle (mevcut
`erstmonat_betrag` / `personenzahl` deseniyle aynı).

**K6 — Normalizasyon.** `typ` yalnızca `haupt`/`unter` kabul eder; başka her değer `NULL` (= `haupt`).

---

## 6. API etkisi

| Endpoint | Değişiklik | Kırıcı mı? |
|---|---|---|
| `POST /immo/tenancies` | `TenancyIn` + `typ`, `parent_tenancy_id` (opsiyonel) + K2 doğrulaması | hayır (additive) |
| `PATCH /immo/tenancies/{tid}` | `TenancyPatch` + aynı alanlar, `-1` = temizle | hayır |
| `GET /immo/units/{uid}/tenancies` (`_tenancy_dict`) | yanıta `typ`, `parent_tenancy_id` eklenir | hayır |
| `GET /immo/mieter` (feed) | yanıta `typ`, `parent_tenancy_id` eklenir | hayır |

- Yeni endpoint **yok**.
- Hauptmieter adı ayrı bir alan olarak **dönmez**: istemci zaten aynı listede `tenancy_id → mieter_name`
  eşlemesine sahiptir; ikinci bir kaynak yaratmamak için ad istemcide çözülür.
- Eski istemciler: alanlar opsiyonel → istek gövdesi değişmeden çalışır; `typ` yoksa `haupt` sayılır.

---

## 7. UI etkisi

**Form A — `ImmoTenancyForm`** (Immobilien görünümü, ekle + düzenle): `🔗 Untermieter (ayrı dairede)`
onay kutusu; işaretlenince `Hauptmieter` dropdown'ı — aday listesi: **aynı bina, farklı Unit, `typ≠unter`**.
Varsayılan işaretsiz = Hauptmieter (eski davranış).

**Form B — `MieterView` satır-içi hızlı düzenleme** (kalan iş): aynı iki kontrol, aynı aday kuralı,
mevcut `editF` / `openEdit` / `saveEdit` üçlüsüne alan ekleyerek. Yeni bileşen yok.

**Rozet** (kalan iş): kiracı kartında ad satırının altında salt-okunur
`🔗 Untermieter → [Hauptmieter adı]`. Hauptmieter listede bulunamazsa yalnızca `🔗 Untermieter`.

**Dokunulmayan:** `Neuer Mieter` sihirbazı (Erfassung), Mietkonto ekranı, Mahnung akışı, NK ekranları.
Diller: DE (birincil) · TR · EN — mevcut `_L`/`_iL` deseniyle.

---

## 8. Riskler

| # | Risk | Seviye | Önlem |
|---|---|---|---|
| R1 | Yeni alanlar muhasebeye sızar | 🟢 Düşük | Alanlar hiçbir hesaba girmez; `monat_soll`/`monat_nk_soll` regresyon testi |
| R2 | Geçersiz bağ (kendine / döngü / yabancı kullanıcı) | 🟡 Orta | K2 sunucu doğrulaması + testler |
| R3 | Aynı-daire NK çift sayımı | 🟢 (kapsam dışı) | Seçenek B: farklı Unit zorunlu → senaryo doğmaz |
| R4 | Migration | 🟢 Düşük | Idempotent `ADD COLUMN`, nullable, Sprint 1.1'de kanıtlanmış desen |
| R5 | İki formun farklı davranması (Form A yapıldı, Form B yapılmadı) | 🟡 Orta | **Şu an fiilen açık.** Form B tamamlanana kadar sprint "bitti" sayılamaz (CLAUDE.md: çelişen akış kalmayacak) |
| R6 | Hauptmieter silinince sarkan `parent_tenancy_id` | 🟢 Düşük | Rozet ada çözülemezse sadece `🔗 Untermieter` gösterir; borç etkilenmez |

---

## 9. Rollback planı

1. **UI geri alma:** frontend commit'i revert → formlar Sprint 1.2 haline döner. Backend alanları kalır,
   kimse yazmaz → görünür davranış eskisi.
2. **API geri alma:** `c92f49e` revert → alanlar yanıtlarda kaybolur, istemciler kırılmaz (opsiyoneldi).
3. **Şema:** kolonlar additive/nullable → **DROP gerekmez**, veri kaybı riski almadan yerinde kalabilir.
4. **Veri:** yanlış girilmiş bağlar `parent_tenancy_id = -1` PATCH'i ile tek tek temizlenebilir.
5. Frontend ve backend **ayrı commit'lerdir** → parça parça geri alınabilir.

Rollback sonrası hiçbir borç/Soll/Mahnung yeniden hesaplanmaz (alanlar hesaba girmiyordu).

---

## 10. Test planı

| # | Kontrol | Beklenen | Nerede |
|---|---|---|---|
| T1 | `typ`/`parent` eklenince `monat_soll` | **birebir aynı** | `tests/test_immo_sprint_2_1.py` ✅ |
| T2 | `monat_nk_soll` | değişmez | aynı ✅ |
| T3 | `_norm_typ` normalizasyonu | `haupt`/`unter`, diğer → `None` | aynı ✅ |
| T4 | `_validate_parent`: self / same-unit / unter-parent / not-found | 400 ile **reddedilir** | aynı ✅ |
| T5 | `_tenancy_dict` yeni alanları döndürür; eski kiracıda `typ=None` | kırılmaz | aynı ✅ |
| T6 | `tests/test_immo_untermieter.py` (ayrı Unit senaryosu) | yeşil | ✅ |
| T7 | Mevcut backend suite | tamamı yeşil (regresyon yok) | tüm suite |
| T8 | **Form B kaydı** (`PATCH` + `typ/parent`) | ilişki kaydedilir, tutarlar değişmez | kalan iş |
| T9 | **Rozet** doğru Hauptmieter adını gösterir | evet | kalan iş |
| T10 | `tests/_babelcheck.js` + `tests/check_jsx_structure.py` | yeşil | UI değişikliği sonrası |
| T11 | Manuel UX: Untermieter oluştur → kendi Mietkonto'su ve kendi Mahnung'u var; Hauptmieter'in borcu değişmedi | evet | prod smoke |

---

## 11. Çıkış kriterleri (sprint "bitti" demek için hepsi)

1. `typ` + `parent_tenancy_id` şema + migration canlıda, mevcut kiracılarda davranış değişmemiş.
2. API create/patch/read yeni alanları destekliyor; K2 doğrulamaları çalışıyor.
3. **Form A ve Form B aynı davranıyor** — iki ekran çelişmiyor.
4. Kiracı kartında rozet görünüyor.
5. Backend suite tamamı yeşil; `babel` + `structure` kontrolleri yeşil.
6. Prod smoke: bir Untermieter oluşturuldu, ilişki göründü, **Hauptmieter'in borcu/Soll'u değişmedi**.
7. `SPRINT.md` kapanış raporu yazıldı: tamamlanan · bilinçli ertelenen (aynı-daire, WG) · açık riskler.
8. Kullanıcı gözünden kritik boşluk yok.

---

## Kapanış

Sekiz çıkış kriterinin tamamı karşılandı (2026-07-21). Ayrıntılı kapanış raporu — commit listesi,
test/visual/prod-smoke kanıtları ve açık teknik borçlar — `SPRINT.md` içindedir.

Faz 3 (WG / Zimmervermietung) ve aynı-daire Untermieter (Faz 4) bu belgenin kapsamı dışındadır ve
kendi tasarım belgelerini gerektirir.
