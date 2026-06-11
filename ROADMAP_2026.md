# ROADMAP 2026 — AutoTax-Cloud

> Son güncelleme: 2026-06-11 · Model değişimi: **Feature-first → Performance-first + Product-first.**
> Yeni özellik ikinci planda. Öncelik: **hız · stabilite · UX · satış dönüşümü.**
> Etiketler: **P0 Kritik · P1 Yüksek · P2 Orta · P3 Düşük**
> Referans dokümanlar: `PERFORMANCE_AUDIT.md`, `TECHNICAL_DEBT.md`, `UI_UX_AUDIT.md`.

---

## A. CTO-SEVİYESİ STRATEJİK ANALİZ (dürüst, övgüsüz)

### A.1 "Kullanıcı neden satın almıyor?" (hipotezler — bazıları doğrulanmalı)
1. **Ürün çok geniş, odak yok.** OCR + gelir-gider + Angebot + Rechnung + PDF + DATEV + Steuererklärung + Kasse + AI advisor. Solo bir founder'ın bu kadar geniş yüzeyi "bitmiş ve güvenilir" göstermesi imkânsız → kullanıcı "yarım kalmış" algılıyor. Almanya'da vergi/finans yazılımında **güven = her şey**.
2. **İlk izlenim yavaş.** Babel transpile → açılışta beyaz ekran (PERFORMANCE_AUDIT P0-1). "Yavaş = ucuz = güvenmem."
3. **En değerli modül (Steuererklärung) BETA + "ohne Gewähr".** En yüksek niyetli özelliğe güvensizlik etiketi → dönüşüm kırıcı.
4. **Fiyat/algı uçurumu.** AI Steuer €89/ay; WISO yıllık ~€30-40 tek sefer. Aylık vergi yazılımı, ucuz yıllık rakip varken zor satılır.
5. **"Neden ben?" net değil.** Ana ekran görev-akışı sunmuyor (sidebar 13 öğe), kullanıcı değeri 30 saniyede yaşayamıyor.

> **DOĞRULANACAK (varsayım yapma):** Gerçek dönüşüm verisi — kaç kayıt → kaç aktif → kaç ödeyen? Stripe + DB'den funnel çıkar. Bu sayılar olmadan "neden almıyor" tahmin kalır.

### A.2 "Rakiplere karşı en büyük avantajım nedir?" (gerçek moat)
- **WISO/Taxfix (vergi beyanı) ile kafa kafaya YARIŞMA — kaybedersin.** Onlar fonlu, olgun, ucuz. Steuererklärung'u WISO kadar güzel yapmak moat değil.
- **Gerçek wedge (ICP — memory):** **Manuel/eski-kasalı, kutu-fişli küçük işletme.** WISO onlara çok DIY, Steuerberater çok pahalı/yavaş. Senin OCR → otomatik ön-muhasebe → müşavir-export hattın "bir kutu fişim var" sorununu çözüyor. **Savunulabilir avantaj bu.**
- **Sonuç:** Steuererklärung modülü wedge'den **dikkat dağıtıyor**. Çekirdek hikâye: *"Fişini çek, gerisini biz yapalım, müşavirine hazır gitsin."*

### A.3 "Hangi özellikler para kazandırmıyor / durdurulmalı?"
- **Steuererklärung tam beyan motoru (Phase 9 tax engine):** Devasa emek, WISO ile yarış, beta, sorumluluk riski. Memory'de sen de işaretledin ("ELSTER gönderim/GewSt/GmbH YOK; isim yanıltıcı"). → **Tam beyan iddiasını DURDUR.** "Entwurf/ön-hazırlık + müşavire export" olarak konumla, "WISO alternatifi" olarak değil.
- **Kasse V2:** Zaten durduruldu (flag OFF) — doğru.
- **Steuererklärung UI'ını WISO'ya benzetme maratonu (bugün yapılan):** Görsel olarak iyi ama **gelir hareket ettirmez** — wedge bu değil. Cila yeter; derinleştirme P2'ye.

### A.4 "Hangi özellikler öncelikli olmalı?" (gelir-merkezli)
1. **OCR hızı + doğruluğu** — günlük kullanım, retention, demo "wow". Doğrudan satış.
2. **Beleg → Bookkeeping → Müşavir export akışının pürüzsüzlüğü** — wedge'in kalbi.
3. **İlk-değer süresi (time-to-value):** Kayıt → ilk fiş okunmuş → "işte vergi-hazır defterin" 2 dakikada.
4. Steuererklärung = **destekleyici** (Entwurf + export), baş rol değil.

