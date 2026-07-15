"""NEBENKOSTENABRECHNUNG — endpoints + PDF (Sprint 2, commit 2).

Walks the real path a landlord walks:
  create → add cost lines → see the live result → finalise (freeze snapshot + lock) → PDF
and proves the binding principles:
  A. after finalise the numbers come from the FROZEN snapshot, not from live master data — change a
     tenant's rent afterwards and the finalised statement does NOT move.
  B. a finalised statement refuses every write (409); only Entsperren re-opens it.
  C. the Vorauszahlung on the statement == what the Mietkonto charged (monat_nk_soll).

Run:  PYTHONIOENCODING=utf-8 PYTHONPATH=. python tests/test_immo_nk_api.py
"""
import os
import sys
from datetime import date, datetime

os.environ.setdefault("JWT_SECRET", "x" * 44)

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi import FastAPI
from fastapi.testclient import TestClient

from autotax.models import Base, ImmoProperty, ImmoUnit, ImmoTenancy, UserCompany, NkAbrechnung
from autotax import immo_api
from autotax.auth import get_current_user

TODAY = date(2027, 2, 1)      # after the 2026 period → statements can be finalised in time


class _FakeDate(date):
    @classmethod
    def today(cls):
        return TODAY


class _FakeDT(datetime):
    @classmethod
    def now(cls, tz=None):
        return datetime(2027, 2, 1, tzinfo=tz)


immo_api.date = _FakeDate
immo_api.datetime = _FakeDT

PASS = FAIL = 0


def ok(c, m):
    global PASS, FAIL
    if c:
        PASS += 1
        print(f"  PASS  {m}")
    else:
        FAIL += 1
        print(f"  FAIL  {m}")


