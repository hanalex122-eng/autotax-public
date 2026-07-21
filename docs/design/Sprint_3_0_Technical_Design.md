# Sprint 3.0 — Teknik Tasarım Belgesi (Design Only)

> **Belge türü:** Uygulama planı. **KOD YOK · MIGRATION YOK · COMMIT/PUSH/DEPLOY YOK.**
> **Referans (bağlayıcı):** `docs/design/Phase3_WG_Zimmervermietung.md` (ADD Rev. 2) — kararları bu belge **değiştirmez**, uygulamaya çevirir.
> **Üst belgeler:** `VERMIETER_MASTERPLAN.md` · `CLAUDE.md` (Architecture law) · `SPRINT.md` · `.claude/nk_architecture.md`
> **Tarih:** 2026-07-21 · **Durum:** onay bekliyor

> ✅ **Kararlar alındı (2026-07-21):**
> **(1) Guardrail = HARD VALIDATION** — örtüşen tenancy oluşturulması **engellenir**; override yok,
> sadece-uyarı yok. ADD **Revision 3** olarak güncellendi. Sprint 3.1 sonrasında yeniden değerlendirilebilir.
> **(2) Wohnung Akte'de "Toplam Açık" gösterilir** — salt-okunur, **UI'da hesaplanan** değer:
> DB'ye yazılmaz · endpoint değişmez · Mahnung üretmez · ledger değişmez · **N=1 görünümü korunur**.
> **(3) §4/§6 kapsamı** — `anteil_flaeche` ADD'ye göre **Sprint 3.1** işidir; 3.0'a alan eklenmez.
>
> **Terminoloji notu (kayıt doğruluğu için):** Sprint 3.0 aynı Unit'te çoklu tenancy desteğini
> **getirmez** — tam tersine, NK motoru bunu doğru hesaplayana kadar (3.1) **engeller**. 3.0'ın getirdiği
> şey, bugün zaten oluşabilen çoklu tenancy durumunda yanlış hesaplanan unit-seviye türetmelerin
> düzeltilmesi + bu durumun oluşmasının engellenmesidir. Guardrail kararının gerekçesi aynıdır.

---

# 1. Sprint Amacı

## 1.1 Tek cümlelik hedef

> **Bugün sessizce yanlış hesaplanan unit-seviye türetmeleri düzeltmek ve aynı Unit'te ikinci bir
> sözleşmenin fark edilmeden oluşmasını engellemek — hiçbir yeni özellik eklemeden, şemaya dokunmadan.**

Sprint 3.0 bir **doğruluk** sprintidir, WG özelliği değildir. WG desteği 3.1'de gelir.

## 1.2 Neleri çözüyor

| # | Sorun | Bugünkü davranış | 3.0 sonrası |
|---|---|---|---|
| P1 | **Property Soll eksik** | `soll_u += _monat_soll(act[0], …)` — unit-ay başına **yalnız ilk** aktif tenancy sayılır (`immo_api.py:1185`) | Tüm aktif tenancy'lerin toplamı |
| P2 | **Portföy Soll eksik** | Aynı `act[0]` hatası (`immo_api.py:1292`) | Tüm aktif tenancy'lerin toplamı |
| P3 | **Inkasso/score bozulur** | `ist` tüm tenancy'lerden, `soll` yalnız `act[0]`'dan → oran >100 çıkıp `min(100)` ile maskeleniyor (`immo_api.py:1428`) | Pay ve payda aynı kümeden gelir |
| P4 | **Rapor iç tutarsızlığı** | `zahlungsausfall` tüm tenancy'lerden ama `summe.soll_miete` `act[0]`'dan → "Rückstand > Soll" görülebilir (`immo_api.py:1213,1219`) | Tutarlı |
| P5 | **Wohnung Akte ikinci kiracıyı gizler** | `akteActiveTen` **tek** tenancy döndürür (`index.html:3939`); ikinci kiracının Mietkonto'su, borcu, Mahnung'u Akte'de **hiç görünmez** (`:3944, :4229`) | N aktif sözleşme listelenir |
| P6 | **Aynı Unit'e ikinci sözleşme sessizce açılabiliyor** | `create_tenancy` / `update_tenancy` çakışma doğrulaması **yapmıyor** (`immo_api.py:1047-1104`) | Guardrail (§5) |

**Ortak nitelik:** altısı da **bugün mevcut olan hatalardır**; Faz 3 beklenmeden tetiklenebilirler.
Prod'da bugün örtüşen kayıt olmadığı için (ADD §9.1-T2: 0) bu sprint **hiçbir mevcut rakamı değiştirmez**.

