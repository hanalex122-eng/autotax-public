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


# ----------------------------------------------------------------------
# Document upload hardening (Security Hotfix 2026-07-23)
# One rule set shared by /immo/documents AND vault upload, so both paths
# behave identically. Allowed types are decided by magic bytes (server-derived),
# never by the client-supplied Content-Type.
# ----------------------------------------------------------------------

# Product decision (2026-07-23): PDF + JPEG + PNG + WebP only. No XML.
ALLOWED_UPLOAD_MIME = ("application/pdf", "image/jpeg", "image/png", "image/webp")


def sniff_upload_mime(content: bytes):
    """Return the canonical MIME for `content` IFF it is one of the allowed types,
    based on magic bytes only. Returns None for anything else (reject at upload;
    serve as octet-stream at download). Never trusts a client Content-Type."""
    if not content or len(content) < 4:
        return None
    if content[:4] == b"%PDF":
        return "application/pdf"
    if content[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if content[:4] == b"\x89PNG":
        return "image/png"
    if len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "image/webp"
    return None


def sanitize_filename(name):
    """Strip path components and header-breaking chars from a user filename
    (prevents Content-Disposition header injection). Falls back to 'dokument'."""
    name = (name or "").replace("\\", "/").split("/")[-1]
    for ch in ('"', "\r", "\n", "\x00"):
        name = name.replace(ch, "")
    name = name.strip()[:120]
    return name or "dokument"


__all__ = [
    "_fuzzy_match",
    "_extract_first_iban", "_extract_first_phone", "_extract_first_address",
    "_safe_json_list",
    "_MAGIC_BYTES", "_validate_file_magic",
    "ALLOWED_UPLOAD_MIME", "sniff_upload_mime", "sanitize_filename",
]
