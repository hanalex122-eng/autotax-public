# PRODUCTION DATABASE AUDIT — P1 POST-DEPLOY

> 2026-06-13 · Kanıt: canlı SQL (`/admin/db-audit`) + kod (file:line). Tahmin yok.
> DB: PostgreSQL 18.3 · users=3 · invoices=832 · cash_entries=839

---

# Executive Summary

| # | Alan | Durum | Özet |
|---|---|---|---|
| 0 | DB bağlantısı | ✅ **PASS** | PostgreSQL 18.3, bağlantı + sorgu OK |
| 1 | Alembic | 🟡 **WARNING** | `alembic_version` tablosu YOK; şema yine de modellerle birebir (drift yok) |
| 2 | Validator uyumu | 🟡 **WARNING** | Son 20'de 10 "uyumsuz" — sebebi **veri değil, benim fazla-katı validatörüm** (hotfix'lendi) |
| 3 | Create-path tarih | 🔴 **FAIL** | F1 sadece PATCH/PUT'ta; **create yolunda tarih doğrulama YOK** → 275760 hâlâ girilebilir |
| 4 | Bookkeeping | 🟡 **WARNING** | 0 dangling ref (iyi), ama 52 cash_entry invoice'a bağsız |
| 5 | Schema | ✅ **PASS** | Model ↔ DB kolonları birebir; eksik/fazla yok |

---

# Evidence (SQL çıktıları)

**#0 Bağlantı:** `SELECT version()` → `PostgreSQL 18.3 (Debian)` · `1_db_connection.ok=true`

**#1 Alembic:**
```
SELECT version_num FROM alembic_version
→ (psycopg2.errors.UndefinedTable) relation "alembic_version" does not exist
```
Migration dosyaları (repo): `001_baseline`, `002_kasse_sprint1`, **`003_kasse_sprint2` (head)**.
`#6 schema_mismatch` tüm tablolarda boş → DB şeması fiilen 003 ile **uyumlu**.

**#2 Validator (son 20):** `incompatible_count=10` —
```
id 832/830/829/825/823/821/820/814/813 → vat_rate='19.0%'/'20.0%'/'7.0%'/'0.0%'/'8.1%'/'4.4%'  (9)
id 831 → total_amount=-55.35  (1)
```
→ Hepsi **format/iş-kuralı**; gerçek bozuk veri DEĞİL (bkz Root Causes).

**#4/#5 Bookkeeping:**
```
orphan_cash_entries_dangling_invoice_id = 0      (referans bütünlüğü SAĞLAM)
cash_entries_without_invoice_link        = 52     (invoice_id NULL)
```

**#5 Schema:** `invoices/cash_entries/users` → `model_cols_missing_in_db=[]`, `db_cols_not_in_model=[]`

---

# Root Causes (teknik nedenler)

1. **#1 Alembic yok:** DB, `init_db()` (`db.py:32` `create_all` + elle `ALTER`) ile kurulmuş; `alembic upgrade head` (`Procfile: release`) ya hiç çalışmadı ya `|| echo` ile yutuldu → `alembic_version` hiç oluşmadı. Şema doğru ama Alembic "takipsiz".
2. **#2 Uyumsuzluk = benim hatam:** F3 validatörüm `vat_rate` için **string whitelist** ("19%") kullanıyordu; DB **"19.0%"** (ondalık + 8.1%/4.4% yabancı oran) saklıyor. Ayrıca `amount<0` reddediyordu; DB'de **meşru negatif** (id 831 = -55.35, Gutschrift/Storno) var. → 10 faturayı düzenleme **kırılırdı**. **DÜZELTİLDİ** (commit 70f9d4b): vat_rate sayısal aralık 0–30%, amount sadece |büyüklük|≤10M.
3. **#3 Create-path açığı (KANIT - kod):** `_create_bookkeeping` (`main.py:9746`) → `date=body.date or ""` **ham**; Rechnung create (`main.py:7317`) benzer. F1 `_sane_invoice_date` **yalnız** `patch_invoice`/`put_invoice`'ta. → `275760-12-31` create yoluyla **hâlâ girilebilir**.
4. **#4 52 bağsız cash_entry:** `_create_bookkeeping` her zaman invoice bağlar; ama DATEV/CSV import & banka/manuel-kasa yolları invoice'sız cash_entry üretebilir (fatura olmayan nakit normaldir). Dangling ref = 0 olduğundan **veri kaybı yok**.

