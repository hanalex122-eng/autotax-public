# Faz 3 — WG / Zimmervermietung · Architecture Decision Document

> **Belge türü:** Mimari karar analizi (KOD DEĞİL). **Commit / push / deploy / migration YOK.**
> **Tarih:** 2026-07-21 · **Ön koşul:** Faz 1 ✅ · Faz 2 (Sprint 2.1/2.2) ✅ canlı
> **Bağlayıcı üst belgeler:** `VERMIETER_MASTERPLAN.md` (kilitli) · `CLAUDE.md` (Architecture law) ·
> `.claude/nk_architecture.md` (Principle A/B/C) · `docs/roadmap/Flexible_Mietmodelle_Phase1.md` (§7 Ürün Prensibi, §8 Veri Modeli, §9 Tasarım İlkeleri)
> **Yöntem:** Bu belgedeki her teknik iddia mevcut kod okunarak doğrulandı; iddialar `dosya:satır` ile referanslıdır. Varsayım kullanılmadı.
>
> **Revizyon 3 (2026-07-21) — Guardrail = HARD VALIDATION.** §9.3-U3 ve §10/Sprint 3.0'daki
> *"uyarı, engelleme değil"* ifadesi geçersizdir. Karar: aynı Unit'te tarih aralığı **örtüşen** ikinci
> tenancy'nin oluşturulması **engellenir** — **override yok, sadece-uyarı yok.** Gerekçe: Sprint 3.0
> unit-seviye türetmeleri düzeltir ama **NK motoru aynı Unit'teki çoklu tenancy'yi henüz doğru
> hesaplamaz** (Sprint 3.1); hesaplanamayan bir durumun kaydedilmesine izin vermek, sessizce yanlış
> Abrechnung üretmek ve finalize edilirse snapshot'a dondurmak demektir. Bu karar **Sprint 3.1 sonrasında
> yeniden değerlendirilebilir** (o zaman kural kaldırılmaz, alan korunumuna **koşullu** hale gelir).
> Uygulama planı: `Sprint_3_0_Technical_Design.md` §5.
>
> **Revizyon 2 (2026-07-21) — alınan kararlar:** ① T2 prod'da ölçüldü → **0 örtüşme** (§9.1-T2) ·
> ② HeizkostenV: oda bazlı tüketim dağıtımı **kapsam dışı**, m² + görünür Hinweis, **Professional Review
> Required** (§6.3) · ③ Gesamtschuldnerische WG **kapsam dışı — onaylandı** (§1.2-A, §2.2) ·
> ④ Sprint planı buna göre daraltıldı (§10).

---

## 0. En önemli tespit (önce bu okunmalı)

Kod incelemesi tek bir cümlede özetlenebilir:

> **Borç zinciri (Mietkonto · Mahnung · Payment Service · Exception Engine) zaten tenancy seviyesindedir ve WG'ye bugünden hazırdır. Kırılan şey, "1 Unit = 1 tenancy" varsayan UNIT SEVİYESİ TÜRETMELERDİR.**

Doğru çalışanlar (tenancy-seviye oldukları için): `monat_soll` / `month_open` / `open_debt`
(`immo_rules.py:93,235`, `immo_payments.py:248`) · `/tenancies/{tid}/mietkonto` (`immo_api.py:334`) ·
Mahnung tutarı ve PDF kalemleri (`immo_api.py:1691-1716`) · `ImmoRent.tenancy_id` (`models.py:976`;
`unit_id` kolonu **yok**) · `ImmoMahnung.tenancy_id` (`models.py:1127`) · `/immo/mieter` feed satırları
(`immo_api.py:231-268`) · NK'nın `vorauszahlung()`'u (`immo_nebenkosten.py:587`).

**Ve ikinci, daha rahatsız edici tespit:**

> **Aynı Unit'te iki eşzamanlı tenancy bugün DE mümkün — sadece desteklenmiyor, hiçbir yerde de engellenmiyor.**
> `create_tenancy` / `update_tenancy` (`immo_api.py:1047-1104`) çakışan `von/bis` için hiçbir doğrulama yapmaz.
> Yani aşağıdaki hataların bir kısmı Faz 3 beklenmeden, bugün, **sessizce** üretilebilir.

Bu, Faz 3'ün ilk sprintinin neden bir *özellik* değil bir *doğruluk* sprinti olması gerektiğini belirler (§10).

---

## 1. Problem tam olarak nedir?

### 1.1 Çözülen kullanıcı senaryoları

Roadmap §3'teki 8 ve 9 numaralı satırlar:

| # | Senaryo | Bugünkü durum |
|---|---|---|
| 8 | **WG (Wohngemeinschaft)** — bir dairede birden çok **bağımsız** sözleşme | ❌ ifade edilemiyor |
| 9 | **Zimmervermietung** — oda-oda: farklı kira, farklı sözleşme, farklı ödeme, farklı Mahnung | ❌ ifade edilemiyor |

Somut ev sahibi cümlesi: *"3 odalı 90 m² dairemi öğrencilere oda oda kiralıyorum. Her odanın ayrı sözleşmesi, ayrı kirası var. Biri ödemezse sadece ona Mahnung göndermek istiyorum. Nebenkostenabrechnung'da her biri kendi payını görmeli."*

### 1.2 Almanca hukuki ayrım — bu belgenin kapsamını belirler

Almanya'da "WG" iki farklı hukuki yapıyı anlatır ve **ikisi aynı şey değildir**:

| Biçim | Yapı | Bu fazda? |
|---|---|---|
| **A — Gesamtschuldnerische WG** | TEK sözleşme, birden çok kişi müştereken sorumlu (Gesamtschuldner). Kira tektir; ev sahibi tamamını herhangi birinden isteyebilir. | ❌ **KAPSAM DIŞI — ONAYLANDI (2026-07-21).** Bugün zaten modellenebilir: bir tenancy, `mieter_name` içinde birden çok isim. **Her tenancy kendi borcundan sorumludur; Payment Service, Mahnung ve Single Ledger bu fazda değişmez.** İleride değerlendirilmek üzere ayrı **backlog** maddesi (§2.2). |
| **B — Einzelmietverträge / Zimmervermietung** | Oda başına AYRI sözleşme, ayrı kira, ayrı borç, ayrı Mahnung. | ✅ **EVET** — Faz 3 tam olarak budur. |

Bu ayrım kapsamı dramatik biçimde daraltır ve tasarımı basitleştirir: **Faz 3 = aynı Unit içinde N adet bağımsız, eşit statülü tenancy.** Aralarında hiyerarşi yoktur (bu Faz 2'nin Untermieter'inden farklıdır).

