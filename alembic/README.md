# Alembic — şema migration'ları

## Durum (Sprint 3 sonrası, 2026-05-14)

- ✅ Baseline revision oluşturuldu: `001_baseline` (boş upgrade)
- ✅ Procfile'a `release: alembic upgrade head` directive eklendi
- ⚠️ İlk gerçek migration'da prod'da bir kerelik `alembic stamp head`
  gerekebilir (alembic_version tablosu yoksa)
- ⚠️ db.py:init_db() içindeki manuel ALTER TABLE blokları **şu an
  korunuyor** (defense-in-depth). Yeni şema değişiklikleri Alembic +
  init_db'de birlikte tutulur.

## Yeni şema değişikliği (önerilen akış)

1. `autotax/models.py`'de değişiklik yap.
2. Yerel revision üret:
   ```bash
   alembic revision --autogenerate -m "açıklama"
   ```
3. `alembic/versions/*.py` üretilen dosyayı **incele**. Autogenerate her
   zaman doğru değildir — özellikle:
   - Index için `op.create_index` kontrolü
   - Server_default + nullable kombinasyonu
   - Yeni tablo: `op.create_table` yerine yine init_db'de
     `Base.metadata.create_all` yeterli
4. Yerel DB'de uygula:
   ```bash
   alembic upgrade head
   ```
5. Aynı değişikliği `db.py:init_db()` içine de **idempotent ALTER**
   olarak ekle (Alembic atlamış olsa bile yeni deploy şemayı düzeltir).
6. Commit + push. Railway deploy `release: alembic upgrade head`
   directive'i ile otomatik uygular.

## İlk migration için prod hazırlığı

Mevcut prod DB'de `alembic_version` tablosu yok. İlk deploy'ta
`alembic upgrade head` baseline revision'ı uygular (boş upgrade) +
`alembic_version` tablosunu oluşturur. Sonraki gerçek migration'lar
normal akışla devam eder.

Eğer ilk deploy'da hata çıkarsa (örn. version tablo conflict), bir
defaya mahsus Railway shell'de:

```bash
alembic stamp head
```

## Mevcut init_db() rolü

`init_db()` (autotax/db.py) hâlâ:
- `Base.metadata.create_all` — yeni tablolar (idempotent)
- Manuel `ALTER TABLE ... IF NOT EXISTS` — kolon ekleme (idempotent)

Bu KORUNUYOR — Alembic baseline'dan önce yaratılmış tüm tablolar için
geriye uyumluluk + dev/test ortamlarında SQLite kolaylığı sağlıyor.

Sprint 3 ileri aşaması: Alembic stabil hale gelince init_db'deki
manuel ALTER blokları emekli edilir. Şu an iki katman birlikte
çalışıyor — defense-in-depth.

## Komut özeti

```bash
# Yeni revision üret (autogenerate ile)
alembic revision --autogenerate -m "açıklama"

# Tüm bekleyen migration'ları uygula
alembic upgrade head

# Bir geri al
alembic downgrade -1

# Mevcut DB'yi en son revision'a stamp et (CREATE TABLE çalıştırmadan)
alembic stamp head

# Geçmişi göster
alembic history --verbose

# Mevcut DB'nin hangi revision'da olduğunu görüntüle
alembic current
```
