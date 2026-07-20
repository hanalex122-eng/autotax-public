# Sprint 1.1 — Teknik Tasarım · Flexible Mietmodelle Faz 1

> **Belge türü:** Teknik tasarım (KOD DEĞİL). **Commit/deploy YOK.**
> **Kapsam:** SADECE `heizkostenvorauszahlung` + `zahler` + `warmmiete`. Başka özellik yok.
> **Üst belge:** `docs/roadmap/Flexible_Mietmodelle_Phase1.md` · Ürün prensibi: `CONTRIBUTING.md`.
> **Onay sonrası** kodlamaya geçilir (Çalışma Sırası §13).

---

## 1. Sprint Amacı

**Çözdüğü problem:** Bir kira sözleşmesinde ödemenin üç bileşeni (Kaltmiete + NK-Vorauszahlung + **Heizkostenvorauszahlung**) ayrı tutulabilsin ve aylık borç (Warmmiete) bu üçünden doğru kurulsun. Ayrıca kirayı **kimin ödediği (Zahler)** kaydedilebilsin (Mieter / Sozialamt / Jobcenter / Sonstige).

**Bilinçli olarak çözMEdiği:**
- ❌ Untermieter / Hauptmieter ilişkisi / parent tenancy (Faz 2)
- ❌ WG / Zimmervermietung / aynı dairede birden çok sözleşme (Faz 3)
- ❌ **NK-Abrechnung'da Heizkosten-Voraus'un mahsubu** (Faz 4) — Bu sprint NK motoruna **DOKUNMAZ**.
- ❌ Mahnung/PDF'i otomatik Zahler'e (Sozialamt) yönlendirme — Zahler bu sprintte **salt bilgi**.

---

## 2. Veri Modeli

`ImmoTenancy` (`models.py:911`) tablosuna **3 additive, nullable** kolon:

| İsim | Tip (SQL) | Nullable | Default | Neden gerekli |
|---|---|---|---|---|
| `heizkosten_voraus` | `DOUBLE PRECISION` (Float) | ✅ | `NULL` (hesapta 0) | Kalt + NK'ya ek **ayrı Heizkosten** bileşeni |
| `zahler_typ` | `VARCHAR(20)` | ✅ | `NULL` (→ `mieter` gibi davranır) | Kirayı kim ödüyor |
| `zahler_name` | `VARCHAR(200)` | ✅ | `NULL` | Ödeyen kurum/kişi adı (ör. "Sozialamt Krefeld") |

`zahler_typ` geçerli değerler: `mieter` \| `sozialamt` \| `jobcenter` \| `sonstige` (DB enum DEĞİL, string — yeni değer migration istemez, `nk_kostenposition.kategorie` deseni).

### Migration stratejisi
Mevcut desenle **birebir aynı** (`db.py:67-93`): startup'ta idempotent kontrol + `ALTER TABLE`:
```
_tc = [c["name"] for c in inspector.get_columns("immo_tenancy")]
if "heizkosten_voraus" not in _tc: ALTER TABLE immo_tenancy ADD COLUMN heizkosten_voraus DOUBLE PRECISION
if "zahler_typ"        not in _tc: ALTER TABLE immo_tenancy ADD COLUMN zahler_typ VARCHAR(20)
if "zahler_name"       not in _tc: ALTER TABLE immo_tenancy ADD COLUMN zahler_name VARCHAR(200)
```
Try/except ile sarılı (mevcut deseni izler); başarısızsa loglar, uygulama açılmaya devam eder.

### Geriye dönük uyumluluk / eski kayıtların davranışı
- Kolonlar **nullable + defaultsuz** → eski satırlar `NULL` kalır.
- Hesapta `heizkosten_voraus = NULL → 0`, `zahler_typ = NULL → "mieter"` kabul edilir.
- **Eski kayıtların Warmmiete'si, Mietkonto'su, Mahnung'u birebir aynı kalır.** (Kanıt: §6 regresyon.)

---

## 3. İş Kuralları