### 1.3 Bugün ne oluyor? (kullanıcının gerçek davranışı)

İki kaçış yolu var, ikisi de zararlı:

1. **Sahte Unit açmak** (Sprint 2.1'in Seçenek B'sinin yan etkisi): 90 m² daire "Zimmer 1 / Zimmer 2 / Zimmer 3" adıyla üç Unit olur. Ev sahibi `wohnflaeche` alanlarını elle böler — **böler***se***.* Bölmezse bina toplam alanı 270 m² sanılır, **binadaki tüm diğer kiracıların NK payı bozulur.** Roadmap bu tuzağı zaten kayda geçmiş: madde 10 "çift-sayım (yaşanan 340 vs 228 hatası)" ve backlog'daki **Doppel-Wohnung Guardrail**.
2. **Tek Unit'e iki tenancy girmek** (bugün API izin veriyor): §0'daki sessiz yanlış hesaplar.

Yani Faz 3 "yeni özellik" olmaktan çok **var olan bir sessiz hatanın kapatılmasıdır**.

---

## 2. Kapsam

### 2.1 İçeride

1. Aynı `ImmoUnit` altında **birden çok eşzamanlı, bağımsız `ImmoTenancy`** — desteklenen, doğrulanan, hesaplanan bir durum haline gelir.
2. **Alan korunumu**: bir Unit'in `wohnflaeche`'si, içindeki tenancy'ler arasında paylaşılır; toplam asla aşılamaz.
3. Unit seviyesi türetmelerin çoklu tenancy'ye göre düzeltilmesi: property/portföy **Soll**, **Belegung**, **Leerstandsverlust**, cockpit skoru.
4. **NK motorunda ağırlık normalizasyonu**: `wohnflaeche` ve `wohneinheiten` anahtarlarında Unit'in bir kereden fazla sayılmaması.
5. **Verbrauch** anahtarının paylaşımlı Unit'te tanımlı ve **görünür** bir davranışa kavuşması.
6. Oda başına ayırt edicilik: Mahnung / WGB / Mietkonto'da kiracının hangi odada olduğunun görünmesi.
7. Wohnung Akte'nin (bugün tek kiracı gösteren `akteActiveTen`, `index.html:3939`) N kiracıyı göstermesi.
8. **Çakışma guardrail'i**: aynı Unit'te örtüşen tenancy oluşturulurken ev sahibinin ne yaptığını bilerek onaylaması.

### 2.2 Kesinlikle dışarıda

