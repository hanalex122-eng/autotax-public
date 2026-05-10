"""AutoTax-Cloud Scanner Watcher.

Bir klasörü izler. Yeni PDF/JPG/PNG geldiginde otomatik olarak
AutoTax-Cloud'a upload eder.

Kullanim:
    python autotax_watcher.py --config config.json
veya
    python autotax_watcher.py --url https://api.autotax.cloud \
                              --token YOUR_TOKEN \
                              --folder "C:\\Scans"

Gereksinim: Python 3.8+, pip install requests
"""

import argparse
import json
import logging
import os
import shutil
import sys
import time
from pathlib import Path

try:
    import requests
except ImportError:
    print("HATA: 'requests' kutuphanesi eksik. Kurmak icin:")
    print("  pip install requests")
    sys.exit(1)


SUPPORTED_EXTS = {".pdf", ".jpg", ".jpeg", ".png", ".webp"}
POLL_INTERVAL = 5  # saniye
STABILITY_WAIT = 3  # dosya boyutu degismedikten sonra X saniye bekle (tarama bitsin)


def setup_logging(log_file: str | None = None) -> None:
    fmt = "%(asctime)s [%(levelname)s] %(message)s"
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    if log_file:
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))
    logging.basicConfig(level=logging.INFO, format=fmt, handlers=handlers)


def load_config(args: argparse.Namespace) -> dict:
    cfg: dict = {}
    if args.config and Path(args.config).exists():
        with open(args.config, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    if args.url:
        cfg["api_url"] = args.url
    if args.token:
        cfg["api_token"] = args.token
    if args.folder:
        cfg["watch_folder"] = args.folder
    if args.invoice_type:
        cfg["invoice_type"] = args.invoice_type

    if not cfg.get("api_url"):
        cfg["api_url"] = "https://api.autotax.cloud"
    if not cfg.get("invoice_type"):
        cfg["invoice_type"] = "expense"
    if not cfg.get("processed_folder"):
        cfg["processed_folder"] = str(Path(cfg.get("watch_folder", ".")) / "Uploaded")
    if not cfg.get("failed_folder"):
        cfg["failed_folder"] = str(Path(cfg.get("watch_folder", ".")) / "Failed")

    missing = [k for k in ("api_url", "api_token", "watch_folder") if not cfg.get(k)]
    if missing:
        raise SystemExit(f"Config eksik: {missing}. --config <file> veya --url/--token/--folder kullan.")
    return cfg


def is_file_stable(path: Path, wait_seconds: int = STABILITY_WAIT) -> bool:
    """Dosya yazimi tamamlandi mi kontrol et — boyut wait_seconds boyunca degismemeli."""
    try:
        size1 = path.stat().st_size
    except (FileNotFoundError, PermissionError):
        return False
    time.sleep(wait_seconds)
    try:
        size2 = path.stat().st_size
    except (FileNotFoundError, PermissionError):
        return False
    return size1 == size2 and size1 > 0


def upload_file(file_path: Path, cfg: dict) -> tuple[bool, str]:
    """Dosyayi AutoTax-Cloud'a upload et. (success, message) doner."""
    url = cfg["api_url"].rstrip("/") + "/invoices/upload"
    headers = {"Authorization": f"Bearer {cfg['api_token']}"}
    params = {"invoice_type": cfg.get("invoice_type", "expense")}
    try:
        with open(file_path, "rb") as f:
            mime = "application/pdf" if file_path.suffix.lower() == ".pdf" else f"image/{file_path.suffix.lower().lstrip('.')}"
            files = {"file": (file_path.name, f, mime)}
            resp = requests.post(url, headers=headers, params=params, files=files, timeout=120)
        if resp.status_code in (200, 201):
            try:
                data = resp.json()
                inv_id = data.get("id") or data.get("invoice_id") or "?"
                return True, f"OK (invoice #{inv_id})"
            except Exception:
                return True, "OK"
        return False, f"HTTP {resp.status_code}: {resp.text[:200]}"
    except Exception as e:
        return False, f"Exception: {e}"


def move_to(file_path: Path, dest_dir: Path) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / file_path.name
    # Cakisma varsa timestamp ekle
    if target.exists():
        stem, suffix = target.stem, target.suffix
        target = dest_dir / f"{stem}_{int(time.time())}{suffix}"
    shutil.move(str(file_path), str(target))
    return target


def watch_loop(cfg: dict) -> None:
    watch = Path(cfg["watch_folder"])
    processed = Path(cfg["processed_folder"])
    failed = Path(cfg["failed_folder"])
    if not watch.exists():
        raise SystemExit(f"Watch folder yok: {watch}")
    processed.mkdir(parents=True, exist_ok=True)
    failed.mkdir(parents=True, exist_ok=True)

    logging.info("AutoTax Watcher basladi")
    logging.info("  Izlenen klasor : %s", watch)
    logging.info("  Yuklenenler   -> %s", processed)
    logging.info("  Hatalilar     -> %s", failed)
    logging.info("  API URL       : %s", cfg["api_url"])
    logging.info("  Tip           : %s", cfg.get("invoice_type"))
    logging.info("Yeni faturalar bekleniyor... (Ctrl+C ile cik)")

    seen_unstable: set[str] = set()  # bir kez kararsiz gorulen dosyalar
    while True:
        try:
            for entry in sorted(watch.iterdir()):
                if not entry.is_file():
                    continue
                if entry.suffix.lower() not in SUPPORTED_EXTS:
                    continue
                # Subfolder olarak yaratilmis processed/failed'i atla
                if entry.parent != watch:
                    continue
                if not is_file_stable(entry):
                    if str(entry) not in seen_unstable:
                        logging.info("Bekleniyor (tarama bitsin): %s", entry.name)
                        seen_unstable.add(str(entry))
                    continue
                seen_unstable.discard(str(entry))

                logging.info("Upload basliyor: %s", entry.name)
                ok, msg = upload_file(entry, cfg)
                if ok:
                    target = move_to(entry, processed)
                    logging.info("  -> %s | %s", msg, target.name)
                else:
                    target = move_to(entry, failed)
                    logging.error("  HATA: %s | %s", msg, target.name)
        except Exception:
            logging.exception("watch_loop hatasi")
        time.sleep(POLL_INTERVAL)


def main() -> None:
    p = argparse.ArgumentParser(description="AutoTax-Cloud Scanner Watcher")
    p.add_argument("--config", help="config.json dosya yolu", default="config.json")
    p.add_argument("--url", help="API base URL (orn: https://api.autotax.cloud)")
    p.add_argument("--token", help="JWT token (atx_token)")
    p.add_argument("--folder", help="Izlenecek klasor")
    p.add_argument("--invoice-type", choices=["expense", "income"], help="Fatura tipi (default: expense)")
    p.add_argument("--log-file", help="Log dosyasi (opsiyonel)")
    args = p.parse_args()

    setup_logging(args.log_file)
    cfg = load_config(args)
    try:
        watch_loop(cfg)
    except KeyboardInterrupt:
        logging.info("Durduruldu (Ctrl+C)")


if __name__ == "__main__":
    main()
