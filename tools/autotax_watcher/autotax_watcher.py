"""AutoTax Watcher v2 — Scanner-to-Cloud agent.

Tarayıcı çıktı klasörünü izler, yeni PDF/JPG/PNG belgelerini AutoTax-Cloud'a
otomatik yükler. v2'de eklenenler:

- Tkinter login GUI (email + şifre — token kopyalama yok)
- Refresh-token loop (401 alınca otomatik yenile)
- 429 Retry-After backoff (server'ın yeni eklediği header'ı dinler)
- Offline JSON queue (internet kesilirse dosya kaybolmaz)
- pystray system-tray ikonu (Pause / Resume / Open Folder / Quit)
- Multi-folder watch (config'de liste)
- Zero-disk modu (delete_after_upload) — başarılı upload sonrası dosya silinir
- Logging: konsol + dosya rotasyonu

Tek-dosya tasarımı PyInstaller ile single-EXE üretmek için.

Bağımlılıklar: requests, pystray, Pillow (Tkinter built-in)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import queue
import re
import shutil
import sys
import threading
import time
import traceback
from dataclasses import asdict, dataclass, field
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Callable

# ---------------------------------------------------------------------------
# Sabitler
# ---------------------------------------------------------------------------
APP_NAME = "AutoTaxWatcher"
APP_VERSION = "2.2.0"
DEFAULT_API = "https://autotax.cloud"

# Auto-update state — set by updater callback, read by tray menu
_tray_icon = None
_update_url: str | None = None
_last_notify_ts: float = 0.0  # toast throttling — batch scan'de spam olmasin
NOTIFY_MIN_INTERVAL = 4.0  # saniye — iki bildirim arasi minimum bosluk
SUPPORTED_EXTS = {".pdf", ".jpg", ".jpeg", ".png", ".webp"}
POLL_INTERVAL = 5  # saniye — klasör tarama
STABILITY_WAIT = 3  # saniye — dosya boyutu sabitleşene kadar bekle
RETRY_INTERVAL = 30  # saniye — offline queue retry
MAX_429_RETRIES = 3
DEFAULT_BACKOFF = [15, 30, 60]  # Retry-After yoksa kullanılacak süreler


_PAGE_PATTERNS = [
    re.compile(r"^(.+)_page_?(\d+)$", re.IGNORECASE),  # scan_page_1, doc_pageN
    re.compile(r"^(.+)_p(\d+)$", re.IGNORECASE),       # scan_p1, scan_p01
    re.compile(r"^(.+)_(\d{2,})$"),                    # scan_001, IMG_20260517_001
    re.compile(r"^(.+)\s\((\d+)\)$"),                  # Document (1), Document (2)
    re.compile(r"^(.+)-(\d{3,})$"),                    # scan-001 (3+ dijit, tarihlerle karismasin)
]


def _split_page_suffix(stem: str) -> tuple[str, int] | None:
    """Dosya adinin sayfa-suffix'i varsa (base, page_num) doner, yoksa None.

    Ornek: 'scan_001' -> ('scan', 1), 'Document (2)' -> ('Document', 2),
           '2026-05-17' -> None (tarih, sayfa degil).
    """
    for pat in _PAGE_PATTERNS:
        m = pat.match(stem)
        if m:
            base = m.group(1).rstrip(" _-.")
            if base:
                return base, int(m.group(2))
    return None


def _merge_pdfs(pages: list[Path], output: Path) -> Path | None:
    """pypdf ile PDF birlestir. Hata olursa None doner (caller fallback'e duser)."""
    try:
        from pypdf import PdfWriter
    except ImportError:
        logging.warning("pypdf eksik — PDF merge atlandi (pip install pypdf)")
        return None
    if output.exists():
        output = output.with_name(f"{output.stem}_merged{output.suffix}")
    try:
        writer = PdfWriter()
        for p in pages:
            writer.append(str(p))
        with output.open("wb") as fh:
            writer.write(fh)
        writer.close()
        return output
    except Exception:
        logging.exception("PDF merge basarisiz: %s", output.name)
        return None


def _tray_notify(title: str, message: str, force: bool = False) -> None:
    """Tray balon bildirimi (Windows toast). Tray yoksa veya hata olursa sessizce yutar.

    Throttle: ardisik bildirimleri NOTIFY_MIN_INTERVAL kadar bekletir; force=True
    bildirim kritik (hata) ise atlanir.
    """
    global _last_notify_ts
    if _tray_icon is None:
        return
    now = time.monotonic()
    if not force and (now - _last_notify_ts) < NOTIFY_MIN_INTERVAL:
        return
    try:
        _tray_icon.notify(message, title)
        _last_notify_ts = now
    except Exception:
        pass  # bildirim hatasi watcher'i durdurmamali

# ---------------------------------------------------------------------------
# Bağımlılık kontrolü (kullanıcı dostu hata mesajı)
# ---------------------------------------------------------------------------
try:
    import requests
except ImportError:
    print("HATA: 'requests' kutuphanesi eksik. Kurmak icin:\n  pip install requests")
    sys.exit(1)

try:
    import pystray
    from PIL import Image, ImageDraw
    HAS_TRAY = True
except ImportError:
    HAS_TRAY = False  # Tray olmadan da çalışır — sadece konsol modu


# ---------------------------------------------------------------------------
# Config — kullanıcının ayarlar dosyası
# ---------------------------------------------------------------------------
def _config_dir() -> Path:
    """Windows'ta %LOCALAPPDATA%\\AutoTax\\Watcher, diğerinde ~/.autotax."""
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "AutoTax" / "Watcher"
    return Path.home() / ".autotax" / "watcher"


@dataclass
class Config:
    api_url: str = DEFAULT_API
    api_token: str = ""
    refresh_token: str = ""
    email: str = ""  # otomatik tekrar-login için
    folders: list[str] = field(default_factory=list)
    invoice_type: str = "expense"
    delete_after_upload: bool = False
    processed_subfolder: str = "Uploaded"
    failed_subfolder: str = "Failed"
    retry_interval: int = RETRY_INTERVAL
    auto_start: bool = True  # Windows başlangıcında otomatik aç (default açık)
    merge_multi_page: bool = True  # scan_001/scan_002 → tek PDF merge
    merge_idle_seconds: int = 10  # son sayfa yazildiktan sonra bekleme suresi
    hot_folder_routing: bool = True  # watch/expense/, watch/income/ subfolder routing
    routing_map: dict[str, str] = field(default_factory=lambda: {
        "expense": "expense",
        "income": "income",
        "ausgabe": "expense",
        "einnahme": "income",
    })

    @classmethod
    def load(cls, path: Path) -> "Config":
        if not path.exists():
            return cls()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            logging.warning("Config okunamadı (%s) — varsayılan kullanılıyor", e)
            return cls()
        # Eski v1 config uyumluluğu — `watch_folder` (tek string) → `folders` (liste)
        if "watch_folder" in data and "folders" not in data:
            data["folders"] = [data.pop("watch_folder")]
        valid = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**valid)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False), encoding="utf-8")


