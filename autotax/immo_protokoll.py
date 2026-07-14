"""Übergabeprotokoll + Zählerstände — PURE domain rules (no DB, no HTTP, no ORM).

Sprint 1: "a landlord must complete an entire tenant handover inside AutoTax."
This module is the part that can be reasoned about and tested without a database:
the default room list, the condition scale, what a valid protocol looks like, when it may
still be edited, and how meter consumption is derived.

Layering (same discipline as the Payment Service):
    immo_protokoll.py   ← rules (this file)
    immo_api.py         ← thin endpoints (commit 2)
    index.html          ← wizard (commit 3), displays only

The hard rule of this domain:
    **A completed protocol is immutable.** Once both parties have signed, the document must
    not change — that is what makes it worth anything in a dispute. A correction is a NEW
    protocol (Nachtrag), never an edit.
"""
from __future__ import annotations

import json
from datetime import date
from typing import Optional

# ── vocabulary ────────────────────────────────────────────────────────

ARTEN = ("einzug", "auszug")
STATUS_ENTWURF = "entwurf"
STATUS_ABGESCHLOSSEN = "abgeschlossen"

#: condition of one element — 4 steps, big enough to tap on a phone
ZUSTAENDE = ("neu", "gut", "gebraucht", "beschaedigt")
ZUSTAND_LABEL = {"neu": "neu", "gut": "gut", "gebraucht": "gebraucht", "beschaedigt": "beschädigt"}

#: meter types and their units (Masterplan #7)
ZAEHLER_ARTEN = {
    "strom": "kWh",
    "wasser": "m³",
    "warmwasser": "m³",
    "gas": "m³",
    "heizung": "Einheiten",
}
ZAEHLER_LABEL = {
    "strom": "Strom", "wasser": "Wasser (kalt)", "warmwasser": "Warmwasser",
    "gas": "Gas", "heizung": "Heizung",
}

#: every room is checked for these
STANDARD_ELEMENTE = ["Wände", "Boden", "Decke", "Türen", "Fenster", "Heizkörper"]

#: …plus what is specific to the room
ZUSATZ_ELEMENTE = {
    "Küche": ["Herd", "Spüle", "Küchenschränke", "Dunstabzug"],
    "Bad": ["WC", "Dusche", "Badewanne", "Waschbecken"],
    "Gäste-WC": ["WC", "Waschbecken"],
}

DEFAULT_RAEUME = ["Flur", "Wohnzimmer", "Schlafzimmer", "Küche", "Bad"]

DEFAULT_SCHLUESSEL = [
    {"typ": "Haustür", "anzahl": 1},
    {"typ": "Wohnungstür", "anzahl": 2},
    {"typ": "Briefkasten", "anzahl": 1},
    {"typ": "Keller", "anzahl": 0},
]

MAX_FOTOS = 40          # a handover with more than 40 photos is a data-dump, not a document


class ProtokollError(ValueError):
    """Business-rule violation (unknown condition, editing a signed protocol, …)."""


# ── construction ──────────────────────────────────────────────────────


def default_raeume(namen: Optional[list] = None) -> list:
    """The pre-filled room list. The landlord adds/removes rooms in the wizard; he must never
    start from an empty page in a cold flat."""
    out = []
    for name in (namen or DEFAULT_RAEUME):
        elemente = list(STANDARD_ELEMENTE) + list(ZUSATZ_ELEMENTE.get(name, []))
        out.append({
            "name": name,
            "elemente": [{"was": e, "zustand": "gut", "notiz": ""} for e in elemente],
            "notiz": "",
        })
    return out


def default_schluessel() -> list:
    return [dict(s) for s in DEFAULT_SCHLUESSEL]


def neues_protokoll(art: str, datum: Optional[date] = None, raeume: Optional[list] = None) -> dict:
    """A fresh draft — the shape the API stores and the wizard fills in."""
    if art not in ARTEN:
        raise ProtokollError("art muss 'einzug' oder 'auszug' sein")
    return {
        "art": art,
        "datum": datum or date.today(),
        "status": STATUS_ENTWURF,
        "raeume": default_raeume(raeume),
        "schluessel": default_schluessel(),
        "personen": {"vermieter": "", "mieter": "", "zeugen": []},
        "notiz": "",
    }


# ── validation / normalisation ────────────────────────────────────────


def normalize_raeume(raeume) -> list:
    """Accept what the wizard sends, reject what makes no sense. Unknown conditions are a bug,
    not a preference: they would silently ruin the document."""
    if not isinstance(raeume, list):
        raise ProtokollError("raeume muss eine Liste sein")
    out = []
    for r in raeume:
        if not isinstance(r, dict) or not str(r.get("name") or "").strip():
            raise ProtokollError("Jeder Raum braucht einen Namen")
        elemente = []
        for e in (r.get("elemente") or []):
            was = str((e or {}).get("was") or "").strip()
            if not was:
                continue
            z = str((e or {}).get("zustand") or "gut")
            if z not in ZUSTAENDE:
                raise ProtokollError(f"Unbekannter Zustand: {z}")
            elemente.append({"was": was[:80], "zustand": z,
                             "notiz": str((e or {}).get("notiz") or "")[:300]})
        out.append({"name": str(r["name"]).strip()[:60], "elemente": elemente,
                    "notiz": str(r.get("notiz") or "")[:500]})
    return out


