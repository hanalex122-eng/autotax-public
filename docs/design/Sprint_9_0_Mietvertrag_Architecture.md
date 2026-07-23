# Sprint 9 — Mietvertrag Generator · Architecture Report (Faz 0: analiz + tasarım)

> **Belge türü:** Mevcut mimarinin **DOĞRULAMASI** — yeni mimari DEĞİL. **KOD YOK · migration YOK · endpoint YOK · UI YOK · commit/push/deploy YOK.**
> **🔒 Source of truth:** **`.claude/mietvertrag_architecture.md`** (product owner, 2026-07-16, v1 scope KİLİTLİ).
> Bu rapor onu **değiştirmez, yeniden yazmaz, çelişmez** — yalnızca (a) güncel kodla karşılaştırır,
> (b) eksik/değişmesi gereken noktaları işaretler, (c) Sprint 13 sonrası Akte entegrasyonunu ekler,
> (d) Unicode font (DejaVuSans) riskini açıkça işaretler.
> **Tarih:** 2026-07-23 · **Durum:** onay bekliyor
> **Diğer üst belgeler:** `VERMIETER_MASTERPLAN.md` #9 · `.claude/legal_review.md` · `CLAUDE.md`.
> **Yöntem:** backend/veri/PDF/UI kod okunarak; her iddia `dosya:satır` referanslı. Varsayım yok.

---

## §V — Source-of-truth doğrulama matrisi (kaynak doküman ↔ güncel kod)

`.claude/mietvertrag_architecture.md`'deki her bağlayıcı iddia, bugünkü kodla karşılaştırıldı:

| Kaynak dokümandaki iddia | Güncel kod durumu | Sonuç |
|---|---|---|
| §1 Veri hazır: `UserCompany`, `ImmoProperty.adresse`, `ImmoUnit.name/wohnflaeche`, `ImmoTenancy.*` | Hepsi mevcut (`models.py:472,880,895,916-941`) | ✅ **DOĞRULANDI** |
| §2 Yeni tablo `ImmoMietvertrag` (status/vertrag_json/snapshot/version) | Kodda **yok** — sadece dokümanda | ✅ **DOĞRU (henüz yapılmadı)** |
| §2 "boot-time create_all, ALTER yok" | Mevcut desen aynen böyle (Sprint 1.1/2.1/3.x) | ✅ **DOĞRULANDI** |
| §3 Saf modül `mietvertrag_template.py` (`immo_nebenkosten.py` deseni) | Kodda **yok**; ama desen kanıtlı (`immo_nebenkosten.py`, `immo_protokoll.py`) | ✅ **DOĞRU** |
| §6 Snapshot + finalize-lock (NK Principle A/B) | Referans implementasyon canlı: `NkAbrechnung` + `finalize_nk`/`unlock_nk` (`immo_api.py:3265/3297`) | ✅ **DOĞRULANDI, kopyalanabilir** |
| §6 "PDF via existing reportlab path" | reportlab platypus deseni canlı (`protokoll_pdf:2634`, `nk_pdf:3319`) | ⚠️ **DOĞRU AMA EKSİK** → font (aşağı) |
| §7 write-back "one Payment-Service-safe update" | Payment Service tek yol mevcut; write-back kodu yok | ✅ **DOĞRU (tasarım geçerli)** |
| §0 StBerG/RDG duruşu + disclaimer | Desen canlı: NK footer (`immo_api.py:3473`), `legal_review.md:41` | ✅ **DOĞRULANDI** |
| §8 "Wohnung Akte contract+protocol+statements toplar" | **Akte artık canlı (Sprint 13.0)** — kaynak doküman yazıldığında yoktu | 🆕 **GÜNCELLEME → §2.S6** |

**Kaynak dokümana eklenmesi/güncellenmesi gereken YALNIZCA iki nokta** (ikisi de doküman 2026-07-16'da
yazıldığından beri değişen gerçekler; mimariyle **çelişmez**, tamamlar):

