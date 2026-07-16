"""Sprint 4 END-TO-END — the real user path through the API (create → readings → NK → finalize → PDF).
Uses a live FastAPI TestClient on SQLite, exactly the calls the browser makes.

Run:  PYTHONIOENCODING=utf-8 PYTHONPATH=. python tests/test_immo_nk_verbrauch_e2e.py
"""
import os
import sys
from datetime import date, datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("JWT_SECRET", "x" * 44)

from sqlalchemy import create_engine                       # noqa: E402
from sqlalchemy.orm import sessionmaker                     # noqa: E402
from sqlalchemy.pool import StaticPool                      # noqa: E402
from fastapi import FastAPI                                 # noqa: E402
from fastapi.testclient import TestClient                   # noqa: E402
import json as _json                                        # noqa: E402

from autotax.models import (Base, ImmoProperty, ImmoUnit, ImmoTenancy, UserCompany,  # noqa: E402
                            NkAbrechnung, ImmoZaehlerstand)
from autotax import immo_api                                # noqa: E402
from autotax.auth import get_current_user                   # noqa: E402

TODAY = date(2027, 2, 1)
class _FD(date):
    @classmethod
    def today(cls): return TODAY
class _FDT(datetime):
    @classmethod
    def now(cls, tz=None): return datetime(2027, 2, 1, tzinfo=tz)
immo_api.date = _FD
immo_api.datetime = _FDT

PASS = FAIL = 0
def ok(c, m):
    global PASS, FAIL
    if c: PASS += 1; print(f"  PASS  {m}")
    else: FAIL += 1; print(f"  FAIL  {m}")
def eq(m, got, want, tol=0.02):
    ok(abs((got or 0) - want) <= tol, f"{m} (got {got}, want {want})")

e = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
Base.metadata.create_all(bind=e)
S = sessionmaker(bind=e)
immo_api.SessionLocal = S
db = S()
db.add(UserCompany(id=1, user_id=1, company_name="Test", address="Wiesenstr. 10\n66115 SB", iban="DE02120300000000202051", is_default=True))
db.commit(); db.close()

app = FastAPI(); app.include_router(immo_api.router)
app.dependency_overrides[get_current_user] = lambda: {"sub": "1", "email": "o@test.de"}
cl = TestClient(app)

_pid = [100]
def make_building(units, tenants):
    """units=[(unit_id,m²)], tenants=[(tid,unit_id,name,von,bis)] → creates a property. Returns pid."""
    _pid[0] += 1; pid = _pid[0]
    db = S()
    db.add(ImmoProperty(id=pid, user_id=1, name=f"Haus{pid}", adresse="Wiesenstr. 10"))
    for uid, wf in units:
        db.add(ImmoUnit(id=uid, property_id=pid, user_id=1, name=f"W{uid}", wohnflaeche=wf))
    def _d(s): return date.fromisoformat(s) if s else None
    for tid, uid, nm, von, bis in tenants:
        db.add(ImmoTenancy(id=tid, unit_id=uid, user_id=1, mieter_name=nm, von=_d(von), bis=_d(bis), kaltmiete=400, nk_voraus=70))
    db.commit(); db.close()
    return pid

def add_reading(uid, art, stand, d):
    r = cl.post("/immo/zaehler", json={"unit_id": uid, "art": art, "stand": stand, "datum": d})
    assert r.status_code == 200, r.text

def run_nk(pid, positions, jahr=2026):
    a = cl.post("/immo/nk", json={"property_id": pid, "jahr": jahr}).json()
    aid = a["id"]
    for body in positions:
        cl.post(f"/immo/nk/{aid}/position", json=body)
    return aid, cl.get(f"/immo/nk/{aid}").json()

def shares(res):
    return {t["name"]: t["umlage"] for t in res["ergebnis"]["tenants"]}


