"""Speedy Kasse Z-/Sammel-Endabrechnung parser (Vorbuchhaltung-Import).

Speedy (POS mit TSE) liefert PDF-Berichte. Wir übernehmen NUR den Umsatz
ins Kassenbuch — die TSE/Einzelbelege bleiben in Speedy. Aus dem OCR-Text
lesen wir den Block "Gesamtumsatz nach Steuersätzen" (je Satz: Steuer/Netto/
Brutto) plus Zeitraum + Zahlungsart. Kein Auto-Commit: das Ergebnis geht in
eine Vorschau, der Nutzer bestätigt.

Beispiel-Block (Sammel-Endabrechnung):
    Gesamtumsatz nach Steuersätzen
            Steuern   Netto    Brutto
    0%       0,00     20,00     20,00
    19%   1010,51   5318,49   6329,00
"""
from __future__ import annotations

import re


def _num(s: str) -> float:
    """Deutsche Zahl '5.318,49' / '5318,49' / '-15,00' -> float."""
    s = (s or "").strip().replace(".", "").replace(",", ".")
    try:
        return round(float(s), 2)
    except ValueError:
        return 0.0


# Zeile: "19%  1010,51  5318,49  6329,00"  (Satz, Steuer, Netto, Brutto)
_RATE_RE = re.compile(
    r"(?<!\d)(\d{1,2})\s*%\s+(-?\d[\d.]*,\d{2})\s+(-?\d[\d.]*,\d{2})\s+(-?\d[\d.]*,\d{2})"
)
# Datum DD.MM.YYYY
_DATE_RE = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})")
# Zeitraum "01. - 30.04.2026"  -> bis = 30.04.2026
_RANGE_RE = re.compile(r"(\d{2})\.\s*[-–]\s*(\d{2})\.(\d{2})\.(\d{4})")


def parse_speedy_report(text: str) -> dict:
    """OCR-Text einer Speedy Z-/Sammel-Endabrechnung -> strukturierte Summen.

    Rückgabe:
        {
          "ok": bool,
          "datum": "YYYY-MM-DD" | "",
          "zeitraum": "01.-30.04.2026" | "",
          "zahlungsart": "BAR" | "",
          "positions": [{"rate": "19%", "steuer": .., "netto": .., "brutto": ..}, ...],
          "brutto_total": float, "netto_total": float, "steuer_total": float,
        }
    Nur Zeilen mit Satz%+3 Beträgen werden übernommen (der Steuersatz-Block);
    Summenzeilen ohne % werden ignoriert -> keine Doppelzählung.
    """
    text = text or ""
    positions = []
    seen = set()
    for m in _RATE_RE.finditer(text):
        rate, steuer, netto, brutto = m.group(1), _num(m.group(2)), _num(m.group(3)), _num(m.group(4))
        key = (rate, steuer, netto, brutto)
        if key in seen:
            continue
        # Plausibilität: Netto+Steuer ~ Brutto (Toleranz 2 ct), Brutto != 0
        if brutto == 0 and netto == 0:
            continue
        if abs((netto + steuer) - brutto) > 0.02:
            continue
        seen.add(key)
        positions.append({"rate": f"{rate}%", "steuer": steuer, "netto": netto, "brutto": brutto})

    # Datum: bevorzugt Selektionszeitraum-Ende, sonst spätestes Datum im Text
    datum, zeitraum = "", ""
    rng = _RANGE_RE.search(text)
    if rng:
        d1, d2, mo, yr = rng.groups()
        zeitraum = f"{d1}.-{d2}.{mo}.{yr}"
        datum = f"{yr}-{mo}-{d2}"
    else:
        dates = _DATE_RE.findall(text)
        if dates:
            d, mo, yr = max(dates, key=lambda t: (t[2], t[1], t[0]))
            datum = f"{yr}-{mo}-{d}"

    zahlungsart = ""
    if re.search(r"\bBAR\b", text):
        zahlungsart = "BAR"
    elif re.search(r"\b(EC|Karte|Kartenzahlung)\b", text, re.I):
        zahlungsart = "Karte"

    return {
        "ok": bool(positions),
        "datum": datum,
        "zeitraum": zeitraum,
        "zahlungsart": zahlungsart,
        "positions": positions,
        "brutto_total": round(sum(p["brutto"] for p in positions), 2),
        "netto_total": round(sum(p["netto"] for p in positions), 2),
        "steuer_total": round(sum(p["steuer"] for p in positions), 2),
    }
