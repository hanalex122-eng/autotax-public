# Flexible Mietmodelle — Ürün Yol Haritası (Phase 1)

> **Belge türü:** SaaS ürün + mimari tasarımı (KOD DEĞİL).
> **Durum:** TASLAK — birlikte gözden geçirilecek. Onay alınmadan kod geliştirmesine başlanmaz.
> **Kapsam:** AutoTax Cloud'un **tüm** ev-sahibi müşterileri. Hiçbir tekil kullanıcı senaryosuna göre tasarlanmaz.
> **Amaç uygulanabilir bir roadmap'tir — mümkün olduğunca çok özellik eklemek DEĞİL.**
> **Engineering Constitution v1'e tabidir.** Bu belge kapsamında migration/commit/deploy YOK.

---

## 0. Epic Kimliği

**Epic adı: `Flexible Mietmodelle`** (Esnek Kiralama Modelleri).

Bu bir "Untermieter özelliği" değildir. `Flexible Mietmodelle`, "1 daire = 1 standart kira sözleşmesi = kirayı kiracı öder" varsayımının dışında kalan **tüm uzun-süreli Alman kiralama biçimlerini** kapsayan bir **şemsiye** ürün ailesidir. Untermieter, bu şemsiyenin yalnızca bir modelidir.

---

## 1. Amaç

AutoTax Cloud'un Immobilien modülü bugüne kadar şu örtük varsayımla gelişti:

**1 Wohnung = 1 Kaltmiete + 1 NK-Vorauszahlung = Zahler her zaman der Mieter.**

Küçük ev sahiplerinin gerçek portföylerinde bu varsayım sık sık kırılır: kirayı bazen bir kurum öder, bazen Heizkosten ayrı anlaşılır, bazen bir dairede birden çok bağımsız sözleşme olur. `Flexible Mietmodelle`, bu gerçek biçimleri **standart, tekrar kullanılabilir** ürün özellikleri olarak destekler — hiçbir müşteriye özel "hack" gerektirmeden.

**Faz 1'in dar amacı:** Warmmiete'yi doğru üç bileşenden kurmak (Kalt + NK + **Heiz**) ve her sözleşmeye **kimin ödediğini (Zahler)** kaydetmek. Böylece borç/Mietkonto/Mahnung doğru tutarı gösterir ve kurumsal ödeyiciler (Sozialamt/Jobcenter/diğer) izlenebilir.

---

## 2. Hedef Kullanıcı

- **Almanya'daki küçük ev sahipleri.**
- **Bireysel kiraya verenler** (profesyonel yönetim şirketi değil).
- **1–20 birimlik** portföyler.

Tasarım bu ölçeğe göre **basit ve düşük-bakım** olmalıdır.

---

## 3. Kullanım Senaryoları (Ürün Gereksinimleri)

Herhangi bir AutoTax müşterisinin kullanabileceği **standart** kiralama biçimleri:

| # | Senaryo | Ürün gereksinimi | Faz |
|---|---|---|---|
| 1 | **Normal kiralama** | Kalt + NK, Zahler = Mieter (mevcut temel) | ✅ Var |
| 2 | **Eigennutzung** | Ev sahibi oturur; borç yok, NK'da kendi payı | ✅ Var |
| 3 | **Ayrı Heizkostenvorauszahlung** | Kalt + NK + **Heiz** üç ayrı bileşen | **1** |
| 4 | **Sozialamt ödeme** | Zahler = Sozialamt (Mieter değil) | **1** |
| 5 | **Jobcenter ödeme** | Zahler = Jobcenter | **1** |
| 6 | **Kurumsal / 3. kişi ödeyen** | Zahler = Sonstige + Zahler adı | **1** |
| 7 | **Untermieter** | Ana kiracıya/eve bağlı alt sözleşme | 2 |
| 8 | **WG (Wohngemeinschaft)** | Bir dairede birden çok bağımsız sözleşme | 3 |
| 9 | **Zimmervermietung** | Oda-oda: farklı kira/sözleşme/ödeme/Mahnung | 3 |
| 10 | **Eigengenutztes Haus + Vermietung** | Ev sahibi binada oturur (Eigennutzung) + N kiracı — **çok yaygın!** Saf hâl ✅; karışık hâl (aynı dairede Eigennutzung + Untermieter) Faz 2/4 | ✅ / 2 / 4 |

