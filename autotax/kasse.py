"""Cash register import parser (DSFinV-K + Speedy Kasse + generic CSV).

MVP: parse uploaded CSV / ZIP from a customer's cash register export,
detect format, return rows ready to become CashEntry records.

See .claude/kasse_plan.md for full DSFinV-K context. We only parse the
"transactions" view in MVP — multi-file DSFinV-K (vat.csv, payment.csv,
etc.) is a future expansion.

Supported formats (auto-detected by column headers):
- **DSFinV-K** transactions.csv  — TYP/Z_NR/BON_NR/BON_GESAMT_BRUTTO/...
- **Speedy Kasse** export        — BUCHUNGSTAG/UMS_BRUTTO/UMS_NETTO/...
- **Generic CSV**                — date,amount,description (fallback)
"""
from __future__ import annotations

import csv
import hashlib
import io
import logging
import re
import zipfile
from datetime import date, datetime
from typing import Iterable, Optional

logger = logging.getLogger(__name__)


# ───────────────────────────────────────────────────────────────────
# Helpers
# ───────────────────────────────────────────────────────────────────

def file_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def parse_de_money(s: str | None) -> float:
    """Parse German number: '1.234,56' or '1234,56' or '1234.56' → float."""
    if s is None:
        return 0.0
    s = str(s).strip().replace("€", "").replace(" ", "")
    if not s:
        return 0.0
    # German: dot=thousands, comma=decimal
    if "," in s and "." in s:
        # Both present → assume German format
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


def parse_de_date(s: str | None) -> Optional[date]:
    """Parse common German/ISO date variants."""
    if not s:
        return None
    s = str(s).strip().split(" ")[0].split("T")[0]
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%Y/%m/%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


# ───────────────────────────────────────────────────────────────────
# Format detection
# ───────────────────────────────────────────────────────────────────

# Distinctive keys per format (more unique = stronger signal).
# DSFinV-K official transactions.csv has specific column names per BMF.
_DSFINVK_KEYS = {"Z_NR", "BON_GESAMT_BRUTTO", "Z_KASSE_ID", "TYP"}
_SPEEDY_KEYS = {"BUCHUNGSTAG", "UMS_BRUTTO", "UMS_NETTO", "BON_GESAMT_BRUTTO"}
_GENERIC_DATE_KEYS = ("date", "datum", "buchungsdatum", "tag")
_GENERIC_AMOUNT_KEYS = ("amount", "betrag", "brutto", "summe", "total")


def detect_format(headers: list[str]) -> str:
    """Pick format with strongest header match. Ties → DSFinV-K (more strict)."""
    upper = {h.upper().strip() for h in headers}
    dsfinvk_score = len(upper & _DSFINVK_KEYS)
    speedy_score = len(upper & _SPEEDY_KEYS)
    if max(dsfinvk_score, speedy_score) == 0:
        return "generic"
    if dsfinvk_score >= speedy_score and dsfinvk_score >= 2:
        return "dsfinvk"
    if speedy_score >= 2:
        return "speedy"
    return "generic"


# ───────────────────────────────────────────────────────────────────
# CSV reader (auto-detects delimiter)
# ───────────────────────────────────────────────────────────────────

def _detect_delimiter(sample: str) -> str:
    for delim in (";", ",", "\t", "|"):
        if sample.count(delim) >= 1:
            return delim
    return ","