1. **🔴 Unicode font (DejaVuSans) — kaynak doküman §6 "existing reportlab path" der ama fontu adlandırmaz.**
   Güncel kod incelemesi: hiçbir PDF Unicode font kaydetmiyor → **Türkçe karakter bozuk basar** (T1).
   Kaynak doküman §6'ya "DejaVuSans zorunlu" notu eklenmeli.
2. **🆕 Akte entegrasyonu — kaynak doküman §8 Akte'yi "later/gelecek" diye anar; artık Sprint 13.0 ile CANLI.**
   Entegrasyon noktası netleşti: Akte'ye "📄 Mietvertrag" accordion bölümü (§2.S6). Bu bir **güncelleme**,
   yeni mimari değil.

---

## 0. En önemli tespit — bu sıfırdan başlamıyor

İki şey zaten hazır ve bu raporu **analiz** olmaktan çıkarıp **doğrulama + güncelleme** yapıyor:

1. **`.claude/mietvertrag_architecture.md` (146 satır)** — product owner tarafından **2026-07-16'da v1
   scope'u KİLİTLENMİŞ** bir mimari doküman. §0 hukuki duruş (BGH-Smartlaw), §2 `ImmoMietvertrag` tablo
   tasarımı, §7 v1/deferred ayrımı hep yazılı. Bu rapor onu **kod gerçekliğiyle karşılaştırır ve teyit
   eder**, yeniden icat etmez.
2. **Akte entegrasyon noktası** — Sprint 13.0'da "#9 Mietvertrag kendi sprintinde Akte'ye bölüm ekler"
   diye bilinçli boşluk bırakıldı (`SPRINT.md` Sprint 13.0 kapanışı). Yani entegrasyon noktası **kararlı**.

---

## 1. Mevcut UI durumu (özel soruların cevabı)

| Soru | Cevap | Kanıt |
|---|---|---|
| Mietvertrag ile ilgili ekran/buton/menü/placeholder var mı? | **HAYIR.** "Mietvertrag" kelimesi UI'de tek yerde: kiracı-adı alanının ipucu metni | `index.html:3182` (*"…wie im Mietvertrag"*) |
| Yarım kalmış UI var mı? | **HAYIR** — hiçbir bileşen, route, state yok | grep: 0 eşleşme |
| Gizli / feature-flag / erişilemez arayüz var mı? | **HAYIR** — backend'de de `mietvertrag` flag'i yok | `autotax/*.py` + `config.py` grep: 0 |
| Akte içinde kullanılabilecek hazır bölüm var mı? | **EVET** — Akte kompozisyon hub'ı; Sprint 13.0 "📄 Mietvertrag" bölümünü bilinçli olarak eklemedi | `index.html:4229+` (Akte); `SPRINT.md` 13.0 kapanışı |
| Yeni ekran açmadan entegre edilebilir mi? | **EVET** — iki mevcut yüzey: (a) Akte'ye "📄 Mietvertrag" accordion'u, (b) kiracı kartındaki WGB/Protokoll butonlarının yanına "Mietvertrag" | `index.html:3116` (dlWgb butonu), `:4229+` (Akte) |

> "Bald / Coming soon" bloğu (`index.html:7278`) **fatura** özellikleriyle ilgili — Mietvertrag'la ilgisi yok.

**Sonuç:** temiz sayfa. Ne kaldırılacak eski kod var, ne çelişecek bir yarım UI. Yeni bir tam-ekran gerekmez;
Akte'nin içine bir bölüm + bir sihirbaz yeterli.

---

## 2. 12 sorunun cevabı

### S1 — Gerekli verinin yüzde kaçı zaten mevcut?
**Çekirdek sözleşme verisinin ~%75-80'i hazır.** Tarafların kimliği, obje, ve tüm mali koşullar var:

