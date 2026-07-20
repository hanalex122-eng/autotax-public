# Sprint 1.2 — UX Tasarım · Flexible Mietmodelle Faz 1

> **Belge türü:** UX + teknik tasarım (KOD DEĞİL). **Commit/deploy YOK.**
> **Ön koşul:** Sprint 1.1 CANLI (ee8f299) — `heizkosten_voraus`/`zahler_typ`/`zahler_name` alanları + API zaten var.
> **Kural:** Bu sprint **hesap mantığını DEĞİŞTİRMEZ.** Sadece Sprint 1.1 altyapısını forma **güvenli ve anlaşılır** sunar.
> **Üst belge:** `docs/roadmap/Flexible_Mietmodelle_Phase1.md` · Ürün prensibi: `CONTRIBUTING.md`.

---

## 1. Sprint Amacı

Sprint 1.1 backend'i hazır ama kullanıcı bu alanları **formda göremiyor/giremiyor**. Sprint 1.2, sözleşme oluşturma/düzenleme ekranına şunları ekler:

- **Heizkostenvorauszahlung** (girdi)
- **Zahler** (Mieter / Sozialamt / Jobcenter / Sonstige)
- **Zahler adı** (koşullu — Sonstige'de veya ihtiyaç halinde)
- **Warmmiete** (otomatik hesaplanan, **salt-okunur**)

**Çözmediği (bilinçli):** hesap mantığı (backend `monat_soll` değişmez), NK motoru, yeni ekran, Untermieter/WG/Zimmer.

---

## 2. Etkilenen ekranlar (kapsam kararı)

Kodda tenancy alanları **3 yerde** giriliyor:

| # | Yer | `index.html` | Sprint 1.2 kapsamı |
|---|---|---|---|
| A | **`ImmoTenancyForm`** (ana create+edit form) | ~2461 | ✅ **ÇEKİRDEK** — burada tam yapılır |
| B | Satır-içi hızlı düzenleme (`editF`) | ~3189 | 🟡 Öneri: dahil (aynı alanlar, tutarlılık) |
| C | Erfassung sihirbazı (Neuer Mieter) | ~3128 | 🟡 Öneri: **ertele** (ayrı akış; scope şişmesin) — sadece varsayılan Zahler=Mieter, heiz boş |

**Öneri:** Çekirdek = **A (ImmoTenancyForm)**. B tutarlılık için eklenebilir. C ertelenir (kullanıcı isterse ayrı mini-adım). Yeni ekran YOK.

---

## 3. UX Tasarımı (form düzeni)

Alan sırası (mantıksal: soğuktan sıcağa, sonra ödeyici):

```
┌─ Mietvertrag ────────────────────────────────┐
│ Mieter (Name)            [______________]     │
│ Einzug [__.__.____]   Auszug [__.__.____]      │
│                                                │
│ Kaltmiete €/Monat        [   290 ]             │
│ NK-Vorauszahlung €/Monat [    70 ]  (Wasser…)  │
│ Heizkosten-Voraus. €/Mon [    45 ]  ← YENİ     │
│ ─────────────────────────────────────────      │
│ Warmmiete / Monat        405 €  🔒 (otomatik)  │  ← salt-okunur, canlı toplam
│ ─────────────────────────────────────────      │
│ Zahler   [ Mieter ▼ ]                ← YENİ    │
│          (Mieter / Sozialamt / Jobcenter / …)  │
│ Zahler-Name [__________________]  ← YENİ,      │
│          yalnız Sozialamt/Jobcenter/Sonstige'de│
│                                                │
│           [ İptal ]      [ Kaydet ]            │
└────────────────────────────────────────────────┘
```

**Anahtar davranışlar:**
- **Warmmiete** = `Kaltmiete + NK-Voraus. + Heizkosten-Voraus.` — formda **canlı** hesaplanır (kullanıcı yazdıkça günceller), **salt-okunur** (input değil, gösterim). Bu, backend `monat_soll` ile **aynı formül** (kullanıcı güvenini artırır: "her ay bunu borçlanacak").
- **Zahler** varsayılan **Mieter** (boş = Mieter gibi). Dropdown 4 seçenek.
- **Zahler-Name** alanı **koşullu**: Zahler = Mieter iken **gizli**; Sozialamt/Jobcenter/Sonstige seçilince **görünür** (opsiyonel, placeholder "z.B. Sozialamt Krefeld").
- Heizkosten **boş bırakılabilir** → 0 → Warmmiete = Kalt+NK (eski davranış, güvenli).

---

## 4. Davranış Kuralları (hesap DEĞİŞMEZ)

- Warmmiete **sadece görüntüde** hesaplanır (`kalt+nk+heiz`); **kaydedilmez** — backend zaten `monat_soll`'dan türetir. Form yalnızca 3 ham alanı (`kaltmiete`, `nk_voraus`, `heizkosten_voraus`, `zahler_typ`, `zahler_name`) POST/PATCH eder.
- Erstmonat (`erstmonat_betrag`) mantığına **dokunulmaz**; Warmmiete gösterimi normal ayı temsil eder (mevcut "Warmmiete/Monat" gösterimiyle tutarlı, `index.html:4181`).
- Kaydetme: mevcut `onSave` payload'ına 3 alan eklenir → mevcut `POST/PATCH /immo/tenancies` (Sprint 1.1 kabul ediyor).

---

## 5. i18n (DE/TR/EN)

Mevcut `_iL(de,tr,en)` helper'ıyla, yeni etiketler:

| Alan | DE | TR | EN |
|---|---|---|---|
| Heizkosten | Heizkosten-Vorauszahlung €/Monat | Isıtma avansı €/ay | Heating advance €/mo |
| Warmmiete | Warmmiete / Monat (automatisch) | Brüt kira / ay (otomatik) | Warm rent / mo (auto) |
| Zahler | Zahler | Ödeyen | Payer |
| Zahler-Name | Name des Zahlers | Ödeyen adı | Payer name |
| Zahler seçenekleri | Mieter · Sozialamt · Jobcenter · Sonstige | Kiracı · Sozialamt · Jobcenter · Diğer | Tenant · Sozialamt · Jobcenter · Other |

> UX ses kuralı: hukuki tavsiye yok; sadece alanı betimle (StBerG — `CONTRIBUTING.md`/ux_voice).

---

## 6. Backend / API Etkisi

**YOK.** Sprint 1.1 zaten:
- `TenancyIn`/`TenancyPatch` 3 alanı kabul ediyor,
- `_tenancy_dict` + `/immo/mieter` feed 3 alanı + `gesamtmiete=kalt+nk+heiz` döndürüyor.

Sprint 1.2 **yalnızca frontend** (index.html). Backend'e **tek satır** eklenmez.

---

## 7. Regresyon / Test Planı

| Kontrol | Beklenen |
|---|---|
| `node tests/_babelcheck.js` | PASS (JSX bozulmadı) |
| `python tests/check_jsx_structure.py` | BALANCED (DE/TR'de tipografik `'` kullan) |
| Mevcut form (heiz boş) | Warmmiete = Kalt+NK; kayıt eskisi gibi |
| Zahler=Mieter | Zahler-Name gizli; kayıtta zahler_typ=mieter/None |
| Heiz=45 girilince | Warmmiete anında Kalt+NK+45 gösterir (salt-okunur) |
| Backend suite | 44/44 (değişmedi — backend'e dokunulmadı) |
| Canlı marker | Deploy sonrası served-HTML'de yeni etiketler |

**Kabul:** babel+structure yeşil · mevcut kiracı düzenleme bozulmuyor · Warmmiete doğru gösteriliyor · backend değişmedi.

---

## 8. Riskler + Rollback

| Risk | Seviye | Önleme |
|---|---|---|
| JSX yapısı bozulur (tek-dosya SPA) | 🟠 | babel + structure gate; tipografik `'` |
| Warmmiete gösterimi ≠ backend soll | 🟡 | Aynı formül (`kalt+nk+heiz`); erstmonat'a girme |
| Zahler-Name koşullu görünürlük hatası | 🟢 | Basit state; Mieter'de gizle |
| Scope şişmesi (C/Erfassung) | 🟢 | Erfassung ertelendi; çekirdek A |

**Rollback:** Sadece frontend değişikliği → önceki `index.html` commit'ine revert; backend/veri etkilenmez. Alanlar backend'de zaten var (Sprint 1.1), UI kaldırılsa da veri durur.

---

## 9. Kodlama Sırası (onaylanırsa)

1. `ImmoTenancyForm` (A): 3 alan + canlı Warmmiete (salt-okunur) + koşullu Zahler-Name.
2. (Öneri) Satır-içi `editF` (B): aynı alanlar.
3. i18n (DE/TR/EN) + babel/structure test.
4. Smoke (served-HTML marker) → deploy onayı.

---

## Onay

Bu **yalnızca UX tasarımıdır**. Onay sonrası kodlamaya geçilir. Kapsam kararı senin:
- **A yeterli mi**, yoksa **A+B** mi (satır-içi düzenleme de)?
- **Erfassung sihirbazı (C)** bu sprintte mi, ertelensin mi?
- Zahler-Name: sadece Sonstige'de mi, yoksa Sozialamt/Jobcenter'da da mı görünsün? (Öneri: mieter dışı hepsinde)
