"""PERSONENZAHL ALLOCATION ENGINE — pure rules (Sprint 3, commit 1).

Switches on the Personenzahl Umlageschlüssel (the single-water-meter / Sammelzähler scenario: split
water/Abwasser/Müll by the number of persons per flat). No DB change — uses the existing
ImmoTenancy.personenzahl.

The rules under test:
  * cost split by personenzahl × Zeitanteil;
  * a VACANT unit has 0 persons → contributes 0 weight (no invented head count), so the cost is borne
    by the actual occupants — NOT wrongly redistributed;
  * if any active tenant lacks personenzahl → fall back to Wohnfläche WITH a note (no silent wrong split);
  * the invariant Σ(tenant shares) + Leerstand == umlagefähige total STILL holds;
  * Wohnfläche/Wohneinheiten behaviour is unchanged (regression);
  * a finalised statement is unaffected (snapshot immutability — CALCULATION_VERSION bumped to 2).

Run:  PYTHONIOENCODING=utf-8 PYTHONPATH=. python tests/test_immo_nk_personenzahl.py
"""
import os
import sys
from dataclasses import dataclass
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
    individuell: Optional[dict] = None


UNITS = [Unit(1), Unit(2), Unit(3)]


print("\n[0] CALCULATION_VERSION bumped (v2 computes persons, v3 computes Individuell)")
ok(NK.CALCULATION_VERSION == 4, f"version is 4 — {NK.CALCULATION_VERSION}")
ok("personenzahl" in NK._COMPUTED, "personenzahl is now a computed key")

print("\n[1] Split by persons — the core case")
# Müll 600. A: 3 persons full year, B: 1 person full year, C: 2 persons full year. Total persons = 6.
tens = [Tenancy(101, 1, "A", VON, None, personenzahl=3),
        Tenancy(102, 2, "B", VON, None, personenzahl=1),
        Tenancy(103, 3, "C", VON, None, personenzahl=2)]
v = NK.verteile([Pos("muell", 600.0, schluessel="personenzahl")], UNITS, tens, VON, BIS)
sh = {t: d["summe"] for t, d in v["per_tenant"].items()}
eq("A (3 persons) pays 3/6 = 300", sh[101], 300.0)
eq("B (1 person) pays 1/6 = 100", sh[102], 100.0)
eq("C (2 persons) pays 2/6 = 200", sh[103], 200.0)
eq("INVARIANT Σ + Leerstand == 600", round(sum(sh.values()) + v["leerstand"], 2), 600.0)
ok(not any("Wohnfläche verteilt" in h for h in v["hinweise"]), f"NO fallback note — it computed by persons ({v['hinweise']})")
ok("Personen" in v["per_tenant"][101]["positionen"][0]["anteil_text"],
   f"the ratio text says Personen — {v['per_tenant'][101]['positionen'][0]['anteil_text']}")

print("\n[2] Zeitanteil — a person present only part of the year")
# A 3 persons full year (36 p-mo), B 2 persons 6 months (12 p-mo). Total 48 p-mo. Wasser 480.
tens2 = [Tenancy(201, 1, "A", VON, None, personenzahl=3),
         Tenancy(202, 2, "B", VON, date(2026, 6, 30), personenzahl=2)]
v2 = NK.verteile([Pos("wasser", 480.0, schluessel="personenzahl")], [Unit(1), Unit(2)], tens2, VON, BIS)
s2 = {t: d["summe"] for t, d in v2["per_tenant"].items()}
eq("A = 36/48 × 480 = 360", s2[201], 360.0)
eq("B = 12/48 × 480 = 120", s2[202], 120.0)
eq("INVARIANT holds with Zeitanteil", round(sum(s2.values()) + v2["leerstand"], 2), 480.0)

print("\n[3] Vacant unit — 0 persons, borne by the occupants (NOT redistributed wrongly)")
# 3 units: A 2 persons full year, B 2 persons full year, C VACANT. Müll 400.
tens3 = [Tenancy(301, 1, "A", VON, None, personenzahl=2),
         Tenancy(302, 2, "B", VON, None, personenzahl=2)]
