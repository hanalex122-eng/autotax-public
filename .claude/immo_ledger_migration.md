# Immobilien — Ledger-First Migration Planı

**Karar (2026-06-21):** Türetilmiş yıllık muhasebeden → **olay-bazlı ledger muhasebesine** geç.
**Kural:** Mevcut Mahnung / Leerstand / Cockpit / Debtor / Risk kodu **SİLİNMEZ, YENİDEN YAZILMAZ**. Strangler-fig ile ledger tabanına **taşınır**. Mevcut formüller, ledger'dan beslenen adapter ile aynı çıktıyı verene kadar dokunulmaz.
**Bu doküman = sadece migration planı.** Kod yok. P1 = Mietkonto Ledger.

> NOT: Bu doküman, `.claude/immo_p1_p4_plan.md` içindeki "Soll-only `immo_charge`" fikrinin yerine geçer. Artık tek birleşik **hareket defteri** (`immo_ledger_entry`) kullanılıyor — Soll + Zahlung + Korrektur + Mahnung aynı tabloda.

---

## 1. Hedef mimari — tek birleşik Mietkonto

**Bir Mietkonto = bir Konto, çok Buchung.** Her tenancy'nin (ileride her boş unit / NK / Anlage V) bir kontosu var; tüm hareketler tek tabloda saklanır.

**Buchungsarten (typ):**
| typ | Almanca | İşaret | Anlam |
|-----|---------|--------|-------|
| `sollbuchung` | Sollstellung | `+` (Forderung) | Aylık kira borcu doğdu |
| `zahlung` | Zahlung | `−` (Tilgung) | Tam ödeme |
| `teilzahlung` | Teilzahlung | `−` | Kısmi ödeme (zahlung ile aynı mekanik, ayrı etiket) |
| `korrektur` | Korrektur | `±` | Manuel düzeltme (iade, indirim, hata düzeltme) |
| `mahngebuehr` | Mahngebühr | `+` | Mahnung ücreti (ops, Mahnung olayına bağlı) |

**İşaret kuralı (karar):** `betrag` her zaman **işaretli** saklanır. `sollbuchung/mahngebuehr > 0` (Forderung artar), `zahlung/teilzahlung < 0` (borç azalır), `korrektur` ±.
→ **Konto-Saldo = Σ betrag.** Pozitif saldo = açık borç (Rückstand). Sıfır/negatif = ödenmiş/avans.
Bu kural tüm türetilmiş hesapları (debtor, risk, cockpit) tek `SUM()` ile besler.

**Neden tek tablo (ayrı charge+rent değil):** "Sollbuchung, Zahlung, Teilzahlung, Korrektur, Mahnung hareketleri saklansın" = klasik Mietkonto. Tek defter → saldo tek toplam, ay-durumu (paid/partial/open) tek sorgu, denetim izi (kim ne zaman ne booked) tam.

---

## 2. Yeni veri modeli

```
immo_ledger_entry  (Mietkonto-Buchung)
  id              PK
  user_id         FK users(id), idx            # izolasyon
  konto_art       String  = 'miete'            # gelecek: 'leerstand'|'nebenkosten'|'anlage_v'
  property_id     FK immo_property(id), idx
  unit_id         FK immo_unit(id), nullable, idx
  tenancy_id      FK immo_tenancy(id), nullable, idx   # miete kontosu için dolu
  typ             String  # sollbuchung|zahlung|teilzahlung|korrektur|mahngebuehr
  betrag          Float   # İŞARETLİ (bkz §1)
  jahr            Int, idx
  monat           Int     # 1-12, hangi aya ait (sollbuchung için zorunlu; zahlung mahsup ayı)
  buchungsdatum   Date    # olay tarihi (ödeme tarihi / sollstellung tarihi)
  faellig_am      Date, nullable   # sollbuchung için Fälligkeit (aging hesabı)
  beleg           String, nullable # serbest açıklama / referans
  source          String, nullable # 'auto'|'import_rent'|'manual'|'mahnung'
  source_rent_id  Int, nullable, idx   # backfill idempotency: hangi immo_rent'ten geldi
  mahnung_id      FK immo_mahnung(id), nullable  # mahngebuehr ↔ mahnung bağı
  created_at, is_deleted, deleted_at

  # idempotency için kısmi unique:
  UNIQUE(user_id, tenancy_id, typ, jahr, monat) WHERE typ='sollbuchung'   # ay başına 1 soll
  UNIQUE(source_rent_id) WHERE source_rent_id IS NOT NULL                 # 1 rent = 1 ledger
```