## 1.3 Neleri özellikle ÇÖZMÜYOR (3.0 kapsam dışı)

| Konu | Nereye |
|---|---|
| `anteil_flaeche` · `zimmer` kolonları, alan korunumu | **3.1** |
| NK ağırlık normalizasyonu (K1 `wohnflaeche` çift sayımı, K2 `wohneinheiten`, K5 Leerstand) | **3.1** |
| Verbrauch çift sayımı (K3) + Zähler şeffaflığı | **3.2** |
| Mahnung/WGB'de oda gösterimi, "2/3 oda dolu" göstergesi | **3.3** |
| Oda bazlı tüketim dağıtımı | **Professional Review Required** — açılmadı (ADD §6.3) |
| Gesamtschuldnerische WG | **Kapsam dışı — onaylandı** (ADD §1.2-A) |
| Aynı Unit'te Untermieter (parent-child) | **Faz 4** — `_validate_parent`'ın aynı-Unit reddi (`immo_api.py:883-884`) **korunur** |
| Belegung/Leerstand'ın alan-ağırlıklı hale gelmesi | **3.1** (fraksiyonel doluluk `anteil_flaeche` gerektirir) |

> ⚠️ **3.0'ın bilinçli asimetrisi:** P1–P5 düzeltilir ama **NK motoru düzeltilmez** (3.1). Yani 3.0
> sonrası aynı Unit'te iki tenancy olursa **Soll doğru, NK hâlâ yanlış** olur. Guardrail'in sertliği
> (§5) tam olarak bu boşluğu yönetmek içindir.

---

# 2. Ön Koşullar (Implementation Gates)

Aşağıdaki üç kapı **kod yazılmadan önce** yeşil olmalıdır. Kırmızı bir kapı = sprint başlamaz.

## Gate H4 — Mahnung varsayımı ✅ (karar verildi, 2026-07-21)

**Karar (bağlayıcı):**
- **Her tenancy kendi borcundan sorumludur.**
- **Bir tenancy = bir borç hesabı = bir Mahnung muhatabı.**
- **Payment Service değişmez.**
- **Mahnung değişmez.**
- **Single Ledger korunur.**

**Uygulama sonucu (bu sprintte kanıtlanacak):** `autotax/immo_payments.py`, `autotax/immo_rules.py`,
`autotax/immo_payment_repository.py`, `autotax/immo_payment_models.py` dosyalarında **tek satır değişiklik
olmayacaktır**. Bu, DoD'de `git diff --stat` ile kanıtlanır (§8, D9). Bir odanın ödemesi başka odanın
borcunu **kapatamaz**; bu davranış bugünkü `reconcile_month` (`immo_payments.py:96`) semantiğidir ve
regresyon testiyle kilitlenir.

**Not:** H4'ün hukuki tarafı (müşterek sorumluluk her sözleşme tipinde gerçekten yok mu?) ADD §9.2'de
**profesyonel onay** maddesi olarak duruyor. Ürün kararı olarak Gate H4 yeşildir; hukuki teyit
Zimmervermietung sözleşme metinleriyle ilgilidir ve 3.0'ın teknik kapsamını değiştirmez.

## Gate T2 — Deploy öncesi tekrar çalıştırılacak salt-okunur sorgu 🔁

**Bugünkü ölçüm (2026-07-21, production, salt-okunur SELECT):**

| Ölçüm | Değer |
|---|---|
| Aktif tenancy | **3** |
| Aktif unit | **3** |
| **Aynı Unit'te örtüşen aktif tenancy** | **0** |
| Etkilenen unit / kullanıcı | 0 / 0 |

> ⚠️ Bu sonuç **yalnızca bugünkü pilot veri seti için geçerlidir.** Gelecekteki kullanıcılar hakkında
> istatistiksel bir güvence değildir.

**Kural:** Bu sorgu **Sprint 3.0 deploy'undan hemen önce tekrar çalıştırılacaktır.**

| Sonuç | Aksiyon |
|---|---|
| **= 0** | Deploy devam eder. 3.0 saf iyileştirmedir; hiçbir mevcut rakam değişmez |
| **> 0** | 🛑 **DEPLOY DURUR.** Mimari yeniden değerlendirilir: etkilenen kayıtlar ev sahibiyle netleştirilir, değişecek rakamlar önceden çıkarılır, guardrail'in geçmişe dönük etkisi (§5) yeniden karara bağlanır |

