# UI / UX AUDIT — AutoTax-Cloud

> Son güncelleme: 2026-06-11 · Referans: WISO Steuer (steuer-web.de) ekran görüntüleri (kullanıcı sağladı).
> Kural: WISO **kopyalanmayacak**, tasarım dili referans alınacak.
> Etiketler: **P0 Kritik · P1 Yüksek · P2 Orta · P3 Düşük**

---

## 0. Kullanıcının kendi sözleri (ground truth)
- "WISO çok modern, sıkıcı değil, **oyun gibi kart kart açılıyor**."
- "Bizimki **20 yıl geriden** geliyordu."
- "Sayfa **tek tek butonlardan** oluşuyor (WISO), bizimki **çizgi gibi**."

Bu üç cümle tüm UI yön kararının çıpasıdır: **büyük buton-bloklar, ferah, adım adım, oyunsu akış.**

---

## BACKLOG — Rechnung/Kassenbuch UX (2026-06-12 kullanıcı testi)
> Phase 3 (UI/UX). REPAIR MODE'da performans+correctness'tan sonra.
- **P1 (correctness, REPAIR MODE'a uygun):** Arama tutara (amount) bakmıyor — "total 23.09" bulmuyor. Backend `/invoices` + `/bookkeeping` aramasına amount eşleşmesi ekle.
- **P1 (performans):** "Belege bearbeiten" foto hâlâ geç yükleniyor — resize fix canlı (4dk→sn). Kalıcı çözüm: **sunucuda thumbnail'i bir kez üret + sakla** (anlık açılış, her istekte PIL decode etme).
- **P2 (UI):** Rechnung listesinde **satır başına çöp-tenekesi** (tekli hızlı silme). Şu an seçim → toplu silme.
- **P2 (UI):** **Löschen/silme butonu listenin ÜSTÜNDE** olsun (şu an çok üstte/uzakta kalıyor — scroll gerektiriyor).
- **✅ Tarih:** 275760 yıl bug'ı düzeltildi (backend guard PATCH+PUT + editör takvim min/max).

## 1. WISO neyi doğru yapıyor (referans analizi)

| Öğe | WISO |
|---|---|
| **Tema** | Beyaz, ferah, bol boşluk |
| **Sonuç göstergesi** | "Erstattung: 0,00 €" **hep sağ üstte sabit**, sen yazdıkça güncellenir |
| **Adım navigasyonu** | Solda **dikey numaralı** adımlar (1·2·3·4), büyük |
| **Form** | Etiket solda, **büyük yuvarlak input** sağda, yanında "?" yardım |
| **Yardım** | Sağda **bağlamsal panel** ("Worum geht's hier? / Tipps zur Eingabe") |
| **Seçim** | Büyük **pill butonlar** (Ja/Nein), açık sarı vurgu |
| **CTA** | Büyük sarı **pill** ("Starten →") |
| **Diğer** | Dostça illüstrasyon, breadcrumb, soru-kartları (SteuerGPT) |

**Çıkarım:** Modernlik hissi "wizard vs form" değil; **büyük tıklanabilir bloklar + ferahlık + bağlamsal yardım + sürekli görünen sonuç**.

---

## 2. Mevcut durum → Problem → Rakip → Önerilen tasarım

### 2.1 Steuererklärung ekranı (`DeclarationView`, index.html)
- **Mevcut durum:** 2026-06-11'de form → adım sihirbazına çevrildi; ince çizgi şerit → büyük numaralı butonlar; alanlar büyük buton-kart + Ja/Nein pill yapıldı; alt sticky sonuç barı eklendi.
- **Problem (kalan):** (a) Sonuç sağ üstte değil, altta. (b) Sağ bağlamsal yardım paneli yok — yardım hâlâ alan-başı "? Hilfe" buton+modal. (c) Adım listesi yatay; WISO dikey/kalıcı. (d) Koyu tema (kullanıcı açık temada test ediyor — açık tema WISO hissine yakın).
- **Rakip:** WISO sol-dikey-adım + sağ-yardım + sağ-üst-sonuç üçlüsünü aynı anda gösteriyor.
- **Önerilen:** Bkz. **§4 Yeni Vergi Ekranı**.

### 2.2 Sidebar bağımlılığı
- **Mevcut durum:** Sol menüde ~13 öğe (Dashboard, Upload, Email-Import, Tabelle, Neuen Beleg, Belege, Beleg Editor, Rechnungen, Rechnungen senden, Angebote, Kasse, Export, Firmen).
- **Problem:** Klasik **ERP/sidebar** kalabalığı — kullanıcı nereden başlayacağını bilmiyor; mobilde sidebar değerli alanı yiyor. WISO'da sol rail sadece **adımlar**, dağınık modül listesi değil.
- **Rakip:** WISO/Taxfix **görev-akışı** odaklı (önce ne yapacağın belli); Sevdesk/Lexoffice sidebar ağır ama onlar masaüstü-muhasebe.
- **Önerilen (P1):** Sidebar'ı grupla + sadeleştir; ana ekranda **3 büyük aksiyon kartı** ("Beleg ekle", "Rechnung yaz", "Beyan/Export") — sidebar ikincil. Mobilde sidebar → alt tab bar (3-4 ikon).

### 2.3 Uzun formlar / alt alta inputlar
- **Mevcut durum:** Birçok ekran ince input'ların dikey yığını (eski ERP hissi).
- **Problem:** Bilgi yoğunluğu yüksek, nefes yok, "iş yazılımı" hissi → güven/tamamlanma hissini düşürür.
- **Rakip:** WISO her soruyu büyük blok + bolca boşlukla veriyor.
- **Önerilen (P1):** Steuererklärung'da uygulanan **büyük buton-kart** dilini diğer formlara da yay (Rechnung, Angebot, Beleg editör).

### 2.4 İki tasarım dili
- **Mevcut durum:** Kasse görünümleri `css.card`/`theme.*`; Steuer ve genel `var(--*)`. İki ayrı stil sistemi.
- **Problem:** Ekranlar arası tutarsızlık → "yarım bitmiş / amatör" algısı; güven kaybı.
- **Önerilen (P1):** **Tek tasarım dili.** Ortak token seti (renk/spacing/radius/shadow/buton) → tüm ekranlar aynı. (Memory prensibi: "Tek tasarım dili".)

### 2.5 Performans = UX (Babel)
- **Mevcut durum:** İlk açılışta Babel transpile → beyaz ekran (bkz. PERFORMANCE_AUDIT P0-1).
- **Problem:** En iyi UI bile **yüklenmeden** kötü his verir. "Yavaş = ucuz = güvenilmez" algısı satışı düşürür.
- **Önerilen (P0):** Build step (PERFORMANCE_AUDIT P0-1) — UX'in ön koşulu.

---

## 3. "Eski ERP hissi" veren yerler (liste)
1. Sidebar 13 öğe, gruplama yok — **P1**
2. Steuer dışındaki formlarda ince/yığılı input'lar — **P1**
3. İki tasarım dili (Kasse vs genel) — **P1**
4. Koyu yoğun tema + küçük tipografi (WISO açık/ferah) — **P2**
5. Modal-tabanlı yardım (WISO kalıcı sağ panel) — **P2**
6. Sonuç/sonuç-rakamı her zaman görünür değil — **P2**

---

## 4. YENİ VERGİ EKRANI (tasarım hedefi — kod değil)

**12 yeşil çubuk KALDIRILDI** → yerine **kart-bazlı ilerleme sistemi.** Üst seviye, WISO'nun teknik "Anlage" mantığını gizleyen **hayat-temalı** kartlar:

```
┌──────────────────────────────────────────────┐
│  Steuererklärung 2025        Erstattung +1.240€│  ← sağ üst sabit
├──────────────────────────────────────────────┤
│  👤 Persönlich     ✓ Tamam        100%        │
│  🏠 Wohnen         ● 2 eksik alan  60%        │
│  💼 Arbeit         ● 5 eksik alan  30%        │
│  ❤️ Gesundheit     ○ Başlanmadı    0%         │
│  👨‍👩‍👧 Familie       ✓ Tamam        100%        │
│  📤 ELSTER         🔒 önce yukarısı            │
└──────────────────────────────────────────────┘
```

**Her kart gösterir:**
- **Durum:** ✓ Tamam · ● Devam (eksik var) · ○ Başlanmadı · 🔒 Kilitli
- **Eksik alan sayısı** (ör. "5 eksik alan")
- **Tamamlanma yüzdesi** (dolan halka/bar)

**Etkileşim:** Karta tıkla → o temanın büyük buton-kart alanları açılır (zaten yapılan stil) → "Weiter" üst karta döner, yüzde güncellenir. Sağ üstte Erstattung sürekli canlı.

**Mevcut şema eşlemesi (kod yokken plan):** Mevcut `schema` bölümleri (anlage_s, anlage_n, anlage_vorsorge, anlage_sonderausgaben, kinder, persönlich) bu 6 hayat-temalı karta gruplanır — backend şeması değişmeden, sadece sunum katmanında kategori → kart.

**Hedef his:** WISO kadar modern · mobil kadar basit · oyun kadar akıcı.
- Modern = ferah beyaz, büyük bloklar, sağ-üst canlı sonuç
- Basit = teknik "Anlage/Zeile" kodları gizli, hayat dili ("Wohnen", "Arbeit")
- Akıcı = kart geçiş animasyonu + her tamamlamada görünür ilerleme (mikro-ödül)

> NOT: Bu ekran **yeni özellik değil**, mevcut Steuererklärung'un yeniden sunumu. Önce P0 performans (Babel + OCR) çözülmeden büyük UI yatırımı yapılmaz — sıralama ROADMAP_2026.md'de.
