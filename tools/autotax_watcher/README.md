# AutoTax Scanner Watcher

Scanner'ın PDF/JPG çıktılarını otomatik olarak AutoTax-Cloud'a yükler.

## Nasıl çalışır

1. Scanner'ın çıktıyı verdiği klasörü (örn. `C:\Scans`) izler.
2. Yeni dosya geldiğinde tarama bitsin diye birkaç saniye bekler.
3. Otomatik olarak `/invoices/upload` endpoint'ine yükler.
4. Başarılı dosyaları `Uploaded/` alt klasörüne taşır, başarısızları `Failed/`'e.

## Kurulum (Windows)

1. **Python yükle** (yoksa): https://www.python.org/downloads/ — kurulumda **"Add Python to PATH"** kutusunu işaretle.
2. Bu klasörü bilgisayarına indir (örn. `C:\AutoTaxWatcher`).
3. `config.example.json` → `config.json` olarak kopyala, içini doldur:
   - `api_token`: AutoTax-Cloud'a giriş yaptıktan sonra browser'da `F12` → Console → `localStorage.getItem("atx_token")` ile al.
   - `watch_folder`: Scanner'ın çıktıyı verdiği klasör (örn. `C:\Scans`).
4. `run_watcher.bat` dosyasına çift tıkla. Konsol açılır, "Yeni faturalar bekleniyor..." yazısı çıkar.
5. Scanner'la tarama yap → otomatik upload olur.

## Otomatik başlatma (opsiyonel)

`run_watcher.bat` kısa yolunu `Win+R` → `shell:startup` klasörüne kopyala — bilgisayar açılınca otomatik başlar.

## Tek başına çalıştırma (config'siz)

```bat
python autotax_watcher.py --url https://api.autotax.cloud --token YOUR_TOKEN --folder "C:\Scans"
```

## Sorun giderme

- **`pip install` çalışmıyor**: `python -m pip install requests` dene.
- **HTTP 401**: Token yanlış veya süresi dolmuş — tekrar al.
- **HTTP 413**: Dosya çok büyük (max 25 MB).
- **Hiç dosya alınmıyor**: `watch_folder` doğru mu? Scanner aynı klasöre mi yazıyor?

## Desteklenen formatlar

PDF, JPG, JPEG, PNG, WEBP
