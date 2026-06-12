# P1 FIX REPORT — Data Integrity & Security

> 2026-06-12 · REPAIR MODE · feature DEĞİL. Kaynak: `VALIDATION_AUDIT.md`.
> Durum: **3 fix yerelde commit'li, DEPLOY EDİLMEDİ** (onay bekliyor).
> Kural: kanıt olmadan "düzeltildi" denmez — test sonuçları aşağıda.

---

## Değişen dosyalar
| Dosya | Fix | Commit |
|---|---|---|
| `autotax/main.py` | F1 (`_sane_invoice_date`), F3 (`InvoiceUpdate` validators) | 207866c, 319b1dc |
| `editor.html` | F2 (escHtml + sink'ler), 422 mesaj gösterimi | 554e429, 319b1dc |

Hepsi additive + fail-soft. `py_compile` OK (3 kez doğrulandı).

---

## F1 — Gerçek takvim doğrulaması
**Önce:** `if not (1 <= d <= 31)` — gün ay'a bakmıyor → `2026-02-30` KABUL.
**Sonra:** `datetime(y, mo, d)` ile gerçek takvim; `ValueError` → 400.
**Test (çalıştırıldı):**
```
ACCEPT: 2026-12-31 [PASS]   2024-02-29 (artık yıl) [PASS]
REJECT: 2026-02-30 [PASS]   2025-02-29 [PASS]   2026-13-01 [PASS]
        2026-00-01 [PASS]   2026-01-32 [PASS]   0000-00-00 [PASS]
-> TÜM TESTLER GEÇTİ
```
**Risk:** min yıl 2020 → 2019 ve öncesi fiş düzenlenince reddedilir (GAP-2, P3 — ayrı). Aksi halde risk yok.

---

## F2 — XSS-1 filename / innerHTML escape
**Önce:** `srcRef.innerHTML = ...+ fn +...` (339) ve import-kartı `...+ inv.filename +...` + vendor/no/date alanları (418) **escape'siz** → stored XSS (advisor modunda cross-user).
**Sonra:** `escHtml()` helper; tüm kullanıcı/OCR verisi sarmalandı (339 + 418 + kart satır değerleri).
**Test (node ile çalıştırıldı):**
```
<script>alert(1)</script>          -> &lt;script&gt;alert(1)&lt;/script&gt;   [SAFE]
<img src=x onerror=alert(cookie)>  -> &lt;img ... &gt;                        [SAFE]
"><svg onload=alert(1)>            -> &quot;&gt;&lt;svg ...&gt;               [SAFE]
normal_rechnung.pdf                -> normal_rechnung.pdf (bozulmadı)         [SAFE]
-> F2 XSS GEÇTİ (ham <> kalmadı, script çalışmaz)
```
**Not:** OCR render (715) zaten escape'liydi (güvenli). Line-item `date` attr (760) = XSS-2/F4, P2, bu dalgada DEĞİL.
**Risk:** yok (yalnız çıktı escape, davranış aynı).

---

## F3 — InvoiceUpdate backend validator'ları
**Önce:** tüm alanlar doğrulayıcısız → API-direkt negatif tutar / "999%" KDV / `<script>` vendor kabul.
**Sonra:** `field_validator`'lar — API-direkt çağrıda da 422 ile reddedilir; editör mesajı temiz gösterir.
- amount, vat_amount: `>= 0` ve `<= 10.000.000`
- vat_rate: whitelist `{0,5,5.5,7,10,16,19,20}%`
- invoice_type: `expense|income`
- vendor: boş değil + `<` `>` yok

**Test (pydantic 2.12.5 ile çalıştırıldı):**
```
REJECT: amount<0 [PASS]  amount>max [PASS]  vat_amount<0 [PASS]
        vat_rate 999% [PASS]  vat_rate 'abc' [PASS]  vendor boş [PASS]
        vendor <script> [PASS]  invoice_type 'hack' [PASS]
ACCEPT: amount 234.99 [PASS]  vat_rate 19% [PASS]  vendor 'Lidl GmbH' [PASS]
        invoice_type income [PASS]
-> F3 GEÇTİ
```
**Risk (orta):** Eski bir fişin `vat_rate`'i whitelist dışındaysa (ör. nadiren "16%" dışı bir değer) o fiş düzenlenip kaydedilince 422 olur. Whitelist Almanya geçmiş+güncel oranları kapsıyor; gerçek dünyada düşük olasılık. İzlenecek.

---

## Genel riskler & geri alma
- 3 fix de **küçük + izole + fail-soft**. Sorun olursa tek commit revert (`git revert <hash>`).
- Date/validator hataları kullanıcıya **açık 400/422 mesajı** döner (sessiz kayıp yok).
- Yeni dependency yok, DB migration yok, şema değişikliği yok.

## Kapsam dışı (bilerek — sonraki dalga)
- F4 line-item `date` attr escape (XSS-2, P2)
- F5 Email/IBAN/Website format (şu an PATCH'le yazılmıyor)
- F7 `Invoice.date` String→Date migration (P3, riskli, yedekli ayrı sprint)

---

## ONAY
3 commit yerelde hazır + test'li. **Push (=Railway deploy) için onayını bekliyorum.**
Onaylarsan push eder, deploy sağlığını + canlıda 1-2 senaryoyu doğrularım.
