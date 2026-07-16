"""Zählerstände-Matrix — bulk entry endpoint + it feeds Nebenkosten. Real API on SQLite.

Run:  PYTHONIOENCODING=utf-8 PYTHONPATH=. python tests/test_immo_zaehler_matrix.py
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

from autotax.models import Base, ImmoProperty, ImmoUnit, ImmoTenancy, UserCompany  # noqa: E402
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
def eq(m, g, w, tol=0.02): ok(abs((g or 0) - w) <= tol, f"{m} (got {g}, want {w})")

e = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
Base.metadata.create_all(bind=e)
S = sessionmaker(bind=e)
immo_api.SessionLocal = S
db = S()
db.add(UserCompany(id=1, user_id=1, company_name="T", address="A", iban="DE02120300000000202051", is_default=True))
db.add(ImmoProperty(id=10, user_id=1, name="Haus", adresse="Wiesenstr. 10"))
db.add(ImmoUnit(id=1, property_id=10, user_id=1, name="Whg 1", wohnflaeche=50))
db.add(ImmoUnit(id=2, property_id=10, user_id=1, name="Whg 2", wohnflaeche=50))
db.add(ImmoTenancy(id=101, unit_id=1, user_id=1, mieter_name="A", von=date(2026, 1, 1), kaltmiete=400, nk_voraus=70))
db.add(ImmoTenancy(id=102, unit_id=2, user_id=1, mieter_name="B", von=date(2026, 1, 1), kaltmiete=400, nk_voraus=70))
db.commit(); db.close()

app = FastAPI(); app.include_router(immo_api.router)
app.dependency_overrides[get_current_user] = lambda: {"sub": "1", "email": "o@test.de"}
cl = TestClient(app)

print("\n[1] Empty matrix — every unit × meter present, values null")
m = cl.get("/immo/properties/10/zaehler-matrix?jahr=2026").json()
ok(len(m["units"]) == 2, "2 units returned")
ok(set(m["arten"]) == {"wasser", "warmwasser", "heizung", "gas"}, "4 meter types")
ok(m["units"][0]["arts"]["heizung"]["anfang"] is None, "no readings yet")

print("\n[2] Bulk save — Anfang/Ende per unit for heizung")
r = cl.post("/immo/properties/10/zaehler-bulk", json={"jahr": 2026, "entries": [
    {"unit_id": 1, "art": "heizung", "zaehler_nr": "HZ-1", "anfang": 0, "ende": 70},
    {"unit_id": 2, "art": "heizung", "zaehler_nr": "HZ-2", "anfang": 0, "ende": 30},
]}).json()
ok(r["success"] and r["saved"] == 4, f"saved 4 readings (2 units × Anfang+Ende) — {r['saved']}")
ok(not r["warnings"], "no warnings")

print("\n[3] Matrix reloads with the saved values + meter no.")
m2 = cl.get("/immo/properties/10/zaehler-matrix?jahr=2026").json()
u1 = [u for u in m2["units"] if u["unit_id"] == 1][0]
eq("Whg1 heizung Anfang", u1["arts"]["heizung"]["anfang"], 0.0)
eq("Whg1 heizung Ende", u1["arts"]["heizung"]["ende"], 70.0)
ok(u1["arts"]["heizung"]["zaehler_nr"] == "HZ-1", "meter number saved")

print("\n[4] THE POINT — Nebenkosten now computes Verbrauch/HeizkostenV from the matrix data")
aid = cl.post("/immo/nk", json={"property_id": 10, "jahr": 2026}).json()["id"]
res = cl.post(f"/immo/nk/{aid}/position", json={"kategorie": "heizkosten", "betrag": 1000,
              "schluessel": "verbrauch", "verbrauch_art": "heizung", "grund_prozent": 30}).json()
sh = {t["name"]: t["umlage"] for t in res["ergebnis"]["tenants"]}
eq("A = 640 (Grund 150 + Verbrauch 490)", sh.get("A"), 640.0)
eq("B = 360", sh.get("B"), 360.0)
ok(not res["ergebnis"]["hinweise"], f"no fallback — used the matrix readings ({res['ergebnis']['hinweise']})")

print("\n[5] Re-save updates in place (no duplicate rows) + Ende<Anfang is flagged")
r2 = cl.post("/immo/properties/10/zaehler-bulk", json={"jahr": 2026, "entries": [
    {"unit_id": 1, "art": "heizung", "anfang": 100, "ende": 50},   # Ende < Anfang
]}).json()
ok(len(r2["warnings"]) == 1, f"Ende<Anfang flagged — {r2['warnings']}")
m3 = cl.get("/immo/properties/10/zaehler-matrix?jahr=2026").json()
u1b = [u for u in m3["units"] if u["unit_id"] == 1][0]
eq("update in place: Anfang now 100", u1b["arts"]["heizung"]["anfang"], 100.0)
# still only one Anfang reading at von (no duplicates)
from autotax.models import ImmoZaehlerstand  # noqa: E402
dbx = S(); cnt = dbx.query(ImmoZaehlerstand).filter(ImmoZaehlerstand.unit_id == 1, ImmoZaehlerstand.art == "heizung", ImmoZaehlerstand.datum == date(2026, 1, 1)).count(); dbx.close()
ok(cnt == 1, f"no duplicate Anfang row after re-save — {cnt}")

print(f"\n================  {PASS} passed, {FAIL} failed  ================")
sys.exit(1 if FAIL else 0)
