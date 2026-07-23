"""Unicode font registration for PDFs that must render Turkish names correctly.

Sprint 9.0a. The existing PDFs use Helvetica (Latin-1) which cannot render Turkish
ş/ğ/İ/ı/ç — a tenant/landlord name in a Mietvertrag would print .notdef boxes.
This helper registers a Unicode TrueType family once (idempotent) under a stable name.

Source order (first that exists wins):
  1. a repo-bundled DejaVuSans in autotax/assets/fonts/   (if added later)
  2. reportlab's own bundled Vera (Bitstream Vera Sans)   (always ships with reportlab)
Both cover the German + Turkish glyph sets this project needs. Only PDFs that opt in
(by using FONT_NAME in their styles) are affected; every other PDF keeps Helvetica.
"""
from __future__ import annotations

import os

FONT_NAME = "AtxUnicode"
FONT_NAME_BOLD = "AtxUnicode-Bold"

_registered = False

_ASSET_DIR = os.path.join(os.path.dirname(__file__), "assets", "fonts")
# (regular, bold) candidate pairs, tried in order
_CANDIDATES = (
    (os.path.join(_ASSET_DIR, "DejaVuSans.ttf"), os.path.join(_ASSET_DIR, "DejaVuSans-Bold.ttf")),
)


def _reportlab_bundled():
    import reportlab
    d = os.path.join(os.path.dirname(reportlab.__file__), "fonts")
    reg, bold = os.path.join(d, "Vera.ttf"), os.path.join(d, "VeraBd.ttf")
    return (reg, bold) if os.path.exists(reg) and os.path.exists(bold) else None


def register_unicode_font():
    """Register the Unicode family once. Returns FONT_NAME. Safe to call repeatedly."""
    global _registered
    if _registered:
        return FONT_NAME
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    pair = None
    for reg, bold in _CANDIDATES:
        if os.path.exists(reg) and os.path.exists(bold):
            pair = (reg, bold)
            break
    if pair is None:
        pair = _reportlab_bundled()
    if pair is None:
        raise RuntimeError("No Unicode TTF available for PDF (neither bundled DejaVu nor reportlab Vera)")

    reg, bold = pair
    pdfmetrics.registerFont(TTFont(FONT_NAME, reg))
    pdfmetrics.registerFont(TTFont(FONT_NAME_BOLD, bold))
    pdfmetrics.registerFontFamily(FONT_NAME, normal=FONT_NAME, bold=FONT_NAME_BOLD,
                                  italic=FONT_NAME, boldItalic=FONT_NAME_BOLD)
    _registered = True
    return FONT_NAME
