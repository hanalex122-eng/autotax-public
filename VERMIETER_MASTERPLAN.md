# 🏛️ VERMIETER MASTERPLAN (KİLİTLİ / LOCKED)

**Durum:** Kalıcı ürün planı. **Bu dosya backlog değildir.** Silinmez.
Yeni fikirler bu listenin önüne geçemez. Önce bu tamamlanacaktır.

---

## NORTH STAR

AutoTax, **Almanya'daki 1–20 dairesi olan küçük ev sahiplerinin günlük kullandığı tek uygulama**
olacaktır. Bir landlord: Excel'e, Word şablonlarına, PDF aramaya, klasör tutmaya ihtiyaç duymamalı.
Her şeyi AutoTax içinde yapabilmelidir.

## KURAL — Finish > New Features

Bu liste bitmeden yeni modül geliştirilmez. Her madde: geliştirilir → test edilir → UX tamamlanır →
deploy edilir → **pilotta kullanılır** → ancak o zaman "tamamlandı" işaretlenir. **Yarım bırakmak
yasaktır.** Aktif sprint takibi: `SPRINT.md`. Sprint disiplini: `CLAUDE.md`.

---

## MVP — mutlaka bitecek

| # | Modül | İçerik | Masterplan durumu | Kod-kanıtlı gerçek durum (review 2026-07-14) |
|---|-------|--------|-------------------|-----------------------------------------------|
| 1 | **Immobilien** | Property · Units · Address · Documents | ✅ mevcut | 🟡 mevcut, ama silme kiracıyı öksüz bırakıyor (`immo_api.py:375-385`), loading/error state yok |
| 2 | **Mieter** | Tenant · Contact · Phone · Email · Kaution · Mieterhöhung geçmişi | ✅ mevcut | 🟡 mevcut, ama Kaution/Telefon/E-Mail kayıt akışında girilemiyor (sadece ✎ Bearbeiten), Almanca arayüzde Türkçe butonlar |
| 3 | **Mietkonto** | Aylık genel bakış · Ödeme geçmişi · Exception Engine · This Month | ✅ mevcut | 🔴 **DEĞİL** — borç yanlış: geçmiş aylar Bu Ay'da görünmüyor, borç yıl sınırında siliniyor, **NK borca dahil değil**, Mieteingang sekmesi borcu değiştirmiyor, Berichte kendiyle çelişiyor |
| 4 | **Mahnung** | Erinnerung · Mahnung 1 · Mahnung 2 · Letzte Mahnung · PDF · History | 🟡 geliştirilecek | 🟡 `stufe:1` sabit (eskalasyon UI yok), mektupta kiracı adresi/tarih yok, imza "Die Hausverwaltung", history endpoint'i UI'sız |
| 5 | **Wohnungsgeberbestätigung** | Tam otomatik PDF | 🟡 geliştirilecek | 🟡 PDF var (`immo_api.py:1577`), "○ Anmeldung" çipi hiç tiklenemiyor |
| 6 | **Übergabeprotokoll** ⭐ | Tarih · ev sahibi · kiracı · oda-oda kontrol (duvar/zemin/kapı/pencere/mutfak/banyo) · anahtar sayısı · sayaçlar (Strom/Wasser/Warmwasser/Heizung/Gas) · fotoğraflar · imzalar · PDF | 🔴 zorunlu | 🔴 yok |
| 7 | **Zählerstände** ⭐ | Her taşınmada Strom/Wasser/Warmwasser/Gas/Heizung · geçmiş · grafik | 🔴 zorunlu | 🔴 yok |
| 8 | **Nebenkostenabrechnung** ⭐⭐⭐ | Heizkosten · Wasser · Abwasser · Müll · Versicherung · Grundsteuer · Hausmeister · Gartenpflege · Allgemeinstrom · Schornsteinfeger · Winterdienst · Sonstige · **Umlageschlüssel · Vorauszahlungen · Nachzahlung · Guthaben · PDF** | 🔴 zorunlu | 🔴 yok — **ve #3'e bağımlı**: NK bugün Soll'a dahil değil (`immo_api.py:832-838`), Vorauszahlung takibi olmadan Abrechnung yapılamaz |
| 9 | **Mietvertrag Generator** | Şablon · PDF · imzaya hazır | 🔴 zorunlu | 🔴 yok |
| 10 | **Kurzzeitmiete** | Günlük/haftalık/aylık sözleşmeler | 🟡 | 🔴 yok |
| 11 | **Kündigung Generator** | Hazır şablonlar | 🟡 | 🔴 yok |
| 12 | **SEPA Lastschrift** | Mandat · PDF | 🟡 | 🔴 yok |
| 13 | **Wohnung Akte** ⭐⭐⭐ | Her dairenin tek ekranı: 🏠 Stammdaten · 👤 Kiracı · 📄 Mietvertrag · 💰 Mietkonto · 📬 Mahnung · 📑 Nebenkosten · ⚡ Sayaçlar · 🛠 Tamiratlar · 📷 Fotoğraflar · 📁 Belgeler | 🔴 zorunlu | 🔴 yok (bugün 5 ayrı ekrana dağılmış) |
| 14 | **Schäden / Reparaturen** | Bakım geçmişi · fotoğraf · masraf · durum | 🟡 | 🔴 yok |
| 15 | **Dokumente** | Daire başına Energieausweis · Grundriss · Versicherungen · Rechnungen · Protokolle | 🟡 | 🟡 belge yükleme var, daire bazlı tasnif zayıf |

---

## SIRA (bağımlılığa göre — Finish kuralı gereği)

**Sprint 0 — Fundament (ŞU AN AKTİF).** Masterplan'da ✅ işaretli 1/2/3 gerçekte ✅ değil.
Mietkonto yanlış borç gösteriyor. #8 (Nebenkostenabrechnung) doğrudan #3'ün üstüne oturuyor —
NK bugün Soll'a dahil olmadığı için önce bu düzelmeden NK Abrechnung yapılamaz.
→ Detay ve DoD: `SPRINT.md`. Kanıt: `.claude/immo_finish_review.md`.

Sonraki sıra (Sprint 0 kapanmadan açılmaz):
**S1** #4 Mahnung (tam eskalasyon + history + doğru mektup) →
**S2** #5 WGB + #7 Zählerstände →
**S3** #6 Übergabeprotokoll →
**S4** #8 Nebenkostenabrechnung ⭐⭐⭐ →
**S5** #13 Wohnung Akte (yukarıdakileri tek ekranda toplar) →
**S6** #9 Mietvertrag → **S7** #14/#15 → **S8** #10/#11/#12

## ÜRÜN VİZYONU

Bu modül tamamlandıktan sonra AutoTax yalnızca muhasebe yazılımı olmayacak;
**Almanya'daki küçük ev sahipleri için günlük kullanılan eksiksiz bir Vermieter Platformu** olacaktır.