print("\n=== TEST 1 — Kaltwasser by Verbrauch (3 flats, 70 m³, 700 €) ===")
p1 = make_building([(1, 50), (2, 50), (3, 50)],
                   [(11, 1, "A", "2026-01-01", None), (12, 2, "B", "2026-01-01", None), (13, 3, "C", "2026-01-01", None)])
for uid, s0, s1 in [(1, 100, 130), (2, 200, 220), (3, 50, 70)]:
    add_reading(uid, "wasser", s0, "2026-01-01"); add_reading(uid, "wasser", s1, "2026-12-31")
aid1, res1 = run_nk(p1, [{"kategorie": "wasser", "betrag": 700, "schluessel": "verbrauch", "verbrauch_art": "wasser"}])
s1 = shares(res1)
eq("A used 30/70 → 300", s1.get("A"), 300.0)
eq("B used 20/70 → 200", s1.get("B"), 200.0)
eq("C used 20/70 → 200", s1.get("C"), 200.0)
eq("Σ == 700", sum(s1.values()) + res1["ergebnis"]["leerstand"], 700.0)
ok(not res1["ergebnis"]["hinweise"], f"no fallback note — real Verbrauch ({res1['ergebnis']['hinweise']})")

print("\n=== TEST 2 — mid-year move-out with a Zwischenablesung ===")
p2 = make_building([(21, 50)],
                   [(211, 21, "Alt", "2026-01-01", "2026-06-30"), (212, 21, "Neu", "2026-07-01", None)])
add_reading(21, "wasser", 0, "2026-01-01"); add_reading(21, "wasser", 40, "2026-06-30"); add_reading(21, "wasser", 100, "2026-12-31")
aid2, res2 = run_nk(p2, [{"kategorie": "wasser", "betrag": 1000, "schluessel": "verbrauch", "verbrauch_art": "wasser"}])
s2 = shares(res2)
eq("Alt-Mieter used 40 (Jan–Jun) → 400", s2.get("Alt"), 400.0)
eq("Neu-Mieter used 60 (Jul–Dec) → 600", s2.get("Neu"), 600.0)
eq("Σ == 1000", sum(s2.values()), 1000.0)

print("\n=== TEST 3 — HeizkostenV 1000 € = 30% Grund (m²) + 70% Verbrauch ===")
p3 = make_building([(31, 50), (32, 50)],
                   [(311, 31, "A", "2026-01-01", None), (312, 32, "B", "2026-01-01", None)])
add_reading(31, "heizung", 0, "2026-01-01"); add_reading(31, "heizung", 70, "2026-12-31")
add_reading(32, "heizung", 0, "2026-01-01"); add_reading(32, "heizung", 30, "2026-12-31")
aid3, res3 = run_nk(p3, [{"kategorie": "heizkosten", "betrag": 1000, "schluessel": "verbrauch", "verbrauch_art": "heizung", "grund_prozent": 30}])
s3 = shares(res3)
eq("A = 150 Grund + 490 Verbrauch = 640", s3.get("A"), 640.0)
eq("B = 150 Grund + 210 Verbrauch = 360", s3.get("B"), 360.0)
# prove the 300 + 700 split explicitly from the per-tenant position rows
allpos = [pp for t in res3["ergebnis"]["tenants"] for pp in t["positionen"]]
grund_sum = round(sum(pp["anteil_betrag"] for pp in allpos if "Grundkosten" in pp["anteil_text"]), 2)
verb_sum = round(sum(pp["anteil_betrag"] for pp in allpos if pp["anteil_text"].startswith("Verbrauch")), 2)
eq("Grundkosten part == 300 (30%)", grund_sum, 300.0)
eq("Verbrauch part == 700 (70%)", verb_sum, 700.0)
eq("Σ == 1000", sum(s3.values()), 1000.0)

print("\n=== TEST 4 — no readings → Wohnfläche fallback + a visible note ===")
p4 = make_building([(41, 50), (42, 50)],
                   [(411, 41, "A", "2026-01-01", None), (412, 42, "B", "2026-01-01", None)])
