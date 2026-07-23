# Sprint 9.0 — Mietvertrag Generator · Technical Design (Architecture Freeze)

> **Belge türü:** Teknik tasarım (uygulama planı). **KOD YOK · migration YOK · endpoint YOK · UI YOK · commit/push/deploy YOK.**
> **🔒 Source of truth:** `.claude/mietvertrag_architecture.md` (2026-07-16, v1 scope KİLİTLİ) — bu tasarım onunla **çelişmez**, uygulamaya çevirir.
> **Onaylı Architecture Report:** `docs/design/Sprint_9_0_Mietvertrag_Architecture.md`.
> **Product decisions (KESİN, 2026-07-23):** ① Standart Alman konut kira sözleşmesi · kloz metinleri
> parametrik · canlı öncesi Mietrecht onayı · **kod içine hukuki yorum yok**. ② Write-back **ON** ·
> finalize sonrası tenancy güncellenir · immutable snapshot · **Revision** · eski sürümler değişmez.
> ③ Gesamtschuldner **v1 dışı** — tek kiracı.
> **Bağlayıcı:** Sprint 13 Akte (Composition Hub) korunur · **yeni tam-ekran YOK** · entegrasyon Akte içi
> "📄 Mietvertrag" bölümü · Architecture law (tek defter, muhasebe açılmaz).

---

## 1. Veri modeli

**Tek yeni tablo: `ImmoMietvertrag`** (source of truth §2 ile birebir). Mevcut tablolara dokunulmaz;
boot-time `create_all` ile gelir (Sprint 1.1/2.1/3.x deseni), ALTER/migration aracı yok.

| Kolon | Tip | Null | Anlam |
|---|---|---|---|
| `id` | Integer PK | — | |
| `user_id` | Integer, index | ✅ değil | veri izolasyonu (her sorgu filtreler) |
| `tenancy_id` | Integer (soft FK → `immo_tenancy.id`) | ✅ değil | sözleşme bir tenancy'ye bağlı |
| `status` | String(10) | ✅ değil | `entwurf` \| `final` (default `entwurf`) |
| `vertrag_json` | Text | ✅ | sihirbaz seçimleri (yapılandırılmış JSON) — taslakta canlı |
| `html_snapshot` | Text | ✅ | **finalize'de donan belge** (Principle A); taslakta NULL |
| `vertrag_version` | Integer | ✅ | kloz-set versiyonu (`TEMPLATE_VERSION` damgası) |
| `revision` | Integer | ✅ değil | sürüm no (v1, v2…); default 1 |
| `supersedes_id` | Integer (self-ref, soft) | ✅ | bu revision hangi sözleşmenin yerine geçti |
| `created_at` | DateTime | — | |
| `finalized_at` | DateTime | ✅ | finalize damgası |
| `is_deleted` | Boolean | — | soft-delete (mevcut desen) |

