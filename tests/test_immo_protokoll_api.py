"""ÜBERGABEPROTOKOLL — endpoints + PDF (Sprint 1, commit 2).

Walks the exact path a landlord walks in the flat:
  create → fill the rooms → read the meters → count the keys → both sign → abschliessen → PDF
and then proves the rule that makes the document worth anything:

    A COMPLETED PROTOCOL CANNOT BE CHANGED — not the rooms, not the meters, not the photos,
    and it cannot be deleted. A correction is a new protocol (Nachtrag).

Run:  PYTHONIOENCODING=utf-8 PYTHONPATH=. python tests/test_immo_protokoll_api.py
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

from autotax.models import Base, ImmoProperty, ImmoUnit, ImmoTenancy, UserCompany
from autotax import immo_api
from autotax.auth import get_current_user

TODAY = date(2026, 8, 1)
SIG = "data:image/png;base64," + (
    # a tiny but REAL 1x1 png, long enough to pass the "not an empty canvas" guard
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
    + "A" * 120)


class _FakeDate(date):
    @classmethod
    def today(cls):
        return TODAY


class _FakeDT(datetime):
    @classmethod
    def now(cls, tz=None):
        return datetime(2026, 8, 1, tzinfo=tz)


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
                       address="Wiesenstr. 10\n66115 Saarbrücken", is_default=True))
    db.add(ImmoProperty(id=10, user_id=1, name="Haus", adresse="Musterstr. 12, 10115 Berlin"))
    db.add(ImmoUnit(id=1, property_id=10, user_id=1, name="EG links", wohnflaeche=57))
    db.add(ImmoTenancy(id=101, unit_id=1, user_id=1, mieter_name="Ahmet Yilmaz",
                       von=date(2026, 8, 1), kaltmiete=400, nk_voraus=70))
    db.commit()
    db.close()

    immo_api.SessionLocal = S
    app = FastAPI()
    app.include_router(immo_api.router)
    app.dependency_overrides[get_current_user] = lambda: {"sub": "1", "email": "o@test.de"}
    cl = TestClient(app)

    print("\n[1] A new Einzug protocol is never an empty page")
    r = cl.post("/immo/protokolle", json={"tenancy_id": 101, "art": "einzug"})
    ok(r.status_code == 200, f"created (got {r.status_code})")
    p = r.json()
    pid = p["id"]
    ok(p["status"] == "entwurf" and not p["gesperrt"], "it starts as an editable draft")
    ok(p["datum"] == "2026-08-01", f"the date defaults to the move-in date — {p['datum']}")
    ok([x["name"] for x in p["raeume"]] == ["Flur", "Wohnzimmer", "Schlafzimmer", "Küche", "Bad"],
       "5 rooms pre-filled")
    ok(p["personen"]["mieter"] == "Ahmet Yilmaz", "the tenant's name is already there")
    ok(len(p["schluessel"]) == 4, "the key list is pre-filled")
    ok(p["property_adresse"].startswith("Musterstr."), "the flat is identified")

    print("\n[2] The landlord walks through the flat")
    raeume = p["raeume"]
    kueche = [x for x in raeume if x["name"] == "Küche"][0]
    for el in kueche["elemente"]:
        if el["was"] == "Boden":
            el["zustand"] = "beschaedigt"
            el["notiz"] = "Brandfleck vor dem Herd, ca. 5 cm"
    r = cl.patch(f"/immo/protokolle/{pid}", json={"raeume": raeume})
    ok(r.status_code == 200, "the rooms are saved")
    d = r.json()
    ok(d["maengel"] == [{"raum": "Küche", "was": "Boden", "notiz": "Brandfleck vor dem Herd, ca. 5 cm"}],
       f"the defect list is derived automatically — {d['maengel']}")

    r = cl.patch(f"/immo/protokolle/{pid}", json={"raeume": [
        {"name": "Küche", "elemente": [{"was": "Boden", "zustand": "kaputt"}]}]})
    ok(r.status_code == 400, f"an invalid condition is refused (got {r.status_code})")

    print("\n[3] Meters — the readings live in their own series (Sprint 2 will need them)")
    r = cl.post("/immo/zaehler", json={"unit_id": 1, "art": "strom", "stand": 12345.5,
                                       "zaehler_nr": "1ESY-A1", "datum": "2026-08-01",
                                       "protokoll_id": pid})
    ok(r.status_code == 200 and r.json()["einheit"] == "kWh", f"Strom reading saved in kWh — {r.json().get('einheit')}")
    cl.post("/immo/zaehler", json={"unit_id": 1, "art": "wasser", "stand": 210.0,
                                   "zaehler_nr": "W-77", "datum": "2026-08-01", "protokoll_id": pid})
    r = cl.post("/immo/zaehler", json={"unit_id": 1, "art": "solar", "stand": 5})
    ok(r.status_code == 400, "an unknown meter type is refused")
    r = cl.post("/immo/zaehler", json={"unit_id": 1, "art": "strom", "stand": -5})
    ok(r.status_code == 400, "a negative reading is refused")

    d = cl.get(f"/immo/protokolle/{pid}").json()
    ok(len(d["zaehler"]) == 2, f"both readings hang on the protocol — {len(d['zaehler'])}")

    print("\n[4] Keys")
    r = cl.patch(f"/immo/protokolle/{pid}", json={"schluessel": [
        {"typ": "Haustür", "anzahl": 2}, {"typ": "Wohnungstür", "anzahl": 3}]})
    ok(r.status_code == 200 and r.json()["schluessel"][1]["anzahl"] == 3, "key counts saved")

    print("\n[5] Signatures — both are required")
    r = cl.post(f"/immo/protokolle/{pid}/abschliessen")
    ok(r.status_code == 400, f"cannot complete without signatures (got {r.status_code})")
    r = cl.post(f"/immo/protokolle/{pid}/unterschrift", json={"rolle": "mieter", "png": "ich stimme zu"})
    ok(r.status_code == 400, "a typed name is not a signature")
    cl.post(f"/immo/protokolle/{pid}/unterschrift", json={"rolle": "vermieter", "png": SIG})
    r = cl.post(f"/immo/protokolle/{pid}/abschliessen")
    ok(r.status_code == 400, "one signature is still not enough")
    cl.post(f"/immo/protokolle/{pid}/unterschrift", json={"rolle": "mieter", "png": SIG})
    r = cl.post(f"/immo/protokolle/{pid}/abschliessen")
    ok(r.status_code == 200, f"both signatures → completed (got {r.status_code})")
    d = r.json()
    ok(d["status"] == "abgeschlossen" and d["gesperrt"] is True, "the protocol is now a locked document")
    ok(d["abgeschlossen_am"] is not None, "the lock is timestamped")

    print("\n[6] THE RULE: a completed protocol is immutable")
    r = cl.patch(f"/immo/protokolle/{pid}", json={"notiz": "doch nicht"})
    ok(r.status_code == 409, f"editing is refused with 409 (got {r.status_code})")
    ok("Nachtrag" in r.json().get("detail", ""), "…and the message says what to do instead")
    r = cl.post(f"/immo/protokolle/{pid}/unterschrift", json={"rolle": "mieter", "png": SIG})
    ok(r.status_code == 409, "re-signing is refused")
    r = cl.post("/immo/zaehler", json={"unit_id": 1, "art": "gas", "stand": 1, "protokoll_id": pid})
    ok(r.status_code == 409, "adding a meter reading to it is refused")
    r = cl.delete(f"/immo/protokolle/{pid}")
    ok(r.status_code == 409, "and it cannot be deleted — a handover is evidence")
    r = cl.post(f"/immo/protokolle/{pid}/foto", files={"file": ("x.jpg", b"\xff\xd8\xff", "image/jpeg")},
                data={"raum": "Küche"})
    ok(r.status_code == 409, "no photo can be slipped in afterwards")

    print("\n[7] The PDF — the artefact that replaces the Word template")
    r = cl.get(f"/immo/protokolle/{pid}/pdf")
    ok(r.status_code == 200 and r.headers["content-type"] == "application/pdf", "a PDF comes back")
    ok(r.content[:4] == b"%PDF" and len(r.content) > 2000, f"a real PDF ({len(r.content)} bytes)")

    print("\n[8] A draft CAN still be corrected and deleted")
    r = cl.post("/immo/protokolle", json={"tenancy_id": 101, "art": "auszug"})
    pid2 = r.json()["id"]
    ok(r.json()["art"] == "auszug", "an Auszug protocol can be created too")
    ok(cl.patch(f"/immo/protokolle/{pid2}", json={"notiz": "Nachtrag"}).status_code == 200,
       "a draft is editable")
    ok(cl.delete(f"/immo/protokolle/{pid2}").status_code == 200, "a draft can be deleted")

    print("\n[9] Meter history + consumption (Masterplan #7)")
    cl.post("/immo/zaehler", json={"unit_id": 1, "art": "strom", "stand": 13000.0,
                                   "zaehler_nr": "1ESY-A1", "datum": "2027-01-31"})
    z = cl.get("/immo/units/1/zaehler").json()["zaehler"]
    strom = z["strom"]
    ok(strom["einheit"] == "kWh" and len(strom["messungen"]) == 2, "the Strom series has 2 readings")
    ok(abs(strom["messungen"][1]["verbrauch"] - 654.5) < 0.01,
       f"consumption = 13000 − 12345,5 = 654,5 kWh — {strom['messungen'][1]['verbrauch']}")
    ok(strom["letzter_stand"] == 13000.0, "the latest reading is reported")
    ok(z["gas"]["messungen"] == [], "a meter without readings is simply empty, not an error")

    print("\n[10] Photos — a phone photo is downscaled, and it lands in the PDF")
    from io import BytesIO

    from PIL import Image
    big = Image.new("RGB", (4032, 3024), (120, 140, 160))      # a typical phone photo
    buf = BytesIO()
    big.save(buf, format="JPEG", quality=95)
    raw = buf.getvalue()

    r = cl.post("/immo/protokolle", json={"tenancy_id": 101, "art": "einzug"})
    pid3 = r.json()["id"]
    r = cl.post(f"/immo/protokolle/{pid3}/foto",
                files={"file": ("kueche.jpg", raw, "image/jpeg")}, data={"raum": "Küche"})
    ok(r.status_code == 200, f"the photo is accepted (got {r.status_code})")
    j = r.json()
    ok(j["bytes_gespeichert"] < j["bytes_original"] / 3,
       f"it is downscaled: {j['bytes_original']//1024} KB → {j['bytes_gespeichert']//1024} KB")
    ok(j["raum"] == "Küche", "it remembers which room it belongs to")

    d = cl.get(f"/immo/protokolle/{pid3}").json()
    ok(len(d["fotos"]) == 1 and d["fotos"][0]["raum"] == "Küche", "the photo hangs on the protocol")

    r = cl.get(f"/immo/protokolle/{pid3}/pdf")
    ok(r.status_code == 200 and r.content[:4] == b"%PDF" and len(r.content) > 8000,
       f"the photo is embedded in the PDF ({len(r.content)} bytes)")

    r = cl.delete(f"/immo/protokolle/{pid3}/foto/{j['id']}")
    ok(r.status_code == 200 and cl.get(f"/immo/protokolle/{pid3}").json()["fotos"] == [],
       "a photo can be removed while the protocol is still a draft")

    print(f"\n=== PROTOKOLL API: {PASS} passed, {FAIL} failed ===")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
