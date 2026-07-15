"""NEBENKOSTENABRECHNUNG — pure rules (Sprint 2, commit 1).

No database, no FastAPI: the distribution engine, Zeitanteil, Leerstand, the balance and the snapshot
are all testable on their own. Endpoints (commit 2) call exactly these functions.

The rules that matter most:
  * Σ tenant shares + Leerstand == umlagefähige total, to the cent (the vacant share is NEVER
    redistributed to the other tenants — a legal error);
  * the Vorauszahlung comes ONLY from immo_rules.monat_nk_soll (Single-Ledger Principle);
  * umlagefähig defaults protect the landlord from dunning a repair;
  * a finalised statement is immutable.

Scenario (from the WOW design): 1 Objekt, 4 units 50 m² each. Ahmet 12 mo, Mehmet 9, Ali 7, Ayşe 5
(so unit D is vacant 7 months). Kalt 400 + NK 70 each. Period 2026-01-01 … 2026-12-31.

Run:  PYTHONIOENCODING=utf-8 PYTHONPATH=. python tests/test_immo_nk_rules.py
"""
import os
import sys
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

os.environ.setdefault("JWT_SECRET", "x" * 44)

from autotax import immo_nebenkosten as NK

VON = date(2026, 1, 1)
BIS = date(2026, 12, 31)

PASS = FAIL = 0


def ok(c, m):
    global PASS, FAIL
    if c:
        PASS += 1
        print(f"  PASS  {m}")
    else:
        FAIL += 1
        print(f"  FAIL  {m}")


def eq(name, got, want, tol=0.02):
    ok(abs(float(got) - float(want)) <= tol, f"{name} (got {got}, want {want})")


@dataclass
class Unit:
    id: int
    wohnflaeche: float = 50.0
    mea: Optional[float] = None
    name: str = ""


@dataclass
class Tenancy:
    id: int
    unit_id: int
    mieter_name: str
    von: Optional[date]
    bis: Optional[date]
    kaltmiete: float = 400.0
    nk_voraus: float = 70.0
    erstmonat_betrag: Optional[float] = None
    miete_historie: Optional[str] = None
    offene_monate: Optional[str] = None
    personenzahl: Optional[int] = None


@dataclass
class Pos:
    kategorie: str
    betrag: float
    umlagefaehig: bool = True
    umlage_pct: int = 100
    schluessel: str = "wohnflaeche"
    verbrauch_art: Optional[str] = None
    individuell: Optional[str] = None


UNITS = [Unit(1), Unit(2), Unit(3), Unit(4)]
TENS = [
    Tenancy(101, 1, "Ahmet", date(2026, 1, 1), None),            # full year
    Tenancy(102, 2, "Mehmet", date(2026, 1, 1), date(2026, 9, 30)),   # 9 months
    Tenancy(103, 3, "Ali", date(2026, 6, 1), None),             # 7 months (Jun–Dec)
    Tenancy(104, 4, "Ayşe", date(2026, 8, 1), None),            # 5 months (Aug–Dec) → unit 4 vacant Jan–Jul
]


print("\n[1] umlagefähig defaults — the correctness core (the #1 landlord mistake)")
ok(NK.umlagefaehig_default("grundsteuer") is True, "Grundsteuer is umlagefähig")
ok(NK.umlagefaehig_default("muell") is True, "Müll is umlagefähig")
ok(NK.umlagefaehig_default("reparatur") is False, "Reparatur is NOT umlagefähig (protects the landlord)")
ok(NK.umlagefaehig_default("verwaltung") is False, "Verwaltung is NOT umlagefähig")
ok(NK.umlagefaehig_default("finanzierung") is False, "Finanzierung (Zins/Tilgung) is NOT umlagefähig")
ok(NK.default_schluessel("heizkosten") == "verbrauch", "Heizkosten defaults to the Verbrauch key")
ok(NK.default_schluessel("muell") == "personenzahl", "Müll defaults to the Personenzahl key")

print("\n[2] Zeitanteil — mid-year move in/out")
eq("Ahmet full year = 1.0", NK.zeitanteil(TENS[0], VON, BIS), 1.0)
eq("Mehmet 9/12", NK.zeitanteil(TENS[1], VON, BIS), 9 / 12)
eq("Ali 7/12", NK.zeitanteil(TENS[2], VON, BIS), 7 / 12)
eq("Ayşe 5/12", NK.zeitanteil(TENS[3], VON, BIS), 5 / 12)

