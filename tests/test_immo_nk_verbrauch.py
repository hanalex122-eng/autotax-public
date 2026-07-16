"""Sprint 4 — Verbrauch / Zählerstand engine + HeizkostenV. Pure-python, no DB."""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from autotax import immo_nebenkosten as NK   # noqa: E402

VON, BIS = date(2026, 1, 1), date(2026, 12, 31)
PASS = 0
FAIL = 0


def ok(c, m):
    global PASS, FAIL
    if c:
        PASS += 1; print("  PASS ", m)
    else:
        FAIL += 1; print("  FAIL ", m)


def eq(name, got, want, tol=0.02):
    ok(abs((got or 0) - want) <= tol, f"{name} (got {got}, want {want})")


class Unit:
    def __init__(s, i, wf=50.0, eig=None):
        s.id = i; s.unit_id = i; s.wohnflaeche = wf; s.name = f"W{i}"; s.mea = None
        s.eigennutzung_personen = eig


class Ten:
    def __init__(s, i, uid, nm, von=VON, bis=None):
        s.id = i; s.unit_id = uid; s.mieter_name = nm; s.von = von; s.bis = bis
        s.personenzahl = None; s.kaltmiete = 0.0; s.nk_voraus = 0.0; s.monat_nk_soll = 0.0


class Pos:
    def __init__(s, kat, betrag, schluessel="verbrauch", verbrauch_art=None, grund_prozent=None):
        s.kategorie = kat; s.betrag = betrag; s.umlagefaehig = True; s.umlage_pct = 100
        s.schluessel = schluessel; s.verbrauch_art = verbrauch_art; s.grund_prozent = grund_prozent
        s.individuell = None


def R(uid, art, stand, d):
    return {"unit_id": uid, "art": art, "stand": stand, "datum": d}


print("\n[0] version bumped to 4")
ok(NK.CALCULATION_VERSION == 4, f"CALCULATION_VERSION is 4 — {NK.CALCULATION_VERSION}")

print("\n[1] Pure Verbrauch (kalt water) — split by measured consumption")
u = [Unit(1), Unit(2)]
t = [Ten(1, 1, "A"), Ten(2, 2, "B")]
rd = [R(1, "wasser", 0, VON), R(1, "wasser", 30, BIS), R(2, "wasser", 0, VON), R(2, "wasser", 10, BIS)]
v = NK.verteile([Pos("wasser", 400.0, verbrauch_art="wasser")], u, t, VON, BIS, rd)
r = NK.ergebnis(v, t, VON, BIS)
rows = {x["name"]: x["umlage"] for x in r["tenants"]}
eq("A used 30/40 → 300", rows["A"], 300.0)
eq("B used 10/40 → 100", rows["B"], 100.0)
eq("INVARIANT Σ + rest == 400", sum(rows.values()) + r["leerstand"] + r["eigennutzung"], 400.0)
ok(v["per_tenant"][1]["positionen"][0]["schluessel"] == "verbrauch", "billed as Verbrauch (no fallback)")

print("\n[2] HeizkostenV — 1000€, 30% Grund (area) + 70% Verbrauch (meter)")
uh = [Unit(1, 50.0), Unit(2, 50.0)]
th = [Ten(1, 1, "A"), Ten(2, 2, "B")]
rh = [R(1, "heizung", 0, VON), R(1, "heizung", 70, BIS), R(2, "heizung", 0, VON), R(2, "heizung", 30, BIS)]
vh = NK.verteile([Pos("heizkosten", 1000.0, verbrauch_art="heizung", grund_prozent=30)], uh, th, VON, BIS, rh)
rhh = {x["name"]: x["umlage"] for x in NK.ergebnis(vh, th, VON, BIS)["tenants"]}
# Grund 300 → 150/150 (equal area); Verbrauch 700 → 490 (70/100) / 210 (30/100)
eq("A = 150 Grund + 490 Verbrauch = 640", rhh["A"], 640.0)
eq("B = 150 Grund + 210 Verbrauch = 360", rhh["B"], 360.0)
eq("INVARIANT Σ == 1000", sum(rhh.values()), 1000.0)
ok(any("Grundkosten 30%" in p["anteil_text"] for p in vh["per_tenant"][1]["positionen"]), "a Grundkosten 30% row exists")
ok(any("Verbrauch 70%" in p["anteil_text"] for p in vh["per_tenant"][1]["positionen"]), "a Verbrauch 70% row exists")

print("\n[3] HeizkostenV default 30/70 when grund_prozent not set")
vd = NK.verteile([Pos("heizkosten", 1000.0, verbrauch_art="heizung")], uh, th, VON, BIS, rh)
rd2 = {x["name"]: x["umlage"] for x in NK.ergebnis(vd, th, VON, BIS)["tenants"]}
eq("default 30/70 → A 640", rd2["A"], 640.0)