> ⚠️ **Kritik yaygın senaryo (madde 10):** Almanya'da en sık durum — ev sahibi kendi binasında oturur + kiralar (eigengenutztes Mehrfamilienhaus). **Saf hâl** (Eigennutzung dairesi + ayrı kiracı daireleri) motorda **doğru çalışır** (kiracı payları / Leerstand / Eigennutzungsanteil ayrışır — canlı doğrulandı). **AMA karışık hâl** — aynı dairede hem Eigennutzung hem Untermieter/Sozialamt — mevcut model tarafından **ifade EDİLEMEZ**: kullanıcı daireyi iki kez açar → **çift-sayım** (yaşanan 340 vs 228 hatası). Robustluk = Faz 2 (Untermieter) + Faz 4 (m² paylaşımı) + **çift-kayıt guardrail** (madde 6 backlog). Bu senaryo, "genel SaaS" prensibinin (madde 7) doğrudan hedefidir.

---

## 4. Faz 1 Kapsamı — 🔒 DONDURULDU (FREEZE)

**SADECE aşağıdaki üç özellik. Bu faza başka özellik EKLENMEYECEK.**

| Özellik | Ne yapar |
|---|---|
| **Heizkostenvorauszahlung** | Sözleşmeye ayrı Heizkosten alanı |
| **Zahler** | `Mieter` / `Sozialamt` / `Jobcenter` / `Sonstige` + Zahler adı |
| **Warmmiete** | Aylık soll = Kalt + NK-Voraus + **Heiz** (tek soll fonksiyonundan) |

**Faz 1 tamamlanmadan yeni kapsam açılmaz.** WG, Zimmervermietung, Untermieter, NK m² paylaşımı — hiçbiri Faz 1'e alınmaz.

---

## 5. Gelecek Fazlar

### Faz 2 — Untermieter ✅ TAMAMLANDI (Sprint 2.1, canlı 2026-07-21)
Tasarım: [`docs/design/Sprint_2_1_Untermieter.md`](../design/Sprint_2_1_Untermieter.md) · kapanış raporu: `SPRINT.md`.

- ✅ Untermieter
- ✅ Hauptmieter ilişkisi
- ✅ Parent tenancy (`typ` haupt|unter, `parent_tenancy_id`) — additive/nullable, **relationship-only**
      (muhasebe değişmedi; her tenancy kendi Mietkonto/borç/Mahnung akışını korur)
- ⏭️ **Eigennutzung + Untermieter AYNI dairede** (ev sahibi oturur + aile bireyi/başkası Sozialamt Untermieter) → çift-kayıt olmadan tek dairede modellenir (madde 10 karışık hâlin çözümü)
      — **Sprint 2.1 kapsamı dışı bırakıldı (Seçenek B: ayrı Unit).** NK m²-payı sorununu açtığı için **Faz 4**'e taşındı.