# ---------------------------------------------------------------------------
# AuthClient — login + refresh token + auto-renew
# ---------------------------------------------------------------------------
class AuthClient:
    """JWT token yaşam döngüsünü yöneten basit istemci.

    - login(email, password) → token + refresh_token
    - refresh() → 401 alınca yeni access token üretir
    - on_token_changed callback → token değişince config'i kaydetmek için
    """

    def __init__(self, cfg: Config, on_token_changed: Callable[[Config], None] | None = None):
        self.cfg = cfg
        self.on_token_changed = on_token_changed

    def _save(self) -> None:
        if self.on_token_changed:
            try:
                self.on_token_changed(self.cfg)
            except Exception:
                logging.exception("Token kaydedilemedi")

    def login(self, email: str, password: str) -> tuple[bool, str]:
        url = self.cfg.api_url.rstrip("/") + "/auth/login"
        try:
            r = requests.post(url, json={"email": email, "password": password}, timeout=20)
        except requests.RequestException as e:
            return False, f"Bağlantı hatası: {e}"
        if r.status_code != 200:
            return False, f"Giriş başarısız (HTTP {r.status_code})"
        try:
            data = r.json()
        except ValueError:
            return False, "Geçersiz sunucu yanıtı"
        token = data.get("token") or data.get("access_token")
        if not token:
            return False, "Token alınamadı"
        self.cfg.email = email
        self.cfg.api_token = token
        self.cfg.refresh_token = data.get("refresh_token", "")
        self._save()
        return True, "OK"

    def refresh(self) -> bool:
        if not self.cfg.refresh_token:
            return False
        url = self.cfg.api_url.rstrip("/") + "/auth/refresh"
        try:
            r = requests.post(url, json={"refresh_token": self.cfg.refresh_token}, timeout=20)
        except requests.RequestException:
            return False
        if r.status_code != 200:
            return False
        try:
            data = r.json()
        except ValueError:
            return False
        token = data.get("token") or data.get("access_token")
        if not token:
            return False
        self.cfg.api_token = token
        if data.get("refresh_token"):
            self.cfg.refresh_token = data["refresh_token"]
        self._save()
        return True


