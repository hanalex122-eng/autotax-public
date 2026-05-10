# AutoTax Scanner Watcher v2

Tarayıcınızdan gelen PDF/JPG belgelerini otomatik AutoTax-Cloud'a yükleyen küçük bir Windows uygulaması. Tray'de çalışır, login penceresinden e-mail + şifreyle giriş yaparsınız, klasör seçersiniz, sonrası otomatik.

## Hızlı kurulum (son kullanıcı)

1. **`AutoTaxWatcher.exe`** dosyasını indirin (`tools/autotax_watcher/release/`).
2. Çift tıklayın.
3. Açılan pencereye **e-mail + şifre** girin → "Anmelden".
4. **Tarayıcınızın çıktı klasörünü** seçin (örn. `C:\Scans`).
5. Tray'de yeşil "AT" ikonu belirir → Watcher arka planda çalışıyor.
6. Tarayıcıdan kâğıdı tarayın → birkaç saniye sonra AutoTax dashboard'da belirir.

> **Windows Defender uyarısı çıkarsa:** "Daha fazla bilgi → Yine de çalıştır". Code-signing sertifikası henüz eklenmedi.

## Tray menüsü

Sağ tıklayın:

| Menü | Açıklama |
|---|---|
| Durum | "ÇALIŞIYOR / DURDU — Kuyruk: N" |
| Ordner öffnen | İzlenen klasörü Explorer'da aç |
| Pausieren / Fortsetzen | Watcher'ı geçici durdur/sürdür |
| Failed-Uploads erneut versuchen | Kuyruktaki başarısızları hemen yeniden dene |
| Beenden | Çıkış |

## Sıfır-disk modu (önerilen müşteri ayarı)

Tarayıcıdan gelen belgenin PC'de **dosya olarak gözükmemesini** istiyorsanız:

```json
{
  "delete_after_upload": true
}
```

Bu ayar açıldığında: belge yüklenir → sunucuda güvenli → yerel kopya **silinir**. Kullanıcı `C:\Scans` klasörünü açtığında her zaman boş görür. Yedek backend'de saklı (`Invoice.file_data`).

Başarısız upload'lar `Failed/` alt klasörüne taşınır (silinmez — veri kaybolmasın).

## Config dosyası

Konum (otomatik oluşturulur):
- Windows: `%LOCALAPPDATA%\AutoTax\Watcher\config.json`
- Linux/Mac: `~/.autotax/watcher/config.json`

Tüm alanlar:

```json
{
  "api_url": "https://autotax-public-production-3f2a.up.railway.app",
  "api_token": "...",
  "refresh_token": "...",
  "email": "kullanici@firma.de",
  "folders": ["C:\\Scans", "D:\\Belege"],
  "invoice_type": "expense",
  "delete_after_upload": false,
  "processed_subfolder": "Uploaded",
  "failed_subfolder": "Failed",
  "retry_interval": 30,
  "auto_start": false
}
```

`api_token` ve `refresh_token` login sonrası otomatik dolar — elle dokunmayın.

## Komut satırı

```bat
AutoTaxWatcher.exe --reset           Mevcut girişi sıfırla, tekrar login iste
AutoTaxWatcher.exe --no-tray         Tray olmadan, terminal modunda çalış (debug)
AutoTaxWatcher.exe --config X.json   Özel config dosyası
```

## Geliştirici modu

```bat
git clone https://github.com/hanalex122-eng/autotax-public
cd autotax-public\tools\autotax_watcher
pip install -r requirements.txt
python autotax_watcher.py
```

EXE üretmek için:

```bat
pyinstaller AutoTaxWatcher.spec
```

Çıktı: `dist\AutoTaxWatcher.exe`

## Özellikler

- **Login GUI** (Tkinter, built-in) — token kopyalama yok
- **Auto refresh token** — 401 alınca arka planda yeni token al
- **429 Retry-After backoff** — server quota'ya takılırsa otomatik bekler
- **Offline JSON queue** — internet kesintisinde dosyalar kuyruğa alınır, 30s'de bir retry
- **Multi-folder** — `folders` listesinde birden fazla klasör
- **Pause/Resume** tray'den
- **Duplicate koruma** — backend zaten yüklenmiş dosyayı atlar (kayıt kopyası eklenmez)
- **File stability check** — tarayıcı dosyayı yazarken upload yapmaz, boyut sabitleşmesini bekler
- **Logging** — `%LOCALAPPDATA%\AutoTax\Watcher\logs\watcher.log` (5MB × 3 rotation)

## Tarayıcı yapılandırması

| Marka | "Tara" hedefi nasıl ayarlanır |
|---|---|
| HP | HP Smart → "PDF olarak kaydet" → klasör: `C:\Scans` |
| Brother | ControlCenter4 → "Dosyaya Tara" → hedef klasör |
| Canon | IJ Scan Utility → "Auto" tarayıcı butonu → kayıt yeri |
| Epson | Epson ScanSmart → tarama profili → kayıt klasörü |
| Network/SMB scanner | Tarayıcı SMB'yi `\\PC-ADI\Scans` paylaşımına yapılandır |

## Sorun giderme

- **Tray ikonu görünmez:** Saat'in yanındaki "^" ile gizli ikonları aç → AutoTaxWatcher sürükleyip görünür yap.
- **HTTP 401 sürekli:** `--reset` ile çalıştır → tekrar login ol.
- **HTTP 413:** Dosya çok büyük (max 25 MB). Tarayıcı çözünürlüğünü düşür (300 dpi yeterli).
- **Hiç dosya alınmıyor:** Tray menü → "Ordner öffnen" — klasör doğru mu? Tarayıcı oraya mı yazıyor?
- **Scanner PDF'i parça parça yazıyor:** Watcher `STABILITY_WAIT=3s` kontrolüyle yazma bitsin diye bekler — sorun olmamalı, sürekli oluşuyorsa logda "Bekleniyor..." görünür.

## Desteklenen formatlar

PDF, JPG, JPEG, PNG, WEBP