**Sorgu (referans, salt `SELECT`):** aynı `unit_id` altında `von/bis` aralıkları örtüşen, silinmemiş
tenancy çiftleri — ADD §9.1-T2'deki sorgunun aynısı. Çalıştırma yolu: app container
(`railway ssh --service AutoTax-Hub`), çünkü Postgres servisinin PG* değişkenleri senkron değil
(`SPRINT.md` → BACKLOG → *[OPS] PGPASSWORD senkronsuzluğu*).

## Gate G1 — Guardrail kararı ✅ (karar verildi, 2026-07-21)

**Guardrail = HARD VALIDATION.** Aynı Unit'te tarih aralığı örtüşen ikinci tenancy'nin oluşturulması
**engellenir** (HTTP 400). **Override yok · sadece-uyarı yok.** ADD Revision 3'e işlendi.
Sprint 3.1 sonrasında yeniden değerlendirilebilir (kural kaldırılmaz, alan korunumuna koşullu hale gelir).
Uygulama: §5.3 şartları (dar kapsam · yol gösteren mesaj · geçmişe dönük değil · 3.1'de planlı gevşeme).

---

# 3. Etkilenecek Modüller

| Katman | Dosya | Değişiklik | Risk |
|---|---|---|---|
| **API — raporlama** | `autotax/immo_api.py:1182-1192` (`_accounting`) | `act[0]` → aktif tenancy'ler üzerinde toplam; `occ/vac` sayacı **aynı kalır** (ikili doluluk 3.1'e ait) | 🟡 |
| **API — portföy** | `autotax/immo_api.py:1289-1305` (`_portfolio`) | Aynı düzeltme; `occupied_now` / `vacant_now` **değişmez** | 🟡 |
| **API — validation** | `autotax/immo_api.py:1047-1114` (`create_tenancy`, `update_tenancy`) | Guardrail (§5). Yeni yardımcı: aynı Unit'te tarih örtüşmesi tespiti | 🔴 |
| **API — Akte verisi** | `autotax/immo_api.py` (`/units/{uid}/tenancies` zaten liste döndürüyor) | **Değişiklik gerekmiyor** — veri zaten çoklu; sorun frontend'de | 🟢 |
| **UI — Wohnung Akte** | `index.html:3939` (`akteActiveTen`), `:3944`, `:4229` | Tek tenancy seçimi → N aktif sözleşme listesi | 🟠 |
| **UI — tenancy formları** | `index.html` Form A (`ImmoTenancyForm`), Form B (`MieterView` satır-içi), sihirbaz (`saveErf`) | Guardrail hata/uyarı mesajının gösterimi — **üçünde de aynı** (Sprint 2.1'in dersi) | 🟠 |
| **Service** | `autotax/immo_payments.py`, `immo_rules.py`, `immo_payment_*.py` | ❌ **DEĞİŞMEZ** (Gate H4) | — |
| **NK motoru** | `autotax/immo_nebenkosten.py` | ❌ **DEĞİŞMEZ** (3.1) | — |
| **Model** | `autotax/models.py` | ❌ **DEĞİŞMEZ** (§4) | — |
| **Migration** | `autotax/db.py` | ❌ **GEREKMİYOR** — şema değişmiyor | — |
| **Test** | `tests/test_immo_sprint_3_0.py` (yeni), mevcut suite (46) | §7 | — |

**Dokunulmayacaklar (açık taahhüt):** `models.py` · `db.py` · `immo_payments.py` · `immo_rules.py` ·
`immo_payment_models.py` · `immo_payment_repository.py` · `immo_nebenkosten.py` · `immo_ledger.py`.

---

# 4. Veri Modeli

## 4.1 Değişen alanlar

**HİÇBİRİ.** Sprint 3.0 **şema değişikliği içermez** — yeni kolon yok, yeni tablo yok, migration yok
(ADD §10: *"Şema değişikliği yok. NK motoruna dokunulmaz."*).

## 4.2 Değişmeyen alanlar (ve neden bu sprintte yeterli)

| Alan | Durum | Not |
|---|---|---|
| `ImmoTenancy.unit_id` | Değişmez | Aynı Unit'e N tenancy zaten mümkün; kısıt yok |
| `ImmoUnit.wohnflaeche` · `soll_miete` | Değişmez | Semantik aynı: Unit'in tamamı |
| `ImmoRent.tenancy_id` · `ImmoMahnung.tenancy_id` | Değişmez | Borç zinciri zaten tenancy seviyesinde (ADD §0) |
| `ImmoTenancy.typ` · `parent_tenancy_id` | Değişmez | Faz 2 alanları; WG bunları **kullanmaz** (WG = bağımsız `haupt` sözleşmeler) |

## 4.3 3.1'e bırakılan alanlar (burada TANIMLANIR, EKLENMEZ)

Aşağıdakiler **bu sprintte eklenmez**; 3.0'ın UI ve API kararları bunlarla **ileri-uyumlu** olacak
şekilde tasarlanır (ör. guardrail mesajı "3.1'de oda payı girilebilecek" beklentisini bozmamalı):

| Alan | Tip | Sprint |
|---|---|---|
| `ImmoTenancy.anteil_flaeche` | `FLOAT`, null | **3.1** |
| `ImmoTenancy.zimmer` | `VARCHAR(60)`, null | **3.1** |

## 4.4 Backward compatibility nasıl korunur

1. **Şema dokunulmadığı için veri riski yok** — geri alma = kod revert.
2. **Tek tenancy'li her senaryoda çıktı birebir aynı:** `Σ` bir elemanlı kümede `act[0]`'a eşittir.
   Bu, DoD'de **SHA256 snapshot testiyle** kanıtlanır (§7, R1).
3. **API sözleşmesi genişlemez:** `_accounting` / `_portfolio` yanıt şemaları **aynı kalır**; yalnız
   `soll` değerleri (çoklu tenancy varsa) düzelir.
4. **Guardrail yalnız YAZMA yollarını etkiler** (`POST/PATCH /immo/tenancies`); okuma yüzeyleri etkilenmez.
5. **Mevcut veri hiç dokunulmaz** — backfill yok, düzeltme script'i yok.

---

# 5. Guardrail (U3) — en önemli bölüm

## 5.1 Problem

Bugün `create_tenancy` (`immo_api.py:1047`) aynı Unit'te tarihleri örtüşen ikinci bir sözleşmeyi
**sessizce kabul ediyor**. Sonuç: kullanıcı hata yaptığını fark etmez, sistem yanlış NK üretir
(ADD §6.1 K1–K5) ve bu yanlış Abrechnung finalize edilirse **snapshot'a donar** (Principle A).

**3.0'ın özel durumu:** bu sprint P1–P5'i düzeltir ama **NK'yı düzeltmez**. Yani 3.0 sonrası aynı Unit'te
iki tenancy → **Soll doğru, NK yanlış**. Guardrail kararı bu boşluğu yönetmek zorundadır.

## 5.2 Seçenekler

### A) Hard validation — engelle (400)
Aynı Unit'te tarih aralığı örtüşen ikinci aktif tenancy **reddedilir**; hata mesajı yol gösterir
("Bu daire seçilen tarihlerde zaten kiralı. Ayrı bir daire (Einheit) açın — oda-oda kiralama yakında.").

| Artı | Eksi |
|---|---|
| Hesaplanamayan durum **hiç oluşmaz** → hatalı NK ve donmuş yanlış snapshot riski **sıfır** | Bugün API'nin izin verdiği bir şey yasaklanır — teknik olarak **kırıcı** bir API değişikliği |
| "No silent wrong numbers" ilkesinin en net uygulaması | 3.1'e kadar WG'yi *hiç* yapamama; ev sahibi sahte Unit'e yönelir (ADD §1.3'teki anti-pattern) |
| Prod'da örtüşme **0** olduğu için bugün **hiç kimse etkilenmez** (Gate T2) | 3.1'de kuralın **gevşetilmesi** gerekir → iki sprintte iki farklı davranış |
| Test edilmesi en kolay, davranışı en öngörülebilir | Meşru kenar durum: aynı gün taşınma (A çıkıyor, B giriyor) — **çözülebilir**, §5.4'e bak |