def _read_csv(raw: bytes) -> tuple[list[dict], list[str]]:
    """Return (rows, headers). Handles BOM, encoding fallback,
    auto-delimiter."""
    # Encoding
    text: str
    for enc in ("utf-8-sig", "utf-8", "latin-1", "cp1252"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = raw.decode("utf-8", errors="replace")

    sample = text[:2000]
    delim = _detect_delimiter(sample)
    reader = csv.DictReader(io.StringIO(text), delimiter=delim)
    rows = []
    headers = list(reader.fieldnames or [])
    for row in reader:
        if not row:
            continue
        rows.append(row)
    return rows, headers


# ───────────────────────────────────────────────────────────────────
# Per-format extractors → unified row dict
# ───────────────────────────────────────────────────────────────────

def _row_dsfinvk(r: dict) -> Optional[dict]:
    """DSFinV-K transactions.csv row → unified."""
    # Skip non-transaction (Z_KASSENBERICHT, AVTransfer, etc.)
    typ = (r.get("TYP") or "").strip().upper()
    if typ and typ not in ("BELEG", "AVRECHNUNG", "SUMME"):
        return None
    brutto = parse_de_money(r.get("BON_GESAMT_BRUTTO") or r.get("Z_SE_ZAHLART"))
    if brutto <= 0:
        return None
    d = parse_de_date(r.get("BON_ABSCHLUSS") or r.get("Z_ERSTELLUNG"))
    payment = (r.get("ZAHLART_TYP") or r.get("BON_ZAHLART") or "").strip().lower()
    return {
        "date": d.isoformat() if d else "",
        "amount": brutto,
        "payment_method": payment or "unknown",
        "vendor": "Kassensystem",
        "ref": r.get("BON_NR") or r.get("Z_NR") or "",
        "category": "kasse_income",
        "note": f"DSFinV-K BON {r.get('BON_NR','')}",
    }


def _row_speedy(r: dict) -> Optional[dict]:
    """Speedy Kasse row → unified."""
    if (r.get("BON_STORNO") or "").strip().lower() in ("1", "true", "ja"):
        return None
    brutto = parse_de_money(r.get("UMS_BRUTTO") or r.get("BON_GESAMT_BRUTTO"))
    if brutto <= 0:
        return None
    d = parse_de_date(r.get("BUCHUNGSTAG") or r.get("BON_ENDE") or r.get("Z_BUCHUNGSTAG"))
    payment = (r.get("ZAHLUNGSART") or r.get("BEDIENER_ID") or "").strip().lower() or "bar"
    return {
        "date": d.isoformat() if d else "",
        "amount": brutto,
        "payment_method": payment,
        "vendor": "Speedy Kasse",
        "ref": r.get("BON_NR") or "",
        "category": "kasse_income",
        "note": f"Speedy BON {r.get('BON_NR','')} Terminal {r.get('TERMINAL_NR','')}",
    }


def _row_generic(r: dict) -> Optional[dict]:
    """Generic CSV → unified (best-effort by column names)."""
    keys_lower = {k.lower().strip(): k for k in r.keys()}
    # Find date col
    date_key = next((keys_lower[k] for k in _GENERIC_DATE_KEYS if k in keys_lower), None)
    amount_key = next((keys_lower[k] for k in _GENERIC_AMOUNT_KEYS if k in keys_lower), None)
    if not amount_key:
        return None
    amount = parse_de_money(r.get(amount_key))
    if amount <= 0:
        return None
    d = parse_de_date(r.get(date_key)) if date_key else None
    desc = ""
    for k in ("description", "beschreibung", "notiz", "note", "text", "verwendungszweck"):
        if k in keys_lower:
            desc = (r.get(keys_lower[k]) or "").strip()
            break
    return {
        "date": d.isoformat() if d else "",
        "amount": amount,
        "payment_method": "unknown",
        "vendor": "Kasse (generic)",
        "ref": "",
        "category": "kasse_income",
        "note": desc or "Generic CSV import",
    }


_EXTRACTORS = {
    "dsfinvk": _row_dsfinvk,
    "speedy": _row_speedy,
    "generic": _row_generic,
}


# ───────────────────────────────────────────────────────────────────
# Public parse entry-point
# ───────────────────────────────────────────────────────────────────

def parse_kasse_file(raw: bytes, filename: str = "") -> dict:
    """Parse uploaded file (CSV or ZIP). Returns:

    {
      "source": "dsfinvk|speedy|generic",
      "rows": [unified dict, ...],
      "total_rows": int,
      "total_amount": float,
      "period_start": ISO date or "",
      "period_end": ISO date or "",
      "skipped_rows": int,
      "errors": [str, ...],
      "raw_excerpt": str (first 500 chars CSV),
    }
    """
    result: dict = {
        "source": "generic",
        "rows": [],
        "total_rows": 0,
        "total_amount": 0.0,
        "period_start": "",
        "period_end": "",
        "skipped_rows": 0,
        "errors": [],
        "raw_excerpt": "",
    }

    csv_bytes: bytes
    inner_name = ""

    # ZIP support — look for transactions.csv or similar inside
    if raw[:2] == b"PK" or filename.lower().endswith(".zip"):
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as z:
                # Prefer DSFinV-K transactions.csv
                candidates = [
                    n for n in z.namelist()
                    if n.lower().endswith(".csv")
                ]
                if not candidates:
                    result["errors"].append("ZIP enthält keine CSV-Datei")
                    return result
                # Priority: transactions.csv > Z*.csv > first csv
                pref = [c for c in candidates if "transaction" in c.lower()]
                if not pref:
                    pref = [c for c in candidates if c.lower().startswith("z")]
                inner_name = (pref or candidates)[0]
                csv_bytes = z.read(inner_name)
        except Exception as e:
            result["errors"].append(f"ZIP-Lesefehler: {e}")
            return result
    else:
        csv_bytes = raw

    try:
        rows_raw, headers = _read_csv(csv_bytes)
    except Exception as e:
        result["errors"].append(f"CSV-Lesefehler: {e}")
        return result

    if not headers:
        result["errors"].append("Keine CSV-Header gefunden")
        return result

    source = detect_format(headers)
    result["source"] = source
    extractor = _EXTRACTORS[source]

    excerpt = csv_bytes[:500].decode("utf-8", errors="replace")
    result["raw_excerpt"] = excerpt

    unified_rows: list[dict] = []
    skipped = 0
    for r in rows_raw:
        try:
            ur = extractor(r)
            if ur:
                unified_rows.append(ur)
            else:
                skipped += 1
        except Exception:
            skipped += 1
            logger.debug("kasse row skip (parse error)")

    result["rows"] = unified_rows
    result["total_rows"] = len(unified_rows)
    result["skipped_rows"] = skipped
    result["total_amount"] = round(sum(r.get("amount", 0) for r in unified_rows), 2)

    dates = [r["date"] for r in unified_rows if r.get("date")]
    if dates:
        result["period_start"] = min(dates)
        result["period_end"] = max(dates)

    return result


__all__ = [
    "file_sha256",
    "parse_kasse_file",
    "detect_format",
    "parse_de_money",
    "parse_de_date",
]