---

## B. UYGULAMA YOL HARİTASI (sıralı)

### FAZ 0 — Ölçüm & Stabilite (P0) · "Önce gör"
- [ ] **P0** OCR pipeline timing enstrümantasyonu (`ocr.py`/`main.py` — PERFORMANCE_AUDIT son bölüm). Gerçek ms'leri logla, raporu sayılarla güncelle.
- [ ] **P0** Stripe + DB funnel raporu: kayıt → aktif → ödeyen (A.1 doğrulaması).

### FAZ 1 — Performans (P0) · "Hızlı hisset"
- [ ] **P0** Frontend build step: `babel-standalone` kaldır, JSX'i deploy'da bir kez derle, cache'lenebilir `app.js` sun (`index.html:18/149`).
- [ ] **P0** OCR'ı threadpool'a al (`asyncio.to_thread`) — event-loop bloğunu kaldır (`main.py:8022`).
- [ ] **P0** OCR öncesi downscale cap ~2000px (`ocr.py:789`).
- [ ] **P0/P1** `/vault` sayfalama + `defer(file_data)` (`main.py:11837`).
- [ ] **P1** OCR.space 3→1 çağrı; QR tek decode; Tesseract 4×→akıllı (`ocr.py`).

### FAZ 2 — Backend verimi (P1)
- [ ] **P1** dashboard/summary/chat → SQL aggregation; chat `defer(raw_text)` (`main.py:4946/8874/12399`).
- [ ] **P1** `(user_id, date)` index invoices (`models.py:263`).
- [ ] **P1** `email_invoices_bulk` PDF döngüsü threadpool (`main.py:4422`).
- [ ] **P2** N+1 admin_list_users; quadratic sync_invoices_to_bookkeeping.

### FAZ 3 — UX / Tek tasarım dili (P1)
- [ ] **P1** Tek tasarım dili: Kasse (`css.*`) ↔ genel (`var(--*)`) birleştir (UI_UX 2.4).
- [ ] **P1** Büyük buton-kart dilini Rechnung/Angebot/Beleg'e yay (UI_UX 2.3).
- [ ] **P1** Ana ekran: 3 büyük aksiyon kartı + sidebar sadeleştir; mobil alt tab bar (UI_UX 2.2).
- [ ] **P2** Steuererklärung: sağ-üst sabit Erstattung + sağ bağlamsal yardım paneli (UI_UX 2.1).

### FAZ 4 — Yeni Vergi Ekranı (P2) · "Önce performans bitsin"
- [ ] **P2** 12 çubuk → 6 hayat-temalı ilerleme kartı (👤🏠💼❤️👨‍👩‍👧📤), her kart: durum + eksik alan + % (UI_UX §4).
- [ ] **P2** Steuererklärung'u "Entwurf + müşavir export" olarak yeniden konumla (A.3) — "WISO alternatifi" iddiasını kaldır.

### FAZ 5 — Product-first / Satış (sürekli)
- [ ] Time-to-value 2 dk hedefi (onboarding: kayıt → ilk fiş → vergi-hazır defter).
- [ ] Fiyat/konumlandırma gözden geçir (A.1.4) — wedge'e göre paketle.
- [ ] Wedge mesajı netleştir: "Fişini çek, müşavirine hazır gitsin."

---

## C. RED LINE (değişmez kurallar)
- Stack FastAPI + Railway + React-CDN **KALIR**. TypeScript/Next.js/Supabase rewrite **YOK**.
- Tek seferde **büyük refactor YOK** — endpoint endpoint, küçük commit, her adımda test + deploy onayı.
- Yeni özellik, FAZ 0-1-2 (performans) bitmeden **YOK**.
- AI maliyet koruması + StBerG uyumu (Vorschlag/Empfehlung) korunur.

---

## D. Durum takibi
| Faz | Durum | Not |
|---|---|---|
| Audit dokümanları | ✅ 2026-06-11 | 4 rapor oluşturuldu |
| FAZ 0 ölçüm | ⏳ sırada | timing + funnel |
| FAZ 1 performans | ⬜ | Babel build step ilk iş |