> 🔒 **Faz 2 bağlayıcı prensipler (kullanıcı, 2026-07-20):**
> 1. **Geriye dönük uyumluluk bozulmaz.**
> 2. **Mevcut kiracı modeli VARSAYILAN olarak AYNI çalışır** (`typ` boş/null = `haupt`; eski davranış birebir).
> 3. **Untermieter mevcut mimarinin ÜZERİNE eklenir, onu DEĞİŞTİRMEZ** (additive/nullable, Sprint 1.1'deki gibi).
> 4. **Ön koşul:** Faz 1 kapanışı + **kısa stabilizasyon** tamamlanmadan Faz 2'ye başlanmaz.

### Faz 3 — WG / Zimmervermietung 🔁 TRIGGER-BASED (2026-07-22 · iptal değil)
Sprint 3.0 (doğruluk düzeltmeleri + hard guardrail) ✅ canlı. Kalan 3.1/3.2/3.3 **ilk gerçek
ihtiyaç veya müşteri talebi** geldiğinde yeniden önceliklendirilir; o ana kadar sıra
`VERMIETER_MASTERPLAN.md`'dedir. Tetikleyiciler: `SPRINT.md` → BACKLOG.
Mimari kararlar: [`docs/design/Phase3_WG_Zimmervermietung.md`](../design/Phase3_WG_Zimmervermietung.md) (Rev. 3).

- WG (Wohngemeinschaft)
- Zimmervermietung
- Aynı daire içinde birden fazla sözleşme (`anteil_flaeche`)

### Faz 4 — Gelişmiş Nebenkosten
- Nebenkosten m² dağılımı (Wohnfläche alan-korunumu)
- Ortak kullanım senaryoları (Gemeinschaftsflächen)
- Gelişmiş Umlageschlüssel

---

## 6. Product Backlog (Future)

Aşağıdaki özellikler **not edilir** ama **hiçbiri Faz 1'e alınmaz** ve şu an bir faza atanmamıştır. Sadece ürün backlog'udur; zamanı gelince "Ürün Prensibi" (madde 7) kapısından geçerse bir faza alınır:

- Staffelmiete (kademeli kira)
- Indexmiete (endeksli kira)
- Gewerbemiete (ticari kira)
- Garage
- Stellplatz (otopark yeri)
- Keller (bodrum)
- Möblierte Vermietung (mobilyalı)
- Zeitmietvertrag (süreli sözleşme)
- Nachmieter (yeni/devralan kiracı)
- Bürgschaft (kefalet)
- **Doppel-Wohnung Guardrail** — aynı binada aynı m²/daire ikinci kez eklenince **uyar** ("Bu daireyi zaten eklediniz — Eigennutzung mı, kiralık mı?"). **Yüksek değer · düşük risk · faz-bağımsız** — 340↔228 çift-sayım tuzağını önler. (Madde 10 için ilk savunma hattı.)
- **Eigengenutztes Haus — Robustluk** (madde 10) — her daire için net seçim: **"Kim oturuyor: Ev sahibi / Kiracı / Ev sahibi + Untermieter"**; karışık kullanım rehberi + NK doğrulama.

> Bu liste kapsam taahhüdü değildir; sadece unutulmaması için kayıttır.

---

## 7. Ürün Prensibi (Bağlayıcı)

> 📌 Kanonik kaynak: **`CONTRIBUTING.md`** → "Ürün Prensibi". Tüm roadmap/tasarım belgeleri bu prensibe atıf yapar. Aşağıdaki, o prensibin bu Epic'e uygulanmış özetidir.

**AutoTax Cloud, tek bir kullanıcının ihtiyaçlarına göre değil, Almanya'daki küçük ve orta ölçekli ev sahiplerinin ORTAK ihtiyaçlarına göre geliştirilir.**

Her yeni özellik roadmap'e alınmadan önce **üç kriteri sağlamalıdır:**

1. Gerçek hayatta **yaygın kullanılan** bir kiralama senaryosunu çözüyor mu?
2. SaaS ürünü olarak **birçok müşteri** tarafından kullanılabilecek kadar **genel** mi?
3. **Mevcut müşterilerin verisini ve çalışma şeklini bozmadan** eklenebiliyor mu?

- Üç cevap da **"Evet"** ise → roadmap'e alınır.
- Aksi hâlde → **backlog'da bekletilir.**
- **Phase 1 tamamlanmadan yeni kapsam açılmaz.**

---

## 8. Veri Modeli

**Yeni hiyerarşi KURULMAZ.** Mevcut `Immobilie → ImmoUnit → ImmoTenancy` korunur; sadece **additive, nullable** kolon eklenir — `personenzahl`, `mea`, `eigennutzung_personen`'in eklendiği güvenli yöntem gibi (`models.py:900,905,937`).

### Faz 1'de eklenecek alanlar (`ImmoTenancy`)

| Kolon | Tip | Neden |
|---|---|---|
| `heizkosten_voraus` | Float, null | `kaltmiete` + `nk_voraus` var (`models.py:919,921`) ama **ayrı Heizkosten YOK** |
| `zahler_typ` | String, null | `mieter` \| `sozialamt` \| `jobcenter` \| `sonstige` |
| `zahler_name` | String, null | Ödeyen kurum/kişi adı (PDF/kayıt) |

### Neden mevcut sistemi bozmaz
- Hepsi **nullable/defaultlu** → mevcut satırda `heizkosten_voraus=null=0` → aylık soll **birebir aynı**.
- **Tek soll fonksiyonu:** `monat_soll = effective_kalt + nk_voraus` (`immo_rules.py:109`), her yerde kullanılır (`immo_rules.py:878`). Heiz eklemek = o **tek satıra bir terim** → tüm ekranlar otomatik tutarlı (CLAUDE.md → "ONE accounting model").
- **Zahler** salt bilgi; hiçbir hesaba girmez (Faz 1'de Mahnung'u otomatik ödeyiciye yönlendirmez).

### Faz 2+ alanları (planlı, additive)
`typ`, `parent_tenancy_id` (Faz 2); `anteil_flaeche` (Faz 3). Hiçbiri `ImmoUnit`'e alt-birim gerektirmez.

---

## 9. Tasarım İlkeleri (bağlayıcı)

1. **Mevcut kullanıcılar etkilenmez** — yeni alan boşken davranış birebir eski.
2. **Tüm yeni alanlar additive/nullable** — hiçbir kolon silinmez/yeniden adlandırılmaz.
3. **Mietkonto, Mahnung, Nebenkosten akışı korunur** — tek soll fonksiyonundan türer.
4. **Single-Ledger korunur** — bir ekonomik olay tek yerde; ikinci defter yok.
5. **Her faz bağımsız deploy edilebilir** — Faz 1 tek başına canlıya çıkar.
6. **Geriye dönük uyumluluk** — eski veri ve eski API çağrıları çalışmaya devam eder.

---

## 10. Risk Analizi

| Modül | Etki | Risk |
|---|---|---|
| **Mietkonto** | `heizkosten_voraus` aylık soll'a girer → Warmmiete artar | 🟠 Orta — borç yoluna dokunur; mevcut satır 0 → değişmez, **regresyon testi şart** |
| **Mahnung** | Warmmiete değiştiği için borç eşiği değişir | 🟠 Aynı soll'dan türer; ikinci defter yok |
| **Nebenkosten** | Faz 1'de **dokunulmaz**; Heiz-Voraus mahsubu Faz 4'e ertelendi | 🟡 Faz 1'de NK-Abrechnung Heiz ön-ödemesini **henüz mahsup etmez** |
| **PDF** | Warmmiete kalemleri görünür | 🟢 Düşük |
| **Dashboard** | Gesamtmiete = Kalt+NK+Heiz | 🟢 Düşük — türetilen değer |

**En büyük risk 🔴 Faz 4'te** (NK Wohnfläche alan-korunumu; `basis_weight` immutable snapshot'a dokunur — `immo_nebenkosten.py:249`). Faz 1 bu riske **girmez**.