### B) Warning + Override — uyar, kullanıcı onaylarsa geç
Sunucu örtüşmeyi tespit eder, 409 + açıklama döner; istemci `confirm_overlap=true` ile tekrar gönderirse kabul edilir.

| Artı | Eksi |
|---|---|
| Kullanıcı özerkliği; meşru kenar durumlar bloke olmaz | Kullanıcı "devam"a basar → **yanlış NK üretilir**, üstelik *onayladığı* için sorumluluk ona geçmiş sayılır (ürün açısından savunulamaz) |
| 3.1'e geçiş yumuşak (override sonradan gereksizleşir) | Yeni bir API parametresi = kalıcı sözleşme yüzeyi |
| — | Onaylanan durum **sessiz değil ama yine de yanlış** — 3.0 NK'yı düzeltmiyor |

### C) Sadece uyarı — kaydet, sonra bilgi ver
Kayıt her hâlükârda oluşur; UI bir uyarı rozeti/mesajı gösterir.

| Artı | Eksi |
|---|---|
| En az kırıcı; hiçbir akış bozulmaz | Bugünkü sessiz hatanın **sadece kozmetik** olarak iyileştirilmiş hâli |
| Uygulaması en ucuz | Uyarı kapatılabilir/gözden kaçar; yanlış NK yine finalize edilebilir |
| — | ADD §9.1-T8'deki riski gerçekleştirir: guardrail "var" sanılır ama korumaz |