print("\n[4] HeizkostenV 50/50")
v5 = NK.verteile([Pos("heizkosten", 1000.0, verbrauch_art="heizung", grund_prozent=50)], uh, th, VON, BIS, rh)
r5 = {x["name"]: x["umlage"] for x in NK.ergebnis(v5, th, VON, BIS)["tenants"]}
# Grund 500 → 250/250; Verbrauch 500 → 350/150
eq("A = 250 + 350 = 600", r5["A"], 600.0)
eq("B = 250 + 150 = 400", r5["B"], 400.0)

print("\n[5] Move-out via Zwischenablesung — leaving tenant bills only their interval")
um = [Unit(1)]
tm = [Ten(101, 1, "A", von=VON, bis=date(2026, 6, 30)), Ten(102, 1, "B", von=date(2026, 7, 1), bis=None)]
rm = [R(1, "wasser", 0, VON), R(1, "wasser", 40, date(2026, 6, 30)), R(1, "wasser", 100, BIS)]
vm = NK.verteile([Pos("wasser", 1000.0, verbrauch_art="wasser")], um, tm, VON, BIS, rm)
rmm = {x["name"]: x["umlage"] for x in NK.ergebnis(vm, tm, VON, BIS)["tenants"]}
eq("A used 40 (Jan–Jun) → 400", rmm["A"], 400.0)
eq("B used 60 (Jul–Dec) → 600", rmm["B"], 600.0)
eq("INVARIANT Σ == 1000", sum(rmm.values()) + vm["leerstand"], 1000.0)

print("\n[6] Missing readings → fall back to Wohnfläche WITH a note (never a silent wrong number)")
vf = NK.verteile([Pos("heizkosten", 1000.0, verbrauch_art="heizung")], uh, th, VON, BIS, readings=None)
ef = NK.ergebnis(vf, th, VON, BIS)
rf = {x["name"]: x["umlage"] for x in ef["tenants"]}
eq("fallback to area → 500/500 (equal m²)", rf["A"], 500.0)
ok(any("Verbrauch" in h for h in ef["hinweise"]), f"a note explains the fallback — {ef['hinweise']}")
ok(all(p["schluessel"] == "wohnflaeche" for p in vf["per_tenant"][1]["positionen"]), "rows are Wohnfläche on fallback")

print("\n[7] Eigennutzung + Verbrauch — owner's consumption is the owner's own cost, not the tenant's")
ue = [Unit(1, eig=None), Unit(2, eig=3)]     # unit2 owner-occupied
te = [Ten(1, 1, "A")]                         # only unit1 has a tenant
re_ = [R(1, "wasser", 0, VON), R(1, "wasser", 20, BIS), R(2, "wasser", 0, VON), R(2, "wasser", 80, BIS)]
ve = NK.verteile([Pos("wasser", 1000.0, verbrauch_art="wasser")], ue, te, VON, BIS, re_)
ree = NK.ergebnis(ve, te, VON, BIS)
ree_rows = {x["name"]: x["umlage"] for x in ree["tenants"]}
eq("tenant A pays only their 20/100 → 200", ree_rows["A"], 200.0)
eq("owner's 80/100 → Eigennutzung 800 (not billed to A)", ree["eigennutzung"], 800.0)
eq("no true vacancy", ree["leerstand"], 0.0)
eq("INVARIANT Σ + Eig + Leer == 1000", sum(ree_rows.values()) + ree["eigennutzung"] + ree["leerstand"], 1000.0)

print("\n[8] grund_prozent validation clamps to 30–50")
eq("clamp(20) → 30", NK.clamp_grund(20), 30, tol=0)
eq("clamp(60) → 50", NK.clamp_grund(60), 50, tol=0)
eq("clamp(40) → 40", NK.clamp_grund(40), 40, tol=0)
eq("clamp(None) → 30 default", NK.clamp_grund(None), 30, tol=0)
# an out-of-range grund_prozent on a position is clamped, not trusted
vc = NK.verteile([Pos("heizkosten", 1000.0, verbrauch_art="heizung", grund_prozent=10)], uh, th, VON, BIS, rh)
rc = {x["name"]: x["umlage"] for x in NK.ergebnis(vc, th, VON, BIS)["tenants"]}
eq("grund=10 clamped to 30 → A 640", rc["A"], 640.0)

print("\n[9] snapshot freezes grund_prozent + readings (re-producible years later)")
snap = NK.build_snapshot({"id": 1, "jahr": 2026}, {"id": 9, "adresse": "x"}, uh, th,
                         [Pos("heizkosten", 1000.0, verbrauch_art="heizung", grund_prozent=30)], VON, BIS, readings=rh)
ok(snap["calculation_version"] == 4, "snapshot stamped v4")
ok(snap["cost_lines"][0]["grund_prozent"] == 30, "grund_prozent frozen in the snapshot")
ok(len(snap["readings"]) == 4, "meter readings frozen in the snapshot")
_al = {a["name"]: a["umlage"] for a in snap["allocation"]}
eq("frozen allocation matches live (A 640)", _al["A"], 640.0)

print(f"\n=== VERBRAUCH / HEIZKOSTENV ENGINE: {PASS} passed, {FAIL} failed ===")
sys.exit(1 if FAIL else 0)