---

# Recommended Fixes (öncelik sırası)

| Öncelik | Fix | Dosya | Risk |
|---|---|---|---|
| **P0** | ✅ F3 hotfix (vat_rate aralık + negatif amount) — **YAPILDI/deploy** | main.py | düşük |
| **P0** | **Create-path date guard:** `_sane_invoice_date`'i `_create_bookkeeping` + Rechnung create'e uygula (#3 FAIL'i kapatır) | main.py:9746, 7317 | düşük |
| **P1** | **Alembic stamp:** Railway shell → `alembic stamp head` (şema zaten 003; migration takibini hizalar). ALTERNATİF: `alembic upgrade head` ÇALIŞTIRMA (tablolar var → çakışır) | ops | orta (yanlış komut riskli) |
| **P1** | **Bozuk-tarih temizliği:** tam-tablo taramasından (`4b`) `date_format/date_calendar/date_year` ID'leri → editörde elle düzelt (doğru tarih uydurulamaz). SQL listesi aşağıda | DB | orta |
| **P2** | 52 bağsız cash_entry'nin hangi yoldan geldiğini doğrula (DATEV/import?) — muhtemelen meşru | — | düşük |

**Bozuk tarih LİSTELEME SQL (önce gör, sonra karar):**
```sql
SELECT id, date, vendor, total_amount FROM invoices
WHERE date IS NOT NULL AND date <> ''
  AND date !~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$';        -- format bozuk (ör. 810: 275760-12-31)
```
> NOT: Toplu `UPDATE` ile tarih **uydurulmaz** (orijinal fiş gerekir). Güvenli seçenek: bozuk tarihleri **flag/NULL** yapıp kullanıcının editörden (artık kısıtlı takvim) düzeltmesini istemek. vat_rate/amount için **temizleme GEREKMEZ** — veri doğru, validatör düzeldi.

---

# Risk Assessment (production)

- **Veri kaybı riski: DÜŞÜK.** Dangling referans = 0; schema drift = 0; bağlantı sağlam.
- **Aktif regresyon riski: GİDERİLDİ.** F3-hotfix öncesi 10+ faturanın düzenlenmesi 422 ile bloklanıyordu → hotfix deploy edildi.
- **Açık FAIL: create-path tarih (#3)** — kullanıcı/araç create yoluyla geçersiz tarih yazabilir; P0 fix bekliyor (bu turda öneriyorum).
- **Alembic:** app çalışmasını etkilemiyor (create_all şemayı tutuyor); risk yalnız gelecekteki migration'lar için → `stamp head` ile hizalanmalı.
- **Bütünlük:** Tüm sorgular `user_id` izolasyonlu; audit ucu read-only (SELECT). Yazma/silme yok.

## Tam-tablo sonucu (832 invoice, düzeltilmiş validatör — 2026-06-13)
`4b_fulltable_scan_corrected.counts`:
- ✅ `vat_rate_bad=0`, `amount_magnitude=0`, `invoice_type_bad=0`, `date_year=0` → **F3-hotfix doğrulandı; vat/amount temiz, temizlik gerekmez**
- 🔴 `date_format=5` → id **751, 582, 594, 570, 737** (tarih YYYY-MM-DD değil)
- 🔴 `date_calendar=6` → id **559, 380, 583, 571, 726, 740** (takvim-geçersiz gün)
- 🟠 `vendor_html=1` → id **661** (vendor'da `<`/`>`)

**Aksiyon (YARIN):** 12 kayıt — bozuk tarihler editörde elle düzeltilecek (artık kısıtlı takvim) ya da flag/NULL; id 661 vendor'ı incele (XSS payload mı, stray char mı) + temizle. vat_rate/amount için işlem YOK.
`5_bookkeeping`: 0 dangling, 0 orphan manual invoice, 52 invoice'suz cash_entry (incele — muhtemelen meşru nakit).