def main():
    e = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=e)
    S = sessionmaker(bind=e)
    db = S()
    db.add(UserCompany(id=1, user_id=1, company_name="Hancer Immobilien",
                       address="Wiesenstr. 10\n66115 Saarbrücken", iban="DE02120300000000202051", is_default=True))
    db.add(ImmoProperty(id=10, user_id=1, name="Haus", adresse="Musterstr. 12, 10115 Berlin"))
    for i in (1, 2, 3, 4):
        db.add(ImmoUnit(id=i, property_id=10, user_id=1, name=f"W{i}", wohnflaeche=50))
    db.add(ImmoTenancy(id=101, unit_id=1, user_id=1, mieter_name="Ahmet", von=date(2026, 1, 1), kaltmiete=400, nk_voraus=70))
    db.add(ImmoTenancy(id=102, unit_id=2, user_id=1, mieter_name="Mehmet", von=date(2026, 1, 1), bis=date(2026, 9, 30), kaltmiete=400, nk_voraus=70))
    db.add(ImmoTenancy(id=103, unit_id=3, user_id=1, mieter_name="Ali", von=date(2026, 6, 1), kaltmiete=400, nk_voraus=70))
    # unit 4 stays vacant → landlord bucket
    db.commit()
    db.close()

    immo_api.SessionLocal = S
    app = FastAPI()
    app.include_router(immo_api.router)
    app.dependency_overrides[get_current_user] = lambda: {"sub": "1", "email": "o@test.de"}
    cl = TestClient(app)

    print("\n[1] Create a statement — period defaults to the year")
    r = cl.post("/immo/nk", json={"property_id": 10, "jahr": 2026})
    ok(r.status_code == 200, f"created ({r.status_code})")
    a = r.json()
    aid = a["id"]
    ok(a["status"] == "entwurf" and not a["final"], "starts as a draft")
    ok(a["zeitraum_von"] == "2026-01-01" and a["zeitraum_bis"] == "2026-12-31", "period = the full year")

    print("\n[2] Add cost lines — BetrKV umlagefähig defaults apply automatically")
    cl.post(f"/immo/nk/{aid}/position", json={"kategorie": "grundsteuer", "betrag": 1200})
    cl.post(f"/immo/nk/{aid}/position", json={"kategorie": "muell", "betrag": 600, "schluessel": "wohnflaeche"})
    r = cl.post(f"/immo/nk/{aid}/position", json={"kategorie": "reparatur", "betrag": 5000})   # NOT umlagefähig
    d = r.json()
    rep = [p for p in d["positionen"] if p["kategorie"] == "reparatur"][0]
    ok(rep["umlagefaehig"] is False, "Reparatur is defaulted NOT umlagefähig — the landlord is protected")
    ok(d["ergebnis"]["umlagefaehige_summe"] == 1800.0, f"the repair is NOT in the total (1800) — {d['ergebnis']['umlagefaehige_summe']}")

    print("\n[3] Live result — the invariant holds and the vacancy is the landlord's")
    erg = d["ergebnis"]
    tot = round(sum(t["umlage"] for t in erg["tenants"]) + erg["leerstand"], 2)
    ok(tot == 1800.0, f"Σ tenant shares + Leerstand == 1800 (invariant) — {tot}")
    ok(erg["leerstand"] > 0, f"the vacant unit 4 is carried by the landlord — {erg['leerstand']}")

    print("\n[4] Principle C — Vorauszahlung == what the Mietkonto charged (monat_nk_soll)")
    ahmet = [t for t in erg["tenants"] if t["tenancy_id"] == 101][0]
    ok(ahmet["vorauszahlung"] == 840.0, f"Ahmet advance 840 = 12 × 70 (from the Mietkonto) — {ahmet['vorauszahlung']}")
    mehmet = [t for t in erg["tenants"] if t["tenancy_id"] == 102][0]
    ok(mehmet["vorauszahlung"] == 630.0, f"Mehmet advance 630 = 9 × 70 — {mehmet['vorauszahlung']}")

    print("\n[5] A draft PDF works (overview + per tenant)")
    r = cl.get(f"/immo/nk/{aid}/pdf")
    ok(r.status_code == 200 and r.content[:4] == b"%PDF" and len(r.content) > 2000, f"overview PDF ({len(r.content)} B)")
    r = cl.get(f"/immo/nk/{aid}/pdf?tenancy_id=101")
    ok(r.status_code == 200 and r.content[:4] == b"%PDF", "per-tenant PDF")

    print("\n[6] Finalise — freeze the snapshot + lock (Principle A + B)")
    r = cl.post(f"/immo/nk/{aid}/finalisieren")
    ok(r.status_code == 200 and r.json()["final"] is True, "finalised")
    ok(r.json()["ergebnis"].get("umlagefaehige_summe") == 1800.0, "the result is served from the snapshot")
    # the snapshot carries the frozen calculation
    db2 = S()
    snap_raw = db2.query(NkAbrechnung).get(aid).ergebnis_snapshot
    db2.close()
    import json
    snap = json.loads(snap_raw)
    ok(snap["calculation_version"] == 1 and snap["umlagefaehige_summe"] == 1800.0, "snapshot frozen with version")
    ok(len(snap["tenants"]) == 3 and all("zeitanteil" in t for t in snap["tenants"]), "snapshot has each tenant's Zeitanteil")

    print("\n[7] THE RULE: a finalised statement refuses every write (409)")
    ok(cl.post(f"/immo/nk/{aid}/position", json={"kategorie": "wasser", "betrag": 100}).status_code == 409, "cannot add a cost line")
    pid = d["positionen"][0]["id"]
    ok(cl.patch(f"/immo/nk/{aid}/position/{pid}", json={"betrag": 1}).status_code == 409, "cannot edit a cost line")
    ok(cl.delete(f"/immo/nk/{aid}/position/{pid}").status_code == 409, "cannot delete a cost line")
    ok(cl.patch(f"/immo/nk/{aid}", json={"notiz": "x"}).status_code == 409, "cannot edit the period")
    ok(cl.delete(f"/immo/nk/{aid}").status_code == 409, "cannot delete a finalised statement")

    print("\n[8] Principle A — the snapshot is immutable even when master data changes afterwards")
    db3 = S()
    t = db3.query(ImmoTenancy).get(101)
    t.nk_voraus = 999          # change Ahmet's advance AFTER finalising
    db3.commit(); db3.close()
    r = cl.get(f"/immo/nk/{aid}")
    ah = [t for t in r.json()["ergebnis"]["tenants"] if t["tenancy_id"] == 101][0]
    ok(ah["vorauszahlung"] == 840.0, f"the finalised statement STILL shows 840, not the changed 999×12 — {ah['vorauszahlung']}")
    ok(r.json()["aus_snapshot"] is True, "it is served from the snapshot, not recomputed")

    print("\n[9] Finalised PDF also comes from the snapshot")
    r = cl.get(f"/immo/nk/{aid}/pdf?tenancy_id=101")
    ok(r.status_code == 200 and r.content[:4] == b"%PDF", "finalised per-tenant PDF from snapshot")

    print("\n[10] Entsperren — the only way to correct (Principle B)")
    r = cl.post(f"/immo/nk/{aid}/entsperren")
    ok(r.status_code == 200 and r.json()["status"] == "entwurf", "unlock reverts to draft")
    ok(cl.post(f"/immo/nk/{aid}/position", json={"kategorie": "wasser", "betrag": 100}).status_code == 200, "…and now it is editable again")
    # after unlock the result recomputes live (and now reflects the changed 999 advance)
    r = cl.get(f"/immo/nk/{aid}")
    ah = [t for t in r.json()["ergebnis"]["tenants"] if t["tenancy_id"] == 101][0]
    ok(ah["vorauszahlung"] == 999 * 12, f"after unlock it recomputes live (999×12) — {ah['vorauszahlung']}")

    print("\n[C4] Personenzahl is collectable now (Sprint 2 data-ready), computed in Sprint 3")
    r = cl.patch("/immo/tenancies/101", json={"personenzahl": 3})
    ok(r.status_code == 200, "the tenant edit accepts personenzahl")
    card = cl.get("/immo/mieter").json()["mieter"]
    ah = [m for m in card if m["tenancy_id"] == 101][0]
    ok(ah["personenzahl"] == 3, f"…and it is returned on the card ({ah.get('personenzahl')})")
    # a personenzahl position is accepted, stored, and falls back to Wohnfläche WITH a note (not computed yet)
    r = cl.post("/immo/nk", json={"property_id": 10, "jahr": 2024})
    a2 = r.json()["id"]
    d = cl.post(f"/immo/nk/{a2}/position", json={"kategorie": "wasser", "betrag": 400, "schluessel": "personenzahl"}).json()
    pos = d["positionen"][0]
    ok(pos["schluessel"] == "personenzahl", "the personenzahl key is stored on the position")
    ok(any("Wohnfläche" in h for h in d["ergebnis"]["hinweise"]),
       f"…and the result notes it falls back to Wohnfläche until Sprint 3 — {d['ergebnis']['hinweise']}")

    print("\n[11] Cannot finalise an empty statement")
    r = cl.post("/immo/nk", json={"property_id": 10, "jahr": 2025})
    empty = r.json()["id"]
    ok(cl.post(f"/immo/nk/{empty}/finalisieren").status_code == 400, "no cost lines → nothing to settle")

    print(f"\n=== NEBENKOSTEN API: {PASS} passed, {FAIL} failed ===")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
