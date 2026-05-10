"""Build a clean multi-resolution .ico for AutoTaxWatcher.exe.

Pillow ile yazılmış üretim script'i — repo'da binary .ico tutmamak için
build sırasında üretilir (build.bat çağırır).

Üretilen ico içinde Windows'un ihtiyaç duyduğu tüm boyutlar (16-256) bulunur,
böylece tray, shortcut, taskbar ve installer'da net görünür.
"""

from __future__ import annotations

import sys
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("ERROR: Pillow is required. pip install Pillow", file=sys.stderr)
    sys.exit(1)


SIZES = [16, 24, 32, 48, 64, 128, 256]
BG = (10, 14, 23)         # var(--bg) — koyu lacivert
ACCENT = (16, 185, 129)   # tailwind emerald-500
WHITE = (255, 255, 255)


def _load_font(size: int) -> ImageFont.ImageFont:
    """Sistem fontunu yükle, yoksa default'a düş."""
    for name in ("arialbd.ttf", "arial.ttf", "DejaVuSans-Bold.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _draw(size: int) -> Image.Image:
    """Tek bir boyutta ikon üret. Köşeleri yuvarlak, ortada beyaz "AT"."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    pad = max(1, size // 16)
    radius = max(2, size // 6)
    # Yumuşak köşeli yeşil zemin
    d.rounded_rectangle(
        (pad, pad, size - pad - 1, size - pad - 1),
        radius=radius,
        fill=ACCENT,
    )
    # AT yazısı — boyuta göre ölçekli
    if size >= 24:
        font = _load_font(int(size * 0.55))
        text = "AT"
        bbox = d.textbbox((0, 0), text, font=font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        d.text(
            ((size - tw) / 2 - bbox[0], (size - th) / 2 - bbox[1] - 1),
            text,
            font=font,
            fill=WHITE,
        )
    else:
        # 16/24px'te yazı bulanık olur — küçük bir tik glyphu çiz
        d.line([(size * 0.30, size * 0.55), (size * 0.45, size * 0.70), (size * 0.72, size * 0.35)], fill=WHITE, width=max(1, size // 10))
    return img


def build(out_path: Path) -> None:
    base = _draw(max(SIZES))
    extra = [_draw(s) for s in SIZES if s != max(SIZES)]
    base.save(out_path, format="ICO", sizes=[(s, s) for s in SIZES], append_images=extra)
    print(f"OK -> {out_path} ({out_path.stat().st_size} bytes)")


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / "AutoTaxWatcher.ico"
    build(out)
