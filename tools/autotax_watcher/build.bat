@echo off
REM ============================================================
REM AutoTax Watcher - production build
REM
REM Adimlar:
REM   1. version.txt'den surum oku
REM   2. version_info.txt'i o surume gore yeniden uret
REM   3. Pillow ile AutoTaxWatcher.ico uret
REM   4. PyInstaller ile dist\AutoTaxWatcher.exe uret
REM   5. Inno Setup ile release\AutoTaxWatcher-Setup-x.y.z.exe uret
REM
REM Gereksinim:
REM   - Python 3.10+  (PATH'te)
REM   - Inno Setup 6  (https://jrsoftware.org/isinfo.php)  [opsiyonel]
REM
REM Kullanim:    build.bat
REM ============================================================
setlocal EnableExtensions
cd /d "%~dp0"

echo.
echo === [1/5] Version oku ===
if not exist version.txt (
    echo HATA: version.txt yok.
    exit /b 1
)
set /p APP_VERSION=<version.txt
REM CR ve bosluklari temizle
for /f "tokens=* delims= " %%a in ("%APP_VERSION%") do set APP_VERSION=%%a
set APP_VERSION=%APP_VERSION:.0=.0%
echo     Version: %APP_VERSION%

echo.
echo === [2/5] version_info.txt yeniden uret ===
python packaging\bump_version_info.py %APP_VERSION%
if errorlevel 1 (
    echo HATA: version_info uretilemedi.
    exit /b 1
)

echo.
echo === [3/5] Icon uret ===
python packaging\build_icon.py packaging\AutoTaxWatcher.ico
if errorlevel 1 (
    echo HATA: icon uretilemedi.
    exit /b 1
)

echo.
echo === [4/5] PyInstaller - EXE ===
if exist dist rmdir /s /q dist
if exist build rmdir /s /q build
python -m PyInstaller --noconfirm AutoTaxWatcher.spec
if errorlevel 1 (
    echo HATA: PyInstaller basarisiz.
    exit /b 1
)
echo     Cikti: dist\AutoTaxWatcher.exe

echo.
echo === [5/5] Inno Setup - Installer ===
set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" (
    echo UYARI: Inno Setup bulunamadi - installer atlandi.
    echo Indir: https://jrsoftware.org/isinfo.php
    echo EXE hala dist\AutoTaxWatcher.exe altinda kullanilabilir.
    goto :done
)
"%ISCC%" /DAppVersion=%APP_VERSION% packaging\installer.iss
if errorlevel 1 (
    echo HATA: Inno Setup basarisiz.
    exit /b 1
)
echo     Cikti: release\AutoTaxWatcher-Setup-%APP_VERSION%.exe

:done
echo.
echo === BUILD TAMAMLANDI ===
echo.
echo   EXE        : dist\AutoTaxWatcher.exe
echo   Installer  : release\AutoTaxWatcher-Setup-%APP_VERSION%.exe
echo.
endlocal