print("\n[3] Distribution by Wohnfläche + Zeitanteil, and THE INVARIANT")
# Grundsteuer 1200, all four units 50 m². Weights: 1.0, 0.75, 0.583, 0.417 (×50). Unit 4 also vacant 7/12.
pos = [Pos("grundsteuer", 1200.0, schluessel="wohnflaeche")]
v = NK.verteile(pos, UNITS, TENS, VON, BIS)
tot_tenant = round(sum(x["summe"] for x in v["per_tenant"].values()), 2)
eq("Σ tenant shares + Leerstand == total (INVARIANT)", tot_tenant + v["leerstand"], 1200.0)
eq("umlagefähige Summe == 1200", v["umlagefaehige_summe"], 1200.0)
ok(v["leerstand"] > 0, f"the landlord carries the vacant share, it is NOT redistributed ({v['leerstand']})")
# Ahmet has the biggest Zeitanteil → the biggest share
shares = {tid: d["summe"] for tid, d in v["per_tenant"].items()}
ok(shares[101] > shares[102] > shares[103] > shares[104],
   f"more months → bigger share: {[round(shares[t],2) for t in (101,102,103,104)]}")

print("\n[4] The vacant share is NEVER pushed onto the other tenants")
# a fully-occupied building: no leerstand
tens_full = [Tenancy(201, 1, "A", date(2026, 1, 1), None), Tenancy(202, 2, "B", date(2026, 1, 1), None),
             Tenancy(203, 3, "C", date(2026, 1, 1), None), Tenancy(204, 4, "D", date(2026, 1, 1), None)]
vf = NK.verteile([Pos("grundsteuer", 1200.0)], UNITS, tens_full, VON, BIS)
eq("full house → each pays 1/4", vf["per_tenant"][201]["summe"], 300.0)
eq("full house → Leerstand 0", vf["leerstand"], 0.0)

print("\n[5] umlage_pct — the mixed Hausmeister case")
vh = NK.verteile([Pos("hausmeister", 1000.0, umlage_pct=60)], UNITS, tens_full, VON, BIS)
eq("only 60% is umlagefähig", vh["umlagefaehige_summe"], 600.0)
eq("each tenant pays 1/4 of 600", vh["per_tenant"][201]["summe"], 150.0)

print("\n[6] non-umlagefähige positions are excluded entirely")
vn = NK.verteile([Pos("reparatur", 5000.0, umlagefaehig=False), Pos("grundsteuer", 1200.0)],
                 UNITS, tens_full, VON, BIS)
eq("the repair is NOT in the total", vn["umlagefaehige_summe"], 1200.0)
eq("no tenant pays for the repair", vn["per_tenant"][201]["summe"], 300.0)

print("\n[7] Vorauszahlung comes ONLY from monat_nk_soll (Single-Ledger Principle)")
from autotax import immo_rules as R
# Ahmet full year, nk_voraus 70 → 12 × 70 = 840
eq("Ahmet advance = Σ monat_nk_soll = 840", NK.vorauszahlung(TENS[0], VON, BIS), 840.0)
eq("Mehmet advance = 9 × 70 = 630", NK.vorauszahlung(TENS[1], VON, BIS), 630.0)
eq("Ali advance = 7 × 70 = 490", NK.vorauszahlung(TENS[2], VON, BIS), 490.0)
manual = round(sum(R.monat_nk_soll(TENS[0], 2026, m) for m in range(1, 13)), 2)
eq("it is literally Σ monat_nk_soll, not a second source", NK.vorauszahlung(TENS[0], VON, BIS), manual)

print("\n[8] Ergebnis — Guthaben / Nachzahlung")
# Costs: Grundsteuer 1200 + Müll 600 (both wohnflaeche for this test) = 1800 umlagefähig
pos = [Pos("grundsteuer", 1200.0), Pos("muell", 600.0, schluessel="wohnflaeche")]
res = NK.ergebnis(NK.verteile(pos, UNITS, TENS, VON, BIS), TENS, VON, BIS)
ahmet = [r for r in res["tenants"] if r["tenancy_id"] == 101][0]
ok(ahmet["vorauszahlung"] == 840.0, f"Ahmet advance 840 (from the Mietkonto) — {ahmet['vorauszahlung']}")
ok(ahmet["saldo"] == round(ahmet["vorauszahlung"] - ahmet["umlage"], 2), "saldo = advance − share")
ok(ahmet["typ"] in ("guthaben", "nachzahlung", "ausgeglichen"), "the balance has a type")
# invariant holds through ergebnis too
tot = round(sum(r["umlage"] for r in res["tenants"]) + res["leerstand"], 2)
eq("Σ umlage + Leerstand == 1800 (invariant through ergebnis)", tot, 1800.0)

