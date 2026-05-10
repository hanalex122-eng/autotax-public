@echo off
REM AutoTax Watcher v2 — geliştirici/test modu (Python ile direkt çalıştır)
REM Son kullanıcı: AutoTaxWatcher.exe'yi kullansın, .bat değil.

cd /d "%~dp0"
echo.
echo  ============================================
echo   AutoTax Scanner Watcher v2
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

python -m pip install --quiet --upgrade -r requirements.txt
python autotax_watcher.py %*
