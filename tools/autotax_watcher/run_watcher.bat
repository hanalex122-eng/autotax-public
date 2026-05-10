@echo off
REM AutoTax Watcher - tek tikla baslatici
REM Bu dosyayi config.json ile ayni klasorde tut

cd /d "%~dp0"
echo.
echo  ============================================
echo   AutoTax Scanner Watcher
echo  ============================================
echo.

where python >nul 2>&1
if errorlevel 1 (
    echo [HATA] Python kurulu degil.
    echo Indir: https://www.python.org/downloads/
    echo Kurarken "Add Python to PATH" isaretle.
    pause
    exit /b 1
)

if not exist config.json (
    echo [HATA] config.json bulunamadi.
    echo config.example.json'i kopyala -^> config.json yap, icini doldur.
    pause
    exit /b 1
)

python -m pip install --quiet --upgrade requests
python autotax_watcher.py --config config.json
pause