**Migration mekaniği:** `db.py` idempotent `CREATE TABLE IF NOT EXISTS` (mevcut immo deseni, Alembic yok). `Base.metadata.create_all` otomatik kurar. Partial-unique index Postgres'te `CREATE UNIQUE INDEX IF NOT EXISTS ... WHERE`.

**immo_rent'in geleceği:** **SİLİNMEZ.** Faz boyunca kaynak olarak kalır, ledger'a backfill edilir. Cutover sonrası `immo_rent` = legacy/yedek; yeni ödemeler ledger'a yazılır (bkz §3 Faz 4). Veri kaybı = sıfır.

---

## 3. Migration fazları (strangler-fig, non-destructive)

Her faz **canlıda mevcut davranışı bozmaz**; eski yol çalışmaya devam eder, yeni yol paralel kurulur, **parity (eşitlik) doğrulanınca** geçiş yapılır.

### Faz 0 — Temel (write-path, okuma değişmez)
- `immo_ledger_entry` tablosu + model.
- `ledger.py` (veya immo_api içi) **posting service**: `post_entry(...)`, `ensure_sollbuchungen(uid, year)`, `konto_saldo(...)`.
- Hiçbir mevcut endpoint/okuma değişmez. Tablo boş kurulur. **Risk: sıfır.**

### Faz 1 — Backfill (idempotent, tek seferlik + tekrarlanabilir)
- **Sollbuchung üret:** her tenancy'nin aktif ayları (von..min(bis,bugün)) için `sollbuchung` (+kaltmiete, faellig_am = ayın N'i). `ensure_sollbuchungen` idempotent (partial-unique).
- **immo_rent import:** her `immo_rent` → 1 `zahlung`/`teilzahlung` entry (`−betrag`, `source='import_rent'`, `source_rent_id=r.id`). `source_rent_id` unique → 2× çalışsa da çift yazmaz.
- Boş unit ayları HENÜZ ledger'a girmez (Leerstandkonto = ayrı faz; P1 sadece miete).
- **Çıktı:** ledger artık mevcut tüm veriyi olay-bazlı içeriyor. Eski tablolar dokunulmadı.

### Faz 2 — Read model (türetme katmanı)
- `konto_state(uid, tenancy_id, year)` → `{rows:[{monat, soll, ist, saldo, status, faellig_am, tage_ueberfaellig}], summe}` — **sadece ledger'dan**.
- `portfolio_arrears(uid, year)`, `debtors_from_ledger(uid, year)`, `risk_inputs_from_ledger(...)` — eski `_portfolio`/`_cockpit`'in ihtiyaç duyduğu **aynı şekilli** veriyi ledger'dan üretir.
- Hâlâ hiçbir tüketici buna bağlı değil. Sadece hesaplanır.

### Faz 3 — Parity gate (KRİTİK — kanıt kapısı)
- **Çift hesap + karşılaştır:** `_accounting`/`_portfolio`/debtor'ın ürettiği eski sayılar vs Faz 2 ledger sayıları.
- `GET /immo/_ledger_parity?year` (admin/debug) → her property için `{eski:{rueckstand,ist,...}, ledger:{...}, diff, ok:bool}`.
- **Tüm diff ≈ 0 (±0.01) olmadan cutover YOK.** Diff varsa kök-sebep (eksik backfill, yuvarlama, tarih sınırı) bulunur, düzeltilir.
- Bu kapı = "ledger doğru" kanıtı. CTO-mode: tahmin değil ölçüm.

### Faz 4 — Strangler cutover (tüketicileri ledger'a bağla)
Parity yeşil olunca, **formülleri yeniden yazmadan**, mevcut tüketicilerin veri kaynağını ledger adapter'a çevir:
- **Debtor Detection** (`_portfolio.top_debtors`): arrears'i `debtors_from_ledger`'dan al.
- **Cockpit** (`_cockpit`): `rueckstand`/actions/missing_rent → ledger read model.
- **Risk Scoring** (`score.components.schulden`): ledger saldo'dan.
- **Mahnung** (`_tenancy_arrears`, `create_mahnung`): açık tutar + **ay-ay döküm** ledger'dan; Mahnung kesilince `mahngebuehr` + kayıt ledger'a (`mahnung_id` bağı).
- Her biri **adapter fonksiyonu** ile beslenir; eski fonksiyon imzası/çıktısı korunur → UI/diğer kod değişmez. Eski derived hesap kod olarak kalır (fallback/feature-flag `IMMO_LEDGER_READ=1`), silinmez.