## 5.3 Öneri

## ✅ **A — Hard validation**, aşağıdaki dört şartla.

**Gerekçe:** 3.0, aynı Unit'teki iki sözleşmeyi **doğru hesaplayamıyor** (NK 3.1'de düzeliyor).
Hesaplayamadığımız bir durumu kabul etmek, kullanıcıya *sessizce yanlış* Abrechnung üretmek demektir;
üstelik finalize edilirse snapshot'a donar ve düzeltmesi Unlock gerektirir. B ve C bu sonucu **kullanıcı
onayıyla** ya da **uyarıyla** meşrulaştırır — ikisi de yanlış rakamı engellemez. Prod'da bugün örtüşme
**0** olduğu için (Gate T2) hard validation **hiç kimseyi** etkilemez; yani en güvenli seçenek aynı
zamanda en ucuz seçenektir. Bu, senin varsayılan tercihinle de örtüşür.

**Şartlar:**
1. **Kapsam dar:** yalnız *aynı `unit_id` + tarih aralığı örtüşmesi + silinmemiş*. Ardışık sözleşmeler
   (A çıkar, B girer) **etkilenmez**.
2. **Mesaj yol gösterir:** ne yapılamadığı + neden + alternatif (ayrı Einheit) + "oda-oda kiralama
   yakında" beklentisi. Hata metni üç formda da **aynı**.
3. **Geçmişe dönük değil:** mevcut kayıtlar hiç doğrulanmaz, hiç değiştirilmez. Kural yalnız yeni
   `POST/PATCH` isteklerinde işler.
4. **3.1'de planlı gevşeme:** 3.1'de `anteil_flaeche` gelince kural *kaldırılmaz*, **koşullu** hale
   gelir: örtüşme ancak alan korunumu sağlanıyorsa (`Σ anteil ≤ wohnflaeche`) kabul edilir. Bu, 3.0'ın
   kuralını 3.1'in invariantına **dönüştürür** — iki farklı davranış değil, aynı kuralın olgunlaşması.

> ⚠️ **ADD tadilatı gerektirir.** ADD Rev.2 §10, 3.0 için *"guardrail uyarısı (engelleme değil)"* diyor.
> Yukarıdaki öneri bunu **hard validation**'a çeviriyor. Bu değişiklik ancak senin açık onayınla yapılır;
> onaylarsan ADD §10 ve §9.3-U3 tek cümlelik bir Revision 3 notuyla güncellenir.

## 5.4 Kenar durumlar (A seçilirse ele alınacak)

| Durum | Beklenen davranış |
|---|---|
| Aynı gün taşınma: A'nın `bis` = B'nin `von` | **İzin verilir** — örtüşme tanımı "aynı gün bitiş/başlangıç"ı örtüşme saymaz (yarı-açık aralık) |
| `bis` boş (süresiz) iki sözleşme | Örtüşme → **reddedilir** |
| Silinmiş (`is_deleted`) tenancy | Hesaba katılmaz |
| Eigennutzung (`eigennutzung_personen`) + tenancy aynı Unit'te | **3.0'da dokunulmaz** — Faz 4 konusu, guardrail bunu kontrol etmez |
| PATCH ile tarih değiştirip örtüşme yaratma | Aynı kural PATCH'te de işler (`update_tenancy`) |
| Untermieter (Faz 2) | Zaten ayrı Unit zorunlu (`immo_api.py:883-884`); guardrail bununla çakışmaz |

---

# 6. UI Akışı

> **Not:** `anteil_flaeche` girişi **3.1**'e aittir (§4.3). 3.0'ın UI işi iki başlıktan ibarettir:
> **(a)** guardrail mesajı, **(b)** Wohnung Akte'nin N sözleşme göstermesi.

## 6.1 "WG oluşturma" — 3.0'daki gerçek akış

