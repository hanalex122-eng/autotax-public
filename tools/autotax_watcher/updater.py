"""AutoTax Watcher — auto-update foundation.

Bağımsız modül.  Mevcut watcher mantığını DEĞİŞTİRMEZ.  İsteğe bağlı tek
satırla aktive edilir:

    from updater import check_for_update_async
    check_for_update_async(current_version=APP_VERSION, on_update_available=...)

Akış:
    1. GET <api_url>/watcher/version.json
    2. JSON: {"version":"2.1.0","download_url":"...","mandatory":false,"notes":"..."}
    3. Local sürümle karşılaştır (semver tarzı tuple).
    4. Yeni varsa callback tetikle (tray bildirimi, dialog, vs).

Yapmadığı:
    - Otomatik indirme/kurma (henüz).  Bu altyapı v2.1+ için hazır,
      şimdilik sadece "haber ver, kullanıcı manuel indirsin" modunda.
    - Self-replace.  PyInstaller onefile EXE çalışırken üzerine
      yazılamaz; future updater küçük bir "AutoTaxUpdater.exe"
      yardımcısıyla şu mantıkla yapacak:
          1. updater.exe başlat → ana exe'yi sonlandır
          2. yeni dosyayı indir, hash kontrol et, eski yerine kopyala
          3. ana exe'yi tekrar başlat → updater.exe çıkar
"""

from __future__ import annotations

import json
import logging
import re
import threading
from dataclasses import dataclass
from typing import Callable, Optional

try:
    import requests
except ImportError:
    requests = None  # type: ignore[assignment]


_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Sürüm karşılaştırma
# ---------------------------------------------------------------------------
def _to_tuple(s: str) -> tuple[int, ...]:
    """'2.0.1' → (2, 0, 1).  Sayısal olmayan parça ('beta') = 0."""
    parts = re.split(r"[.\-+]", s.strip())
    out: list[int] = []
    for p in parts:
        try:
            out.append(int(p))
        except ValueError:
            out.append(0)
    return tuple(out) or (0,)


def is_newer(remote: str, local: str) -> bool:
    """remote > local mı?"""
    return _to_tuple(remote) > _to_tuple(local)


# ---------------------------------------------------------------------------
# Update info
# ---------------------------------------------------------------------------
@dataclass
class UpdateInfo:
    version: str
    download_url: str
    mandatory: bool = False
    notes: str = ""
    sha256: str = ""

    @classmethod
    def from_json(cls, d: dict) -> "UpdateInfo":
        return cls(
            version=str(d.get("version", "")).strip(),
            download_url=str(d.get("download_url", "")).strip(),
            mandatory=bool(d.get("mandatory", False)),
            notes=str(d.get("notes", "")),
            sha256=str(d.get("sha256", "")).strip(),
        )


# ---------------------------------------------------------------------------
# Senkron + asenkron checker
# ---------------------------------------------------------------------------
def check_for_update(
    api_url: str,
    current_version: str,
    timeout: int = 10,
) -> Optional[UpdateInfo]:
    """Sunucuya bak, yeni sürüm varsa UpdateInfo döner, yoksa None."""
    if requests is None:
        _log.debug("requests modülü yok — updater pas geçildi")
        return None
    url = api_url.rstrip("/") + "/watcher/version.json"
    try:
        r = requests.get(url, timeout=timeout)
    except requests.RequestException as e:
        _log.debug("Update check başarısız: %s", e)
        return None
    if r.status_code != 200:
        _log.debug("Update check HTTP %d", r.status_code)
        return None
    try:
        data = r.json()
    except (ValueError, json.JSONDecodeError):
        return None
    info = UpdateInfo.from_json(data)
    if not info.version:
        return None
    if not is_newer(info.version, current_version):
        return None
    return info


def check_for_update_async(
    api_url: str,
    current_version: str,
    on_update_available: Callable[[UpdateInfo], None],
    delay_seconds: int = 0,
    timeout: int = 10,
) -> threading.Thread:
    """Arka thread'de update kontrolü.  Yeni varsa callback'i ana app'in
    bir bildirim göstermesi/dialog açması için tetikler.
    """

    def _run() -> None:
        if delay_seconds > 0:
            import time
            time.sleep(delay_seconds)
        info = check_for_update(api_url, current_version, timeout=timeout)
        if info:
            try:
                on_update_available(info)
            except Exception:
                _log.exception("Update callback hatası")

    t = threading.Thread(target=_run, name="UpdateChecker", daemon=True)
    t.start()
    return t


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    info = check_for_update(
        "https://autotax-public-production-3f2a.up.railway.app",
        "0.0.1",
    )
    print("Update info:", info)