v3 = NK.verteile([Pos("muell", 400.0, schluessel="personenzahl")], UNITS, tens3, VON, BIS)
s3 = {t: d["summe"] for t, d in v3["per_tenant"].items()}
eq("A pays 2/4 = 200 (vacant unit contributes 0 persons)", s3[301], 200.0)
eq("B pays 2/4 = 200", s3[302], 200.0)
eq("INVARIANT Σ + Leerstand == 400", round(sum(s3.values()) + v3["leerstand"], 2), 400.0)
ok(v3["leerstand"] <= 0.02, f"no invented vacancy person-share; Leerstand ~0 for a pure person cost ({v3['leerstand']})")
# and critically: the two occupants each pay strictly their own persons, never MORE than 2/4 each
ok(s3[301] == s3[302] == 200.0, "the vacant unit's cost is NOT dumped onto the two tenants beyond their person-share")

print("\n[4] Missing person count → honest fallback to Wohnfläche WITH a note")
tens4 = [Tenancy(401, 1, "A", VON, None, personenzahl=3),
         Tenancy(402, 2, "B", VON, None, personenzahl=None)]   # B has no person count
v4 = NK.verteile([Pos("muell", 600.0, schluessel="personenzahl")], [Unit(1), Unit(2)], tens4, VON, BIS)
ok(any("Personenzahl fehlt" in h for h in v4["hinweise"]),
   f"a note names the missing tenant and the fallback — {v4['hinweise']}")
ok("B" in " ".join(v4["hinweise"]), "the note names WHO is missing (B)")
s4 = {t: d["summe"] for t, d in v4["per_tenant"].items()}
# fell back to Wohnfläche (both 50 m² full year) → 300/300
eq("fell back to Wohnfläche: A 300", s4[401], 300.0)
eq("fell back to Wohnfläche: B 300", s4[402], 300.0)
eq("INVARIANT still holds on fallback", round(sum(s4.values()) + v4["leerstand"], 2), 600.0)

print("\n[5] personenzahl 0 is treated as missing (not a divide-by-zero)")
tens5 = [Tenancy(501, 1, "A", VON, None, personenzahl=2),
         Tenancy(502, 2, "B", VON, None, personenzahl=0)]
v5 = NK.verteile([Pos("muell", 400.0, schluessel="personenzahl")], [Unit(1), Unit(2)], tens5, VON, BIS)
ok(any("Personenzahl fehlt" in h for h in v5["hinweise"]), "0 persons → treated as missing, fallback + note")
eq("INVARIANT holds", round(sum(d['summe'] for d in v5["per_tenant"].values()) + v5["leerstand"], 2), 400.0)

print("\n[6] REGRESSION — Wohnfläche / Wohneinheiten unchanged")
tensR = [Tenancy(601, 1, "A", VON, None, personenzahl=9),
         Tenancy(602, 2, "B", VON, None, personenzahl=1)]   # persons set but key is wohnflaeche
vw = NK.verteile([Pos("grundsteuer", 1000.0, schluessel="wohnflaeche")], [Unit(1), Unit(2)], tensR, VON, BIS)
sw = {t: d["summe"] for t, d in vw["per_tenant"].items()}
eq("Wohnfläche ignores personenzahl: A 500", sw[601], 500.0)
eq("Wohnfläche: B 500", sw[602], 500.0)
ve = NK.verteile([Pos("hausmeister", 1000.0, schluessel="wohneinheiten")], [Unit(1), Unit(2)], tensR, VON, BIS)
eq("Wohneinheiten still 1/2 each", ve["per_tenant"][601]["summe"], 500.0)

print("\n[7] Verbrauch STILL falls back to Wohnfläche with a note (deferred to Sprint 4 / HeizkostenV)")
vv = NK.verteile([Pos("heizkosten", 400.0, schluessel="verbrauch")], [Unit(1), Unit(2)], tensR, VON, BIS)
ok(any("Verbrauch" in h for h in vv["hinweise"]),
   f"verbrauch still announces its Wohnfläche fallback — {vv['hinweise']}")

