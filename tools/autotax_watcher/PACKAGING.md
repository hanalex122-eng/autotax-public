# AutoTax Watcher — Packaging & Release Rehberi

Bu klasör Windows'ta üretim kalitesinde EXE + installer üretmek için her şeyi içerir. Mantık değişikliği yok — sadece paketleme/dağıtım.

## İçindekiler

- [Build hızlı yol](#build-hızlı-yol)
- [Yeni sürüm yayınlama](#yeni-sürüm-yayınlama)
- [Dosya/dizin haritası](#dosyadizin-haritası)
- [Code signing (önerilen)](#code-signing-önerilen)
- [SmartScreen reputation](#smartscreen-reputation)
- [Defender false-positive'i azaltma](#defender-false-positive)
- [Silent install / kurumsal dağıtım](#silent-install--kurumsal-dağıtım)
- [Sorun giderme](#sorun-giderme)

---

## Build hızlı yol

### Bir kerelik kurulum

1. **Python 3.10+** — `python --version` çalışmalı (PATH'te)
2. **Inno Setup 6** — https://jrsoftware.org/isinfo.php (kurulum sırasında "Install ISCC.exe" otomatik gelir)
3. **Bağımlılıklar:**
   ```bat
   cd tools\autotax_watcher
   pip install -r requirements.txt
   ```

### Build

```bat
cd tools\autotax_watcher
build.bat
```

`build.bat` ne yapar:

1. `version.txt`'den sürümü okur (`2.0.0`)
2. `packaging\version_info.txt`'i o sürüme göre yeniden yazar (PyInstaller ile EXE'ye gömülen Windows resource)
3. `packaging\AutoTaxWatcher.ico`'yu Pillow ile üretir (16/24/32/48/64/128/256 px)
4. PyInstaller → `dist\AutoTaxWatcher.exe` (~30-40 MB, single-file, `console=False`)
5. Inno Setup → `release\AutoTaxWatcher-Setup-2.0.0.exe`

**Sadece EXE yeterliyse Inno Setup kurulu olmasın — `build.bat` "installer atlandı" diye yazar, EXE çalışır.**

### Test

```bat
dist\AutoTaxWatcher.exe --no-tray
```

`--no-tray` konsol açar, hatalar terminale düşer. Tray test için ikon flag'siz dene.

---

## Yeni sürüm yayınlama

```bat
cd tools\autotax_watcher
release.bat
```

İnteraktif olarak yeni sürüm sorar (örn. `2.0.1`). Sonra:

1. `version.txt` → `2.0.1`
2. `autotax_watcher.py` içindeki `APP_VERSION = "..."` → `2.0.1`
3. `version_info.txt` → 2.0.1.0 / 2.0.1.0
4. Build çalışır
5. `release\AutoTaxWatcher-Setup-2.0.1.exe.sha256.txt` üretir

Sonra **manuel** adımlar:

```bat
git add version.txt autotax_watcher.py packaging\version_info.txt
git commit -m "release: watcher v2.0.1"
git tag watcher-v2.0.1
git push --follow-tags
```

GitHub Releases → "Draft a new release" → tag `watcher-v2.0.1` → installer + sha256 dosyalarını yükle.

Backend'de Railway env vars güncelle (yeni sürümü duyur):

```
WATCHER_LATEST_VERSION = 2.0.1
WATCHER_DOWNLOAD_URL   = https://github.com/hanalex122-eng/autotax-public/releases/download/watcher-v2.0.1/AutoTaxWatcher-Setup-2.0.1.exe
WATCHER_SHA256         = <release/.sha256.txt içindekini kopyala>
WATCHER_RELEASE_NOTES  = "Bug fixes, daha hızlı kuyruk işleme."
WATCHER_MANDATORY      = 0          # 1 ise zorunlu güncelleme
```

`updater.py` kullanıcı tarafında her başlangıçta `/watcher/version.json`'ı çağırır, yeni varsa tray bildirimi gösterir.

---

## Dosya/dizin haritası

```
tools/autotax_watcher/
├── autotax_watcher.py            # ana app (paketleme dışı — dokunmuyoruz)
├── updater.py                    # auto-update kontrol modülü
├── version.txt                   # tek satır: 2.0.0
├── requirements.txt              # runtime + build dep'leri
├── AutoTaxWatcher.spec           # PyInstaller spec (production-tuned)
├── build.bat                     # tek komutla EXE + installer üret
├── release.bat                   # version bump + build + hash
├── run_watcher.bat               # geliştirici/test modu
├── README.md                     # son kullanıcı rehberi
├── PACKAGING.md                  # BU dosya
├── packaging/
│   ├── installer.iss             # Inno Setup script
│   ├── version_info.txt          # Windows EXE resource (CompanyName, vs.)
│   ├── build_icon.py             # Pillow ile .ico üretici
│   ├── bump_version_info.py      # version.txt → version_info patch
│   └── AutoTaxWatcher.ico        # build sırasında üretilir (gitignore)
├── dist/                         # PyInstaller çıktısı (gitignore)
├── build/                        # PyInstaller temp (gitignore)
└── release/                      # final installer + sha256 (gitignore)
```

---

## Code signing (önerilen)

İmzasız EXE'lerde Windows iki sorun çıkarır:

1. **SmartScreen** — "Bu uygulamanın yayıncısı doğrulanamadı" → "Yine de çalıştır" tıklamak gerek
2. **Defender** — PyInstaller bootloader pattern'i sıkça false-positive üretir

### Sertifika seçenekleri

| Tip | Yıllık fiyat | SmartScreen reputation | Donanım | Tavsiye |
|---|---|---|---|---|
| **Sectigo OV (Standard)** | ~80 € | Birikmesi gerekir (~3000 kurulum) | Sertifika dosyası | Bütçe darsa |
| **Sectigo / DigiCert EV** | ~250-300 € | **İlk kullanımdan itibaren** | USB token (FIPS) | Profesyonel — önerilen |

EV sertifikası SmartScreen'de "anında güvenli" anlamına gelir. OV için reputation birikmesini bekleyeceksin (binlerce müşteri hızlı erişimde değilse aylarca sürebilir).

### İmzalama akışı

```bat
:: Sertifika USB takılı / .pfx hazır olsun
signtool sign /tr http://timestamp.digicert.com /td sha256 /fd sha256 ^
  /a /n "AutoTax-Cloud" dist\AutoTaxWatcher.exe

signtool sign /tr http://timestamp.digicert.com /td sha256 /fd sha256 ^
  /a /n "AutoTax-Cloud" release\AutoTaxWatcher-Setup-2.0.0.exe
```

`build.bat` sonuna ekleyebilirsin (sertifika varsa):

```bat
where signtool >nul 2>&1
if not errorlevel 1 (
    signtool sign /tr http://timestamp.digicert.com /td sha256 /fd sha256 ^
      /a /n "AutoTax-Cloud" dist\AutoTaxWatcher.exe
    signtool sign /tr http://timestamp.digicert.com /td sha256 /fd sha256 ^
      /a /n "AutoTax-Cloud" "release\AutoTaxWatcher-Setup-%APP_VERSION%.exe"
)
```

`/tr` (timestamp) **şart** — sertifika süresi dolduktan sonra bile imza geçerli kalır.

---

## SmartScreen reputation

OV sertifikan varsa süreci hızlandırmak için:

1. **Microsoft Partner Center** → "Application Reputation" submission (ücretsiz, sertifika sahibi gerek)
2. Düzenli imzalı release atın — her yeni binary yeni bir reputation hesabı
3. **Aynı thumbprint** kullanmaya devam et — sertifikayı yenileyince reputation kaybolur

Reputation gelene kadar son kullanıcılara şunu yaz:
> "Yine de çalıştır" → "Daha fazla bilgi" → "Yine de çalıştır"

---

## Defender false-positive

PyInstaller bootloader Windows Defender ile sürekli savaşır. Mücadele yöntemleri:

1. **UPX KAPALI** (`upx=False` spec'te) — UPX en büyük false-positive kaynağı. Boyut artar (~10 MB) ama güven çok daha yüksek.
2. **`console=False`** — terminal pencereli onefile EXE bayrak alma riski yüksek
3. **Version metadata eksiksiz** — CompanyName + FileDescription + ProductVersion (zaten ekledik)
4. **Code signing** (EV ideal, OV iyi) — en etkili yöntem
5. **VirusTotal'a önceden gönder** — yanlış pozitifleri raporla:
   - Microsoft: https://www.microsoft.com/wdsi/filesubmission
   - VirusTotal Community → "False Positive" oy ver
6. **PyInstaller bootloader rebuild** (ileri seviye, opsiyonel):
   ```bat
   git clone https://github.com/pyinstaller/pyinstaller
   cd pyinstaller\bootloader
   python ./waf all
   ```
   Yerel rebuild edilmiş bootloader signature DB'lerinde olmaz → false-positive düşer. Ama her PyInstaller güncellemesinde tekrar gerekir.

---

## Silent install / kurumsal dağıtım

Inno Setup standart bayraklar:

```bat
:: Tamamen sessiz, hiçbir UI göstermeden kurulum
AutoTaxWatcher-Setup-2.0.0.exe /VERYSILENT /NORESTART

:: Sessiz, sadece progress bar
AutoTaxWatcher-Setup-2.0.0.exe /SILENT

:: Otomatik startup'a kayıt + masaüstü ikonu
AutoTaxWatcher-Setup-2.0.0.exe /VERYSILENT /TASKS="desktopicon,startupicon"

:: Sessiz uninstall
"%LOCALAPPDATA%\Programs\AutoTax Watcher\unins000.exe" /VERYSILENT
```

Bayi/IT departmanına dağıtım için:

```bat
:: GPO veya intune'da deploy edilecek tek satır
\\fileserver\autotax\AutoTaxWatcher-Setup-2.0.0.exe /VERYSILENT /TASKS="startupicon"
```

---

## Sorun giderme

| Belirti | Neden | Çözüm |
|---|---|---|
| `pyinstaller: command not found` | venv aktif değil veya pip kurulumu PATH'te değil | `python -m PyInstaller AutoTaxWatcher.spec` |
| Build başarılı ama EXE açılmıyor (sessiz çıkış) | Hidden import eksik | `--no-tray` ile çalıştır → konsol logu gör; eksik modülü `HIDDEN_IMPORTS`'a ekle |
| Defender EXE'yi anında siliyor | UPX açık veya bootloader bayraklı | `upx=False` (zaten kapalı) + signing + dist/'i Defender exclusion'a koy (sadece geliştirici PC) |
| Inno Setup `Source file not found: dist\AutoTaxWatcher.exe` | PyInstaller önce çalışmadı | `build.bat`'i komple çalıştır, `iscc` tek başına değil |
| Tray ikonu görünmez | pystray hidden import eksik | `pystray._win32` HIDDEN_IMPORTS'ta olmalı (zaten var) |
| EXE 50+ MB | excludes liste eksik | `EXCLUDES`'a `pandas`, `numpy`, `matplotlib` eklenmiş mi kontrol et |
| `ImportError: Pillow` build sırasında | Pillow eksik | `pip install -r requirements.txt` |
| Eski sürüm hala startup'ta açılıyor | İki kayıt çakışıyor (manuel + Inno) | Görev Yöneticisi → Başlangıç → eski girdiyi sil |
| `/watcher/version.json` 200 dönüyor ama updater "yeni sürüm" demiyor | Local sürüm yeni / eşit | `python -c "from updater import is_newer; print(is_newer('2.0.1','2.0.0'))"` ile sınama |

---

## Güvenlik checklist (release öncesi)

- [ ] `version.txt`, `version_info.txt`, `APP_VERSION` (autotax_watcher.py) **aynı sürümü** gösteriyor
- [ ] `dist\AutoTaxWatcher.exe` çift tıklayınca login penceresi açılıyor
- [ ] Login → klasör seç → tray ikonu çıkıyor
- [ ] Test PDF tarat → AutoTax dashboard'da beliriyor
- [ ] Internet kapatıp test → dosya kuyruğa giriyor, internet gelince yükleniyor
- [ ] Aynı dosyayı tekrar bırak → "Diese Datei wurde bereits hochgeladen" görünüyor (silinmiyor)
- [ ] Uninstall + yeniden kurulum → eski email/folder hatırlanıyor (`%LOCALAPPDATA%\AutoTax\Watcher\config.json` korunmuş)
- [ ] (Sertifika varsa) `signtool verify /pa /v dist\AutoTaxWatcher.exe` → "Successfully verified"
- [ ] VirusTotal taraması → temiz veya sadece bilinen PyInstaller bootloader bayrakları
