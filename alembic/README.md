# Alembic — sema migration'lari

Bu klasor sema degisikliklerini takip eder. Su an `init_db()` (autotax/db.py)
hala mevcut tablolar icin ALTER TABLE migration'lari yapiyor. Alembic
SONRAKI degisiklikler icin hazir altyapi olarak kuruldu.

## Kurulum (ilk kez)

Prod DB'sinde sema zaten init_db() ile uygulandiysa, baseline'i kayit altina
al ki Alembic CREATE TABLE'i tekrar denemesin:

```bash
alembic stamp head     # mevcut DB'yi en son revizyondaymis gibi isaretle
```

(Eger hic revizyon yoksa, ilk autogenerate sonrasinda yapilir — asagi bak.)

## Yeni sema degisikligi

1. autotax/models.py'ye yeni kolon/tablo ekle.
2. Yerel ortamda revizyon uret:
   ```bash
   alembic revision --autogenerate -m "ne degisti"
   ```
3. `alembic/versions/*.py` dosyasini incele — autogenerate her zaman mukemmel
   degil (ozellikle index ve server_default'lar icin manuel duzenleme gerekebilir).
4. Yerel DB'de uygula:
   ```bash
   alembic upgrade head
   ```
5. Commit + push. Railway'de `release` veya start komutunda otomatik
   `alembic upgrade head` calisacak sekilde Procfile/railway.json guncellenebilir
   (henuz aktif degil — manuel adim).

## Mevcut init_db() ile cakisma

`init_db()` su an Base.metadata.create_all + manuel ALTER TABLE yapiyor.
Alembic devreye girince ikisi cakisabilir. Plan:

1. Alembic baseline alinir (`stamp head`).
2. init_db() icindeki ALTER TABLE blogu kaldirilir; Base.metadata.create_all
   kalir (yeni kullanicilarin local SQLite'i icin pratiktir).
3. Tum yeni sema degisiklikleri yalnizca alembic uzerinden yapilir.

Bu gecis bu PR'da YAPILMIYOR — sadece altyapi kuruldu. Sonraki adim:
prod'da `alembic stamp head` calistirip akisi tasimak.