print("\n[8] Mixed statement — a person cost AND an area cost together, invariant across the whole")
# Müll 300 by persons (A 2, B 1 → 200/100), Grundsteuer 600 by area with unit 3 VACANT (Leerstand)
mixed_units = [Unit(1), Unit(2), Unit(3)]
mixed_tens = [Tenancy(801, 1, "A", VON, None, personenzahl=2),
              Tenancy(802, 2, "B", VON, None, personenzahl=1)]   # unit 3 vacant
vm = NK.verteile([Pos("muell", 300.0, schluessel="personenzahl"),
                  Pos("grundsteuer", 600.0, schluessel="wohnflaeche")], mixed_units, mixed_tens, VON, BIS)
sm = {t: d["summe"] for t, d in vm["per_tenant"].items()}
eq("total umlagefähig 900", vm["umlagefaehige_summe"], 900.0)
eq("INVARIANT over the WHOLE statement: Σ + Leerstand == 900", round(sum(sm.values()) + vm["leerstand"], 2), 900.0)
ok(vm["leerstand"] > 0, f"the vacant unit's AREA share (Grundsteuer) is carried by the landlord ({vm['leerstand']})")
# person cost fully on occupants (200/100 of 300 = 300 assigned), area cost split incl. vacancy
eq("A: 200 (Müll) + 200 (Grundsteuer 1/3) = 400", sm[801], 400.0)

print("\n[8b] ergebnis rows carry personenzahl (so the NK screen can show a per-tenant persons input)")
res_b = NK.ergebnis(NK.verteile([Pos("muell", 400.0, schluessel="personenzahl")], UNITS, tens, VON, BIS), tens, VON, BIS)
byname = {r["name"]: r for r in res_b["tenants"]}
ok(byname["A"]["personenzahl"] == 3 and byname["B"]["personenzahl"] == 1, "each result row exposes personenzahl")

print("\n[Eig] Eigennutzung — owner lives in a flat and is counted in the person split (SaaS scenario)")
# Building: owner in unit 1 (4 persons, Eigennutzung), VANELLE unit 2 (1), YURONG unit 3 (1). Wasser 1267.
u_own = Unit(1); u_own.eigennutzung_personen = 4
eig_units = [u_own, Unit(2), Unit(3)]
eig_tens = [Tenancy(701, 2, "VANELLE", VON, None, personenzahl=1),
            Tenancy(702, 3, "YURONG", VON, None, personenzahl=1)]      # unit 1 has NO tenant (owner lives there)
ve = NK.verteile([Pos("wasser", 1267.0, schluessel="personenzahl")], eig_units, eig_tens, VON, BIS)
res_e = NK.ergebnis(ve, eig_tens, VON, BIS)
bynm = {r["name"]: r for r in res_e["tenants"]}
eq("VANELLE pays 1/6 of 1267", bynm["VANELLE"]["umlage"], round(1267/6, 2))
eq("YURONG pays 1/6 of 1267", bynm["YURONG"]["umlage"], round(1267/6, 2))
eq("owner bears 4/6 (Eigennutzung), NOT the tenants", res_e["eigennutzung"], round(1267*4/6, 2))
eq("no true vacancy", res_e["leerstand"], 0.0)
eq("INVARIANT Σ tenants + Eigennutzung + Leerstand == 1267",
   round(sum(r["umlage"] for r in res_e["tenants"]) + res_e["eigennutzung"] + res_e["leerstand"], 2), 1267.0)
# without Eigennutzung set, the two tenants would wrongly split 100% (1/2 each) — prove the difference
ve0 = NK.verteile([Pos("wasser", 1267.0, schluessel="personenzahl")], [Unit(1), Unit(2), Unit(3)], eig_tens, VON, BIS)
r0 = {r["name"]: r["umlage"] for r in NK.ergebnis(ve0, eig_tens, VON, BIS)["tenants"]}
ok(r0["VANELLE"] == round(1267/2, 2), f"WITHOUT Eigennutzung: tenants wrongly split 1/2 each ({r0['VANELLE']}) — the feature fixes this")

