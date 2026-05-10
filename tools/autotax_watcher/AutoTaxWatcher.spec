# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec — production-ready single-file Windows EXE.
# build.bat tarafından çağrılır; doğrudan da çalışır:
#   pyinstaller --noconfirm AutoTaxWatcher.spec
#
# Önemli noktalar:
# - console=False  → tray modunda siyah konsol penceresi açılmaz
# - icon           → multi-resolution .ico (build_icon.py üretir)
# - version        → version_info.txt (Windows EXE Properties metadata)
# - excludes       → bloat azalt + Defender false-positive azalt
# - upx=False      → UPX sıkıştırma Windows Defender'da yüksek false-positive
#                    oranına yol açıyor; SmartScreen reputation gelene kadar
#                    açmamak güvenli.
# - onefile        → tek EXE müşteri dostu (zip açma gerekmez)

import os
from pathlib import Path

HERE = Path(os.path.abspath(SPECPATH))
PKG = HERE / "packaging"

ICON = str(PKG / "AutoTaxWatcher.ico")
VERSION = str(PKG / "version_info.txt")

# Pillow + pystray + tkinter PyInstaller'ın bazen kaçırdığı submodüller
HIDDEN_IMPORTS = [
    "pystray._win32",
    "PIL._tkinter_finder",
    "PIL.Image",
    "PIL.ImageDraw",
    "PIL.ImageFont",
    "tkinter",
    "tkinter.ttk",
    "tkinter.filedialog",
    "tkinter.messagebox",
    "requests",
    "urllib3",
    "charset_normalizer",
    "certifi",
    "idna",
]

# Watcher'ın ihtiyaç duymadığı ama Python'la gelen ağır paketler — bunları
# dışarıda bırakmak EXE boyutunu ~30 MB ve cold-start'ı 0.5–1 sn azaltır.
EXCLUDES = [
    "matplotlib",
    "numpy",
    "scipy",
    "pandas",
    "PyQt5",
    "PyQt6",
    "PySide2",
    "PySide6",
    "IPython",
    "jupyter",
    "notebook",
    "test",
    "tests",
    "unittest",
    "pydoc_data",
    "doctest",
    "lib2to3",
]

a = Analysis(
    ['autotax_watcher.py'],
    pathex=[str(HERE)],
    binaries=[],
    datas=[],
    hiddenimports=HIDDEN_IMPORTS,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUDES,
    noarchive=False,
    optimize=2,  # __doc__ ve assert'leri çıkar (smaller, marginally faster)
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='AutoTaxWatcher',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # UPX kapalı — antivirus reputation için kritik
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=ICON if os.path.exists(ICON) else None,
    version=VERSION if os.path.exists(VERSION) else None,
    # uac_admin=False → user'ın yazma haklarına sahip olduğu yerlere kurulur,
    # tray uygulaması admin gerektirmemeli.
    uac_admin=False,
    uac_uiaccess=False,
)
