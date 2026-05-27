"""Pure helper functions extracted from main.py (Phase 2 modularization, 2026-05-27).

All functions in this module are:
- Pure (no DB/HTTP/FastAPI dependencies)
- Side-effect free
- Safe to import anywhere in the codebase

Extraction approach: file-by-file, smallest-risk first. See ROADMAP.md
Phase 2 (Low-risk modularization).

Functions exported here are also re-exported from main.py for backward
compatibility (`from autotax.helpers import *` at top of main.py), so no
caller change is required.
"""
from __future__ import annotations

import re as _re


# ----------------------------------------------------------------------
# DSGVO Art. 25 — masking helpers for logging
# ----------------------------------------------------------------------

def _mask_email(email: str) -> str:
    """Mask an email for log output. 'huseyin@example.com' -> 'hu***@example.com'."""
    if not email or "@" not in email:
        return "***"
    local, domain = email.split("@", 1)
    return f"{local[:2]}***@{domain}" if len(local) > 2 else f"***@{domain}"


def _mask_ip(ip: str) -> str:
    """Anonymize last IPv4 octet (or partial IPv6) for log output."""
    if not ip:
        return "***"
    parts = ip.split(".")
    if len(parts) == 4:
        return f"{parts[0]}.{parts[1]}.{parts[2]}.xxx"
    return ip[:10] + "***"  # IPv6 fallback


# ----------------------------------------------------------------------
# Null-coalescing wrappers (avoid `or` pitfalls with falsy values like 0 / "")
# ----------------------------------------------------------------------

def safe_str(val, default=""):
    return val if val is not None else default


def safe_float(val, default=0.0):
    return val if val is not None else default


def safe_vat_rate(val):
    return val if val else "0%"


def safe_category(val):
    return val if val else "other"


def safe_invoice_type(val):
    return val if val in ("income", "expense") else "expense"


def safe_date_str(val):
    if not val:
        return ""
    return val


def safe_vendor(val):
    """Strip non-printable chars and collapse whitespace. Returns 'Unbekannt' on empty."""
    if not val:
        return "Unbekannt"
    # ASCII printable + German/European letters only
    cleaned = _re.sub(
        r'[^\x20-\x7EäöüÄÖÜßàáâãèéêëìíîïòóôùúûçñÀÁÂÃÈÉÊËÌÍÎÏÒÓÔÙÚÛÇÑ]',
        '', str(val)
    )
    cleaned = _re.sub(r'\s{2,}', ' ', cleaned).strip()
    return cleaned or "Unbekannt"


# ----------------------------------------------------------------------
# OWASP CSV / Formula Injection prevention
# ----------------------------------------------------------------------

# Excel & LibreOffice treat cells starting with these as formulas and may
# execute code on the victim's machine when the file is opened. Prefix
# with a single quote (Excel literal marker) to neutralize.
_CSV_FORMULA_CHARS = ("=", "+", "-", "@", "\t", "\r")


def csv_safe(val):
    """Sanitize a value before writing into CSV / XLSX cells. Returns str."""
    s = "" if val is None else str(val)
    if s and s[0] in _CSV_FORMULA_CHARS:
        return "'" + s
    return s


# ----------------------------------------------------------------------
# VAT calculation helpers
# ----------------------------------------------------------------------

def parse_vat_rate_float(vat_rate_str):
    """Parse '19%' / '7%' / '0' / None into float. Returns 0.0 on failure."""
    try:
        return float((vat_rate_str or "0").replace("%", ""))
    except (ValueError, TypeError):
        return 0.0


def calc_vat(gross, vat_rate_str):
    """Calculate VAT amount from gross + rate string. Returns 0.0 if missing."""
    if not gross:
        return 0.0
    rate = parse_vat_rate_float(vat_rate_str)
    if rate <= 0:
        return 0.0
    return round(gross * rate / (100 + rate), 2)


# ----------------------------------------------------------------------
# Response helpers (no FastAPI dependency)
# ----------------------------------------------------------------------

def ok_list(items, total):
    """Standard list response envelope."""
    return {"success": True, "items": items, "total": total}


__all__ = [
    "_mask_email", "_mask_ip",
    "safe_str", "safe_float", "safe_vat_rate", "safe_category",
    "safe_invoice_type", "safe_date_str", "safe_vendor",
    "csv_safe", "_CSV_FORMULA_CHARS",
    "parse_vat_rate_float", "calc_vat",
    "ok_list",
]