### Warmmiete (aylık borç) — `monat_soll` (`immo_rules.py:93`)
Bugün: `warm = effective_kalt(t,y,m) + nk_voraus` (satır 109).
**Sprint 1.1:** `warm = effective_kalt(t,y,m) + nk_voraus + heizkosten_voraus`.
- Tek terim eklenir. `heizkosten_voraus = 0` iken sonuç **değişmez**.
- **Erstmonat istisnası korunur** (satır 106-108): `erstmonat_betrag` GROSS anlaşılan tutar → üstüne NK **veya** Heiz eklenmez (değişiklik yok).

### Heizkosten hangi durumda dahil?
Her normal ay `heizkosten_voraus` (null→0) × Tagesanteil (`month_proration`) borca dahil. Erstmonat'ta değil (gross zaten kapsıyor).

### Single-Ledger korunuyor mu? (KRİTİK)
**Evet — ama dikkat gerektiren bir nokta var.** Bugün `monat_nk_soll = monat_soll − monat_kalt_soll` (`immo_rules.py:123-126`). Heiz'i naifçe `monat_soll`'a eklersek `monat_nk_soll` kendiliğinden `nk + heiz` olur → **NK-Abrechnung'ın Vorauszahlung mahsubu değişir** (Faz 4'e ait, bu sprintte YASAK).

**Çözüm (Single-Ledger'ı bozmadan NK'yı izole et):** üç-yönlü split, tek `monat_soll`'dan türer:
```
monat_soll      = kalt + nk + heiz          (TEK borç kaynağı — Warmmiete)
monat_kalt_soll = kalt                       (değişmez)
monat_nk_soll   = nk   (SADECE — açıkça, heiz HARİÇ)   ← NK-Abrechnung bunu kullanır → DEĞİŞMEZ
monat_heiz_soll = heiz  (YENİ — ileride Faz 4 NK mahsubu için; şimdi NK'ya BAĞLANMAZ)
```
- Invariant: **`monat_soll == monat_kalt_soll + monat_nk_soll + monat_heiz_soll`** (testle güvence).
- `heiz = 0` iken `monat_nk_soll` bugünkü değerle **birebir aynı** → NK-Abrechnung ve mevcut Vorauszahlung mantığı hiç etkilenmez.
- Borç yine **tek yerden** (`monat_soll`) türer → "ONE accounting model" korunur (CLAUDE.md).

### Zahler alanı muhasebeyi nasıl etkiler?
**Etkilemez.** `zahler_typ`/`zahler_name` bu sprintte **salt bilgi/etiket** — soll, Mahnung tutarı, ödeme mantığı değişmez. (Mahnung muhatabının otomatik Sozialamt olması Faz 2+.)

---

## 4. API Etkisi

| Endpoint | Değişiklik |
|---|---|
| `POST /immo/tenancies` (`immo_api.py:996`) | `TenancyIn`'e 3 opsiyonel alan; kayıtta persist |
| `PATCH /immo/tenancies/{tid}` (`:1010`) | `TenancyPatch`'e 3 opsiyonel alan; güncelle |
| Tenant-feed (`:188-236`) | response'a `heizkosten_vorauszahlung` + `zahler` eklenir; `gesamtmiete = kalt+nk+heiz` (`:236`) |
| `GET /immo/tenancies/{tid}/mietkonto` (`:330`) | soll artık Heiz'i içerir (şekil aynı, değer Warmmiete) |
| `GET /immo/units/{uid}/tenancies` (`:855`) | response'a 3 alan (opsiyonel) |

**Eski istemciler:** yeni alanlar **opsiyonel** (request'te göndermezse `NULL`, response'ta okumazsa yok sayar). Hiçbir alan silinmez/yeniden adlandırılmaz → **kırılmaz.**

---

## 5. UI Etkisi

> **Not:** Fiili UI işi **Sprint 1.2**'de (roadmap). Sprint 1.1 şema+backend'dir; burada etkisi tanımlanır.

