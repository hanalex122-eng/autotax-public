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
| 1 | **Immobilien** | Property · Units · Address · Documents | ✅ mevcut | ✅ **TAMAM** (Sprint 0): cascade silme + loading/error/retry |
| 2 | **Mieter** | Tenant · Contact · Phone · Email · Kaution · Mieterhöhung geçmişi | ✅ mevcut | ✅ **TAMAM** (Sprint 0): Almanca butonlar, onay dialogları, 3 dilli hint'ler |
| 3 | **Mietkonto** | Aylık genel bakış · Ödeme geçmişi · Exception Engine · This Month | ✅ mevcut | ✅ **TAMAM** (Sprint 0): tek Payment Service, NK borca dahil (Warmmiete), çok-yıllı borç, Mieteingang borcu kapatıyor, tüm ekranlar aynı sayıyı veriyor (prod smoke 9/9) |
| 4 | **Mahnung** | Erinnerung · Mahnung 1 · Mahnung 2 · Letzte Mahnung · PDF · History | 🟡 geliştirilecek | 🟢 **BÜYÜK ÖLÇÜDE TAMAM** (Sprint 0): eskalasyon (backend karar veriyor) + history UI + gerçek mektup (alıcı adresi, kalem dökümü, somut vade, landlord imzası+IBAN). Kalan: e-posta ile gönderim, Mahnung silme |
| 5 | **Wohnungsgeberbestätigung** | Tam otomatik PDF | 🟡 geliştirilecek | 🟡 PDF var (`immo_api.py:1577`), "○ Anmeldung" çipi hiç tiklenemiyor |
| 6 | **Übergabeprotokoll** ⭐ | Tarih · ev sahibi · kiracı · oda-oda kontrol (duvar/zemin/kapı/pencere/mutfak/banyo) · anahtar sayısı · sayaçlar (Strom/Wasser/Warmwasser/Heizung/Gas) · fotoğraflar · imzalar · PDF | 🔴 zorunlu | 🔴 yok |
| 7 | **Zählerstände** ⭐ | Her taşınmada Strom/Wasser/Warmwasser/Gas/Heizung · geçmiş · grafik | 🔴 zorunlu | 🔴 yok |
| 8 | **Nebenkostenabrechnung** ⭐⭐⭐ | Heizkosten · Wasser · Abwasser · Müll · Versicherung · Grundsteuer · Hausmeister · Gartenpflege · Allgemeinstrom · Schornsteinfeger · Winterdienst · Sonstige · **Umlageschlüssel · Vorauszahlungen · Nachzahlung · Guthaben · PDF** | 🔴 zorunlu | 🔴 yok — ama **ENGELİ KALKTI** (Sprint 0): NK artık Soll'un parçası, Vorauszahlung borç olarak takip ediliyor (`immo_rules.monat_nk_soll`) |
| 9 | **Mietvertrag Generator** | Şablon · PDF · imzaya hazır | 🔴 zorunlu | 🔴 yok |
| 10 | **Kurzzeitmiete** | Günlük/haftalık/aylık sözleşmeler | 🟡 | 🔴 yok |
| 11 | **Kündigung Generator** | Hazır şablonlar | 🟡 | 🔴 yok |
| 12 | **SEPA Lastschrift** | Mandat · PDF | 🟡 | 🔴 yok |
| 13 | **Wohnung Akte** ⭐⭐⭐ | Her dairenin tek ekranı: 🏠 Stammdaten · 👤 Kiracı · 📄 Mietvertrag · 💰 Mietkonto · 📬 Mahnung · 📑 Nebenkosten · ⚡ Sayaçlar · 🛠 Tamiratlar · 📷 Fotoğraflar · 📁 Belgeler | 🔴 zorunlu | 🔴 yok (bugün 5 ayrı ekrana dağılmış) |
| 14 | **Schäden / Reparaturen** | Bakım geçmişi · fotoğraf · masraf · durum | 🟡 | 🔴 yok |
| 15 | **Dokumente** | Daire başına Energieausweis · Grundriss · Versicherungen · Rechnungen · Protokolle | 🟡 | 🟡 belge yükleme var, daire bazlı tasnif zayıf |

---

## SIRA (bağımlılığa göre — Finish kuralı gereği)

**Sprint 0 — Fundament ✅ KAPANDI (2026-07-14 · canlı `32ace6f` · prod smoke 9/9 · suite 35/35).**
Masterplan'ın "✅ mevcut" dediği 1/2/3 gerçekte ✅ değildi: Mietkonto yanlış borç gösteriyordu
(NK yok, geçmiş aylar/yıllar yok, Mieteingang borcu değiştirmiyor, raporlar çelişiyor — üstüne
ledger canlı bir üçüncü defterdi). Hepsi kapatıldı. Kapanış raporu: `SPRINT.md`.

Sonraki sıra:
**S1** #4 Mahnung'un kalanı (e-posta gönderimi, Mahnung silme) →
**S2** #5 WGB + #7 Zählerstände →
**S3** #6 Übergabeprotokoll →
**S4** #8 Nebenkostenabrechnung ⭐⭐⭐ →
**S5** #13 Wohnung Akte (yukarıdakileri tek ekranda toplar) →
**S6** #9 Mietvertrag → **S7** #14/#15 → **S8** #10/#11/#12

## ÜRÜN VİZYONU

Bu modül tamamlandıktan sonra AutoTax yalnızca muhasebe yazılımı olmayacak;
**Almanya'daki küçük ev sahipleri için günlük kullanılan eksiksiz bir Vermieter Platformu** olacaktır.