3.0'da WG **oluşturulamaz** (A seçilirse). Kullanıcı aynı daireye ikinci sözleşme eklemeye çalıştığında:

```
Ev sahibi → Mieter → ➕ Neuer Mieter (veya Form A / Form B)
   → Daire: "EG links" (zaten aktif kiracısı var)
   → Kaydet
        ↓  sunucu doğrulaması
   ⛔ "EG links dairesi 01.01.2026–devam arasında zaten kiralı (Ahmet Yilmaz).
       Bir dairede aynı anda birden çok sözleşme henüz desteklenmiyor.
       → Oda-oda kiralıyorsanız her oda için ayrı bir Einheit açın.
       → Kiracı değişikliğiyse önce eski sözleşmenin Auszug tarihini girin."
```

**Üç girişte de aynı:** Form A (`ImmoTenancyForm`), Form B (`MieterView` satır-içi), sihirbaz (`saveErf`).
Sprint 2.1'in dersi bağlayıcı: bir form farklı davranırsa "iki ekran farklı gerçek söyler".

## 6.2 Yeni tenancy — değişmeyen kısım

Alan seti, varsayılanlar, Untermieter davranışı (Faz 2), Zahler/Heizkosten (Faz 1) **aynen kalır**.
3.0 hiçbir alan eklemez/çıkarmaz.

## 6.3 Wohnung Akte — N sözleşme

| Bugün | 3.0 sonrası |
|---|---|
| "👤 Aktueller Mieter" — `akteActiveTen` **tek** tenancy seçer (`index.html:3939`) | "👤 Aktuelle Mietverhältnisse (N)" — aktif sözleşmeler listesi |
| Mietkonto/Mahnung/son ödeme o tek kiracıya bağlı (`:3944, :4229`) | Her satır kendi Mietkonto'suna ve kendi Mahnung'una götürür |
| N=1 iken görünüm | **Birebir aynı kalmalı** (regresyon: tek kiracıda ekran değişmez) |

**Toplam Açık — KARAR: gösterilir (2026-07-21).** Birden çok sözleşme varken Akte'de bir "Toplam Açık"
satırı görünür. Bağlayıcı kurallar: **salt-okunur** · **UI'da hesaplanan** (computed) değer ·
**DB'ye yazılmaz** · **endpoint değişmez** · **Mahnung üretmez** · **ledger değişmez** ·
**N=1 görünümü korunur** (tek sözleşmede ekran bugünküyle birebir aynı kalır).
Bu, CLAUDE.md yasası #2/#4 ile uyumludur: ekran borcu **türetmez**, tenancy başına gelen sayıları
yalnızca **toplar**.

## 6.4 Hata mesajları — ilkeler

- Almanca birincil, TR/EN mevcut `_L`/`_iL` deseniyle.
- **Ne olduğunu + nedenini + çıkış yolunu** söyler; suçlayıcı değildir.
- Sunucu `detail` metni ile UI metni **çelişmez** (kullanıcı ikisini de görebiliyor).
- "AI", "sistem hatası" gibi ifadeler yok (`.claude/ux_voice.md`).

---

# 7. Test Planı

## 7.1 Unit test (`tests/test_immo_sprint_3_0.py` — yeni)

| # | Test | Beklenen |
|---|---|---|
| U1 | Örtüşme tespiti: tam örtüşme, kısmi örtüşme, ardışık (`bis == von`), süresiz+süresiz, silinmiş kayıt | Sırasıyla: var, var, **yok**, var, yok |
| U2 | `_accounting` Soll toplamı: unit'te 2 aktif tenancy | `soll == t1 + t2` (bugün `t1`) |
| U3 | `_portfolio` Soll toplamı | Aynı |
| U4 | Tek tenancy'de U2/U3 | **Bugünkü değerle birebir aynı** |

## 7.2 Integration test (TestClient)

