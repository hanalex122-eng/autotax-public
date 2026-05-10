@echo off
REM ============================================================
REM AutoTax Watcher — release helper
REM
REM 1. Yeni surum numarasi sor
REM 2. version.txt + autotax_watcher.py icindeki APP_VERSION'u guncelle
REM 3. build.bat calistir
REM 4. SHA256 hash uret  (musteri dogrulayabilsin)
REM 5. release\ klasoru icine README + hash dosyasi koy
REM
REM NOT: Git commit/push'u BU SCRIPT yapmaz — sen manuel yap, build
REM     dosyalarini gozden gecirdikten sonra.
REM ============================================================
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

if not exist version.txt (
    echo HATA: version.txt yok.
    exit /b 1
)
set /p OLD_VER=<version.txt
set OLD_VER=%OLD_VER: =%

echo.
echo Mevcut surum: %OLD_VER%
set /p NEW_VER="Yeni surum (orn 2.0.1): "
if "%NEW_VER%"=="" (
    echo Iptal.
    exit /b 1
)

echo.
echo --- version.txt guncelleniyor ---
> version.txt echo %NEW_VER%

echo.
echo --- autotax_watcher.py icindeki APP_VERSION guncelleniyor ---
python packaging\bump_version_info.py %NEW_VER% --update-py
if errorlevel 1 (
    echo HATA: APP_VERSION yamasi basarisiz.
    exit /b 1
)

echo.
echo --- build basliyor ---
call build.bat
if errorlevel 1 exit /b 1

echo.
echo --- SHA256 ---
set "INSTALLER=release\AutoTaxWatcher-Setup-%NEW_VER%.exe"
if not exist "%INSTALLER%" (
    echo UYARI: Installer yok — hash uretilemedi.
) else (
    certutil -hashfile "%INSTALLER%" SHA256 > "release\AutoTaxWatcher-Setup-%NEW_VER%.sha256.txt"
    type "release\AutoTaxWatcher-Setup-%NEW_VER%.sha256.txt"
)

echo.
echo === RELEASE %NEW_VER% HAZIR ===
echo.
echo Sonraki adimlar:
echo   1. release\ klasorunu test et
echo   2. git add version.txt autotax_watcher.py
echo   3. git commit -m "release: watcher v%NEW_VER%"
echo   4. git tag watcher-v%NEW_VER%
echo   5. git push --follow-tags
echo   6. GitHub Releases sayfasina installer + sha256'yi yukle
echo.
endlocal
