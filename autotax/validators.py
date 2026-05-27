"""Pure validators / extractors / matchers (Phase 2.3 modularization, 2026-05-27).

All functions are:
- Pure (no DB / HTTP / FastAPI deps)
- Side-effect free
- Safe to import from any module

Includes:
- _fuzzy_match: string similarity check
- _extract_first_iban / _phone / _address: regex extractors from OCR text
- _safe_json_list: defensive JSON list parse
- _MAGIC_BYTES + _validate_file_magic: file MIME validation via magic bytes

Extraction approach: file-by-file. See ROADMAP.md Phase 2.
"""
from __future__ import annotations

import json as _json
import re as _re


# ----------------------------------------------------------------------
# String similarity
# ----------------------------------------------------------------------

def _fuzzy_match(a: str, b: str, threshold: float = 0.75) -> bool:
    """Loose string match — exact, substring, or character-overlap >= threshold.
    Used for vendor / category deduplication where OCR may produce small variants."""
    if not a or not b:
        return False
    a, b = a.lower().replace(" ", ""), b.lower().replace(" ", "")
    if a == b or a in b or b in a:
        return True
    common = sum(1 for c in a if c in b)
    return common / max(len(a), len(b)) >= threshold


# ----------------------------------------------------------------------
# OCR text extractors (vendor contact info from invoice text)
# ----------------------------------------------------------------------

def _extract_first_iban(text: str) -> str:
    """First IBAN-like sequence in text, normalized (no spaces). '' if none."""
    if not text:
        return ""
    m = _re.search(r"\b([A-Z]{2}\s?\d{2}\s?(?:\d{4}\s?){2,7}\d{1,4})\b", text.upper())
    return m.group(1).replace(" ", "") if m else ""


def _extract_first_phone(text: str) -> str:
    """First 'Tel/Fon/Phone/Fax: <number>' pattern. '' if none."""
    if not text:
        return ""
    m = _re.search(
        r"(?:tel\.?|fon|phone|fax)\s*:?\s*([\d\s/\-+]{6,20})",
        text, _re.IGNORECASE,
    )
    return m.group(1).strip() if m else ""


def _extract_first_address(text: str) -> str:
    """First German-style postal-code + city pattern (e.g. '66115 Saarbrücken'). '' if none."""
    if not text:
        return ""
    m = _re.search(
        r"(\d{4,5}\s+[A-ZÄÖÜ][a-zäöüß]{2,}(?:\s+[A-ZÄÖÜ][a-zäöüß]{2,})?)",
        text,
    )
    return m.group(1).strip() if m else ""


# ----------------------------------------------------------------------
# JSON defensive parsers
# ----------------------------------------------------------------------

def _safe_json_list(raw):
    """Parse JSON to list. Returns [] on any error or wrong type.
    Accepts already-list input (passthrough)."""
    if not raw:
        return []
    if isinstance(raw, list):
        return raw
    try:
        v = _json.loads(raw)
        return v if isinstance(v, list) else []
    except Exception:
        return []


# ----------------------------------------------------------------------
# File MIME validation via magic bytes
# ----------------------------------------------------------------------

_MAGIC_BYTES = {
    b"\xff\xd8\xff": "image/jpeg",
    b"\x89PNG": "image/png",
    b"%PDF": "application/pdf",
    b"II\x2a\x00": "image/tiff",     # little-endian TIFF
    b"MM\x00\x2a": "image/tiff",     # big-endian TIFF
    b"RIFF": "image/webp",            # WebP starts with RIFF
    b"PK\x03\x04": "application/zip", # ZIP archive
}


def _validate_file_magic(content: bytes, claimed_type: str) -> bool:
    """True if file content begins with a known magic byte signature,
    OR if claimed_type is HEIC/HEIF (those have complex headers we trust).
    Returns False for empty / too-short / unknown content."""
    if not content or len(content) < 4:
        return False
    if "heic" in claimed_type or "heif" in claimed_type:
        return True
    for magic, mime in _MAGIC_BYTES.items():
        if content[: len(magic)] == magic:
            return True
    return False


__all__ = [
    "_fuzzy_match",
    "_extract_first_iban", "_extract_first_phone", "_extract_first_address",
    "_safe_json_list",
    "_MAGIC_BYTES", "_validate_file_magic",
]
