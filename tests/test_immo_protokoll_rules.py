"""ÜBERGABEPROTOKOLL + ZÄHLERSTÄNDE — pure rules (Sprint 1, commit 1).

No database, no FastAPI, no HTTP: if the rules of a handover cannot be tested on their own,
they are in the wrong place. Endpoints come in commit 2 and will call exactly these functions.

The rule that matters most: a SIGNED protocol is immutable. Everything else is convenience;
that one is what makes the document worth anything in a dispute.

Run:  PYTHONIOENCODING=utf-8 PYTHONPATH=. python tests/test_immo_protokoll_rules.py
"""
import os
import sys
from datetime import date

os.environ.setdefault("JWT_SECRET", "x" * 44)

from autotax import immo_protokoll as P

PASS = FAIL = 0


def ok(c, m):
    global PASS, FAIL
    if c:
        PASS += 1
        print(f"  PASS  {m}")
    else:
        FAIL += 1
        print(f"  FAIL  {m}")


def raises(fn, msg):
    try:
        fn()
        ok(False, msg + "  (no ProtokollError raised)")
    except P.ProtokollError:
        ok(True, msg)


print("\n[1] A fresh draft is never an empty page (the landlord stands in a cold flat)")
p = P.neues_protokoll("einzug", date(2026, 8, 1))
namen = [r["name"] for r in p["raeume"]]
ok(namen == ["Flur", "Wohnzimmer", "Schlafzimmer", "Küche", "Bad"], f"5 rooms pre-filled — {namen}")
kueche = [r for r in p["raeume"] if r["name"] == "Küche"][0]
was = [e["was"] for e in kueche["elemente"]]
ok("Wände" in was and "Boden" in was and "Fenster" in was, "every room carries the standard elements")
ok("Herd" in was and "Spüle" in was, f"the kitchen also carries its own — {was[-4:]}")
bad = [r for r in p["raeume"] if r["name"] == "Bad"][0]
ok("Dusche" in [e["was"] for e in bad["elemente"]], "the bathroom too (WC/Dusche/Badewanne/Waschbecken)")
ok(all(e["zustand"] == "gut" for e in kueche["elemente"]), "everything starts at 'gut' — the landlord only marks what differs")
ok([s["typ"] for s in p["schluessel"]] == ["Haustür", "Wohnungstür", "Briefkasten", "Keller"], "keys pre-filled")
ok(p["status"] == "entwurf", "a new protocol is a draft")
raises(lambda: P.neues_protokoll("umzug"), "an unknown art is rejected")

print("\n[2] Validation — a wrong condition would silently ruin the document")
good = [{"name": "Küche", "elemente": [{"was": "Boden", "zustand": "beschaedigt", "notiz": "Kratzer"}]}]
n = P.normalize_raeume(good)
ok(n[0]["elemente"][0]["zustand"] == "beschaedigt", "a valid condition passes")
raises(lambda: P.normalize_raeume([{"name": "Küche", "elemente": [{"was": "Boden", "zustand": "kaputt"}]}]),
       "an unknown condition is rejected ('kaputt')")
raises(lambda: P.normalize_raeume([{"name": "  ", "elemente": []}]), "a room without a name is rejected")
raises(lambda: P.normalize_raeume("Küche"), "raeume must be a list")
ok(P.normalize_schluessel([{"typ": "Haustür", "anzahl": "2"}])[0]["anzahl"] == 2, "key count is coerced to int")
raises(lambda: P.normalize_schluessel([{"typ": "Haustür", "anzahl": -1}]), "a negative key count is rejected")

print("\n[3] Mängel are DERIVED — the list the landlord needs for the deposit")
raeume = [
    {"name": "Küche", "elemente": [{"was": "Boden", "zustand": "beschaedigt", "notiz": "Brandfleck"},
                                   {"was": "Wände", "zustand": "gut", "notiz": ""}]},
    {"name": "Bad", "elemente": [{"was": "Dusche", "zustand": "beschaedigt", "notiz": "Silikon schwarz"}]},
]
m = P.maengel(raeume)
ok(len(m) == 2, f"2 defects found — {len(m)}")
ok(m[0] == {"raum": "Küche", "was": "Boden", "notiz": "Brandfleck"}, f"with room + item + note — {m[0]}")
ok(P.maengel([{"name": "Flur", "elemente": [{"was": "Boden", "zustand": "gut"}]}]) == [],
   "a flat in order produces an empty defect list")