# ── the LOCKED product behaviours for Eigennutzung (Sprint 3 architecture decision: model B) ──
print("\n[Eig-2] Owner NOT living there (eigennutzung_personen unset) → 0 persons, the flat is Leerstand")
u_off = Unit(1)  # eigennutzung_personen stays None → owner does not live here, no tenant → vacant
off_tens = [Tenancy(711, 2, "A", VON, None, personenzahl=1), Tenancy(712, 3, "B", VON, None, personenzahl=1)]
vo = NK.verteile([Pos("wasser", 1200.0, schluessel="personenzahl")], [u_off, Unit(2), Unit(3)], off_tens, VON, BIS)
ro = NK.ergebnis(vo, off_tens, VON, BIS)
rno = {r["name"]: r["umlage"] for r in ro["tenants"]}
eq("empty flat contributes 0 persons — water splits over the 2 tenants only", rno["A"], 600.0)
eq("no Eigennutzung share when the owner does not live in", ro["eigennutzung"], 0.0)
eq("a person-key vacant flat adds no cost (no one consumes there)", ro["leerstand"], 0.0)

print("\n[Eig-3] Eigennutzung and Leerstand are SEPARATE buckets (both in one building, area key)")
# unit1 owner-occupied (2 pers), unit2 tenant, unit3 TRULY vacant — Grundsteuer 900 by area, 3×50 m²
u_mix1 = Unit(1); u_mix1.eigennutzung_personen = 2
mix_tens = [Tenancy(721, 2, "A", VON, None, personenzahl=1)]   # unit3 has no tenant and no eigennutzung → vacant
vx = NK.verteile([Pos("grundsteuer", 900.0, schluessel="wohnflaeche")], [u_mix1, Unit(2), Unit(3)], mix_tens, VON, BIS)
rx = NK.ergebnis(vx, mix_tens, VON, BIS)
eq("tenant bears its 1/3", rx["tenants"][0]["umlage"], 300.0)
eq("Eigennutzung bucket = owner flat 1/3", rx["eigennutzung"], 300.0)
eq("Leerstand bucket = truly vacant flat 1/3", rx["leerstand"], 300.0)
ok(rx["eigennutzung"] != 0 and rx["leerstand"] != 0, "the two concepts coexist WITHOUT merging")
eq("INVARIANT Σ tenants + Eigennutzung + Leerstand == 900",
   round(rx["tenants"][0]["umlage"] + rx["eigennutzung"] + rx["leerstand"], 2), 900.0)

print("\n[9] snapshot records the RAW schluessel (personenzahl), engine version 3")
snap = NK.build_snapshot({"id": 1, "jahr": 2026}, {"id": 10, "adresse": "x"}, [Unit(1), Unit(2)],
                         [Tenancy(901, 1, "A", VON, None, personenzahl=2), Tenancy(902, 2, "B", VON, None, personenzahl=2)],
                         [Pos("muell", 400.0, schluessel="personenzahl")], VON, BIS)
ok(snap["calculation_version"] == 4, "snapshot stamped with version 4")
ok(snap["cost_lines"][0]["schluessel"] == "personenzahl", "the chosen key is frozen in the snapshot")
ok(all("personenzahl" in t for t in snap["tenants"]), "each tenant's personenzahl is frozen for re-production")

# ── Individuell (Sprint 3): the landlord assigns an EXACT amount per tenant, no weighting/fallback ──
IU = [Unit(1), Unit(2), Unit(3)]
itens = [Tenancy(201, 1, "A", VON, None), Tenancy(202, 2, "B", VON, None), Tenancy(203, 3, "C", VON, None)]