print("\n[9] Honesty — a unit without Wohnfläche is flagged, not divided by zero")
bad_units = [Unit(1, wohnflaeche=None), Unit(2, wohnflaeche=None)]
bad_tens = [Tenancy(301, 1, "X", date(2026, 1, 1), None), Tenancy(302, 2, "Y", date(2026, 1, 1), None)]
vb = NK.verteile([Pos("grundsteuer", 1000.0)], bad_units, bad_tens, VON, BIS)
ok(any("nicht verteilt" in h or "keine Wohnfläche" in h for h in vb["hinweise"]),
   f"a note explains it could not be split — {vb['hinweise']}")
eq("the amount is carried by the landlord, not divided by zero", vb["leerstand"], 1000.0)

print("\n[10] A not-yet-wired key (verbrauch) falls back to Wohnfläche WITH A NOTE")
vp = NK.verteile([Pos("heizkosten", 400.0, schluessel="verbrauch")], UNITS, tens_full, VON, BIS)
ok(any("Wohnfläche verteilt" in h for h in vp["hinweise"]),
   f"the Verbrauch fallback is announced — {vp['hinweise']}")
eq("it still splits (by area) and stays exact", vp["per_tenant"][201]["summe"], 100.0)
# personenzahl WITHOUT data also falls back (with its own note); WITH data it computes (Sprint 3)
vpz = NK.verteile([Pos("muell", 400.0, schluessel="personenzahl")], UNITS, tens_full, VON, BIS)
ok(any("Personenzahl fehlt" in h for h in vpz["hinweise"]),
   f"personenzahl with no data → honest fallback note — {vpz['hinweise']}")
ok(NK.verteile([Pos("x", 1.0, schluessel="quatsch")] if False else [], UNITS, TENS, VON, BIS) is not None, "empty positions ok")
try:
    NK.verteile([Pos("x", 100.0, schluessel="quatsch")], UNITS, tens_full, VON, BIS)
    ok(False, "an unknown key is rejected")
except NK.NkError:
    ok(True, "an unknown Umlageschlüssel is rejected")

print("\n[11] 12-month deadline (§556 III)")
ok(NK.frist_ueberschritten(date(2025, 12, 31), as_of=date(2027, 6, 1)) is True, "late (>12 mo) → warning")
ok(NK.frist_ueberschritten(date(2025, 12, 31), as_of=date(2026, 6, 1)) is False, "within 12 months → ok")

print("\n[12] Immutability guard (Principle B)")
NK.require_editable("entwurf")
ok(True, "a draft is editable")
try:
    NK.require_editable("final")
    ok(False, "editing a final statement should be refused")
except NK.NkError as e:
    ok("entsperren" in str(e) or "neue Abrechnung" in str(e), "a final statement is locked, message says how to correct")

print("\n[13] Immutable snapshot (Principle A) — everything needed to re-produce is frozen")
snap = NK.build_snapshot({"id": 7, "jahr": 2026}, {"id": 10, "adresse": "Musterstr. 12"},
                         UNITS, TENS, [Pos("grundsteuer", 1200.0), Pos("muell", 600.0)], VON, BIS)
for key in ("calculation_version", "settlement_id", "abrechnungsperiode", "property", "units",
            "tenants", "cost_lines", "allocation", "leerstand_share", "umlagefaehige_summe",
            "final_result", "hinweise"):
    ok(key in snap, f"snapshot carries '{key}'")
ok(snap["calculation_version"] == NK.CALCULATION_VERSION, "the calculation version is stamped")
ok(all("zeitanteil" in t for t in snap["tenants"]), "each tenant's Zeitanteil is frozen")
ok(all("anteil_text" in p for r in snap["allocation"] for p in r["positionen"]),
   "the exact allocation ratio per line is frozen (allocation_ratios)")

print("\n[14] ARCHITECTURE: the rules are free of persistence")
import inspect as _i

import autotax.immo_nebenkosten as _m
src = _i.getsource(_m)
ok("sqlalchemy" not in src.lower(), "no sqlalchemy")
ok("SessionLocal" not in src, "no DB session")
ok("from autotax.models" not in src, "no ORM models")

print(f"\n=== NEBENKOSTEN RULES: {PASS} passed, {FAIL} failed ===")
sys.exit(1 if FAIL else 0)