---

## 11. Kapsam Dışı

Bu Epic **kapsamaz**: Otel · Hostel · Airbnb · Booking sistemi · Günlük/saatlik kiralama · Check-in/Check-out · Resepsiyon · Temizlik yönetimi.

Amaç yalnızca **uzun süreli Alman kiralama modellerini** destekleyen profesyonel bir SaaS ürünüdür.

---

## 12. Sprint Planı

### Sprint 1.1 — Şema + Warmmiete
- **Amaç:** `ImmoTenancy += heizkosten_voraus, zahler_typ, zahler_name`; `monat_soll`'a Heiz terimi; tenancy POST/PATCH + tenant-feed/mietkonto yanıtlarına 3 alan.
- **Süre:** 1 kısa sprint. **Risk:** Orta (borç yolu, additive).
- **Test:** eski Mietkonto değerleri **birebir aynı** (regresyon); yeni Heiz → soll = Kalt+NK+Heiz; suite yeşil.

### Sprint 1.2 — Sözleşme formu UI
- **Amaç:** Forma ayrı Heizkosten + Zahler seçimi + Zahler adı; Akte/kartta göster (DE/TR/EN).
- **Süre:** 1 kısa sprint. **Risk:** Düşük (frontend).
- **Test:** 3 alan doğru yazılır/okunur; boşken eski davranış; canlı marker.

### Sonraki fazlar (ayrı onaylarla — Faz 1 bitmeden açılmaz)
Sprint 2.x Untermieter · Sprint 3.x WG/Zimmer · Sprint 4.x NK alan-korunumu (**en yüksek risk, en son**).

---

## 13. Çalışma Sırası

Her yeni geliştirme şu sırayı izler:

1. **Roadmap tamamlanır.**
2. **Roadmap onaylanır.**
3. **Sprint tasarımı hazırlanır.**
4. **Kod yazılır.**
5. **Test edilir.**
6. **Deploy edilir.**

Her sprint **bağımsız, geri alınabilir ve üretim ortamı için güvenli** olacaktır.

---

## 14. Onay

Bu belge bir **ürün yol haritasıdır**. Kod/migration/commit/deploy içermez.

Belge onaylandıktan sonra **yalnızca Sprint 1.1** uygulanır (tasarım → onay → kod → test → deploy). **Faz 1 dondurulmuştur; tamamlanmadan yeni kapsam açılmaz.**