# ---------------------------------------------------------------------------
# UploadQueue — JSON-disk persisted retry queue
# ---------------------------------------------------------------------------
class UploadQueue:
    """Yüklenmeyi bekleyen dosyaların kalıcı kuyruğu.

    Dosya yolu listesini bir JSON'a yazar. Internet kesintisi veya server
    hatası sonrasında yeniden başlatma sonrası bile dosyalar kaybolmaz.
    """

    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.Lock()
        self.items: list[str] = []
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    self.items = [str(x) for x in data if isinstance(x, str)]
            except (json.JSONDecodeError, OSError):
                self.items = []

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.items, indent=2), encoding="utf-8")
        except OSError:
            logging.exception("Queue kaydedilemedi")

    def add(self, file_path: str) -> None:
        with self.lock:
            if file_path not in self.items:
                self.items.append(file_path)
                self._save()

    def remove(self, file_path: str) -> None:
        with self.lock:
            if file_path in self.items:
                self.items.remove(file_path)
                self._save()

    def snapshot(self) -> list[str]:
        with self.lock:
            return list(self.items)

    def __len__(self) -> int:
        with self.lock:
            return len(self.items)


# ---------------------------------------------------------------------------
# Uploader — tek dosya yükleme + 429 backoff + 401 refresh
# ---------------------------------------------------------------------------
class Uploader:
    def __init__(self, cfg: Config, auth: AuthClient):
        self.cfg = cfg
        self.auth = auth

    def upload(self, file_path: Path, invoice_type: str | None = None) -> tuple[str, str]:
        """Dosyayı yükle. Dönüş: (status, message).

        invoice_type None ise config default kullanilir (hot-folder routing icin override).

        status değerleri:
          - "ok"        → başarılı
          - "duplicate" → backend duplicate döndü (silinebilir, AutoTax'te zaten var)
          - "retry"     → geçici hata (network / 429 / 5xx) — kuyrukta kalsın
          - "fail"      → kalıcı hata (400 / 415 / dosya bozuk) — Failed/'e taşı
        """
        url = self.cfg.api_url.rstrip("/") + "/invoices/upload"
        params = {"invoice_type": invoice_type or self.cfg.invoice_type or "expense"}

        for attempt in range(MAX_429_RETRIES + 1):
            headers = {"Authorization": f"Bearer {self.cfg.api_token}"}
            try:
                with open(file_path, "rb") as f:
                    mime = self._mime(file_path)
                    files = {"file": (file_path.name, f, mime)}
                    r = requests.post(url, headers=headers, params=params, files=files, timeout=180)
            except requests.RequestException as e:
                # Network kesik — kuyrukta kalsın, retry loop alır
                return "retry", f"Bağlantı hatası: {e}"

            # 401 → refresh dene, sonra tek sefer tekrar et
            if r.status_code == 401 and attempt == 0:
                if self.auth.refresh():
                    continue
                return "retry", "Token geçersiz — yeniden giriş gerekli"

            # 429 → Retry-After kadar bekle, tekrar dene
            if r.status_code == 429 and attempt < MAX_429_RETRIES:
                wait = self._retry_after_seconds(r, attempt)
                logging.info("429 — %ds bekliyor (deneme %d/%d): %s",
                             wait, attempt + 1, MAX_429_RETRIES, file_path.name)
                time.sleep(wait)
                continue

            # 5xx → retry queue'ya
            if 500 <= r.status_code < 600:
                return "retry", f"Sunucu hatası HTTP {r.status_code}"

            if r.status_code in (200, 201):
                try:
                    data = r.json()
                except ValueError:
                    return "ok", "OK"
                if data.get("duplicate"):
                    return "duplicate", "Bu dosya zaten yüklenmiş — atlanıyor"
                inv_id = data.get("id") or data.get("invoice_id") or "?"
                vendor = data.get("vendor") or ""
                amount = data.get("total_amount")
                tail = f" — {vendor}" if vendor else ""
                if amount is not None:
                    tail += f" — €{amount}"
                return "ok", f"Invoice #{inv_id}{tail}"

            # 4xx kalıcı hata
            return "fail", f"HTTP {r.status_code}: {r.text[:160]}"

        return "retry", "429 limit aşıldı — kuyrukta tutuluyor"

    @staticmethod
    def _mime(path: Path) -> str:
        ext = path.suffix.lower().lstrip(".")
        if ext == "pdf":
            return "application/pdf"
        if ext in {"jpg", "jpeg"}:
            return "image/jpeg"
        if ext == "png":
            return "image/png"
        if ext == "webp":
            return "image/webp"
        return "application/octet-stream"

    @staticmethod
    def _retry_after_seconds(r: requests.Response, attempt: int) -> int:
        ra = r.headers.get("Retry-After")
        if ra:
            try:
                return max(1, int(ra))
            except ValueError:
                pass
        return DEFAULT_BACKOFF[min(attempt, len(DEFAULT_BACKOFF) - 1)]