def normalize_schluessel(schluessel) -> list:
    if not isinstance(schluessel, list):
        raise ProtokollError("schluessel muss eine Liste sein")
    out = []
    for s in schluessel:
        typ = str((s or {}).get("typ") or "").strip()
        if not typ:
            continue
        try:
            n = int((s or {}).get("anzahl") or 0)
        except (TypeError, ValueError):
            raise ProtokollError("anzahl muss eine Zahl sein")
        if n < 0:
            raise ProtokollError("anzahl darf nicht negativ sein")
        out.append({"typ": typ[:40], "anzahl": n})
    return out


def maengel(raeume) -> list:
    """Everything that is NOT in order — the list the landlord actually cares about later
    (deposit deductions, repairs). Derived, never stored twice."""
    out = []
    for r in (raeume or []):
        for e in (r.get("elemente") or []):
            if e.get("zustand") == "beschaedigt":
                out.append({"raum": r.get("name"), "was": e.get("was"), "notiz": e.get("notiz") or ""})
    return out


# ── the immutability rule ─────────────────────────────────────────────


def is_locked(status) -> bool:
    return str(status or "") == STATUS_ABGESCHLOSSEN


def require_editable(status) -> None:
    """Guard for every write path. A signed protocol is a document, not a form."""
    if is_locked(status):
        raise ProtokollError(
            "Das Protokoll ist abgeschlossen und kann nicht mehr geändert werden. "
            "Für eine Korrektur bitte ein neues Protokoll (Nachtrag) anlegen.")


def can_abschliessen(unterschrift_vermieter, unterschrift_mieter) -> bool:
    return bool(_is_png_dataurl(unterschrift_vermieter) and _is_png_dataurl(unterschrift_mieter))


def _is_png_dataurl(s) -> bool:
    return isinstance(s, str) and s.startswith("data:image/") and ";base64," in s and len(s) > 120


def require_signatures(unterschrift_vermieter, unterschrift_mieter) -> None:
    if not can_abschliessen(unterschrift_vermieter, unterschrift_mieter):
        raise ProtokollError("Beide Unterschriften (Vermieter und Mieter) werden benötigt.")


# ── Zählerstände (Masterplan #7 — history, consumption, chart) ────────


def zaehler_einheit(art: str) -> str:
    if art not in ZAEHLER_ARTEN:
        raise ProtokollError(f"Unbekannte Zählerart: {art}")
    return ZAEHLER_ARTEN[art]


def validate_stand(art: str, stand) -> float:
    zaehler_einheit(art)                      # raises on an unknown meter type
    try:
        v = round(float(stand), 3)
    except (TypeError, ValueError):
        raise ProtokollError("Zählerstand muss eine Zahl sein")
    if v < 0:
        raise ProtokollError("Zählerstand darf nicht negativ sein")
    return v


def verbrauch(readings: list) -> list:
    """Consumption between consecutive readings of the SAME meter, oldest first.

    A reading LOWER than the previous one is not negative consumption — it means the meter was
    exchanged (or misread). We report it as such instead of inventing a number: a wrong
    Heizkosten split is exactly the kind of lie Sprint 0 spent itself removing.
    """
    rows = sorted([r for r in (readings or []) if r.get("datum")], key=lambda r: (r["datum"], r.get("id") or 0))
    out = []
    prev = None
    for r in rows:
        item = {"id": r.get("id"), "datum": r["datum"], "stand": r["stand"],
                "zaehler_nr": r.get("zaehler_nr"), "verbrauch": None, "hinweis": None}
        if prev is not None:
            if r.get("zaehler_nr") and prev.get("zaehler_nr") and r["zaehler_nr"] != prev["zaehler_nr"]:
                item["hinweis"] = "Zählerwechsel — Verbrauch nicht berechenbar"
            elif r["stand"] < prev["stand"]:
                item["hinweis"] = "Stand niedriger als zuvor — Zählerwechsel oder Tippfehler?"
            else:
                item["verbrauch"] = round(r["stand"] - prev["stand"], 3)
        out.append(item)
        prev = r
    return out


def verbrauch_zeitraum(readings: list, von: date, bis: date) -> Optional[float]:
    """Consumption in a period — the number Sprint 2 (Nebenkostenabrechnung) will need.
    None when it cannot be derived honestly (no reading before/after, or a meter change)."""
    rows = sorted([r for r in (readings or []) if r.get("datum")], key=lambda r: r["datum"])
    start = [r for r in rows if r["datum"] <= von]
    end = [r for r in rows if r["datum"] >= bis]
    if not start or not end:
        return None
    a, b = start[-1], end[0]
    if a.get("zaehler_nr") and b.get("zaehler_nr") and a["zaehler_nr"] != b["zaehler_nr"]:
        return None
    if b["stand"] < a["stand"]:
        return None
    return round(b["stand"] - a["stand"], 3)


# ── (de)serialisation helpers used by the API layer ───────────────────


def loads(raw, fallback):
    if not raw:
        return fallback
    try:
        return json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        return fallback


def dumps(v) -> Optional[str]:
    return json.dumps(v, ensure_ascii=False) if v else None
