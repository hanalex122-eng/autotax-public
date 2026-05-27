"""DATEV Konto (account) mapping for German bookkeeping exports.

Phase 2.4 modularization (2026-05-27).

DATEV (Datenverarbeitungs-Organisation der Steuerberater) is the standard
chart-of-accounts used by German tax advisors. Each receipt is mapped to
a numeric Konto (account) based on its category, then exported in DATEV
CSV format that any Steuerberater can import into their tooling.

Defaults follow SKR 03 (Standard-Kontenrahmen 03) — the most common
small-business chart of accounts in Germany.

This module is pure (no DB / HTTP / FastAPI deps).
"""
from __future__ import annotations


# DATEV expense accounts (Aufwand). SKR 03 codes.
# Most "general purchase" categories map to 6800 (Sonstiger Aufwand)
# unless we have a more specific account.
DATEV_KONTO_MAP = {
    "food":         "6800",
    "groceries":    "6800",
    "restaurant":   "6640",  # Bewirtungskosten
    "fuel":         "6670",  # Reisekosten Kfz / Fahrzeugkosten
    "transport":    "6673",  # Sonstige Reisekosten
    "office":       "6815",  # Bürobedarf
    "software":     "6815",  # Bürobedarf / IT
    "subscription": "6815",
    "telecom":      "6805",  # Telefon / Internet
    "shipping":     "6810",  # Porto
    "electronics":  "6800",
    "shopping":     "6800",
    "insurance":    "6400",  # Versicherungsbeiträge
    "health":       "6800",
    "medical":      "6800",
    "home":         "6800",
    "clothing":     "6800",
    "other":        "6800",
}


# DATEV income accounts (Erlös). SKR 03 codes.
# Most income flows through 8400 (Erlöse 19% USt) by default.
DATEV_KONTO_MAP_INCOME = {
    "other":       "8400",
    "food":        "8400",
    "electronics": "8400",
    "software":    "8400",
    "shopping":    "8400",
}


def konto_for_category(category: str, invoice_type: str = "expense") -> str:
    """Lookup DATEV Konto for (category, invoice_type).
    Falls back to 6800 (expense) or 8400 (income) for unknown categories."""
    if invoice_type == "income":
        return DATEV_KONTO_MAP_INCOME.get(category or "other", "8400")
    return DATEV_KONTO_MAP.get(category or "other", "6800")


# Backward-compat aliases (main.py uses underscore-prefixed names)
_DATEV_KONTO_MAP = DATEV_KONTO_MAP
_DATEV_KONTO_MAP_INCOME = DATEV_KONTO_MAP_INCOME


__all__ = [
    "DATEV_KONTO_MAP", "DATEV_KONTO_MAP_INCOME",
    "_DATEV_KONTO_MAP", "_DATEV_KONTO_MAP_INCOME",
    "konto_for_category",
]