# ---------------------------------------------------------------------------
# Watcher — klasör polling + dosya işleme
# ---------------------------------------------------------------------------
class Watcher:
    def __init__(self, cfg: Config, uploader: Uploader, q: UploadQueue):
        self.cfg = cfg
        self.uploader = uploader
        self.queue = q
        self.paused = threading.Event()  # set olunca duraklar
        self.stop_event = threading.Event()
        self._seen_unstable: set[str] = set()

    def is_paused(self) -> bool:
        return self.paused.is_set()

    def pause(self) -> None:
        self.paused.set()
        logging.info("Watcher duraklatıldı")

    def resume(self) -> None:
        self.paused.clear()
        logging.info("Watcher devam ediyor")

    def stop(self) -> None:
        self.stop_event.set()

    def run(self) -> None:
        logging.info("%s v%s başladı", APP_NAME, APP_VERSION)
        for f in self.cfg.folders:
            logging.info("  İzleniyor: %s", f)
        logging.info("  API: %s", self.cfg.api_url)
        logging.info("  Sıfır-disk modu: %s", "AÇIK" if self.cfg.delete_after_upload else "kapalı")

        while not self.stop_event.is_set():
            try:
                if not self.paused.is_set():
                    self._scan_all()
                    self._drain_queue()
            except Exception:
                logging.exception("Watcher hata")
            self.stop_event.wait(POLL_INTERVAL)

    def _scan_all(self) -> None:
        for folder in self.cfg.folders:
            self._scan(Path(folder))

    def _scan(self, watch: Path) -> None:
        if not watch.exists() or not watch.is_dir():
            return
        # Root klasor: config default invoice_type
        self._scan_dir(watch, watch, self.cfg.invoice_type or "expense")
        # Hot-folder routing: alt klasor adina gore farkli type
        if self.cfg.hot_folder_routing:
            reserved = {self.cfg.processed_subfolder, self.cfg.failed_subfolder}
            for folder_name, inv_type in self.cfg.routing_map.items():
                if folder_name in reserved:
                    continue
                sub = watch / folder_name
                if sub.exists() and sub.is_dir():
                    self._scan_dir(sub, watch, inv_type)

    def _scan_dir(self, scan_dir: Path, watch_root: Path, invoice_type: str) -> None:
        """Tek klasoru tarayip dosyalari verilen invoice_type ile isle.

        Uploaded/Failed her zaman watch_root altina yazilir — hot-folder
        subfolder'larina degil — kullanici hepsini tek yerde gorur.
        """
        processed = watch_root / self.cfg.processed_subfolder
        failed = watch_root / self.cfg.failed_subfolder

        stable_files: list[Path] = []
        for entry in sorted(scan_dir.iterdir()):
            if not entry.is_file():
                continue
            if entry.suffix.lower() not in SUPPORTED_EXTS:
                continue
            if entry.parent != scan_dir:
                continue
            if not self._is_stable(entry):
                if str(entry) not in self._seen_unstable:
                    logging.info("Bekleniyor (tarama bitsin): %s", entry.name)
                    self._seen_unstable.add(str(entry))
                continue
            self._seen_unstable.discard(str(entry))
            stable_files.append(entry)

        groups, singles = self._partition_pdf_groups(stable_files)

        # Tamamlanan PDF gruplari -> tek PDF'e birlestir, normal upload akisina sok
        for base_name, pages in groups.items():
            try:
                newest = max(p.stat().st_mtime for p in pages)
            except OSError:
                continue
            if (time.time() - newest) < self.cfg.merge_idle_seconds:
                logging.info(
                    "Merge bekleniyor: %s (%d sayfa, %ds sonra tetiklenir)",
                    base_name, len(pages), self.cfg.merge_idle_seconds,
                )
                continue
            output = scan_dir / f"{base_name}.pdf"
            merged = _merge_pdfs(pages, output)
            if merged:
                logging.info("PDF Merge: %d sayfa -> %s", len(pages), merged.name)
                _tray_notify("PDF birleştirildi", f"{merged.name} ({len(pages)} sayfa)")
                for p in pages:
                    try:
                        p.unlink()
                    except OSError as e:
                        logging.warning("Sayfa silinemedi (%s): %s", e, p.name)
                self._process(merged, processed, failed, invoice_type)
            else:
                # Merge basarisiz -> sayfalari ayri ayri yukle (fallback)
                for p in pages:
                    self._process(p, processed, failed, invoice_type)

        for entry in singles:
            self._process(entry, processed, failed, invoice_type)

    def _partition_pdf_groups(
        self, files: list[Path]
    ) -> tuple[dict[str, list[Path]], list[Path]]:
        """PDF'leri sayfa-suffix pattern'ine gore grupla. (groups, singles) doner.

        - 2+ sayfa olan gruplar `groups` dict'inde, sayfa numarasina gore sirali
        - Tek dosya / non-PDF / pattern eslesmiyor -> `singles`
        - Config'de merge_multi_page=False ise hicbir sey gruplanmaz
        """
        if not self.cfg.merge_multi_page:
            return {}, list(files)
        pdf_groups: dict[str, list[tuple[int, Path]]] = {}
        singles: list[Path] = []
        for f in files:
            if f.suffix.lower() != ".pdf":
                singles.append(f)
                continue
            info = _split_page_suffix(f.stem)
            if info is None:
                singles.append(f)
                continue
            base, num = info
            pdf_groups.setdefault(base, []).append((num, f))
        result: dict[str, list[Path]] = {}
        for base, items in pdf_groups.items():
            if len(items) >= 2:
                items.sort(key=lambda x: x[0])
                result[base] = [p for _, p in items]
            else:
                singles.extend(p for _, p in items)
        return result, singles

    def _process(self, file_path: Path, processed: Path, failed: Path, invoice_type: str | None = None) -> None:
        eff_type = invoice_type or self.cfg.invoice_type or "expense"
        logging.info("Yükleniyor: %s (type=%s)", file_path.name, eff_type)
        status, msg = self.uploader.upload(file_path, invoice_type=eff_type)
        if status == "ok":
            logging.info("  ✓ %s", msg)
            _tray_notify("Fatura yüklendi", f"{file_path.name} ({eff_type})")
            self._dispose_success(file_path, processed)
        elif status == "duplicate":
            logging.info("  ↻ %s", msg)
            # Duplicate'i success gibi ele al — dosyayı kaldır, tekrar yüklenmesin
            self._dispose_success(file_path, processed)
        elif status == "retry":
            logging.warning("  ⏳ %s — kuyruğa eklendi", msg)
            self.queue.add(str(file_path))
        else:  # fail
            logging.error("  ✗ %s", msg)
            _tray_notify("Yükleme başarısız", f"{file_path.name}\n{msg}", force=True)
            self._move(file_path, failed)

    def _detect_invoice_type(self, file_path: Path) -> str:
        """Hot-folder routing: dosyanin parent klasor adina gore type sec."""
        if self.cfg.hot_folder_routing:
            parent_name = file_path.parent.name
            if parent_name in self.cfg.routing_map:
                return self.cfg.routing_map[parent_name]
        return self.cfg.invoice_type or "expense"

    def _dispose_success(self, file_path: Path, processed: Path) -> None:
        if self.cfg.delete_after_upload:
            try:
                file_path.unlink()
                logging.info("  • silindi (sıfır-disk)")
            except OSError as e:
                logging.warning("Silinemedi (%s) — Uploaded/'e taşınıyor", e)
                self._move(file_path, processed)
        else:
            self._move(file_path, processed)

    def _drain_queue(self) -> None:
        """Kuyruktaki dosyaları yeniden dene."""
        for path_str in self.queue.snapshot():
            file_path = Path(path_str)
            if not file_path.exists():
                self.queue.remove(path_str)
                continue
            watch_root = self._find_watch_root(file_path)
            if not watch_root:
                self.queue.remove(path_str)
                continue
            processed = watch_root / self.cfg.processed_subfolder
            failed = watch_root / self.cfg.failed_subfolder
            inv_type = self._detect_invoice_type(file_path)
            status, msg = self.uploader.upload(file_path, invoice_type=inv_type)
            if status in ("ok", "duplicate"):
                logging.info("Kuyruktan başarılı: %s — %s (type=%s)", file_path.name, msg, inv_type)
                if status == "ok":
                    _tray_notify("Fatura yüklendi", f"{file_path.name} ({inv_type}, kuyruktan)")
                self.queue.remove(path_str)
                self._dispose_success(file_path, processed)
            elif status == "fail":
                logging.error("Kuyruktan kalıcı hata: %s — %s", file_path.name, msg)
                _tray_notify("Yükleme başarısız", f"{file_path.name}\n{msg}", force=True)
                self.queue.remove(path_str)
                self._move(file_path, failed)
            # retry → kuyruğda kalsın

    def _find_watch_root(self, file_path: Path) -> Path | None:
        for folder in self.cfg.folders:
            try:
                file_path.resolve().relative_to(Path(folder).resolve())
                return Path(folder)
            except ValueError:
                continue
        return None

    @staticmethod
    def _is_stable(path: Path, wait_seconds: int = STABILITY_WAIT) -> bool:
        try:
            size1 = path.stat().st_size
        except OSError:
            return False
        time.sleep(wait_seconds)
        try:
            size2 = path.stat().st_size
        except OSError:
            return False
        return size1 == size2 and size1 > 0

    @staticmethod
    def _move(file_path: Path, dest: Path) -> Path | None:
        try:
            dest.mkdir(parents=True, exist_ok=True)
            target = dest / file_path.name
            if target.exists():
                stem, suffix = target.stem, target.suffix
                target = dest / f"{stem}_{int(time.time())}{suffix}"
            shutil.move(str(file_path), str(target))
            return target
        except OSError:
            logging.exception("Taşıma başarısız: %s", file_path)
            return None