### Faz 5 — Yeni write-path (ledger artık birincil)
- `POST /immo/rent` (ve yeni `zahlung/teilzahlung/korrektur` endpoint'leri) → ledger'a yazar. Geçiş için **dual-write** opsiyonu: hem `immo_rent` hem ledger (geri dönüş güvenliği), sonra `immo_rent` salt-legacy.
- Sollbuchung üretimi **lazy** (cockpit/mietkonto çağrısında `ensure_sollbuchungen`, cron yok — kullanıcı kuralı).

### Faz 6 (sonraki sprintler, aynı desen)
- **Leerstandkonto:** boş unit-ay → `konto_art='leerstand'` entry (kayıp metriği).
- **Nebenkostenkonto:** umlagefähig giderler + voraus → `konto_art='nebenkosten'`.
- **Anlage V Export:** ledger toplamlarından yapısal export.

---

## 4. Geriye-dönük uyum & izolasyon
- Her ledger endpoint: `Depends(get_current_user)` + `user_id` filtre + `_own_property/_own_unit` guard + soft-delete.
- Cutover **feature-flag** arkasında: `IMMO_LEDGER_READ` (config.py). OFF → eski derived yol (bugünkü davranış). ON → ledger adapter. Tek satırla geri al.
- UI Faz 4'e kadar değişmez (aynı endpoint şekli). Mietkonto sekmesi (yeni UI) Faz 2 read model hazır olunca eklenir.

## 5. Rollback
- Faz 0-2: tablo eklemek dışında hiçbir şey değişmedi → rollback gereksiz.
- Faz 3: sadece debug endpoint.
- Faz 4: `IMMO_LEDGER_READ=0` → anında eski derived hesaba dön.
- Faz 5: dual-write açıkken `immo_rent` hâlâ dolu → ledger'ı truncate edip Faz 1 backfill tekrar.
- Ledger tablosu hiç drop edilmez; yanlışsa soft-delete + yeniden backfill.

## 6. Test planı
**Backfill (Faz 1)**
- `ensure_sollbuchungen` 2× → satır sabit (partial-unique).
- immo_rent import 2× → çift yok (`source_rent_id` unique).
- tenancy von=2026-03 → Mart..ref_month sollbuchung; Oca-Şub yok.

**Read model (Faz 2)**
- soll=800, zahlung=800 → status=paid, saldo=0.
- soll=800, teilzahlung=500 → partial, saldo=300.
- soll=800, ödeme yok, faellig=bugün−15 → open, tage=15.
- korrektur −100 → saldo doğru azalır.

**Parity (Faz 3)**
- ≥3 gerçek property: eski `rueckstand`/`ist`/`gewinn` == ledger ±0.01. Diff varsa FAIL.

**Cutover (Faz 4)**
- `IMMO_LEDGER_READ` ON/OFF → cockpit/debtor sayıları aynı (parity zaten garanti).
- Mahnung tutarı = ledger açık toplam; ay dökümü doğru; `mahngebuehr` entry oluştu.

**İzolasyon**
- user A ledger'ı user B'ye sızmıyor (her sorgu user_id).

## 7. Uygulama sırası (öneri)
1. **Faz 0** tablo + posting service + `ensure_sollbuchungen` (tek commit, risk yok)
2. **Faz 1** backfill (sollbuchung + immo_rent import, idempotent) + canlı kanıt (satır sayıları)
3. **Faz 2** read model (`konto_state` + adapters)
4. **Faz 3** parity endpoint → **yeşil olana kadar koda devam etme**
5. **Faz 4** strangler cutover (flag arkası) — debtor/cockpit/risk/mahnung ledger'dan
6. **Faz 5** Mietkonto UI sekmesi + yeni write-path
7. Faz 6 (sonra): Leerstand/NK/Anlage V aynı ledger deseniyle

**Deploy:** her faz tek konsolide commit, backend önce. Parity gate geçilmeden Faz 4'e geçilmez.