- **Değişecek ekran:** Sözleşme formu (`ImmoTenancyForm`) — Kaltmiete/NK-Voraus yanına **Heizkosten alanı** + **Zahler seçimi** (Mieter/Sozialamt/Jobcenter/Sonstige) + **Zahler adı**.
- **Gösterim:** Akte / kiracı kartında `Gesamtmiete = Kalt+NK+Heiz` ve Zahler etiketi.
- **Varsayılan davranış:** alanlar boş → eski gibi (Heiz=0, Zahler=Mieter). Kullanıcı doldurmazsa hiçbir fark yok.
- **Yeni ekran:** ❌ önerilmiyor — mevcut form/kart yeterli (yeni ekran gerekçesi yok).

---

## 6. Regresyon Test Planı

| Senaryo | Beklenen sonuç | Kabul kriteri |
|---|---|---|
| **Mevcut kiracı (heiz=NULL)** — `monat_soll` | `kalt + nk` (bugünkü değer) | **Byte-identical** (örnek kiracıda önce/sonra) |
| **Mietkonto** (eski kiracı) | Aylık soll değişmez | 12 ay değerleri aynı |
| **Mahnung** (eski kiracı) | Borç eşiği/tutarı değişmez | Aynı Mahnung tutarı |
| **Nebenkosten** — `monat_nk_soll` (eski) | `= nk` (heiz hariç) | NK-Abrechnung Vorauszahlung **değişmez** |
| **Yeni: heiz=45** — `monat_soll` | `kalt + nk + 45` (×Tagesanteil) | Birim testi |
| **Yeni: heiz=45** — `monat_nk_soll` | Hâlâ `= nk` (heiz HARİÇ) | Birim testi (NK izolasyonu) |
| **Erstmonat + heiz** | `erstmonat_betrag` (gross, +heiz YOK) | Birim testi |
| **Invariant** | `soll == kalt_soll + nk_soll + heiz_soll` | Assertion + test |

**Genel kabul:** backend suite **43/43 yeşil**; `_babelcheck.js` + `check_jsx_structure.py` yeşil (UI 1.2'de); mevcut immo engine testleri geçer.

---

## 7. Risk Analizi

| # | Risk | Seviye | Olası etki | Önleme |
|---|---|---|---|---|
| R1 | `monat_soll` değişikliği borcu etkiler | 🟠 Orta | Yanlış Warmmiete/Mahnung | heiz=null→0; byte-identical regresyon; açık birim testi |
| R2 | Heiz'in `monat_nk_soll`'a sızması → NK'ya dokunma | 🟠 Orta | NK-Abrechnung Vorauszahlung bozulur | `monat_nk_soll`'u **açıkça nk-only** yap + `monat_heiz_soll` ayır; NK-izolasyon testi |
| R3 | `erstmonat_betrag` etkileşimi | 🟡 Düşük | Erstmonat'ta çift sayım | Erstmonat dalı değişmez (gross); test |
| R4 | Migration hatası (prod) | 🟢 Düşük | Kolon eklenmez | Idempotent guarded ALTER (mevcut desen); try/except+log |
| R5 | Eski API istemci | 🟢 Düşük | — | Alanlar opsiyonel/additive |

---

## 8. Rollback Planı

- **Kod geri alma:** `monat_soll`'daki `+ heizkosten_voraus` tek terim; revert → tekrar `kalt + nk`. `monat_heiz_soll`/nk-soll düzeltmesi de revert edilir. **Davranış anında eski hâline döner.**
- **Yeni kolonlar:** additive/nullable → **DB'de kalması zararsız** (revert edilen kod onları yok sayar; `heiz=NULL→0`). DROP COLUMN **gerekmez** (riskli değil, istenmez).
- **Özelliği "kapatma":** Heiz varsayılan `NULL→0` ve Zahler salt-bilgi olduğu için, sadece **kodu revert etmek** kolonlar dursa bile eski davranışı tam getirir.
- **Deploy güvenliği:** Faz bağımsız; bu sprint tek başına geri alınabilir; prod'da yıkıcı migration yok (sadece ADD COLUMN).

---

## Onay

Bu **yalnızca tasarımdır**. Teknik inceleme + onay sonrası kodlamaya (Sprint 1.1) geçilir. Kod/commit/deploy bu aşamada YOK.