**`vertrag_json` şeması** (S2'deki tüm sözleşme seçimleri **yeni kolon açmadan** burada yaşar):
```
{
  "vertrag_typ": "wohnraum_unbefristet" | "wohnraum_staffel",   // v1 iki tip
  "parteien":   { "vermieter": {...auto}, "mieter": {...auto, tek kiracı} },
  "objekt":     { "adresse", "wohnung", "wohnflaeche", "zimmer?", "keller?", "stellplatz?", "schluessel?" },
  "mietzeit":   { "typ": "unbefristet"|"staffel", "beginn", "staffel_schritte?": [{ab, kaltmiete}] },
  "miete":      { "kaltmiete", "nk_voraus", "heizkosten_voraus", "zahlungstermin", "bankverbindung" },
  "kaution":    { "betrag", "art" },                            // motor 3× cap uygular
  "betriebskosten_umlage": [ "wasser", "muell", ... ],          // BetrKV kalemleri
  "klauseln":   { "schoenheitsrep": "keine"|"bgh_gueltig", "kleinrep": {aktiv, einzel_cap, jahres_cap},
                  "tierhaltung": "...", "untervermietung": "..." },
  "template_version": <int>,
  "disclaimer_ack": false                                       // onay checkbox (finalize'de true)
}
```

> **Gesamtschuldner (v1 dışı):** `parteien.mieter` tek kiracıdır. Şema ileride `mieter: [...]` listesine
> genişleyecek biçimde tasarlanır ama v1 tek nesne kabul eder (yeni kolon/tablo gerekmez).

### §1.1 Motor dispatch (BAĞLAYICI — tasarım kontrolü 2026-07-23)

`render()` sözleşme tipine göre davranışı **hardcoded `if/elif` zinciriyle DEĞİL**, bir **registry**'den
veri çekerek belirler. Böylece yeni sözleşme tipi (Indexmiete · Befristet · Gewerbe · Garage · Stellplatz ·
ileride WG) eklemek = **yeni registry + katalog girdisi (veri)**; `render()` ve mevcut tiplerin kodu **değişmez**.

```
VERTRAG_TYPEN = {                      # registry: tip → kural seti (veri, kod değil)
  "wohnraum_unbefristet": { "klausel_ids": [...sıralı...], "rails": {...}, "labels": {...} },
  "wohnraum_staffel":     { "klausel_ids": [...],          "rails": {...}, ... },
  # ileride: "wohnraum_index", "wohnraum_befristet", "gewerbe", "garage", "stellplatz"
}
KLAUSEL_KATALOG = { "<klausel_id>": { "ueberschrift", "text_template", "typ" }, ... }
```

**İki kural (registry + per-type):**
1. **Registry dispatch:** `render(vertrag_json)` → `typ = VERTRAG_TYPEN[vertrag_json["vertrag_typ"]]` →
   `typ["klausel_ids"]` sırasıyla `KLAUSEL_KATALOG`'tan klozları basar. Yeni tip = yeni sözlük girdisi.
2. **Railler tipe bağlı (global sabit YOK):** Kaution 3× cap · §573c Kündigungsfristen · kiracı-koruyucu
   klozlar her tipin `rails`'ine aittir. Örn. Gewerbe'de Wohnraum cap'i uygulanmaz — çünkü rail global
   değil, tipe bağlı. Böylece bir tipin kuralı başka tipi yanlış etkilemez.

> **Değişmeyen sınır:** kloz **metni** her zaman yeni veridir (parametrikliğin amacı); yeni rejim için
> sihirbaza yeni adım = yeni UI. Kilitleme yalnızca **motor + katalog çekirdeği** içindir — oraya yeni tip
> için dokunulmaz.

---

## 2. Snapshot yaşam döngüsü (Principle A)

NK Abrechnung snapshot'ıyla **birebir aynı disiplin** (`immo_api.py:2980` okuma, `:3287` yazma):

```
ENTWURF (taslak)
  · vertrag_json canlı; kullanıcı düzenler
  · html_snapshot = NULL
  · GET .../pdf  →  template motorundan CANLI render (henüz imzalanmadı)
        │
        │  POST .../finalisieren   (disclaimer_ack zorunlu)
        ▼
FINAL (immutable)
  · html_snapshot = motorun o anki tam çıktısı (DONAR)
  · vertrag_version = TEMPLATE_VERSION damgası
  · finalized_at = now
  · GET .../pdf  →  SADECE html_snapshot'tan render (asla canlı master-data'dan)
```

**Neden:** sözleşme imzalandıktan sonra tenancy'de Kaltmiete/Kaution değişse bile **imzalanan metin
değişmemeli.** Okuma yüzeyi (`_vertrag_dict` benzeri) final ise snapshot'tan, taslak ise canlı motordan
servis eder — NK `_abr_dict` (`immo_api.py:2962`) deseni.

---

## 3. Revision mantığı (Principle B — Finalize = Lock)

Final sözleşme **salt-okunur**; her yazma yolunda guard (`require_editable` deseni, `immo_protokoll.py:172`).
Değişiklik **tek yoldan**:

```
Vertrag v1 (FINAL, html_snapshot dolu)
      │  POST .../revision   (yetkili düzeltme)
      ▼
Vertrag v2 (ENTWURF)         · revision = 2 · supersedes_id = v1.id
      · vertrag_json = v1'in kopyası (düzenlenebilir başlangıç)
      · v1 DOKUNULMAZ (is_deleted=false, snapshot sabit — kanıt olarak kalır)
      │  finalize
      ▼
Vertrag v2 (FINAL)           · v1 hâlâ okunabilir/PDF'lenebilir (geçmiş)
```

- **Eski sürümler değiştirilemez** (product decision ②): v1'in `html_snapshot`'ı ve `vertrag_json`'ı sabit.
- Akte "📄 Mietvertrag" bölümü **en güncel** (max revision) sözleşmeyi gösterir; "Versionen" alt-listesi
  eski revizyonları PDF'leriyle listeler.
- Unlock-in-place **yok** (NK'daki `unlock_nk`'tan farklı): bir Mietvertrag için "yeni Revision" hukuken
  daha doğru — imzalanmış kağıt geri açılmaz, yenisi yapılır. *(Source of truth §6 "new Revision (v2)".)*

---

## 4. Write-back akışı (product decision ②: ON)

Finalize anında, sözleşmede anlaşılan mali değerler tenancy'ye **tek güvenli yoldan** yazılır — Mietkonto/NK
tek doğruluk kaynağı bozulmaz (Architecture law: muhasebe açılmaz).

```
finalisieren:
  1. html_snapshot doldur + status=final + finalized_at  (belge tarafı)
  2. WRITE-BACK (mevcut update yollarından, yeni hesap YOK):
       tenancy.kaltmiete        ← vertrag_json.miete.kaltmiete
       tenancy.nk_voraus        ← vertrag_json.miete.nk_voraus
       tenancy.heizkosten_voraus← vertrag_json.miete.heizkosten_voraus
       tenancy.kaution          ← vertrag_json.kaution.betrag
       tenancy.von              ← vertrag_json.mietzeit.beginn   (yalnız boşsa/değişmişse)
     Staffel ise: vertrag_json.staffel_schritte → tenancy.miete_historie (seed)
```

**Kritik kurallar:**
- Write-back **`monat_soll`'u yeniden hesaplamaz** — sadece tenancy alanlarını set eder; Soll bu
  alanlardan zaten türer (`immo_rules.py`). İkinci defter oluşmaz.
- Write-back **idempotent**: aynı finalize iki kez tetiklenirse tenancy aynı değere set edilir.
- **Regresyon güvencesi (DoD):** write-back'ten *önce* ve *sonra* tek-tenancy Mietkonto/accounting çıktısı
  SHA256 ile karşılaştırılır — değerler yalnız sözleşmede değişenler kadar değişmeli, başka hiçbir şey.
- Revision (v2) finalize'inde de write-back çalışır (en güncel anlaşma tenancy'ye yansır).