print("\n[4] THE RULE: a signed protocol is immutable")
ok(not P.is_locked("entwurf"), "a draft is editable")
ok(P.is_locked("abgeschlossen"), "a completed protocol is locked")
P.require_editable("entwurf")
ok(True, "editing a draft is allowed")
raises(lambda: P.require_editable("abgeschlossen"), "editing a COMPLETED protocol is refused")
try:
    P.require_editable("abgeschlossen")
except P.ProtokollError as e:
    ok("Nachtrag" in str(e), "…and the message tells the landlord what to do instead (Nachtrag)")

print("\n[5] Signatures — both, and they must be real drawings")
SIG = "data:image/png;base64," + ("A" * 200)
ok(not P.can_abschliessen(SIG, None), "one signature is not enough")
ok(not P.can_abschliessen(SIG, "data:image/png;base64,AA"), "an empty canvas is not a signature")
ok(not P.can_abschliessen(SIG, "ich stimme zu"), "typing a name is not a signature")
ok(P.can_abschliessen(SIG, SIG), "two real signatures → the protocol may be completed")
raises(lambda: P.require_signatures(SIG, None), "completing without both signatures is refused")

print("\n[6] Zählerstände — units and validation")
ok(P.zaehler_einheit("strom") == "kWh", "Strom is measured in kWh")
ok(P.zaehler_einheit("wasser") == "m³", "Wasser in m³")
raises(lambda: P.zaehler_einheit("solar"), "an unknown meter type is rejected")
ok(P.validate_stand("strom", "1234.5") == 1234.5, "a numeric string is accepted")
raises(lambda: P.validate_stand("strom", -5), "a negative reading is rejected")
raises(lambda: P.validate_stand("strom", "abc"), "a non-number is rejected")

print("\n[7] Consumption — and the honesty rule (a meter change is NOT negative consumption)")
r = [
    {"id": 1, "datum": date(2026, 1, 1), "stand": 1000.0, "zaehler_nr": "A1"},
    {"id": 2, "datum": date(2026, 7, 1), "stand": 1600.0, "zaehler_nr": "A1"},
]
v = P.verbrauch(r)
ok(v[0]["verbrauch"] is None, "the first reading has no consumption (nothing to compare to)")
ok(v[1]["verbrauch"] == 600.0, f"600 kWh between the two readings — {v[1]['verbrauch']}")

r2 = r + [{"id": 3, "datum": date(2026, 8, 1), "stand": 5.0, "zaehler_nr": "B7"}]     # new meter
v2 = P.verbrauch(r2)
ok(v2[2]["verbrauch"] is None and "Zählerwechsel" in (v2[2]["hinweis"] or ""),
   f"a meter change reports itself instead of inventing a number — {v2[2]['hinweis']}")

r3 = r + [{"id": 4, "datum": date(2026, 8, 1), "stand": 900.0, "zaehler_nr": "A1"}]   # lower!
v3 = P.verbrauch(r3)
ok(v3[2]["verbrauch"] is None and "niedriger" in (v3[2]["hinweis"] or ""),
   "a reading lower than the previous one is flagged, not turned into negative consumption")

print("\n[8] Period consumption — the number Sprint 2 (Nebenkostenabrechnung) will ask for")
year = [
    {"datum": date(2025, 12, 31), "stand": 1000.0, "zaehler_nr": "A1"},
    {"datum": date(2026, 6, 30), "stand": 1450.0, "zaehler_nr": "A1"},
    {"datum": date(2026, 12, 31), "stand": 2000.0, "zaehler_nr": "A1"},
]
ok(P.verbrauch_zeitraum(year, date(2026, 1, 1), date(2026, 12, 31)) == 1000.0,
   "2026 consumption = 2000 − 1000 = 1000")
ok(P.verbrauch_zeitraum(year, date(2026, 1, 1), date(2027, 12, 31)) is None,
   "no reading at the end of the period → None (not a guess)")
ok(P.verbrauch_zeitraum([{"datum": date(2025, 12, 31), "stand": 1000.0, "zaehler_nr": "A1"},
                         {"datum": date(2026, 12, 31), "stand": 900.0, "zaehler_nr": "A1"}],
                        date(2026, 1, 1), date(2026, 12, 31)) is None,
   "an impossible (falling) reading yields None, never a negative bill")

print("\n[9] ARCHITECTURE: the rules are free of persistence")
import inspect as _i

import autotax.immo_protokoll as _m
src = _i.getsource(_m)
ok("sqlalchemy" not in src.lower(), "no sqlalchemy")
ok("SessionLocal" not in src, "no DB session")
ok("from autotax.models" not in src, "no ORM models")

print(f"\n=== ÜBERGABEPROTOKOLL RULES: {PASS} passed, {FAIL} failed ===")
sys.exit(1 if FAIL else 0)