print("\n[10] Individuell — exact amounts, sum == invoice, no Wohnfläche fallback")
vi = NK.verteile([Pos("strom", 1200.0, schluessel="individuell",
                      individuell={201: 500, 202: 300, 203: 400})], IU, itens, VON, BIS)
ri = {r["name"]: r["umlage"] for r in NK.ergebnis(vi, itens, VON, BIS)["tenants"]}
eq("A pays exactly its entered amount", ri["A"], 500.0)
eq("B pays exactly its entered amount", ri["B"], 300.0)
eq("C pays exactly its entered amount", ri["C"], 400.0)
eq("no landlord remainder when sum == invoice", vi["leerstand"], 0.0)
eq("INVARIANT Σ tenants + leerstand == invoice", sum(ri.values()) + vi["leerstand"], 1200.0)
ok(vi["per_tenant"][201]["positionen"][0]["anteil_text"] == "Individuell (fester Betrag)",
   "the line is billed as Individuell, NOT a Wohnfläche fallback")
ok(vi["per_tenant"][201]["positionen"][0]["schluessel"] == "individuell", "schluessel stays 'individuell'")

print("\n[11] Individuell — unassigned rest stays with the landlord")
vp = NK.verteile([Pos("strom", 1000.0, schluessel="individuell", individuell={201: 300})], IU, itens, VON, BIS)
rp = {r["name"]: r["umlage"] for r in NK.ergebnis(vp, itens, VON, BIS)["tenants"]}
eq("only the assigned tenant is billed", rp["A"], 300.0)
eq("un-entered tenants pay 0", rp["B"], 0.0)
eq("the rest is the landlord's (leerstand bucket)", vp["leerstand"], 700.0)
eq("INVARIANT holds with a remainder", sum(rp.values()) + vp["leerstand"], 1000.0)

print("\n[12] Individuell — over-assignment is scaled down (never bill more than the cost) + a note")
vo = NK.verteile([Pos("strom", 1000.0, schluessel="individuell", individuell={201: 800, 202: 800})], IU, itens, VON, BIS)
eo = NK.ergebnis(vo, itens, VON, BIS)
ro = {r["name"]: r["umlage"] for r in eo["tenants"]}
eq("entries scaled proportionally to the invoice", ro["A"], 500.0)
eq("entries scaled proportionally to the invoice", ro["B"], 500.0)
eq("INVARIANT holds after scaling", sum(ro.values()) + vo["leerstand"], 1000.0)
ok(len(eo["hinweise"]) >= 1, "an over-assignment note is emitted")

print("\n[13] Individuell — empty selection stays with the landlord + a note")
vn = NK.verteile([Pos("strom", 500.0, schluessel="individuell", individuell=None)], IU, itens, VON, BIS)
en = NK.ergebnis(vn, itens, VON, BIS)
eq("nothing is billed to tenants", sum(r["umlage"] for r in en["tenants"]), 0.0)
eq("the whole invoice is the landlord's", vn["leerstand"], 500.0)
ok(len(en["hinweise"]) >= 1, "an empty-Individuell note is emitted")

print("\n[14] Individuell — snapshot freezes the exact result and the entries (audit)")
snap2 = NK.build_snapshot({"id": 2, "jahr": 2026}, {"id": 11, "adresse": "y"}, IU, itens,
                          [Pos("strom", 1200.0, schluessel="individuell", individuell={201: 500, 202: 300, 203: 400})],
                          VON, BIS)
ok(snap2["calculation_version"] == 4, "individuell snapshot stamped v4")
ok(snap2["cost_lines"][0]["schluessel"] == "individuell", "individuell key frozen")
ok(snap2["cost_lines"][0]["individuell"] == {201: 500.0, 202: 300.0, 203: 400.0}, "per-tenant entries frozen for re-production")
_alloc = {a["name"]: a["umlage"] for a in snap2["allocation"]}
eq("frozen allocation matches the live result", _alloc["A"], 500.0)

print(f"\n=== PERSONENZAHL + INDIVIDUELL ENGINE: {PASS} passed, {FAIL} failed ===")
sys.exit(1 if FAIL else 0)