| Konu | Neden dışarıda |
|---|---|
| **Gesamtschuldnerische WG** (tek sözleşme, çok kişi) | **KAPSAM DIŞI — ONAYLANDI (2026-07-21).** §1.2-A: bugün zaten modellenebilir. Bağlayıcı sonuç: her tenancy kendi borcundan sorumludur → **Payment Service değişmez · Mahnung değişmez · Single Ledger değişmez.** → **BACKLOG:** "WG-Mitmieter — ikinci sözleşme tarafının adı/iletişimi (salt bilgi, borç mimarisine dokunmadan)". Bu madde bir faza atanmamıştır; roadmap §7'deki üç kriter kapısından geçerse değerlendirilir |
| **Aynı Unit'te Untermieter (parent-child)** | Faz 4. `_validate_parent`'ın aynı-Unit reddi (`immo_api.py:883-884`) Faz 3'te **korunur** — WG, `typ=haupt` bağımsız sözleşmelerdir |
| **Eigennutzung + kiracı aynı dairede** (roadmap madde 10 karışık hâl) | Faz 4. Bugün de modellenemiyor (`immo_nebenkosten.py:566-571` → Eigennutzung payı 0 çıkar) |
| **Oda başına fiziksel sayaç** (`ImmoZaehlerstand.tenancy_id`) | Faz 4+. Gerçek WG'lerin çoğunda oda başına sayaç fiziksel olarak yoktur (§6.3) |
| **HeizkostenV §7 kural değişikliği** | Ayrı hukuki sprint; `.claude/nk_architecture.md` → D3 zaten bunu ertelemiş |
| **Yeni hiyerarşi / `ImmoRoom` tablosu** | Roadmap §8: "Yeni hiyerarşi KURULMAZ" (§7'de gerekçesiyle reddedildi) |
| **Ortak alan (Gemeinschaftsfläche) modeli** | Faz 4 (roadmap "Faz 4 — Gelişmiş Nebenkosten") |
| **Mietvertrag/Kündigung üretimi, SEPA** | Masterplan'da ayrı maddeler (#9/#11/#12) |
| **Geriye dönük veri düzeltme (backfill)** | Yok. Mevcut sahte-Unit kurulumları olduğu gibi çalışmaya devam eder; taşıma aracı bu fazda yazılmaz |

---

## 3. Muhasebe — Single Ledger korunabilir mi?

## ✅ **Evet, hem de değişiklik gerektirmeden.**

Sebep §0'da: ekonomik olay (bir kira sözleşmesinin aylık borcu ve ödemesi) zaten **tenancy** düzeyinde temsil ediliyor. WG bu düzeye yeni bir olay eklemiyor; sadece **aynı Unit altında daha fazla tenancy** demek.

Kanıt:

| Katman | Bağlı olduğu seviye | Referans |
|---|---|---|
| Ödeme kaydı | tenancy (`ImmoRent.tenancy_id`; **`unit_id` kolonu yok**) | `models.py:974-986` |
| Exception state | tenancy (`ImmoTenancy.offene_monate`) | `models.py:927` |
| Borç türetme | tenancy (`open_debt(user, t, as_of)`) | `immo_payments.py:248` |
| Aylık Soll | tenancy (`monat_soll(t, y, m)`) | `immo_rules.py:93` |
| Mahnung | tenancy (`ImmoMahnung.tenancy_id` NOT NULL) | `models.py:1127` |
| NK Vorauszahlung | tenancy (`monat_nk_soll` üzerinden — Principle C) | `immo_nebenkosten.py:587` |

**Faz 3'te Payment Service'e, Exception Engine'e, `immo_rules.py`'ye tek satır dokunulmaz.** Bu, CLAUDE.md'deki
"Every payment enters the system exactly once / Debt is derived only from the Exception Engine" yasasının
zaten sağlanmış olması demektir.

**Tehlike nerede:** Single Ledger'ı bozacak tek şey, "WG için Unit seviyesinde bir toplam borç" kavramı icat
etmek olurdu (ör. "daire toplamda 900 € borçlu"). **Bu yasaktır.** Unit seviyesinde görülen her sayı, tenancy
sayılarının **salt-okunur türevi** olmak zorundadır (CLAUDE.md yasası #2 ve #4).

---

## 4. Mietkonto — Unit bazlı mı, tenancy bazlı mı, hybrid mi?

## Karar önerisi: **Tenancy bazlı kalır. Unit seviyesi yalnızca salt-okunur bir GÖRÜNÜM'dür.**

| Seçenek | Artı | Eksi | Karar |
|---|---|---|---|
| **A — Tenancy bazlı (bugünkü)** | Single Ledger korunur · sıfır kod değişikliği · her sözleşmenin kendi hesabı, Zimmervermietung'un doğası bu · Mahnung/ödeme zaten burada | Ev sahibi "bu daire toplamda ne durumda?" sorusunu tek ekranda göremez | ✅ **Seçilen** |
| **B — Unit bazlı defter** | "Daire bazlı" tek rakam | ❌ İkinci defter yaratır → CLAUDE.md yasası #1/#5 ihlali · ödemenin hangi sözleşmeye ait olduğu kaybolur · Mahnung kime gidecek belirsizleşir · geriye dönük uyumsuz | ❌ Reddedildi |
| **C — Hybrid (hem unit hem tenancy defteri)** | Her iki soruyu da cevaplar | ❌ İki defter = iki gerçek. "Contradicting legacy flows" yasağının tam tanımı · mutabakat (reconciliation) kodu gerekir · en pahalı ve en kırılgan seçenek | ❌ Reddedildi |

**Uygulama sonucu (Faz 3):** `/tenancies/{tid}/mietkonto` (`immo_api.py:334`) **aynen kalır**. Wohnung Akte
ekranı, o Unit'teki aktif tenancy'lerin listesini gösterir ve her biri kendi Mietkonto'suna götürür; ekranda
görülebilecek "toplam açık" rakamı, tenancy borçlarının **görsel toplamıdır**, saklanmaz, bir endpoint'e
yazılmaz, Mahnung üretmez.

---

## 5. Mahnung — kim borçlu, kim uyarılır, kim ödedi sayılır?

**Cevap üçü için de aynı: SÖZLEŞME (tenancy).** Faz 3 bu davranışı değiştirmez, sadece görünürlüğü düzeltir.

- **Kim borçlu?** Her tenancy kendi `monat_soll`'undan sorumlu. Zimmervermietung'da oda kiracıları arasında
  müşterek sorumluluk **yoktur** (§1.2-B). A biçimi (Gesamtschuldner) kapsam dışı olduğu için bu fazda
  "diğerinden isteyebilme" mantığı **kurulmaz**.
- **Kim uyarılır?** Yalnız borçlu tenancy. `POST /tenancies/{tid}/mahnung` (`immo_api.py:1675`) değişmez.
- **Kim ödedi sayılır?** Ödemenin yazıldığı tenancy. `reconcile_month` (`immo_payments.py:96`) değişmez.
  **Bir odanın ödemesi başka odanın borcunu kapatamaz** — bu, Payment Service'in bugünkü davranışıdır ve
  korunması Faz 3'ün açık bir güvencesidir.

**Düzeltilmesi gereken tek şey — adresleme:** Mahnung PDF'i bugün alıcı bloğunda `Wohnung: {u.name}` yazıyor
(`immo_api.py:1710-1712`). Üç oda kiracısı **aynı daire adını** görür; mektup hangi odaya ait belli olmaz.
Aynı sorun Wohnungsgeberbestätigung'da da var: "Lage: `u.name`" (`immo_api.py:1644-1657`) — ve WGB §19 BMG
belgesi olduğu için bu sadece kozmetik değil (§9.2).

**Öneri:** tenancy üzerinde opsiyonel bir **`zimmer`** etiketi (§7) → PDF'te `Wohnung: 2.OG links · Zimmer 2`.
Yeni hesap kuralı değil, saf gösterim.

---

## 6. Nebenkosten — en kritik bölüm

### 6.1 Bugün ne kırık (ölçülmüş, varsayım değil)

NK motorunun **iskeleti çoklu tenancy'ye zaten açık**: `active` bir listedir (`immo_nebenkosten.py:434`),
`_area_person_weights` unit içindeki her tenancy için döner (`:371`), `_assign_line` tenancy başına satır
üretir (`:392`). Kırılan şey **ağırlığın kendisidir**:

| # | Kırılma | Referans | Sonuç |
|---|---|---|---|
| K1 | `basis_weight("wohnflaeche")` her tenancy'ye **Unit'in TAM alanını** verir | `immo_nebenkosten.py:249` + `:371-374` | 60 m² daire, 2 kiracıyla binada **120 m²** gibi davranır. `total_w` şişer → **binadaki DİĞER dairelerin payı azalır**, WG dairesi 2× yüklenir. Tek daireli binada tesadüfen doğru çıkar → hata **sessiz** |
| K2 | `basis_weight("wohneinheiten")` **kiracı** sayar, birim değil | `immo_nebenkosten.py:240-241` | 2 kiracılı daire 2 Einheit → Müll/Hausmeister/Allgemeinstrom dağılımı yanlış |
| K3 | `verbrauch` aynı sayaç farkını **her kiracıya tam** yazar | `immo_nebenkosten.py:340-345` | Unit tüketimi 2× sayılır; `rem = max(0, u_total − assigned)` negatifi 0'a kırptığı için (`:346`) fark **sessizce yutulur** |
| K4 | `ImmoZaehlerstand`'da `tenancy_id` yok; upsert anahtarı `(unit_id, art, datum)` | `models.py:1058-1069`, `immo_api.py:2534-2545` | Aynı Unit'te iki kiracı için iki ayrı Anfang/Ende **kaydedilemez** — ikincisi birincinin üstüne yazar |
| K5 | `_unit_vacant_zeitanteil` `min(1.0, Σ proration)` ile kırpar | `immo_nebenkosten.py:566-571` | 3 odadan 1'i boşken Unit "%100 dolu" sayılır → **boş odanın NK payı ev sahibine değil, diğer kiracılara** dağılır |
| K6 | `personenzahl` fallback'i agresif: aktif kiracılardan **birinde** eksikse tüm pozisyon Wohnfläche'ye düşer | `immo_nebenkosten.py:259-265` | WG'de kiracı sayısı arttıkça eksik-veri olasılığı artar; `muell` pratikte hep m²'ye kayar |
| K7 | Snapshot şeması tenancy başına pay bilgisi taşımıyor | `immo_nebenkosten.py:647-681` | Faz 3 alanı eklenirse `CALCULATION_VERSION` (`:34`) ve şema **mutlaka** değişmeli (Principle A) |

**Korunması gereken invariant (bugün geçerli, Faz 3'te de geçerli kalmalı):**
`Σ per_tenant.summe + eigennutzung + leerstand == umlagefaehige_summe` (`immo_nebenkosten.py:427-430`).
Dikkat: bu invariant K1–K5'e rağmen **bugün de sağlanıyor** — yani invariant yeşilken dağılım hukuken yanlış
olabiliyor. Faz 3 bu yüzden **ikinci bir invariant** gerektirir (§6.2).

### 6.2 Önerilen çekirdek: `anteil_flaeche` + alan korunumu

Roadmap zaten bu alanı Faz 3 için planlamış (`Flexible_Mietmodelle_Phase1.md:163`).

**Tanım:** `ImmoTenancy.anteil_flaeche` (FLOAT, nullable) = bu sözleşmenin Unit içinde kapladığı m²
(oda + ortak alan payı). **NULL = bugünkü davranış** (tenancy Unit'in tamamını kaplar).

**Ağırlık kuralı:**

```
anteil_ratio(t) = (t.anteil_flaeche / unit.wohnflaeche)  eğer anteil_flaeche doluysa
                = 1.0                                     eğer NULL ise   ← bugünkü davranış

wohnflaeche ağırlığı   : unit.wohnflaeche × anteil_ratio(t) × zeitanteil(t)
wohneinheiten ağırlığı : anteil_ratio(t)  × zeitanteil(t)          ← Unit toplamda ≤ 1 Einheit
personenzahl ağırlığı  : DEĞİŞMEZ (zaten tenancy alanı, models.py:937)
```

**Yeni hard invariant (alan korunumu):**

```
Her Unit ve her an için:   Σ anteil_flaeche(aktif tenancy'ler) ≤ unit.wohnflaeche
Dağıtılmayan alan          = unit.wohnflaeche − Σ anteil_flaeche  →  Leerstand / Eigennutzung kovası
```

Bu, K1 · K2 · K5'i aynı anda çözer ve K5'in sessiz hatasını **doğru tarafa** düzeltir: boş odanın payı
kiracılara değil, ev sahibine (Leerstand) yazılır — `.claude/nk_architecture.md` D1'deki
"Eigennutzung ≠ Leerstand, ikisi ayrı kova" kuralıyla tutarlı.

**Geriye dönük uyumluluk kanıtı:** tek tenancy'li Unit'te `anteil_flaeche` NULL → `anteil_ratio = 1.0` →
tüm formüller bugünkü değerlere **birebir** iner. Bu, Sprint 1.1/2.1'de kullanılan ve kanıtlanmış desendir.

### 6.3 Verbrauch — en zor karar

Fiziksel gerçek: **Alman WG'lerinin çoğunda oda başına su/ısı sayacı yoktur.** Dolayısıyla "her odanın kendi
Verbrauch'u" çoğunlukla **ölçülemez**. Üç seçenek:

| Seçenek | İçerik | Değerlendirme |
|---|---|---|
| **V1 — Sayacı tenancy'ye bağla** (`ImmoZaehlerstand.tenancy_id`) | Oda başına gerçek ölçüm | Fiziksel olarak nadiren mümkün · K4 için şema değişikliği · matris UI'si yeniden tasarlanır · **Faz 4'e ertelenmeli**, ama `anteil_flaeche` ile ileri-uyumlu |
| **V2 — Paylaşımlı Unit'te Verbrauch, Unit toplamı üzerinden anahtarla bölünür** (`anteil_flaeche`, yoksa `personenzahl`) + **görünür Hinweis** | Unit'in gerçek sayaç farkı **bir kez** alınır, tenancy'ler arasında paya göre bölünür | K3'ü çözer · mevcut şemayla çalışır · `.claude/nk_architecture.md` D3'teki "görünür not ile fallback" desenini birebir tekrarlar · **hukuki dayanak profesyonel onay gerektirir** (§9.2) | 
| **V3 — Paylaşımlı Unit'te Verbrauch anahtarını yasakla** | Kullanıcı bu kalemi m²/kişiye çevirmek zorunda | En güvenli ama en sert; ev sahibi neden yapamadığını anlamaz |

### 🔒 KARAR (ev sahibi, 2026-07-21) — V3'e yakın konservatif hat

> **Oda bazlı tüketim dağıtımı Faz 3 kapsamında DEĞİLDİR.**
> Paylaşımlı dairelerde (aynı Unit'te birden çok aktif tenancy) ısıtma/tüketim kalemleri **m² esas alınarak**
> dağıtılır — yani motorun bugün de yaptığı Wohnfläche davranışı, artık `anteil_flaeche` ile **doğru payda**
> üzerinden. Kullanıcıya **görünür bir Hinweis** gösterilir.
> **PROFESSIONAL REVIEW REQUIRED:** oda bazlı (V2/V1) tüketim bölmesi, profesyonel **hukuki/muhasebe onayı
> gelene kadar uygulanmayacaktır.** Bu madde tasarımda bilinçli olarak **açık** bırakılmıştır.

**Kararın gerekçesi:** V2 yeni bir bölme *yöntemi iddia eder* ve bu iddia finalize edildiğinde
`ergebnis_snapshot`'a **donar** (Principle A); geri alınması Unlock gerektirir. Mevcut m²/Wohnfläche
davranışı ise yeni bir hukuki iddia değil, `.claude/nk_architecture.md` → D3'te zaten belgelenmiş ve canlıda
olan bir ertelemedir. Faz 3'ün asıl kazancı (alan korunumu) bu karardan bağımsız elde edilir.

**K3 (çift sayım) düzeltmesi AYNEN KALIR.** K3 bir yöntem tercihi değil, bir **hatadır**: bugün aynı sayaç
farkı her kiracıya tam yazılıyor ve fark `rem = max(0, …)` ile sessizce yutuluyor (`immo_nebenkosten.py:340-346`).
Faz 3'te Unit'in sayaç farkı **bir kez** alınır ve paylaşımlı Unit'te m² (`anteil_ratio`) ile bölünür.
Yani: **çift sayım düzeltilir, oda bazlı ölçüm iddiası kurulmaz.**

**Zorunlu şartlar:** (a) Unit toplamı bir kez türetilir — çift sayım yapısal olarak imkânsız hale gelir ·
(b) her etkilenen satırda Abrechnung'da **ve** PDF'te açık Hinweis ("Bu dairede oda başına sayaç yoktur;
tüketim payı Wohnfläche/Anteil anahtarına göre bölünmüştür") · (c) snapshot bölme yöntemini kayda geçirir.
Şart (b), `CLAUDE.md` → **"No hidden behaviour"** kuralının doğrudan gereğidir.

### 6.4 Karma dağıtım nasıl hesaplanmalı

Yeni bir "karma anahtar" **icat edilmez**. Bugünkü mimari zaten karmayı destekliyor: her `NkKostenposition`
kendi `schluessel`'ini taşır (`ALLOWED_SCHLUESSEL`, `immo_nebenkosten.py:116-131`), HeizkostenV §7 Grund/
Verbrauch bölmesi zaten var (`:502-516`). Faz 3'ün yaptığı tek şey, bu anahtarların **ağırlık tabanını**
`anteil_ratio` ile düzeltmektir. Yani:

- Grundsteuer / Versicherung / Hausmeister → `wohnflaeche` → `anteil_flaeche` ile bölünür
- Müll / Wasser → `personenzahl` → zaten tenancy seviyesinde doğru
- Heizung → HeizkostenV §7: Grundkosten payı `anteil_flaeche`; **Verbrauch payı da paylaşımlı Unit'te m² (`anteil_ratio`) üzerinden** — oda bazlı bölme §6.3 kararı gereği kapsam dışı (**Professional Review Required**)
- Allgemeinstrom → `wohneinheiten` → Unit artık ≤ 1 Einheit sayılır

---

## 7. Veri modeli — yeni tablo mu, yeni kolon mu?

| Seçenek | İçerik | Artı | Eksi | Karar |
|---|---|---|---|---|
| **A — `ImmoTenancy.anteil_flaeche` (FLOAT, null)** | Roadmap'in planı (`…Phase1.md:163`) | Additive/nullable · migration = boot-time ALTER (Sprint 1.1/2.1 deseni) · yeni hiyerarşi yok · NULL = bugünkü davranış | Odanın **adı** yok → Mahnung/WGB hâlâ ayırt edemez (§5) | 🟡 yeterli değil |
| **B — Yeni `ImmoRoom` tablosu** (`unit → rooms`, `tenancy.room_id`) | Gerçek oda varlığı | Oda adı/alanı tek yerde · ileride oda başına sayaç doğal · fiziksel gerçeğe en yakın model | ❌ **Yeni hiyerarşi** — roadmap §8 açıkça yasaklıyor · ~20 sorgu ve tüm UI etkilenir · boş oda / oda birleştirme gibi yeni kavramlar açar · Faz 3'ü tek sprinte sığmaz hale getirir | ❌ Reddedildi |
| **C — Sahte Unit (bugünkü kaçış yolu)** | Kod değişikliği yok | Sıfır efor | ❌ Alan çift sayımı (§1.3) · sayaçlar bölünemez · WGB/Mahnung yanlış daire gösterir · backlog'daki **Doppel-Wohnung Guardrail** tam olarak bunu önlemek için var | ❌ Reddedildi |
| **D — A + `ImmoTenancy.zimmer` (VARCHAR, null)** | Pay + serbest metin oda etiketi | A'nın tüm artıları · §5'teki adresleme sorununu tablo açmadan çözer · `zimmer` hiçbir hesaba girmez (Faz 2'nin `typ`/`parent` deseni: relationship/label-only) | Oda "varlık" değil etiket — iki tenancy aynı etiketi yazabilir (guardrail ile uyarılır) | ✅ **Önerilen** |

**Önerilen şema (Faz 3):**

| Kolon | Tip | Null | Anlam |
|---|---|---|---|
| `ImmoTenancy.anteil_flaeche` | `FLOAT` | ✅ | Bu sözleşmenin Unit içindeki m² payı. **NULL = tüm Unit** (bugünkü davranış) |
| `ImmoTenancy.zimmer` | `VARCHAR(60)` | ✅ | Salt etiket ("Zimmer 2", "Süd-Zimmer"). Hiçbir hesaba girmez; PDF/UI gösterimi |

**Yeni tablo yok · yeni hiyerarşi yok · silinen/yeniden adlandırılan kolon yok** → roadmap §8 ve §9 ile uyumlu.
`ImmoUnit.soll_miete` semantiği **değişmez** (Unit'in tam hedef kirası; `immo_api.py:1188,1299`).

---

## 8. UI — kullanıcı bunu karmaşıklaşmadan nasıl anlayacak?

**Bağlayıcı ilke önerisi: "Sessiz aktivasyon yok, ama gereksiz karmaşa da yok."**
WG kavramları **yalnızca** bir Unit'te birden fazla aktif tenancy varken görünür. 1 daire = 1 kiracı olan ev
sahibi (kullanıcıların ezici çoğunluğu) ekranında hiçbir değişiklik görmez.

| Ekran | Değişiklik | Not |
|---|---|---|
| Üç giriş formu (Form A · Form B · sihirbaz) | Opsiyonel `Zimmer` + `Anteil (m²)` alanları; yalnız Unit'te başka aktif tenancy varken veya kullanıcı "Zimmer/WG" kutusunu işaretlediğinde açılır | Sprint 2.1/2.2'de kanıtlanan desen: üç form **birebir aynı** davranmalı |
| Anteil alanı | Canlı yardım: "Wohnung 90 m² · dağıtılan 60 m² · kalan 30 m²" | Alan korunumunu **girerken** görünür kılar; ihlali kaydetmeden önce engeller |
| Kiracı kartı | `🚪 Zimmer 2 · 25 m²` rozeti (Faz 2'nin `🔗 Untermieter →` rozetiyle aynı dil) | Salt okunur |
| Wohnung Akte | "Aktueller Mieter" → **"Aktuelle Mietverhältnisse (3)"** listesi; her satır kendi Mietkonto/Mahnung'una | `akteActiveTen` (`index.html:3939`) bugün tek kiracı seçiyor — ikinci kiracı **görünmez**; bu bir doğruluk düzeltmesi |
| Belegung göstergesi | "%100 dolu" yerine "2/3 oda dolu · 30 m² boş" | K5'in kullanıcıya yansıması |
| Mahnung / WGB PDF | `Wohnung: 2.OG links · Zimmer 2` | §5 |

**Anlatım dili (`.claude/ux_voice.md` uyumlu):** "WG", "Anteil", "Umlageschlüssel" gibi terimler ev sahibinin
zaten bildiği kelimeler; icat edilmiş kavram (ör. "sub-unit", "alt birim") **kullanılmaz**.

---

## 9. Riskler

### 9.1 Teknik

| # | Risk | Seviye | Önlem |
|---|---|---|---|
| T1 | **Alan korunumu ihlali** → binadaki *diğer* kiracıların NK payı bozulur (K1) | 🔴 Yüksek | Sunucu tarafı hard doğrulama (`Σ anteil ≤ wohnflaeche`) + motorda invariant testi + UI'da canlı kalan-alan göstergesi |
| T2 | **Bugün zaten var olan çift tenancy verisi** — deploy anında hesapları *değiştirir* | ✅ **KAPANDI** (aşağıya bak) | Prod'da salt-okunur sayım yapıldı: **0 örtüşme** |
| T3 | Verbrauch çift sayımı (K3) | 🟠 Orta | §6.3: Unit toplamı **bir kez** alınır, m² ile bölünür; testte "iki kiracı → toplam == unit sayaç farkı" invariantı |
| T4 | Snapshot şeması ve `CALCULATION_VERSION` (Principle A) | 🟠 Orta | Şemaya `anteil_flaeche`/`zimmer` eklenir, versiyon 4→5; **eski final Abrechnungen snapshot'tan servis edildiği için etkilenmez** (`immo_api.py:2928-2937`) |
| T5 | Fraksiyonel Belegung'un cockpit skoruna sızması (`immo_api.py:1427-1437`) | 🟡 Düşük | Skor formülü aynı kalır; sadece girdi doğrulanır. Tek-tenancy'de değer birebir aynı olmalı (regresyon testi) |
| T6 | `act[0]` düzeltmesi rapor rakamlarını değiştirir | 🟡 Düşük | Değişim **düzeltmedir**; tek tenancy'de fark yok. Sürüm notunda açıkça duyurulur |
| T7 | Zähler matris UI'sinin paylaşımlı Unit'te yanıltması (K4) | 🟠 Orta | Faz 3'te sayaç **Unit seviyesinde kalır**; UI bunu açıkça söyler ("bu daire için tek sayaç") |
| T8 | Bugün örtüşme yok diye guardrail'in gereksiz görülmesi | 🟠 Orta | **Guardrail (U3) kapsamda kalır** — aşağıdaki ölçümün gerekçesine bak |

#### T2 — prod doğrulaması (kapandı)

**Ölçüm tarihi:** 2026-07-21 · **Yöntem:** production veritabanında **salt-okunur** SQL (yalnız `SELECT`;
hiçbir yazma yapılmadı), uygulama container'ı üzerinden çalıştırıldı. Sorgu, aynı `unit_id` altında
`von/bis` aralıkları **örtüşen**, silinmemiş tenancy çiftlerini sayar.

| Ölçüm | Değer |
|---|---|
| Aktif tenancy (silinmemiş) | **3** |
| Aktif unit (silinmemiş) | **3** |
| Aynı Unit'te örtüşen tenancy çifti | **0** |
| Etkilenen unit / kullanıcı | **0 / 0** |
| Bugün itibarıyla ikisi de yürürlükte olan çift | **0** |

**Sonuç:** T2 riski **sıfır**. Sprint 3.0 saf iyileştirmedir; deploy anında **hiçbir mevcut rakam değişmez**.
"Etkilenen mevcut kullanıcıları önceden bilgilendir" maddesi §10'dan kaldırılmıştır.

> ⚠️ **Bu sonucun geçerlilik sınırı (bilinçli kayıt):** ölçüm **yalnızca 2026-07-21 tarihli pilot veri seti**
> için geçerlidir — toplam 3 tenancy / 3 unit. Bu, *bugünkü* veri için kesin bir cevaptır; **gelecekteki
> kullanıcılar hakkında istatistiksel bir güvence değildir.** Ölçüm, kodlamadan önce **tekrarlanabilir**
> (aynı sorgu) ve 3.0 deploy'undan hemen önce tekrarlanmalıdır.
>
> **Bu nedenle guardrail (U3) kapsamda KALIR.** Gerekçe tam olarak budur: kullanıcı tabanı büyüdüğünde bu
> durumun **oluşmasını önceden yakalamak** istiyoruz. Bugün 0 olması guardrail'in değerini azaltmaz —
> aksine, guardrail'i *veri bozulmadan önce* ekleme fırsatı verir. Bugün API bu durumu hiç engellemiyor
> (`immo_api.py:1047-1104`, çakışma doğrulaması yok), yani ilk WG kullanıcısı sessiz yanlış hesapla
> karşılaşabilirdi.

### 9.2 Hukuki

> ⚠️ Bu bölüm hukuki görüş değildir. AutoTax hukuki/vergisel tavsiye vermez (`CLAUDE.md` → StBerG).
> Aşağıdakiler **profesyonel onay gerektiren açık sorulardır**; kodlamadan önce netleşmelidir.

| # | Konu | Soru |
|---|---|---|
| H1 | **NK Abrechnung'un biçimsel doğruluğu** (§556 BGB) | Oda başına ayrılmış bir Abrechnung, kiracının payını denetleyebileceği şekilde anlaşılır mı? Anahtar ve payda açıkça gösterilmeli |
| H2 | **HeizkostenV** ≥%50 tüketim kuralı | 🔒 **PROFESSIONAL REVIEW REQUIRED — açık.** Karar (2026-07-21): onay gelene kadar **oda bazlı tüketim dağıtımı uygulanmaz**; paylaşımlı dairede m² esas alınır + görünür Hinweis (§6.3). Onaylanacak soru: oda başına sayaç yokken hangi bölme yöntemi (Ersatzverfahren) kabul edilebilir? |
| H3 | **Wohnungsgeberbestätigung §19 BMG** | Oda kiracısı için "Lage" alanına ne yazılmalı? Bugün Unit adı yazılıyor (`immo_api.py:1644-1657`) |
| H4 | **Mahnung'un muhatabı** | Zimmervermietung'da müşterek sorumluluk olmadığı varsayımı (§1.2-B) her sözleşme tipi için geçerli mi? |
| H5 | **Zweckentfremdung / oda kiralama izinleri** | Bazı şehirlerde oda-oda kiralama izne tabi. Ürün bunu **denetlemez**; sorumluluk ev sahibindedir — UI'da bilgilendirme gerekir mi? |

### 9.3 UX

| # | Risk | Önlem |
|---|---|---|
| U1 | **Karmaşıklık, çoğunluğa sızar** — 1 daire = 1 kiracı olan ev sahibi yeni alanlar görürse ürün "ağırlaşır" | §8'deki "sessiz aktivasyon yok" ilkesi: WG alanları yalnız gerektiğinde görünür |
| U2 | Ev sahibi `anteil_flaeche`'yi **yanlış anlar** (odanın net alanı mı, ortak alan payı dahil mi?) | Alan yanında tek cümlelik açıklama + toplam/kalan göstergesi. Boş bırakılabilir olması güvenlik supabıdır |
| U3 | **WG'yi yanlış senaryoda kullanma** — aslında ayrı daire olması gereken yerde | **Guardrail = HARD VALIDATION (Rev. 3):** aynı Unit'te tarih aralığı örtüşen ikinci tenancy **reddedilir** (400), override yok. Hata mesajı yol gösterir (ayrı Einheit / kiracı değişimiyse önce Auszug tarihi). Sprint 3.1'de kural kaldırılmaz, **alan korunumuna koşullu** hale gelir. Backlog'daki Doppel-Wohnung Guardrail ile aynı ailedendir |
| U4 | Üç formun yeniden ayrışması | Sprint 2.1'in dersi: her form değişikliği üçünde de aynı anda yapılır, aksi hâlde "iki ekran farklı gerçek söyler" |

---

## 10. Sprint planı — tek sprint mi, bölünmeli mi?

## Öneri: **Tek sprint DEĞİL. Dört küçük sprint (3.0 → 3.3).**

Gerekçe: NK ağırlıkları ile borç türetmeleri **farklı risk sınıflarında**. NK hatası *hukuki* sonuç doğurur ve
snapshot'a donar; rapor hatası *görsel*tir. Bunları aynı commit'e karıştırmak, Sprint 2.1'de kaçındığımız
"büyük değişiklik + zayıf kanıt" durumunu yaratır. Ayrıca **3.0 tek başına bugünkü bir hatayı düzeltir** ve
diğerleri onaylanmasa bile değer üretir.

### Sprint 3.0 — "Sessiz yalanı durdur" (yeni özellik YOK)
Aynı Unit'te birden çok tenancy **bugün de mümkün** olduğu için (API çakışmayı engellemiyor), mevcut yanlış
türetmeler önce düzeltilir. Prod'da bugün örtüşen kayıt **yok** (§9.1-T2) → bu sprint **saf iyileştirmedir**,
hiçbir mevcut rakamı değiştirmez.
Kapsam: `act[0]` → tüm aktif tenancy'lerin toplamı (`immo_api.py:1185`, `:1292`) · Wohnung Akte'nin N kiracı
göstermesi (`index.html:3939`) · aynı Unit'te örtüşen tenancy için **guardrail = hard validation** (Rev. 3, U3).
**Şema değişikliği yok. NK motoruna dokunulmaz.**
**DoD:** tek tenancy'li tüm senaryolarda rakamlar **birebir aynı** (SHA256 snapshot testi) · iki tenancy'li
**sentetik** senaryoda property Soll = iki tenancy'nin toplamı · guardrail yanlış kullanımı yakalıyor ·
T2 sayımı deploy'dan hemen önce **tekrarlanmış** ve hâlâ 0 · suite yeşil · deploy + prod smoke.

### Sprint 3.1 — Veri modeli + alan korunumu + NK ağırlıkları (fazın kalbi)
Kapsam: `anteil_flaeche` + `zimmer` kolonları (additive/nullable) · sunucu doğrulaması
(`Σ anteil ≤ wohnflaeche`) · NK'da `wohnflaeche` ve `wohneinheiten` ağırlıklarının `anteil_ratio` ile
normalize edilmesi (K1, K2) · dağıtılmayan alanın Leerstand/Eigennutzung kovasına gitmesi (K5) ·
`CALCULATION_VERSION` 4→5 + snapshot şeması (T4) · üç formda UI.
**Verbrauch bu sprintte DEĞİŞMEZ** (K3 açık kalır, görünür not ile).
**DoD:** `anteil_flaeche` NULL olan her mevcut kayıtta NK sonucu **byte-identical** · alan korunumu invariant
testi · `Σ tenant + Eigennutzung + Leerstand == umlagefähig` invariantı korunuyor · eski final Abrechnungen
snapshot'tan aynen servis ediliyor · üç form birebir aynı davranıyor.

### Sprint 3.2 — Verbrauch çift sayımı + Zähler şeffaflığı (DARALTILDI)
§6.3 kararı gereği bu sprint **yöntem değiştirmez**, yalnız **hatayı düzeltir ve görünür kılar**:
Kapsam: **K3 düzeltmesi** — Unit'in sayaç farkı **bir kez** türetilir, paylaşımlı Unit'te m² (`anteil_ratio`)
ile bölünür · her etkilenen satırda **görünür Hinweis** · Zähler matris UI'sinin paylaşımlı Unit'te ne
anlama geldiğini açıkça söylemesi ("bu daire için tek sayaç") · snapshot'a kullanılan bölmenin yazılması.
**Kapsam DIŞI:** oda bazlı tüketim dağıtımı (V1/V2) — **Professional Review Required**, onay gelene kadar
açılmaz. Bu nedenle `ImmoZaehlerstand` şeması **değişmez**.
**DoD:** "iki kiracı → toplam tüketim == Unit sayaç farkı" invariant testi · Hinweis Abrechnung'da ve PDF'te
görünüyor · tek tenancy'de davranış **birebir** değişmemiş · H2 profesyonel onay talebi **kayıtlı ve açık**.

### Sprint 3.3 — Belgeler + kapanış
Kapsam: Mahnung/WGB'de `Zimmer` gösterimi (§5) · Belegung göstergesinin "2/3 oda dolu" hâli ·
Faz 3 kapanış raporu. *(Guardrail 3.0'a alındı — veri bozulmadan önce devrede olması gerekiyor.)*
**DoD:** PDF'lerde oda ayırt ediliyor · prod smoke: gerçek bir WG kurulumu uçtan uca
(3 sözleşme → 3 Mietkonto → 1 Abrechnung → 3 farklı pay) · `SPRINT.md` kapanışı.

**Her sprint için ortak DoD (CLAUDE.md 8 madde):** kod · testler · UX · çelişen legacy akış yok · review ·
deploy · prod smoke · kullanıcı gözünden kritik boşluk yok. Ve fazın tamamı için bağlayıcı:
**`anteil_flaeche` NULL iken sistem bugünkü sistemle byte-identical davranır.**

---

## 11. Recommendation — en güvenli mimari

### Önerilen mimari (özet)

1. **Muhasebe hiç açılmaz.** Payment Service, Exception Engine, `immo_rules.py`, Mietkonto ve Mahnung akışı
   Faz 3'te **değişmez**. WG, defter mimarisi değil, **dağıtım (allocation) ve raporlama** problemidir.
2. **Veri modeli: iki additive/nullable kolon** — `ImmoTenancy.anteil_flaeche` + `ImmoTenancy.zimmer`
   (Seçenek D, §7). Yeni tablo yok, yeni hiyerarşi yok, `ImmoUnit` semantiği değişmez.
3. **Tek yeni hard invariant:** *alan korunumu* — `Σ anteil_flaeche(aktif) ≤ unit.wohnflaeche`; artan alan
   Leerstand/Eigennutzung kovasına. Bu tek kural K1, K2 ve K5'i birlikte çözer.
4. **Verbrauch: hatayı düzelt, yöntem iddia etme.** Unit toplamı **bir kez** alınır (K3 hatası kapanır) ve
   paylaşımlı dairede **m² (`anteil_ratio`) ile** bölünür; her satıra Hinweis basılır. **Oda bazlı dağıtım
   Faz 3 kapsamında değildir — Professional Review Required (§6.3, H2).** Oda başına sayaç Faz 4'e ertelenir;
   `anteil_flaeche` bu geçişi bozmaz.
5. **Geriye dönük uyumluluk yasası:** `anteil_flaeche` NULL → sistem **bugünkü sistemle birebir aynı**.
   Bu, Sprint 1.1 ve 2.1'de iki kez kanıtlanmış ve prod'da doğrulanmış desendir.
6. **Sıralama: 3.0 → 3.1 → 3.2 → 3.3**, her biri bağımsız deploy edilebilir; 3.0 tek başına bugünkü bir
   hatayı kapatır.

### Reddedilen alternatifler ve gerekçeleri

| Alternatif | Neden reddedildi |
|---|---|
| **Unit bazlı veya hybrid Mietkonto** (§4-B/C) | İkinci defter yaratır. CLAUDE.md Architecture law #1/#2/#5 doğrudan ihlali. Ödemenin hangi sözleşmeye ait olduğu ve Mahnung'un muhatabı belirsizleşir. Kazanılan tek şey ("daire toplamı"), salt-okunur bir görünümle bedelsiz elde edilebiliyor. |
| **`ImmoRoom` tablosu** (§7-B) | Yeni hiyerarşi kurar; roadmap §8 açıkça yasaklıyor. Boş oda, oda birleştirme, oda-tenancy yaşam döngüsü gibi bir dizi yeni kavram açar ve fazı tek belgeye sığmayacak boyuta çıkarır. **Kapı kapanmıyor:** `anteil_flaeche` ileride oda tablosuna taşınabilir; tersi (önce tablo, sonra basitleştirme) mümkün değil. |
| **Sahte Unit'lerle devam** (§7-C) | Alan çift sayımı → binadaki *diğer* kiracıların Abrechnung'unu bozar; bu, ürünün en pahalı hata sınıfı (hukuki). Roadmap madde 10'daki 340↔228 olayı tam olarak budur. |
| **Oda bazlı tüketim dağıtımı — V2** (§6.3, şimdi) | **Ertelendi (karar 2026-07-21).** Yeni bir bölme yöntemi *iddia eder* ve finalize edilince snapshot'a donar (Principle A); geri alınması Unlock gerektirir. **Professional Review Required** — hukuki/muhasebe onayı gelene kadar açılmaz. Onay gelirse ayrı bir sprintte eklenebilir; `anteil_flaeche` bu kapıyı açık tutar. |
| **Oda başına sayaç zorunluluğu** (§6.3-V1, şimdi) | Fiziksel gerçekle çelişir — çoğu WG'de oda sayacı yoktur. Kullanıcıyı veri uydurmaya iter. Faz 4+. |
| **Verbrauch'u paylaşımlı Unit'te tamamen yasaklamak** (§6.3-V3, saf hâli) | Ev sahibi "neden yapamıyorum" sorusuna cevap alamaz. Seçilen hat V3'ün *yumuşak* hâlidir: kalem çalışır, m² ile bölünür, **neden öyle bölündüğü açıkça yazılır**. |
| **Faz 3'ü tek sprint yapmak** (§10) | NK (hukuki, snapshot'a donuyor) ile raporlama (görsel) aynı risk sınıfında değil. Tek sprint, kanıt üretimini zayıflatır ve rollback'i büyütür. |
| **Aynı Unit'te Untermieter'i (Faz 4) buraya çekmek** | Kapsam genişlemesi. `_validate_parent`'ın aynı-Unit reddi (`immo_api.py:883-884`) Faz 3'te korunur; WG bağımsız sözleşmelerdir, hiyerarşi değil. |

### Kodlamadan önceki üç soru — durum (2026-07-21)

| # | Soru | Durum |
|---|---|---|
| 1 | **T2** — Prod'da aynı Unit'te örtüşen aktif tenancy var mı? | ✅ **CEVAPLANDI**: 3 tenancy / 3 unit / **0 örtüşme** (§9.1-T2). Yalnız bugünkü pilot veri seti için geçerli; deploy öncesi tekrarlanacak |
| 2 | **H2** — HeizkostenV bölmesi (oda sayacı yokken) | 🔒 **AÇIK — Professional Review Required.** Karar: onay gelene kadar oda bazlı dağıtım **uygulanmaz**; m² + görünür Hinweis (§6.3) |
| 3 | **§1.2-A** — Gesamtschuldnerische WG kapsam dışı mı? | ✅ **ONAYLANDI — kapsam dışı.** Her tenancy kendi borcundan sorumlu; Payment Service · Mahnung · Single Ledger değişmez. Backlog maddesi açıldı (§2.2) |

---

## Onay

Bu belge **yalnızca mimari analizdir**. Kod, commit, migration ve implementasyon planı **yoktur**.
Üç sorudan ikisi kapandı; **H2 bilinçli olarak açık** bırakıldı ve Faz 3'ün hiçbir sprintini bloke etmiyor
(§6.3 kararı sayesinde). Sonraki adım: onay üzerine **Sprint 3.0** için ayrı teknik tasarım belgesi.
