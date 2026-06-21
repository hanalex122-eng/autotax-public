# Immobilien — P1→P4 Uygulama Planı (Mietkonto / Aksiyon Platformu)

**Durum:** REPAIR MODE · PRODUCT VALUE SHIFT — "Excel alternatifi" → "aksiyon üreten landlord platformu".
**Tarih:** 2026-06-21 · **Kapsam:** `autotax/immo_api.py`, `autotax/models.py`, `autotax/db.py`, `index.html`
**Kural:** ADDITIVE & İZOLE. OCR/VAT/Kassenbuch/Rechnungen'e SIFIR dokunuş. Mevcut `_accounting`/`_portfolio`/`_cockpit` **formülleri değişmez** — üstüne ledger eklenir.

---

## 0. ÇEKİRDEK KAVRAM — "Konto" (en kritik karar)

Bugünkü sistem **türetilmiş/yıllık** hesap yapıyor: `rückstand = aktif_ay × kaltmiete − Σödeme`. Bu "hangi ay eksik?" sorusunu cevaplayamaz, kısmi ödemeyi aya bağlayamaz, gün-bazlı Mahnung üretemez.

**Yeni model: Mietkonto = ay-ay materyalize edilmiş Soll-Stellung defteri.**

İki tip "Konto":
1. **Mieter-Konto** (her tenancy için): her aktif ay → 1 borç satırı (Soll). Ödemeler (`immo_rent`) bu aylara mahsup edilir. Saldo = Σ Soll − Σ Ist.
2. **Leerstand-Konto** (her boş unit-ay için): kiracısı olmayan her ay → 1 "boşluk" satırı (kayıp = `unit.soll_miete`). Bu da bir hesap olarak izlenir/değerlendirilir → senin "ev boşsa bir id bir kontosu olmalı" talebin.

**Karar: Materyalize tablo (`immo_charge`) — önerilen.**
- **Neden A (materyalize):** "sistem her ay otomatik kira borcu üretmeli" = birebir bu. Gün-bazlı gecikme (Fälligkeit), kısmi ödeme mahsubu, değişmez kayıt, Mahnung aging — hepsi temiz çıkar. Ledger UI doğrudan tablo.
- **Neden B değil (virtual/derived):** tablosuz, on-the-fly grid. Daha az kod ama: due-date/aging muğlak, kısmi ödeme ayı belirsiz, denetim izi yok. Senin istediğin Rent Alert Engine'i zorlaştırır.
- **Sonuç:** A. Aşağıdaki tüm plan A üzerine kurulu.

**Generation mantığı (idempotent):** `ensure_charges(user, year)` → her tenancy'nin aktif ayları + her unit'in boş ayları için eksik `immo_charge` satırlarını üretir. Cron YOK (kullanıcı tercihi: otomatik arka-plan iş yok). Üretim **lazy**: cockpit/mietkonto/dashboard çağrıldığında ilgili yıl için `ensure_charges` çalışır (hızlı, sadece eksikleri ekler). Gelecek aylar üretilmez — sadece bugüne kadar olan + içinde bulunulan ay.

---

## P1 — KİRAYI TAHSİL ETME

### 1.1 Mietkonto (ay-ay ledger)