---

## 5. PDF üretim akışı

Mevcut reportlab **platypus** deseni (`protokoll_pdf` `immo_api.py:2634`, `nk_pdf` `:3319`) + StreamingResponse
(`:2828`). Akış:

```
GET /immo/mietvertrag/{id}/pdf
  · final ise  →  html_snapshot'ı flowable'lara çevir (DONMUŞ metin)
  · taslak ise →  mietvertrag_template.render(vertrag_json) CANLI
  · reportlab: SimpleDocTemplate(A4, margins) + Paragraph/Table/Spacer + KeepTogether (kloz bölünmesin)
  · HER SAYFA footer: disclaimer (§7 H3) — "Muster ohne Gewähr; keine Rechtsberatung; …"
  · StreamingResponse(media_type="application/pdf", Content-Disposition: attachment)
```

- **Klozları saf modül üretir:** `mietvertrag_template.py` (DB-free, `immo_nebenkosten.py` deseni) →
  `render(vertrag_json) -> [ {tip:"heading"|"clause"|"table"|"signature", metin, ...} ]`. PDF katmanı bu
  yapıyı reportlab flowable'larına basar. **Hukuki metin koddan değil, bu modülün parametrik kloz
  kataloğundan gelir** (product decision ①: kod içine hukuki yorum yok, metinler parametrik).