# ---------------------------------------------------------------------------
# Login GUI — Tkinter (built-in)
# ---------------------------------------------------------------------------
def show_login_dialog(cfg: Config, auth: AuthClient) -> bool:
    """Login penceresi göster. Başarılıysa True döner."""
    import tkinter as tk
    from tkinter import messagebox, ttk

    result = {"ok": False}

    root = tk.Tk()
    root.title(f"{APP_NAME} — Anmelden")
    root.geometry("420x280")
    root.resizable(False, False)
    try:
        root.iconbitmap(default="")
    except Exception:
        pass

    frame = ttk.Frame(root, padding=24)
    frame.pack(fill="both", expand=True)

    ttk.Label(frame, text="AutoTax-Cloud Anmeldung", font=("Segoe UI", 14, "bold")).pack(pady=(0, 12))
    ttk.Label(frame, text="E-Mail:").pack(anchor="w")
    email_var = tk.StringVar(value=cfg.email)
    email_entry = ttk.Entry(frame, textvariable=email_var, width=42)
    email_entry.pack(fill="x", pady=(2, 10))

    ttk.Label(frame, text="Passwort:").pack(anchor="w")
    pw_var = tk.StringVar()
    pw_entry = ttk.Entry(frame, textvariable=pw_var, show="•", width=42)
    pw_entry.pack(fill="x", pady=(2, 10))

    ttk.Label(frame, text="API URL:").pack(anchor="w")
    url_var = tk.StringVar(value=cfg.api_url)
    ttk.Entry(frame, textvariable=url_var, width=42).pack(fill="x", pady=(2, 14))

    status = ttk.Label(frame, text="", foreground="gray")
    status.pack(pady=(0, 6))

    def do_login() -> None:
        cfg.api_url = url_var.get().strip() or DEFAULT_API
        email = email_var.get().strip()
        password = pw_var.get()
        if not email or not password:
            status.config(text="E-Mail und Passwort erforderlich", foreground="red")
            return
        status.config(text="Anmeldung läuft…", foreground="gray")
        root.update_idletasks()
        ok, msg = auth.login(email, password)
        if ok:
            result["ok"] = True
            root.destroy()
        else:
            status.config(text=msg, foreground="red")

    btn_row = ttk.Frame(frame)
    btn_row.pack(fill="x")
    ttk.Button(btn_row, text="Abbrechen", command=root.destroy).pack(side="right", padx=(8, 0))
    login_btn = ttk.Button(btn_row, text="Anmelden", command=do_login)
    login_btn.pack(side="right")
    root.bind("<Return>", lambda e: do_login())

    if cfg.email:
        pw_entry.focus_set()
    else:
        email_entry.focus_set()

    root.mainloop()
    return result["ok"]