**Teknik tasarım**
- Yeni tablo `immo_charge`: tenancy başına aylık Soll satırı + boş-unit aylık Leerstand satırı.
- `ensure_charges(db, uid, year)`: idempotent. Her unit için 1..ref_month döngüsü; ayda aktif tenancy varsa `kind=rent` (soll=kaltmiete, fällig_am = ayın 3'ü konfigden), aktif tenancy yoksa `kind=vacancy` (soll=unit.soll_miete, ist=0, alacak DEĞİL — sadece kayıp metriği).
- Ödeme mahsubu: `immo_rent` satırları aya göre eşlenir (datum.month + tenancy_id). Bir ayın `ist`'i = o aya düşen ödemeler toplamı. Status: `paid` (ist≥soll), `partial` (0<ist<soll), `open` (ist=0).
- **Mevcut formüllerle tutarlılık:** `_accounting`/`_portfolio` aynı kalır (regresyon riski yok). Ledger ayrı katman; ileride bu motorlar ledger'dan okuyacak şekilde refactor edilebilir ama bu sprintte DEĞİL.

**DB değişiklikleri** (`models.py` + `db.py` idempotent ALTER deseni)
```
immo_charge:
  id, user_id(FK,idx), property_id(FK,idx), unit_id(FK,idx), tenancy_id(FK,nullable,idx)
  jahr(Int,idx), monat(Int 1-12), kind(String: rent|vacancy)
  soll(Float), faellig_am(Date)
  created_at, is_deleted, deleted_at
  UNIQUE(user_id, unit_id, jahr, monat)   # idempotency garantisi
```
`ist`/`status` saklanmaz — ödeme `immo_rent`'ten türeyince stale olur; **runtime'da hesaplanır** (charge + o ay-tenancy ödemeleri). Sadece Soll-Stellung materyalize.

**API değişiklikleri** (`immo_api.py`)
- `GET /immo/tenancies/{tid}/mietkonto?year` → `{rows:[{monat, monat_text, soll, ist, status, faellig_am, tage_ueberfaellig}], summe:{soll,ist,saldo}}`
- `GET /immo/properties/{pid}/mietkonto?year` → tüm unit/tenancy/leerstand satırları (matris görünüm).
- `POST /immo/properties/{pid}/charges/ensure?year` → manuel "borçları üret" (idempotent; UI buton + lazy çağrı ikisi de kullanır).
- `_ensure_charges` helper + `_charge_status(charge, rents)` helper.

**UI değişiklikleri** (`index.html` · `ImmobilienView`)
- Tenancy detayında **"Mietkonto" sekmesi**: 12 ay tablo, her ay yeşil(paid)/sarı(partial)/kırmızı(open) rozet + Fälligkeit + gecikme günü. "Zahlung erfassen" satır-içi (ay önceden dolu).
- Property "Übersicht"e küçük **Mietkonto-Matrix** (unit × ay grid, renk hücreler) — boş aylar gri "leer".

**Test planı**
- `ensure_charges` idempotent: 2× çağır → satır sayısı sabit (UNIQUE).
- Tenancy von=2026-03, bis=null, kaltmiete=800 → Mart..ref_month arası `rent` satırları, Oca-Şub yok.
- Boş unit (tenancy yok) → tüm aylar `vacancy` satırı, ist=0.
- Kısmi ödeme: soll=800, ödeme=500 → status=partial, saldo=300.
- Mevcut `_accounting` çıktısı değişmedi (snapshot karşılaştır).

### 1.2 Rent Alert Engine (gün-bazlı)

**Teknik tasarım**
- `tage_ueberfaellig = today − faellig_am` (status≠paid olan charge'lar için).
- Bucket: `1-7 → warning`, `8-30 → high`, `30+ → critical`. (0 veya negatif → henüz fällig değil, alert yok.)
- Portfolio toplulaştırma: kaç tenancy'de açık charge var, toplam açık tutar, en kötü bucket.

**DB:** yok (charge + rent'ten türetilir).

**API**
- `GET /immo/alerts?year` → `{summary:{ueberfaellige_mieter, offener_betrag, critical, high, warning}, items:[{tenancy_id, mieter_name, unit, offen, tage, bucket}]}`
- `_cockpit`'e `rent_alerts` bloğu ekle (mevcut `actions`'ı bu gün-bazlı veriyle besle — "X Mon" yerine "X Tage").

**UI**
- Cockpit / ImmoDashboardView kartları: `🔴 2 Mieter nicht gezahlt` · `🔴 Offene Miete: X €`. Bucket renkli.
- Mevcut "Heute wichtig" aksiyon metinlerini gün-bazlıya çevir.

**Test**
- fällig_am bugün−3 → warning; bugün−15 → high; bugün−45 → critical.
- Ödenmiş charge → alert YOK. Gelecek ay charge → alert YOK.
- Sınır: tam 7 gün→warning, 8→high, 30→high, 31→critical.

### 1.3 Mahnung Generator (mevcut → genişlet)

**Teknik tasarım** — `create_mahnung` ZATEN var (satır 1118). Yapılacak:
- Stufe metinleri kullanıcı isteğine hizala: `1 Erste Mahnung · 2 Zweite Mahnung · 3 Letzte Mahnung` (mevcut: Zahlungserinnerung/1./2.). `_STUFE_TXT` güncelle.
- Mahnung tutarı artık **Mietkonto'dan** gelsin (ay-ay açık kalemler listesi), tek yıllık sayı değil. PDF'e **dönem dökümü** (hangi aylar açık) eklenir.
- Adres bloğu: Vermieter (UserCompany'den varsa) + Mieter + Objekt/Whg. (Şu an Mieter adı var, adres eksik — eklenecek.)

**DB:** `immo_mahnung` mevcut yeterli. (Ops: `bis_datum` zahlungsfrist kolonu — gerekirse idempotent ALTER.)

**API**
- `POST /immo/tenancies/{tid}/mahnung` (mevcut) → body'e açık-aylar listesi + adres render.
- Stufe önerisi: son Mahnung stufesi + geçen süreye göre "önerilen stufe" döndür (UI default).

**UI**
- Mietkonto / Mieter-Risiko satırında **"Mahnung"** butonu → stufe seç (Erste/Zweite/Letzte) → PDF indir. History listesi (mevcut `list_mahnungen`).

**Test**
- 3 ay açık (800×3=2400) → PDF tutarı 2400, 3 dönem listelenir.
- Stufe 1/2/3 doğru başlık. Adres bloğu UserCompany varsa dolu, yoksa düşmeden boş.

---

## P2 — GELİR KAYBI ANALİZİ

### 2.1 Leerstand Engine (mevcut → konto'laştır)

**Teknik tasarım** — Leerstandsverlust ZATEN hesaplanıyor (`_accounting`, `top_vacancies`). Eksik: **daire-bazlı boş GÜN sayısı + kümülatif kayıp** ve "Leerstand-Konto" olarak izlenebilirlik.
- `immo_charge` `kind=vacancy` satırları = boş ayların kaydı. Gün sayısı: tenancy boşluklarından (`bis` → sonraki `von` arası) hesaplanır.
- Her unit için: `leerstand_tage` (yıl içi), `verlust = boş_ay × soll_miete`, `leer_seit` (son tenancy.bis).

**DB:** yok (charge vacancy + tenancy gap'lerinden).

**API**
- `GET /immo/leerstand?year` → `{units:[{unit_id, name, property, leer_seit, tage, verlust, risk}], summe_verlust}`
- `_cockpit` `vacancy` bloğu zaten benzer → gün/kayıp alanlarını bu helper'dan al (tek kaynak).

**UI**
- Cockpit "Leerstand-Zentrale" mevcut → her daire: `Wohnung 3 · Leerstand 127 Tage · Verlust 3.810 €`. (Tasarım yok, sadece doğru veri.)

**Test**
- bis=2025-09-01, sonra von yok → 2026'da 12 ay boş, tage doğru, verlust=12×soll.
- İki tenancy arası 2 ay boşluk → o 2 ay vacancy, doğru gün.

### 2.2 Action Center (mevcut → besle)

**Teknik tasarım** — `_cockpit.actions` "Heute wichtig" ZATEN var (satır 1009). Yapılacak: P1.2 gün-bazlı alert + P2.1 leerstand gün/kayıp + sözleşme-bitiş verisiyle besle. Yeni özellik değil, **veri kalitesi** yükseltme.
- Severity sıralı (red→orange→yellow). Tipler: `missing_rent/debt` (gün-bazlı), `vacancy` (gün+kayıp), `contract_ending` (gün).

**API:** `_cockpit` çıktısı zenginleşir, yeni endpoint yok.

**UI:** ImmoDashboardView "HEUTE WICHTIG" bloğu (mevcut) → metinler net:
```
🔴 2 Mieter haben nicht gezahlt
🟠 Wohnung 3 seit 4 Monaten leer
🟡 1 Vertrag endet in 30 Tagen
🔴 Offene Miete: 2.550 €
```

**Test:** 3 senaryo (borç+boşluk+biten sözleşme) → doğru sayı, sıra, renk.

---

## P3 — NEBENKOSTEN

### 3.1 Nebenkostenabrechnung Engine

**Teknik tasarım**
- Umlagefähige Kosten (giderler) yıl bazında toplanır, **dağıtım anahtarı** ile kiracılara paylaştırılır.
- Anahtar (MVP): **Wohnfläche** (`unit.wohnflaeche` oranı) — en yaygın. Sonra: kişi sayısı / birim sayısı (opsiyon).
- Umlagefähig kategoriler (mevcut `EXPENSE_KATEGORIEN`'den eşleme): heizung, nebenkosten(→wasser/müll), versicherung, grundsteuer, garten, + Hausmeister/Wasser/Warmwasser için **alt-kategori veya beschreibung** kullan. (Not: reparaturen/schoenheitsrep/finanzierung **umlagefähig DEĞİL** → dışla.)
- Kiracı başına: `anteil = Σ(umlagefähig_kosten × wohnfläche_payı × aktif_ay/12)`, `voraus = nk_voraus × aktif_ay`, `differenz = anteil − voraus` (Nachzahlung/Guthaben).

**DB**
- Yeni kolon: `immo_expense.umlagefaehig` (Boolean, default heuristik) — idempotent ALTER. Kullanıcı fiş başına işaretler/düzeltir.
- Ops: `immo_expense.nk_typ` (heizung|wasser|warmwasser|muell|hausmeister|garten|versicherung|grundsteuer|sonstige) — Nebenkosten dökümü için net kategori. (Mevcut `kategorie` korunur; `nk_typ` ek.)
- Yeni tablo gerekmez (abrechnung runtime hesaplanır + PDF). Ops `immo_nk_run` (history) — Faz sonu.

**API**
- `GET /immo/properties/{pid}/nebenkosten?year` → `{kosten_by_typ, gesamt_umlagefaehig, verteilschluessel, mieter:[{tenancy, anteil, voraus, differenz}]}`
- `GET /immo/properties/{pid}/nebenkosten/pdf?year&tenancy_id` → kiracı bazlı Abrechnung PDF (reportlab, mevcut report deseni).

**UI**
- Property'de **"Nebenkosten" sekmesi**: yıl seç → umlagefähig gider tablosu (işaretlenebilir) → dağıtım anahtarı seç → kiracı bazlı sonuç tablo → "PDF" per kiracı.

**Test**
- 2 daire (60m²/40m²), umlagefähig 1000€ → 600/400 dağılım.
- Aktif 6 ay kiracı → anteil yarı. voraus düşülür, differenz doğru.
- Umlagefähig=false gider abrechnunga girmez. reparaturen dışlanır.

---

## P4 — VERGİ HAZIRLIĞI (Anlage V)

### 4.1 Anlage V Preparation

**Teknik tasarım** — **Vergi danışmanlığı YOK** (StBerG · CLAUDE.md kuralı). Sadece **hazırlık/özet**: ELSTER Anlage V mantığına göre rakamları topla.
- Einnahmen: Σ kira (ist, `immo_rent`) + NK-Vorauszahlungen (ayrı satır).
- Werbungskosten dökümü (Anlage V satır mantığı): Erhaltungsaufwand (reparaturen/schoenheitsrep), Versicherung, Grundsteuer, Finanzierungskosten (faiz), Verwaltung, Sonstige.
- **AfA** (opsiyon): kaufpreis × %2 (lineer, Gebäudeanteil girilirse) — sadece varsa, "Schätzung" etiketi.
- Net: Einnahmen − Werbungskosten = Überschuss/Verlust.
- Çıktı durumu: **"Steuer-Vorbereitung abgeschlossen"** (tüm zorunlu alanlar dolu mu kontrolü).

**DB**
- Ops: `immo_property.afa_satz` (Float, default 2.0), `immo_property.gebaeude_anteil` (Float %) — AfA için. İkisi de nullable, idempotent ALTER. Yoksa AfA atlanır.

**API**
- `GET /immo/properties/{pid}/anlage-v?year` → yapısal JSON (Einnahmen / Werbungskosten kalemleri / AfA / Überschuss / checklist).
- `GET /immo/properties/{pid}/anlage-v/pdf?year` → Anlage-V-tarzı özet PDF.

**UI**
- Property'de **"Steuer (Anlage V)" sekmesi**: yıl → özet tablo + checklist ("Belege vollständig?", "AfA erfasst?") + PDF. Net sonuç + "Steuer-Vorbereitung abgeschlossen" rozeti.
- Uyarı microcopy: "Vorbereitung, keine Steuerberatung" (ux_voice).

**Test**
- Einnahmen = Σ rent. Werbungskosten kategorileri doğru mapping.
- AfA: gebäude_anteil=80%, kaufpreis=300k, satz=2 → 4.800€/yıl. Yoksa 0.
- Verlust senaryosu (gider>gelir) → negatif net, doğru işaret.

---

## ORTAK / ÇAPRAZ İŞLER

**Migration deseni:** Tüm yeni tablo/kolonlar `db.py` idempotent `CREATE TABLE IF NOT EXISTS` / `ALTER ... IF NOT EXISTS` (mevcut immo deseni). Alembic yok. `Base.metadata.create_all` yeni tabloyu otomatik kurar.

**İzolasyon doğrulaması:** Her yeni endpoint `Depends(get_current_user)` + `user_id` filtre + `_own_property`/`_own_unit` ownership guard. Soft-delete (`is_deleted`).

**Sıralama / öncelik (kullanıcı net):** P1 → P2 → P3 → P4. Grafik/renk/animasyon ERTELENDİ.

**Deploy stratejisi:** Her P kendi içinde tek konsolide commit (çok küçük reaktif deploy YOK — feedback_analyze_then_one_change). Backend önce, UI sonra; flag gerekmiyor (additive, mevcut ekranı bozmaz). Canlı kanıt: test verisi ile her endpoint 200 + sonra sil.

**Risk notları:**
- `ensure_charges` performans: 20 daire × 12 ay = 240 satır/yıl → önemsiz. Lazy + UNIQUE yeter.
- Mevcut `_accounting`/`_portfolio` DOKUNULMAZ → cockpit/dashboard regresyon riski yok. Ledger paralel katman.
- Nebenkosten umlagefähig heuristiği yanlış olabilir → kullanıcı fiş başına override eder (Boolean kolon).

---

## ÖNERİLEN SIRA (uygulama)

1. **P1.1 Mietkonto** (immo_charge + ensure_charges + 2 endpoint + Mietkonto sekmesi) ← çekirdek, her şey buna bağlı
2. **P1.2 Rent Alert** (gün-bazlı, charge'tan türer) + cockpit besle
3. **P1.3 Mahnung** (mevcut PDF'i ledger'a bağla + stufe rename + adres)
4. **P2** (Leerstand konto + Action Center veri kalitesi) — çoğu mevcut, ince işçilik
5. **P3 Nebenkosten** (umlagefähig kolon + engine + PDF + sekme)
6. **P4 Anlage V** (özet engine + PDF + sekme)

Her adım: backend + test + UI + canlı kanıt → tek deploy → sonraki.