- **İmza:** v1 print-and-sign — PDF'te boş `Ort/Datum + Unterschrift` blokları (source of truth §7).
  Dijital imza (`SignaturePad`) ertelendi.

---

## 6. DejaVuSans Unicode stratejisi (🔴 kritik risk — Architecture Report T1)

**Sorun:** mevcut tüm PDF'ler Helvetica/Latin-1 → Türkçe ş/ğ/İ/ı/ç `.notdef` (kutu) basar. Mieter/Vermieter
adı sözleşmeye ham girer.

**Strateji (güncel — 9.0a'da uygulandı, product owner onayı 2026-07-23):** İlla DejaVu olmak zorunda değil;
**"DejaVu veya eşdeğer bir Unicode TTF"** yeterli. Seçilen çözüm **reportlab-bundled Vera (Bitstream Vera
Sans)** — repoya ekstra font binary'si eklenmez, prod'da garanti (reportlab requirements ile geliyor), ve
Türkçe (ş/ğ/İ/ı/ç) + Almanca (ä/ö/ü/ß) + € tamamını **eksiksiz** basıyor (test doğrulandı).

1. **`autotax/pdf_fonts.py`** — idempotent kayıt: **repo-bundled DejaVuSans** (`autotax/assets/fonts/`)
   varsa onu, yoksa **reportlab-bundled Vera**'yı `"AtxUnicode"` ailesi (regular+bold) olarak kaydeder.
   Böylece ileride DejaVu eklenirse otomatik ona geçer; bugün binary gerekmez.
2. **Mietvertrag stilleri bu aileye bağlanır** (`fontName=FONT_NAME`), diğer PDF'lerin default'una dokunulmaz.
3. **Kapsam:** yalnız Mietvertrag PDF'i. WGB/Mahnung/Protokoll aynı Türkçe riskini taşımaya devam eder ama
   **bu sprintin kapsamı dışı** (ayrı iyileştirme).
4. **Test (9.0a'da yeşil):** kayıtlı font'un face'inde tüm Türkçe+€³ glyph'leri var, `.notdef` yok.

---

## 7. Akte entegrasyonu (Sprint 13 Composition Hub korunur)

**Yeni tam-ekran YOK.** Akte'ye (`index.html:4229+`) yeni bir accordion bölümü — Protokolle bölümünün
(Sprint 13.0'da eklendi) hemen yanına, **aynı desen**:

```
📄 Mietvertrag                                    [durum: Entwurf / Final v2 · tarih / "Noch kein Vertrag"] ▸
  (açılınca, lazy — mevcut akteProt/akteZH deseni)
  · Sözleşme listesi: revision · status · finalized_at · [PDF]
  · [Neuen Vertrag erstellen]  →  sihirbaz (aşağı)
  · hata durumu: _errBox + "Erneut versuchen"  (Sprint 13.0 hata≠boş deseni)
```

- **Yükleme:** `openAkte`/`loadAkte` içinde **yeni eager çağrı eklenmez** — bölüm lazy (accordion açılınca
  `GET /immo/mietvertraege?tenancy_id=`). Sprint 13.0'ın performans dersine uyar.
- **Composition hub ilkesi korunur:** Akte veri üretmez; sözleşme durumunu **gösterir**, sihirbaza götürür.
- **N=1 / mevcut Akte görünümü bozulmaz** (Sprint 13.0 regresyon güvencesi).

---

## 8. API tasarımı (mevcut Immo router desenleri; aggregate endpoint YOK)

| Endpoint | İş | Desen kaynağı |
|---|---|---|
| `POST /immo/tenancies/{tid}/mietvertrag` | taslak oluştur (`vertrag_json`) | `create_tenancy` |
| `PATCH /immo/mietvertrag/{id}` | taslak güncelle (final ise 409) | `update_tenancy` + `require_editable` |
| `GET /immo/mietvertraege?tenancy_id=` | tenancy'nin sözleşmeleri (liste, revision'lı) | `list_protokolle` |
| `GET /immo/mietvertrag/{id}` | tek sözleşme (final→snapshot, taslak→canlı) | `_abr_dict` |
| `POST /immo/mietvertrag/{id}/finalisieren` | snapshot + lock + **write-back** | `finalize_nk` |
| `POST /immo/mietvertrag/{id}/revision` | yeni v(n+1) taslağı (eski dokunulmaz) | (yeni, §3) |
| `GET /immo/mietvertrag/{id}/pdf` | StreamingResponse | `protokoll_pdf` |
| `DELETE /immo/mietvertrag/{id}` | soft-delete (yalnız taslak) | `delete` (protokoll) |

- Hepsi `Depends(get_current_user)` + `user_id` filtresi + `_own_*` sahiplik guard'ı.
- **`finalisieren`** disclaimer_ack olmadan **400**; write-back tek güvenli yoldan.
- **Muhasebe endpoint'i eklenmez, ikinci defter yok** (Architecture law).

---

## 9. UI akışı

**Sihirbaz** — `UebergabeWizard` (`index.html:2652`) desenini izler (adımlı, `locked` durumu, finalize onayı).
Yeni tam-ekran değil; Akte içinden açılan overlay/panel.

```
Akte → 📄 Mietvertrag → [Neuen Vertrag erstellen]
  Adım 1 — Parteien & Objekt   (auto-fill: Vermieter/UserCompany, Mieter/tenancy, Wohnung/unit — düzenlenebilir)
  Adım 2 — Mietzeit            (unbefristet | Staffel; Staffel ise adımlar)
  Adım 3 — Miete & Kaution     (auto-fill kaltmiete/nk/heiz/kaution; Kaution 3× CAP + uyarı; Zahlungstermin)
  Adım 4 — Klauseln (guided)   (Schönheitsrep: keine|BGH-gültig · Kleinrep cap on/off · Tierhaltung · Umlage listesi)
                                → GEÇERSİZ klozlar picker'da YOK (toggle değil)
  Adım 5 — Prüfen & Erstellen  (önizleme + Mietpreisbremse nötr uyarı + ☑ disclaimer_ack)
      · [PDF-Vorschau]  (taslak PDF, canlı)
      · [Fertigstellen] → finalisieren (snapshot+lock+write-back) → Akte'ye döner, Final görünür
```

- **Diller:** DE birincil · TR · EN (`_L`/`_iL` deseni).
- **Disclaimer** hem ekranda (Adım 5) hem PDF footer'ında.
- **Final sözleşmede** sihirbaz salt-okunur; değişiklik için "Neue Revision" butonu.
- Üç yüzey tutarlı olmalı (Sprint 2.1 dersi) — ama v1'de tek giriş noktası Akte; ileride kiracı kartı eklenebilir.

---

## 10. Test stratejisi

**Birim (saf modül — `mietvertrag_template.py`, DB-free):**
- Kaution > 3× Kaltmiete → cap + uyarı
- Geçersiz kloz **üretilemez** (picker'da yok; motor yalnız geçerli varyant döndürür)
- Staffel adımları → doğru kloz metni + `miete_historie` seed formatı
- `render(vertrag_json)` deterministik; `TEMPLATE_VERSION` damgası

**Font (T1):**
- Türkçe adlı sözleşme render → PDF'te font `DejaVuSans`, `.notdef` yok

**Snapshot / Revision:**
- finalize → `html_snapshot` doluyor, `status=final`; sonraki PATCH **409**
- final PDF master-data değişse de **byte-identical** (snapshot'tan)
- revision → v2 taslak, v1 **dokunulmaz** (snapshot + json sabit)

**Write-back (regresyon — en kritik):**
- finalize → tenancy alanları güncellendi
- **tek-tenancy Mietkonto/accounting SHA256:** write-back'in değiştirdiği alanlar dışında **hiçbir şey değişmedi**
- idempotent: iki finalize aynı sonucu verir
- `monat_soll` yeniden hesaplanmadı (tek defter korundu)

**UI:**
- `_babelcheck.js` PARSE OK · `check_jsx_structure.py` BALANCED
- Akte N=1 görünümü bozulmadı · sihirbaz üç dil · disclaimer görünür
- Yerel gerçek-app tarayıcı smoke (Sprint 13.0 deseni): sihirbaz → PDF → Akte'de Final

**Regresyon:** mevcut suite tamamı yeşil; **backend'de belge dışı hiçbir dosya değişmedi**
(`immo_rules.py`, `immo_payments.py`, `immo_nebenkosten.py` → 0 satır; write-back yalnız tenancy alan set'i).

---

## 11. Fazlara bölünmüş geliştirme planı

> Source of truth §7 v1 scope'a sadık. Hukuki/muhasebe riski taşıdığı için küçük, doğrulanabilir adımlar.
> Her adım ayrı commit; her adım sonrası test + (gerekirse) yerel smoke. Push/deploy ayrı onayla.

**9.0a — Şablon motoru + font (UI YOK · en yüksek hukuki yoğunluk)**
`mietvertrag_template.py` saf modülü (parametrik kloz kataloğu, `TEMPLATE_VERSION`) · DejaVuSans kaydı ·
birim testleri (cap, geçersiz-kloz-yok, Staffel, font-Türkçe). **Şema/endpoint/UI yok.**
*Kloz metinleri bu adımda üretilir → canlıya çıkmadan Mietrecht onayına sunulacak (H9).*
**DoD:** motor deterministik · font Türkçe basıyor · geçersiz kloz üretilemiyor · testler yeşil.

**9.0b — Model + endpoint + PDF (backend · UI YOK)**
`ImmoMietvertrag` (boot-time create_all) · create/patch/list/get/finalisieren/revision/pdf endpoint'leri ·
snapshot+lock (NK deseni) · **write-back** (tek güvenli yol) · auto-fill.
**DoD:** create→finalize→pdf uçtan uca · snapshot immutable · revision eskiyi bozmuyor · **write-back SHA256
regresyonu temiz** · belge-dışı backend 0 satır · suite yeşil.

**9.0c — Akte UI + sihirbaz**
Akte "📄 Mietvertrag" accordion (lazy) · 5 adımlı sihirbaz · railler (cap/geçersiz-kloz/Mietpreisbremse) ·
disclaimer + ack · PDF indirme · üç dil.
**DoD:** N=1 Akte bozulmadı · disclaimer ekran+PDF · babel/JSX yeşil · yerel tarayıcı smoke (sihirbaz→PDF→Final).

**9.0d — Kapanış**
Faz kapanış raporu · Masterplan #9 durumu · **kloz metinlerinin profesyonel onay durumu kayda geçer** (canlıya
çıkış onaya bağlı).
**DoD:** prod smoke · `SPRINT.md` kapanış · #9 güncel · H9 onay durumu net.

**Ertelenen (source of truth §7):** Indexmiete · befristet · Gewerbe · **Gesamtschuldner/çok-kiracı/WG** ·
dijital imza · Anlagen-bundle · Mietspiegel lookup.

---

## 12. Risk analizi

### Teknik
| # | Risk | Seviye | Önlem |
|---|---|---|---|
| T1 | Türkçe karakter PDF'te bozuk (Helvetica) | 🔴 | DejaVuSans kaydı (§6) — 9.0a'nın parçası; font-Türkçe testi |
| T2 | Write-back Mietkonto'yu bozar (ikinci defter) | 🔴 | Tek güvenli update yolu · `monat_soll` yeniden hesaplanmaz · SHA256 regresyon |
| T3 | Snapshot olmadan final metin kayar | 🔴 | `html_snapshot` + `vertrag_version` (Principle A) |
| T4 | Kloz metni inline string olursa bakımsız/hataya açık | 🟠 | DB-free parametrik `mietvertrag_template.py` |
| T5 | Çok sayfalı belgede kloz bölünmesi | 🟡 | reportlab `KeepTogether` + footer repeat |
| T6 | Revision zinciri karışır (hangi güncel?) | 🟡 | `revision` + `supersedes_id`; Akte max-revision gösterir |

### Hukuki (🔒 hepsi profesyonel onay gerektirir — ürün hukuki tavsiye vermez, `CLAUDE.md` StBerG)
| # | Konu | Duruş |
|---|---|---|
| H1 | RDG/Rechtsdienstleistung | BGH-Smartlaw: soru-katalogu üreteci = yazılım ürünü (source of truth §0) |
| H2 | Dil | "Muster/Vorlage/Vorschlag ohne Gewähr" · asla "rechtssicher/garantiert" |
| H3 | Disclaimer | ekran + PDF footer (her sayfa) |
| H4 | Geçersiz klozlar | picker'da **yok** (üretilemez), toggle değil |
| H5 | Mietpreisbremse §556d | motor **karar vermez** — nötr uyarı |
| H6 | Kaution §551 | 3× cap + uyarı (motor) |
| H7 | Kloz telifi | kendi metnimiz (BGB temelli); Haus&Grund/DMB kopyalanmaz |
| H8 | Onay | `disclaimer_ack` finalize'de zorunlu |
| **H9** | **Launch öncesi** | **kloz metinleri canlıya çıkmadan Mietrecht-Fachanwalt onayına sunulur — 9.0d'de kayıt altına alınır, onaysız canlı YOK** |

---

## 13. Definition of Done (Sprint 9.0)

1. Küçük ev sahibi, **Akte'den** bir Wohnraummietvertrag (unbefristet/Staffel, **tek kiracı**) birkaç dakikada üretebiliyor.
2. Taraflar/obje/mali koşullar **otomatik doluyor**, kullanıcı düzeltebiliyor.
3. **Yalnız BGH-geçerli klozlar** üretilebiliyor · Kaution 3× cap · Mietpreisbremse nötr uyarı.
4. **Disclaimer** ekranda ve PDF footer'ında (her sayfa) · finalize'de **`disclaimer_ack` zorunlu**.
5. PDF **Türkçe karakter dahil** doğru basıyor (DejaVuSans; `.notdef` yok).
6. Finalize → **immutable snapshot + lock**; final PDF byte-identical (snapshot'tan).
7. Değişiklik = **yeni Revision**; eski sürüm dokunulmaz, PDF'lenebilir.
8. **Write-back ON:** finalize tenancy'yi güncelliyor, **Mietkonto'yu bozmuyor** (SHA256 regresyon kanıtı).
9. Muhasebe/NK motoru/Payment Service **değişmedi** (`git diff --stat` — belge üreticisi; write-back yalnız tenancy alan set'i).
10. Suite yeşil · babel/JSX yeşil · Akte N=1 bozulmadı · yerel + prod smoke.
11. **Kloz metinleri profesyonel (Mietrecht) onaya sunuldu; onaysız canlıya çıkış yok** (H9).
12. `SPRINT.md` kapanışı · Masterplan #9 durumu güncel · Sprint 13 Akte hub mimarisi korundu.

---

## Onay

Bu belge **teknik tasarımdır**; kod/migration/endpoint/UI/commit yoktur. Source of truth
`.claude/mietvertrag_architecture.md` ile çelişmez; onu uygulamaya çevirir. Onay sonrasında **Sprint 9.0a**
(şablon motoru + font) kodlamasına geçilir — her adım ayrı commit, push/deploy ayrı onayla.