def show_folder_picker(cfg: Config) -> bool:
    """İlk kurulumda izlenecek klasörü seç."""
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    if cfg.folders:
        return True

    root = tk.Tk()
    root.withdraw()
    messagebox.showinfo(
        APP_NAME,
        "Wählen Sie den Ordner, in den Ihr Scanner gescannt — z. B. C:\\Scans",
    )
    folder = filedialog.askdirectory(title="Scanner-Ordner auswählen")
    root.destroy()
    if not folder:
        return False
    cfg.folders = [folder]
    return True


# ---------------------------------------------------------------------------
# Tray icon — pystray
# ---------------------------------------------------------------------------
def _make_icon_image() -> "Image.Image":
    """Basit yeşil dolar ikonu — bayt-bayt çizilmiş, eksik dosya derdi yok."""
    img = Image.new("RGB", (64, 64), color=(10, 14, 23))
    d = ImageDraw.Draw(img)
    d.rectangle([8, 8, 56, 56], fill=(16, 185, 129))
    d.text((22, 18), "AT", fill=(255, 255, 255))
    return img


def run_tray(cfg_path: Path, cfg: Config, watcher: Watcher) -> None:
    """Tray ikonu + menü. Ana thread'i bloklar."""
    if not HAS_TRAY:
        # Tray paketi yoksa terminalde devam et
        watcher.run()
        return

    def _open_folder(_icon: "pystray.Icon", _item: "pystray.MenuItem") -> None:
        if cfg.folders:
            try:
                os.startfile(cfg.folders[0])  # type: ignore[attr-defined]
            except Exception:
                pass

    def _toggle_pause(icon: "pystray.Icon", _item: "pystray.MenuItem") -> None:
        if watcher.is_paused():
            watcher.resume()
        else:
            watcher.pause()
        icon.update_menu()

    def _retry_now(_icon: "pystray.Icon", _item: "pystray.MenuItem") -> None:
        threading.Thread(target=watcher._drain_queue, daemon=True).start()

    def _quit(icon: "pystray.Icon", _item: "pystray.MenuItem") -> None:
        watcher.stop()
        icon.stop()

    def _open_update(_icon, _item):
        """Yeni surum yayinlandiysa indirme sayfasini aç."""
        import webbrowser
        global _update_url
        url = _update_url or "https://autotax.cloud/app"
        try:
            webbrowser.open(url)
        except Exception:
            logging.exception("Update URL acilamadi")

    def _status_text(_item: "pystray.MenuItem") -> str:
        n = len(watcher.queue)
        state = "DURDU" if watcher.is_paused() else "ÇALIŞIYOR"
        return f"Durum: {state} — Kuyruk: {n}"

    def _update_label(_item):
        global _update_url
        return "🆕 Update verfügbar — Herunterladen" if _update_url else "✓ Aktuelle Version"

    def _update_enabled(_item):
        global _update_url
        return bool(_update_url)

    menu = pystray.Menu(
        pystray.MenuItem(_status_text, lambda *_: None, enabled=False),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Ordner öffnen", _open_folder),
        pystray.MenuItem(
            lambda item: "Fortsetzen" if watcher.is_paused() else "Pausieren",
            _toggle_pause,
        ),
        pystray.MenuItem("Failed-Uploads erneut versuchen", _retry_now),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(_update_label, _open_update, enabled=_update_enabled),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Beenden", _quit),
    )

    icon = pystray.Icon(APP_NAME, _make_icon_image(), f"{APP_NAME} v{APP_VERSION}", menu)
    global _tray_icon
    _tray_icon = icon

    # Watcher'ı arka thread'de çalıştır, tray ana thread'de
    t = threading.Thread(target=watcher.run, daemon=True)
    t.start()
    icon.run()


# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------
def setup_logging(log_dir: Path) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    # Konsol
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    root.addHandler(sh)
    # Rotating file (5MB × 3)
    fh = RotatingFileHandler(log_dir / "watcher.log", maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
    fh.setFormatter(fmt)
    root.addHandler(fh)


# ---------------------------------------------------------------------------
# Auto-start (Windows startup folder shortcut) — opsiyonel
# ---------------------------------------------------------------------------
def ensure_autostart(enabled: bool) -> None:
    """Windows başlangıç klasörüne kısa yol koy/kaldır."""
    if os.name != "nt":
        return
    try:
        startup = Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
        link = startup / f"{APP_NAME}.lnk"
        if not enabled:
            if link.exists():
                link.unlink()
            return
        if link.exists():
            return
        # Kısa yol oluşturmak için PowerShell — ek dependency yok
        target = sys.executable if getattr(sys, "frozen", False) else f'"{sys.executable}" "{Path(__file__).resolve()}"'
        ps = (
            f'$s=(New-Object -ComObject WScript.Shell).CreateShortcut("{link}");'
            f'$s.TargetPath="{sys.executable}";'
            f'$s.Arguments="";'
            f'$s.WorkingDirectory="{Path(sys.executable).parent}";'
            f'$s.Save()'
        )
        os.system(f'powershell -NoProfile -Command "{ps}"')
    except Exception:
        logging.exception("Autostart ayarlanamadı")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser(description=f"{APP_NAME} v{APP_VERSION}")
    ap.add_argument("--config", help="config.json yolu (varsayılan: %LOCALAPPDATA%\\AutoTax\\Watcher\\config.json)")
    ap.add_argument("--no-tray", action="store_true", help="Tray ikonu olmadan, konsolda çalış")
    ap.add_argument("--reset", action="store_true", help="Mevcut girişi sıfırla, tekrar login iste")
    args = ap.parse_args()

    base_dir = _config_dir()
    cfg_path = Path(args.config) if args.config else base_dir / "config.json"
    queue_path = base_dir / "queue.json"
    log_dir = base_dir / "logs"

    setup_logging(log_dir)

    cfg = Config.load(cfg_path)

    if args.reset:
        cfg.api_token = ""
        cfg.refresh_token = ""

    auth = AuthClient(cfg, on_token_changed=lambda c: c.save(cfg_path))

    # Token yoksa veya refresh başarısızsa login penceresi göster
    need_login = not cfg.api_token
    if cfg.api_token and not _quick_token_check(cfg):
        if not auth.refresh():
            need_login = True

    if need_login:
        ok = show_login_dialog(cfg, auth)
        if not ok:
            logging.info("Giriş iptal edildi — kapatılıyor")
            return
        cfg.save(cfg_path)

    # İlk kurulumda klasör seç
    if not cfg.folders:
        if not show_folder_picker(cfg):
            logging.info("Klasör seçilmedi — kapatılıyor")
            return
        cfg.save(cfg_path)

    ensure_autostart(cfg.auto_start)

    # Auto-Update check — backend'in /watcher/version.json'ina bakar,
    # yeni sürüm varsa tray balon ile haber verir. Engellemez/blok yok.
    try:
        from updater import check_for_update_async
        def _on_update(info):
            try:
                logging.info("Update available: v%s — %s", info.version, info.download_url)
                # Tray icon varsa balon mesaj
                global _tray_icon
                if _tray_icon is not None:
                    _tray_icon.notify(
                        f"Neue Version verfügbar: v{info.version}\nKlicke 'Update herunterladen' im Menü.",
                        "AutoTax Watcher Update"
                    )
                # Update URL'ini global'e koy ki tray menü açsın
                global _update_url
                _update_url = info.download_url
            except Exception:
                logging.exception("update notify failed")
        api_base = cfg.api_url.rstrip("/")
        check_for_update_async(
            api_url=f"{api_base}/watcher/version.json",
            current_version=APP_VERSION,
            on_update_available=_on_update,
        )
    except ImportError:
        pass
    except Exception:
        logging.exception("Update check failed (continuing)")

    upload_queue = UploadQueue(queue_path)
    uploader = Uploader(cfg, auth)
    watcher = Watcher(cfg, uploader, upload_queue)

    if args.no_tray or not HAS_TRAY:
        try:
            watcher.run()
        except KeyboardInterrupt:
            logging.info("Durduruldu (Ctrl+C)")
    else:
        run_tray(cfg_path, cfg, watcher)


def _quick_token_check(cfg: Config) -> bool:
    """Mevcut token hala geçerli mi? /account/me ile hızlı sınama."""
    try:
        r = requests.get(
            cfg.api_url.rstrip("/") + "/account/me",
            headers={"Authorization": f"Bearer {cfg.api_token}"},
            timeout=10,
        )
        return r.status_code == 200
    except requests.RequestException:
        # Bağlantı yok → token'ı geçerli kabul et, retry kuyruk hallediyor
        return True


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        # PyInstaller --windowed modunda konsol yok, tray hatasını kullanıcı görsün
        try:
            import tkinter as _tk
            from tkinter import messagebox as _mb
            _r = _tk.Tk()
            _r.withdraw()
            _mb.showerror(APP_NAME, traceback.format_exc())
            _r.destroy()
        except Exception:
            pass