aid4, res4 = run_nk(p4, [{"kategorie": "heizkosten", "betrag": 1000, "schluessel": "verbrauch", "verbrauch_art": "heizung"}])
s4 = shares(res4)
eq("fallback to area → 500/500", s4.get("A"), 500.0)
ok(any("Verbrauch" in h for h in res4["ergebnis"]["hinweise"]), f"a visible note explains the fallback — {res4['ergebnis']['hinweise']}")

print("\n=== TEST 5 — snapshot immutability (finalize, change readings, PDF unchanged) ===")
aid5, res5 = run_nk(p3, [{"kategorie": "heizkosten", "betrag": 1000, "schluessel": "verbrauch", "verbrauch_art": "heizung", "grund_prozent": 30}], jahr=2026)
fin = cl.post(f"/immo/nk/{aid5}/finalisieren").json()
ok(fin["final"] is True, "finalised")
before = {t["name"]: t["umlage"] for t in fin["ergebnis"]["tenants"]}
pdf_before = cl.get(f"/immo/nk/{aid5}/pdf")
ok(pdf_before.status_code == 200 and pdf_before.content[:4] == b"%PDF", "PDF generated from snapshot")
# now CHANGE the meter reading after finalising
db = S()
z = db.query(ImmoZaehlerstand).filter(ImmoZaehlerstand.unit_id == 31, ImmoZaehlerstand.stand == 70).first()
z.stand = 9999
db.commit(); db.close()
after = {t["name"]: t["umlage"] for t in cl.get(f"/immo/nk/{aid5}").json()["ergebnis"]["tenants"]}
eq("A share UNCHANGED after meter tampering (640)", after.get("A"), before.get("A"))
ok(cl.get(f"/immo/nk/{aid5}").json()["aus_snapshot"] is True, "served from the frozen snapshot")
snap = _json.loads(S().query(NkAbrechnung).get(aid5).ergebnis_snapshot)
ok(snap["calculation_version"] == 4 and len(snap["readings"]) >= 4, "snapshot froze v4 + the meter readings")

print("\n=== TEST 6 — regression: the other keys still give the same result ===")
p6 = make_building([(61, 40), (62, 60)],
                   [(611, 61, "A", "2026-01-01", None), (612, 62, "B", "2026-01-01", None)])
_, rw = run_nk(p6, [{"kategorie": "grundsteuer", "betrag": 1000, "schluessel": "wohnflaeche"}])
sw = shares(rw); eq("Wohnfläche 40/100 → A 400", sw.get("A"), 400.0); eq("Wohnfläche → B 600", sw.get("B"), 600.0)
_, ru = run_nk(p6, [{"kategorie": "hausmeister", "betrag": 1000, "schluessel": "wohneinheiten"}])
su = shares(ru); eq("Wohneinheiten 1/2 each → A 500", su.get("A"), 500.0)
db = S()
db.query(ImmoTenancy).filter(ImmoTenancy.id == 611).first().personenzahl = 3
db.query(ImmoTenancy).filter(ImmoTenancy.id == 612).first().personenzahl = 1
db.commit(); db.close()
_, rp = run_nk(p6, [{"kategorie": "muell", "betrag": 400, "schluessel": "personenzahl"}])
sp = shares(rp); eq("Personenzahl 3/4 → A 300", sp.get("A"), 300.0); eq("Personenzahl 1/4 → B 100", sp.get("B"), 100.0)
_, ri = run_nk(p6, [{"kategorie": "strom", "betrag": 500, "schluessel": "individuell", "individuell": {"611": 200, "612": 300}}])
si = shares(ri); eq("Individuell exact → A 200", si.get("A"), 200.0); eq("Individuell exact → B 300", si.get("B"), 300.0)

print(f"\n================  {PASS} passed, {FAIL} failed  ================")
sys.exit(1 if FAIL else 0)