| # | Test | Beklenen |
|---|---|---|
| I1 | `POST /immo/tenancies` — dolu daireye örtüşen ikinci sözleşme | **400** + yol gösteren `detail` (A seçilirse) |
| I2 | `POST` — ardışık sözleşme (`bis == yeni von`) | **200** |
| I3 | `PATCH` — tarih değiştirip örtüşme yaratma | **400** |
| I4 | Mevcut örtüşen kayıt (sentetik olarak DB'ye yazılmış) | Okuma yüzeyleri çalışır, **hiçbir yazma zorunluluğu yok** (geçmişe dönük doğrulama yok) |
| I5 | Farklı Unit'te ikinci sözleşme | **200** (Faz 2 Untermieter akışı bozulmadı) |

## 7.3 Regression test (en kritik)

| # | Test | Beklenen |
|---|---|---|
| R1 | **Tek tenancy'li tam senaryo**: `_accounting` + `_portfolio` + `/immo/mieter` + `mietkonto` çıktıları | **SHA256 birebir aynı** (Sprint 2.1'de kanıtlanmış desen) |
| R2 | `git diff --stat` | `immo_payments.py`, `immo_rules.py`, `immo_payment_*.py`, `immo_nebenkosten.py`, `models.py`, `db.py` → **0 satır** (Gate H4) |
| R3 | Mevcut suite (46 test) | **Tamamı yeşil** |
| R4 | Faz 2 Untermieter E2E (`test_immo_sprint_2_1_e2e.py`) | 25/25 PASS — guardrail Untermieter akışını bozmadı |
| R5 | Bir odanın ödemesi diğerinin borcunu kapatmıyor | Sentetik iki tenancy; ödeme A'ya → B'nin borcu değişmez |

## 7.4 Browser smoke (yerel harness)

`tests/build_untermieter_visual.py` deseninde: guardrail mesajının **üç formda da** göründüğü,
Akte'nin N sözleşme listelediği, N=1'de görünümün değişmediği. `_babelcheck.js` + `check_jsx_structure.py` yeşil.

## 7.5 Production smoke (deploy sonrası)

1. `/health` ok · db connected
2. **Gate T2 sorgusu tekrar** → 0 (deploy ÖNCESİ, §2)
3. Mevcut bir daireye örtüşen sözleşme denemesi → engellendi + mesaj okunabilir *(ev sahibi manuel; kayıt oluşmadığı için veri kirlenmez)*
4. Ardışık sözleşme (kiracı değişimi) hâlâ çalışıyor
5. Bir property raporunda Soll değeri **deploy öncesiyle aynı** (tek tenancy'li portföyde değişmemeli)
6. Console error yok

---

# 8. Definition of Done

Sprint 3.0, aşağıdakilerin **tamamı** doğruysa tamamlanmış sayılır:

| # | Madde |
|---|---|
| D1 | P1–P5 düzeltildi: `act[0]` yerine toplam (`immo_api.py:1185`, `:1292`); Akte N sözleşme gösteriyor |
| D2 | Guardrail (§5, onaylanan seçenek) üç yazma yolunda da çalışıyor; üç formda **aynı** mesaj |
| D3 | **Tek tenancy'li senaryolarda tüm çıktılar SHA256 birebir aynı** (R1) |
| D4 | Yeni test dosyası + mevcut suite tamamen yeşil (46 + yeni) |
| D5 | `_babelcheck.js` PARSE OK · `check_jsx_structure.py` BALANCED |
| D6 | Tarayıcı smoke: guardrail üç formda görüldü, Akte N sözleşme listeledi, N=1'de görünüm değişmedi |
| D7 | **Gate T2 deploy'dan hemen önce tekrar çalıştırıldı ve sonuç 0** (>0 ise deploy durur) |
| D8 | Deploy edildi; `/health` ok; prod smoke 6/6 (§7.5) |
| D9 | **`git diff --stat` kanıtı:** Payment Service · Payment Repository/Models · `immo_rules.py` · `immo_nebenkosten.py` · `models.py` · `db.py` → **0 satır değişiklik** |
| D10 | Çelişen legacy akış yok: üç form + Akte aynı gerçeği söylüyor |
| D11 | `SPRINT.md` kapanış raporu (tamamlanan · bilinçli ertelenen · açık riskler · "gerçekten bitti mi?") |
| D12 | Kullanıcı gözünden kritik boşluk yok |

---

# 9. Riskler

## 9.1 Teknik

| # | Risk | Seviye | Önlem |
|---|---|---|---|
| T-A | `act[0]` → toplam değişimi beklenmedik yerde rakam değiştirir | 🟡 | R1 SHA256 regresyonu; prod'da örtüşme 0 (Gate T2) → pratikte fark yok |
| T-B | Guardrail meşru bir akışı bloke eder (kiracı değişimi) | 🟠 | §5.4 kenar durumları + I2/I3 testleri; ardışık sözleşme açıkça izinli |
| T-C | Örtüşme tespitinin tarih mantığı hatalı (yarı-açık aralık, NULL `bis`) | 🟠 | U1 altı senaryolu tablo testi |
| T-D | Akte'nin N sözleşmeye geçmesi mevcut ekranı bozar | 🟠 | N=1 için görünüm regresyonu (D6) |
| T-E | Guardrail'in geçmişe dönük uygulanması (mevcut kayıtlarda PATCH'i kilitlemesi) | 🟡 | Kural yalnız *yeni oluşan* örtüşmeye bakar; I4 testi |
| T-F | 3.0 sonrası "Soll doğru ama NK yanlış" boşluğu | 🟠 | Guardrail A seçilirse boşluk **kapanır**; B/C seçilirse **açık kalır** ve 3.1'e kadar bilinçli risk olarak kayda geçer |