| Alan | Kaynak | Durum |
|---|---|---|
| Vermieter (ad, adres, IBAN) | `UserCompany.company_name/address/iban` (`models.py:472-477`) | ✅ |
| Mietobjekt (adres, daire, m²) | `ImmoProperty.adresse` (`:880`) + `ImmoUnit.name/wohnflaeche` (`:895-896`) | ✅ |
| Mieter (ad, tel, e-posta) | `ImmoTenancy.mieter_name/telefon/email` (`:916,930,931`) | ✅ |
| Mietbeginn | `ImmoTenancy.von` (`:917`) | ✅ |
| Kaltmiete (+ Staffel geçmişi) | `ImmoTenancy.kaltmiete` (`:919`) + `miete_historie` (`:933`) | ✅ |
| NK-Vorauszahlung · Heizkosten | `nk_voraus` (`:921`) · `heizkosten_voraus` (`:941`) | ✅ |
| Kaution · Personenzahl | `kaution` (`:920`) · `personenzahl` (`:937`) | ✅ |

Eksik olan %20-25, **sözleşmeye özgü seçim verisidir** (kloz tercihleri, ödeme günü, oda listesi) — bunlar
zaten bir sözleşme sihirbazında sorulacak şeyler, mevcut kayıtta olmaları beklenmez.

### S2 — Eksik alanlar neler?
İki grupta:

**(a) Kişi/obje ayrıntıları (opsiyonel, sözleşme kalitesini artırır):**
- Mieter: doğum tarihi, kiracının mevcut adresi; **birden fazla kiracı (Gesamtschuldner)** yapısı yok (tek `mieter_name` string) → §1.2'deki gibi ileri fazlara bırakılabilir
- Vermieter: kişi adı/soyadı ayrımı yok (sadece `company_name`), temsilci/Vertreter yok, BIC/banka adı yok
- Wohnung: **oda sayısı / Zimmer alanı yok** (`ImmoUnit`'te); Keller/Stellplatz/Schlüssel gibi mitvermietete Räume yok

**(b) Sözleşme seçimleri (sihirbazda toplanır, kalıcı olarak `vertrag_json`'da saklanır):**
- Mietzeit-Typ, Zahlungstermin/-weise (§556b), Kautionsart, Betriebskosten-Umlage listesi
- Kloz tercihleri: Schönheitsreparaturen, Kleinreparaturen cap, Tierhaltung, Untervermietung

> **Karar (mimari dokümanla uyumlu):** (b) grubu **ayrı tablolara/ImmoTenancy kolonlarına açılmaz** —
> hepsi `ImmoMietvertrag.vertrag_json` içinde yaşar. (a) grubu v1'de **opsiyonel/boş bırakılabilir**;
> gerçekten gerekliyse sihirbazda tek seferlik metin girişi olarak alınır, kalıcı model genişletilmez.

### S3 — Mevcut PDF sistemi tekrar kullanılabilir mi?
**Evet, büyük ölçüde — ama iki uyarıyla.** Altyapı: reportlab **platypus** (`SimpleDocTemplate` + flowable
listesi). En zengin referanslar: `protokoll_pdf` (`immo_api.py:2634`, imza gömme + çok tablo) ve `nk_pdf`
(`:3319`). Teslim: `StreamingResponse` + `Content-Disposition: attachment` (`:2828`); frontend blob +
`a.click()` (`dlProtokoll` `index.html:3987`, `dlWgb` `:3012`). Hepsi Mietvertrag'a kopyalanabilir.

**Uyarı 1 (🔴 kritik):** Hiçbir PDF Unicode font kaydetmiyor — hepsi **Helvetica/Latin-1**. Almanca
ü/ö/ä/ß/§/€ sorunsuz, ama **Türkçe ş/ğ/İ/ı/ç `.notdef` (kutu) basar.** Mieter/Vermieter adı ham giriyor
(`:2807`, `:1708`). Mietvertrag'da **`pdfmetrics.registerFont(TTFont("DejaVuSans", …))` zorunlu** (font
dosyası repoda yok, eklenecek — <1 MB, `CLAUDE.md` binary sınırı içinde).

**Uyarı 2:** Ortak PDF/şablon soyutlaması **yok** — her PDF inline HTML string ile elle kuruluyor.
Sözleşme çok bölümlü/çok klozlu olduğu için klozları üreten **saf modül** (`mietvertrag_template.py`,
DB-free — `immo_nebenkosten.py` deseni) gerekir; PDF katmanı bu modülün ürettiği metni basar.

### S4 — Yeni tablo gerekir mi?
**Evet — bir tane: `ImmoMietvertrag`** (mimari doküman §2 ile birebir). Additive; mevcut tablolara
dokunmaz; boot-time `create_all` ile gelir (Sprint 1.1/2.1/3.x deseni), migration aracı yok.
```
ImmoMietvertrag: id · user_id · tenancy_id(FK) · status(entwurf|final) ·
  vertrag_json(Text)      -- sihirbaz seçimleri (yapılandırılmış)
  html_snapshot(Text)     -- finalize'de donan belge (Principle A)
  vertrag_version(Int)    -- kloz-set versiyonu (yıllar sonra aynen üretilebilsin)
  created_at · finalized_at · is_deleted
```
`vertrag_json` sayesinde S2'deki tüm sözleşme seçimleri **yeni kolon açmadan** saklanır.

### S5 — Yeni endpoint gerekir mi?
**Evet, minimum set (mevcut Immo router desenleri):**
- `POST /immo/tenancies/{tid}/mietvertrag` — taslak oluştur/güncelle (`vertrag_json`)
- `GET  /immo/mietvertraege?tenancy_id=` ve `GET /immo/mietvertrag/{id}` — oku
- `POST /immo/mietvertrag/{id}/finalisieren` — snapshot + lock (NK `finalize_nk` deseni)
- `POST /immo/mietvertrag/{id}/entsperren` — yetkili düzeltme (yeni Revision) — NK `unlock_nk` deseni
- `GET  /immo/mietvertrag/{id}/pdf` — StreamingResponse (final → snapshot, taslak → canlı)

**Aggregate endpoint yok, ikinci defter yok** (Architecture law). Write-back (§7) tek güvenli update
yolundan gider — Mietkonto tek doğruluk kaynağı bozulmaz.

### S6 — Akte içinde en doğru entegrasyon noktası?
**Akte'ye yeni bir "📄 Mietvertrag" accordion bölümü** (Protokolle bölümünün hemen yanına, aynı desen):
- Bölüm başlığında: son sözleşmenin durumu (Entwurf / Final + tarih) veya "Noch kein Vertrag"
- İçinde: sözleşme listesi + PDF butonu + "Neuen Vertrag erstellen" → sihirbaz
- Sihirbaz `UebergabeWizard` (`index.html:2652+`) desenini izler: adımlı, `locked` durumu, finalize onayı

Bu, Sprint 13.0'ın Akte'yi kompozisyon hub'ı yapma kararının doğrudan devamı. **Yeni tam-ekran gerekmez.**
İkinci (opsiyonel) giriş: kiracı kartındaki WGB/Protokoll butonlarının yanı.

### S7 — Versioning gerekli mi?
**Evet, iki düzeyde:**
- **`vertrag_version` (kloz-set versiyonu):** template metnini ileride değiştirirsek eski sözleşme yıllar
  sonra **aynen** üretilebilsin (NK `CALCULATION_VERSION` deseni, `immo_api.py:3288`).
- **Revision (belge sürümü):** finalize'den sonra değişiklik = **yeni Revision (v2)**, eski saklanır.
  İmzalanmış kağıt sözleşme sessizce mutasyona uğramamalı.

### S8 — Snapshot mı olmalı?
**Evet — kesinlikle (Principle A).** Finalize anında belge (`html_snapshot` + `vertrag_json`) **donar**;
final sözleşme snapshot'tan render edilir, asla canlı master-data'dan. Sebep: sözleşme imzalandıktan
sonra Kaltmiete/Kaution tenancy'de değişse bile **imzalanan metin değişmemeli**. Bu, NK Abrechnung
snapshot'ıyla birebir aynı disiplin (`models.py:1076-1095`, `finalize_nk` `:3265`).

### S9 — İmzalanan sözleşme immutable mı olmalı?
**Evet (Principle B — Finalize = Lock).** Final sözleşme salt-okunur; her yazma yolunda guard
(`require_editable`, `immo_protokoll.py:172` deseni). Düzeltme **tek yoldan**: yetkili Unlock → yeni
Revision. v1'de imza **print-and-sign** (ıslak imza, Schriftform §550 — bir Mietvertrag için en güvenlisi);
dijital parmak imzası (Sprint 1'deki `SignaturePad`, `index.html:2621`) ileri fazda eklenebilir.

### S10 — Hangi bilgiler otomatik dolmalı?
S1'deki hazır veri: **taraflar · obje · Kaltmiete · NK · Heizkosten · Kaution · Mietbeginn · Personenzahl.**
Kullanıcı bunları görür ama sihirbazda **düzeltebilir** (sözleşmede farklı anlaşılmış olabilir); düzeltirse
write-back ile tenancy'ye de yazılır (§7).

### S11 — Hangi bilgiler kullanıcı tarafından değiştirilebilir?
- **Düzenlenebilir (guided):** Mietzeit-Typ · Zahlungstermin · Kleinreparatur cap on/off ·
  Schönheitsreparatur varyantı · Tierhaltung · Stellplatz/Keller · Betriebskosten-Umlage listesi ·
  otomatik dolan mali değerler (üstte)
- **Sabit (yasal, düzenlenemez):** Kaution cap 3× (§551) · Kündigungsfristen · kiracı-koruyucu klozlar.
  **Geçersiz kloz üretilemez** — BGH'nin iptal ettiği varyantlar picker'da **hiç bulunmaz** (toggle-off
  değil, yok). Bu, StBerG/RDG güvenliğinin temeli.

### S12 — Hangi bölümler ileride farklı şablonları destekleyecek şekilde tasarlanmalı?
`mietvertrag_template.py` **şablon-parametrik** olmalı:
- **`vertrag_typ`** ayrımı: v1 = Wohnraum unbefristet + Staffel; ileride Indexmiete (§557b), befristet
  (§575), Gewerbe, Stellplatz-only aynı motora yeni "tip" olarak eklenir
- **Kloz kataloğu ayrık:** her kloz `{id, typ, versiyon, geçerli_mi, metin}` — yeni şablon = farklı kloz
  seçkisi, motor değişmez
- **`vertrag_json` şeması genişlemeye açık:** yeni tip yeni alanlar ekler, eski sözleşmeler `vertrag_version`
  ile aynen render olur

---

## 3. Riskler

### Teknik
| # | Risk | Seviye | Önlem |
|---|---|---|---|
| T1 | **Türkçe karakter PDF'te bozuk** (Helvetica/Latin-1) | 🔴 Yüksek | DejaVuSans TTF kaydı — Mietvertrag'ın ilk kod adımı |
| T2 | Ortak şablon soyutlaması yok → sözleşme metni inline string olursa bakımsız olur | 🟠 Orta | DB-free `mietvertrag_template.py` saf modülü (klozları üretir, test edilir) |
| T3 | Snapshot olmadan finalize → master-data değişince sözleşme metni kayar | 🔴 Yüksek | Principle A: `html_snapshot` + `vertrag_version` (NK deseni) |
| T4 | Write-back Mietkonto'yu bozar (ikinci defter) | 🟠 Orta | Tek güvenli update yolu; `monat_soll` tek kaynak korunur (Architecture law) |
| T5 | Çok sayfalı belgede sayfa taşması / kloz bölünmesi | 🟡 Düşük | reportlab `KeepTogether` + `repeatRows` (Protokoll'de mevcut) |

### Hukuki (🔒 hepsi profesyonel onay gerektirir — bu ürün hukuki tavsiye vermez, `CLAUDE.md` StBerG)
| # | Konu | Duruş |
|---|---|---|
| H1 | RDG / Rechtsdienstleistung | BGH-Smartlaw (Az. II ZR 209/18): soru-katalogu üreteci = yazılım ürünü, danışmanlık **değil** — bireysel değerlendirme yapılmadığı sürece |
| H2 | Dil | "Muster / Vorlage / Vorschlag ohne Gewähr" · **asla** "rechtssicher / garantiert / für Ihren Fall geprüft" |
| H3 | Disclaimer | Ekranda + PDF footer'da: *"Muster ohne Gewähr; keine Rechtsberatung; im Zweifel Mietrecht-Fachanwalt / Haus & Grund"* (`legal_review.md:41` deseni; NK footer örneği `immo_api.py:3473`) |
| H4 | Geçersiz klozlar | BGH-iptal Schönheits-/Kleinreparatur varyantları **picker'da yok** (üretilemez) |
| H5 | Mietpreisbremse §556d | Motor **karar vermez** — sadece nötr uyarı toplar ("Obergrenze gilt — bitte prüfen") |
| H6 | Kaution §551 | 3× Kaltmiete otomatik **cap + uyarı** |
| H7 | Kloz metni telifi | Kendi metnimiz (BGB temelli) — Haus&Grund/DMB formu kopyalanmaz (`mietvertrag_architecture.md:26`) |
| H8 | Onay checkbox'ı | Üretimden önce "Angaben geprüft, ich versende eigenverantwortlich" (`legal_review.md:44`) |
| H9 | Launch öncesi | Mietrecht-Fachanwalt + StB doğrulaması (`legal_review.md:87`) — **kloz metinleri canlıya çıkmadan onaylanmalı** |

---

## 4. Yeniden kullanılacak bileşenler (envanter)

| Bileşen | Nerede | Kullanım |
|---|---|---|
| reportlab platypus PDF deseni | `immo_api.py:2634` (protokoll), `:3319` (nk) | PDF iskeleti kopyalanır |
| `StreamingResponse` teslim | `immo_api.py:2828` | Aynen |
| Frontend blob indirme | `index.html:3987` (dlProtokoll), `:3012` (dlWgb, en olgun hata işleme) | Aynen |
| Snapshot + finalize-lock | `NkAbrechnung` (`models.py:1076`) + `finalize_nk`/`unlock_nk` (`:3265`/`:3297`) | Model + akış deseni |
| Saf kural modülü deseni | `immo_nebenkosten.py`, `immo_protokoll.py` | `mietvertrag_template.py` bunu izler |
| Sihirbaz + finalize UI | `UebergabeWizard` (`index.html:2652`), `SignaturePad` (`:2621`) | Sözleşme sihirbazı deseni |
| Auto-fill veri kaynakları | `UserCompany`, `ImmoProperty`, `ImmoUnit`, `ImmoTenancy` | Doğrudan okuma |
| Disclaimer/StBerG dili | `legal_review.md`, NK footer `immo_api.py:3473` | Metin deseni |
| Akte entegrasyon yüzeyi | `index.html:4229+` | Yeni accordion bölümü |

---

## 5. Önerilen mimari (özet)

1. **Bir yeni tablo:** `ImmoMietvertrag` (tenancy'ye bağlı, versiyonlu, snapshot'lı). Mevcut tablolara dokunulmaz.
2. **Bir yeni saf modül:** `mietvertrag_template.py` (DB-free, şablon-parametrik, test edilebilir) — klozları üretir.
3. **Muhasebe açılmaz:** Mietvertrag bir **belge** üreticisidir; write-back tek güvenli update yolundan, Mietkonto tek kaynak korunur.
4. **Snapshot + finalize-lock (Principle A+B):** imzalanan sözleşme immutable; değişiklik = yeni Revision.
5. **PDF: DejaVuSans (Türkçe) + mevcut reportlab deseni.**
6. **UI: Akte içine "📄 Mietvertrag" bölümü + sihirbaz** — yeni tam-ekran yok.
7. **StBerG/RDG railleri kod seviyesinde:** geçersiz kloz üretilemez · Kaution cap · disclaimer · onay checkbox.

---

## 6. Fazlara bölünmüş geliştirme planı

> Mimari doküman §7'deki kilitli v1 scope'a sadık. NK/hukuki risk taşıdığı için küçük, doğrulanabilir adımlar.

**9.0 — Şablon motoru + font (UI YOK, en yüksek hukuki yoğunluk)**
`mietvertrag_template.py` saf modülü (§§535 ff klozları, BGH-geçerli, kendi metnimiz) · DejaVuSans font
kaydı · birim testleri (Kaution cap, geçersiz kloz üretilemez, Staffel adımları). **Şema/endpoint/UI yok.**
DoD: klozlar profesyonel onaya hazır metin olarak üretiliyor · font Türkçe basıyor · testler yeşil.

**9.1 — Model + endpoint + PDF (backend)**
`ImmoMietvertrag` tablosu (boot-time create_all) · create/patch/finalize/unlock/pdf endpoint'leri · snapshot
+ lock (NK deseni) · auto-fill. **UI yok.** DoD: create→finalize→pdf uçtan uca; snapshot immutable; eski
kayıtlar etkilenmez; suite yeşil.

**9.2 — UI: Akte'de Mietvertrag bölümü + sihirbaz**
Akte accordion · sihirbaz (auto-fill + guided seçimler + railler + onay checkbox) · PDF indirme · üç dil.
DoD: üç giriş yüzeyi tutarlı · disclaimer ekranda ve PDF'te · N=1 Akte görünümü bozulmadı · tarayıcı smoke.

**9.3 — Write-back + kapanış**
Finalize'de Kaltmiete/NK/Kaution → tenancy (tek güvenli yol) · Staffel → `miete_historie` · Faz kapanış raporu.
DoD: write-back Mietkonto'yu bozmuyor (SHA256 regresyon) · prod smoke · `SPRINT.md` + Masterplan #9 güncel.

**Ertelenen (mimari §7):** Indexmiete · befristet · Gewerbe · dijital imza · Anlagen-bundle · Mietspiegel lookup.

---

## 7. Definition of Done (Sprint 9 bütünü)

1. Küçük ev sahibi, Akte'den bir Wohnraummietvertrag (unbefristet / Staffel) **birkaç dakikada** üretebiliyor.
2. Taraflar/obje/mali koşullar **otomatik doluyor**, kullanıcı düzeltebiliyor.
3. **Yalnız BGH-geçerli klozlar** üretilebiliyor; geçersizler picker'da yok · Kaution cap · Mietpreisbremse uyarısı.
4. **Disclaimer** ekranda ve PDF footer'ında · üretimden önce **onay checkbox'ı**.
5. PDF **Türkçe karakter dahil** doğru basıyor (DejaVuSans).
6. Finalize → **immutable snapshot + lock**; değişiklik = yeni Revision.
7. Write-back **Mietkonto'yu bozmuyor** (tek kaynak; SHA256 regresyon kanıtı).
8. Muhasebe/NK motoru/Payment Service **değişmedi** (`git diff --stat` kanıtı — belge üreticisi).
9. Suite yeşil · babel/JSX yeşil · tarayıcı + prod smoke.
10. **Kloz metinleri canlıya çıkmadan profesyonel (Mietrecht) onaya sunuldu** (H9).
11. `SPRINT.md` kapanışı · Masterplan #9 durumu güncel.

---

## 8. Kodlamadan önce cevaplanması gereken sorular (product owner)

Mimari doküman §7 v1 scope'u kilitlemiş; yine de üç nokta netleşmeli:

1. **H9 — kloz metinleri:** 9.0'da ürettiğimiz Almanca kloz metinleri **canlıya çıkmadan** bir Mietrecht
   uzmanına/Haus&Grund'a doğrulatılacak mı? (Bu, launch'u geciktirebilir ama StBerG/RDG güvenliğinin şartı.)
2. **Write-back (§7):** finalize'de mali değerlerin tenancy'ye yazılması onaylanıyor mu, yoksa v1
   salt-okunur mu kalsın? (Mimari doküman "ON" diyor; teyit.)
3. **Gesamtschuldner (birden çok kiracı):** v1'de tek `mieter_name` yeterli mi, yoksa çok-kiracılı
   sözleşme v1 kapsamında mı? (Mimari §3.1 "mehrere Mieter" diyor ama model tek string — kapsam kararı.)

---

## Onay

Bu belge **yalnızca analiz + mimaridir**. Kod, migration, endpoint, UI, commit yoktur. Onay ve üç sorunun
cevabıyla birlikte **Sprint 9.0** (şablon motoru + font) için ayrı teknik tasarım hazırlanır.