## 9.2 UX

| # | Risk | Önlem |
|---|---|---|
| U-A | Hard validation ev sahibini sahte Unit açmaya iter (ADD §1.3 anti-pattern) | Hata mesajı bunu **açıkça** yönlendirir ve "oda-oda kiralama yakında" beklentisi verir |
| U-B | Mesaj anlaşılmaz / suçlayıcı | §6.4 ilkeleri; Almanca birincil, çıkış yolu var |
| U-C | Akte'de N sözleşme = kalabalık ekran | N=1'de bugünkü görünüm birebir korunur; liste yalnız gerektiğinde |

## 9.3 Migration

**Migration YOK** (§4). Risk sınıfı boş. Rollback = kod revert; veri dokunulmadığı için geri dönüş kaybı yok.

## 9.4 Performance

| # | Risk | Önlem |
|---|---|---|
| P-A | Guardrail her `POST/PATCH`'te ek sorgu | Tek Unit'in tenancy'leri (küçük küme, indeksli `unit_id`); yazma yolu, sıcak yol değil |
| P-B | `_accounting` / `_portfolio` döngüsünde `act[0]` yerine toplam | Aynı liste üzerinde toplama — **ek sorgu yok**, ölçülebilir maliyet yok |
| P-C | Akte'nin N sözleşme için Mietkonto çekmesi (`index.html:3944` eager) | N genelde 1–3; gerekirse yalnız ilk açılışta eager, kalanı tıklamayla |

---

# 10. Sprint Sonrası

## Sprint 3.1'e kalanlar (fazın kalbi)
- `ImmoTenancy.anteil_flaeche` + `zimmer` kolonları (additive/nullable) + boot-time ALTER
- Sunucu doğrulaması: **alan korunumu** `Σ anteil_flaeche(aktif) ≤ unit.wohnflaeche`
- Guardrail'in **koşullu** hale gelmesi (§5.3-şart 4): örtüşme, alan korunumu sağlanıyorsa kabul
- NK ağırlıkları: K1 (`wohnflaeche` çift sayımı), K2 (`wohneinheiten`), K5 (boş oda payı Leerstand'a)
- `CALCULATION_VERSION` 4→5 + snapshot şeması (Principle A)
- Üç formda `Anteil (m²)` + `Zimmer` alanları; canlı "kalan alan" göstergesi
- Belegung/Leerstand'ın alan-ağırlıklı hale gelmesi

## Sprint 3.2'ye kalanlar (daraltılmış)
- **K3** düzeltmesi: Unit sayaç farkı **bir kez** türetilir, paylaşımlı Unit'te m² ile bölünür
- Her etkilenen satırda **görünür Hinweis** (Abrechnung + PDF)
- Zähler matris UI'sinin paylaşımlı Unit'te ne anlama geldiğini söylemesi
- **Kapsam dışı:** oda bazlı tüketim dağıtımı — Professional Review Required (`ImmoZaehlerstand` şeması değişmez)

## Sprint 3.3'e kalanlar
- Mahnung / WGB PDF'lerinde `Zimmer` gösterimi (H3 profesyonel onayına bağlı)
- Belegung göstergesinin "2/3 oda dolu · 30 m² boş" hâli
- Faz 3 kapanış raporu (`SPRINT.md`)

## Faz 4'e kalanlar (bu fazın hiçbir sprintinde yok)
- Aynı Unit'te Untermieter (parent-child)
- Eigennutzung + kiracı aynı dairede (roadmap madde 10 karışık hâl)
- Oda başına fiziksel sayaç (`ImmoZaehlerstand.tenancy_id`)
- Ortak alan (Gemeinschaftsfläche) modeli

---

## Onay

Bu belge **uygulama planıdır**; kod, migration ve commit içermez. ADD Rev.2'nin kararları değiştirilmedi —
tek istisna §5'te açıkça işaretlenen **guardrail sertliği tadilatı**, ki uygulanması senin onayına bağlıdır.
