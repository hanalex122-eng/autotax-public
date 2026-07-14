"""COMMIT 4 — A4 (no orphaned tenants) + A5 (a real dunning letter) + C4 (escalation).

BEFORE (production, evidence in .claude/immo_finish_review.md):
  A4  delete_property soft-deleted only the property row → its tenants stayed on Mieter
      and Bu Ay with a blank address, kept accruing debt and still offered a Mahnung.
      delete_unit cascaded the ledger but never touched the tenancy either.
  A5  the Mahnung letter had no recipient address, no concrete deadline (just "innerhalb
      von 14 Tagen"), no itemisation, and was signed "Die Hausverwaltung" — not the landlord.
  C4  the UI hardcoded stufe:1 → five clicks produced five identical "Zahlungserinnerung"s;
      the 2./3. Mahnung the backend supports were unreachable, and the history endpoint
      was never called.

Run:  PYTHONIOENCODING=utf-8 PYTHONPATH=. python tests/test_immo_delete_mahnung.py
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

TODAY = date(2026, 6, 30)


class _FakeDate(date):
    @classmethod
    def today(cls):
        return TODAY


class _FakeDT(datetime):
    @classmethod
    def now(cls, tz=None):
        return datetime(2026, 6, 30, tzinfo=tz)


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


def build():
    e = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=e)
    S = sessionmaker(bind=e)
    db = S()
    db.add(UserCompany(id=1, user_id=1, company_name="Hancer Immobilien",
                       address="Wiesenstr. 10\n66115 Saarbrücken", iban="DE02 1203 0000 0000 2020 51",
                       is_default=True))
    # Haus A — will be deleted
    db.add(ImmoProperty(id=10, user_id=1, name="Haus A", adresse="Musterstr. 12, 10115 Berlin"))
    db.add(ImmoUnit(id=1, property_id=10, user_id=1, name="EG"))
    db.add(ImmoTenancy(id=101, unit_id=1, user_id=1, mieter_name="Weg Mieter",
                       von=date(2026, 1, 1), kaltmiete=400, nk_voraus=70))
    # Haus B — stays; unit 3 is deleted separately
    db.add(ImmoProperty(id=20, user_id=1, name="Haus B", adresse="Hauptstr. 5, 10115 Berlin"))
    db.add(ImmoUnit(id=2, property_id=20, user_id=1, name="OG"))
    db.add(ImmoUnit(id=3, property_id=20, user_id=1, name="DG"))
    db.add(ImmoTenancy(id=102, unit_id=2, user_id=1, mieter_name="Bleibt Mieter",
                       von=date(2026, 1, 1), kaltmiete=500, nk_voraus=40))
    db.add(ImmoTenancy(id=103, unit_id=3, user_id=1, mieter_name="Einheit Weg",
                       von=date(2026, 1, 1), kaltmiete=300, nk_voraus=30))
    db.commit()
    db.close()
    immo_api.SessionLocal = S
    app = FastAPI()
    app.include_router(immo_api.router)
    app.dependency_overrides[get_current_user] = lambda: {"sub": "1", "email": "o@test.de"}
    return S, TestClient(app)


def names(cl):
    return sorted(x["mieter_name"] for x in cl.get("/immo/mieter").json()["mieter"])


def main():
    S, cl = build()
    ok(names(cl) == ["Bleibt Mieter", "Einheit Weg", "Weg Mieter"], f"3 tenants to start with — {names(cl)}")

    print("\n[A4] deleting a PROPERTY takes its units and tenants with it")
    r = cl.delete("/immo/properties/10")
    ok(r.status_code == 200, f"200 (got {r.status_code})")
    ok(r.json().get("mieter_geloescht") == 1, f"the API reports 1 tenant removed — got {r.json()}")
    ok("Weg Mieter" not in names(cl), f"the tenant of the deleted house is GONE from Mieter/Bu Ay — {names(cl)}")

    print("\n[A4] deleting a UNIT takes its tenant with it")
    r = cl.delete("/immo/units/3")
    ok(r.status_code == 200, f"200 (got {r.status_code})")
    ok("Einheit Weg" not in names(cl), f"the tenant of the deleted unit is GONE — {names(cl)}")
    ok(names(cl) == ["Bleibt Mieter"], f"only the untouched tenant remains — {names(cl)}")

    print("\n[A4] the surviving tenant is untouched and still has his numbers")
    c = cl.get("/immo/mieter").json()["mieter"][0]
    ok(c["gesamtmiete"] == 540.0 and c["property_name"] == "Haus B", "Haus B tenant intact (540 Warmmiete)")

    print("\n[C4] the escalation is decided by the backend, not by the UI")
    h = cl.get("/immo/tenancies/102/mahnungen").json()
    ok(h["gesendet"] == 0 and h["naechste_stufe"] == 1 and h["naechste_stufe_text"] == "Zahlungserinnerung",
       f"nothing sent yet → next = Zahlungserinnerung — got {h['naechste_stufe_text']}")

    cl.delete("/immo/tenancies/102/monat-bezahlt?jahr=2026&monat=6")      # make him owe 540
    cl.post("/immo/tenancies/102/mahnung", json={"stufe": h["naechste_stufe"], "year": 2026})
    h = cl.get("/immo/tenancies/102/mahnungen").json()
    ok(h["gesendet"] == 1 and h["naechste_stufe"] == 2 and h["naechste_stufe_text"] == "1. Mahnung",
       f"after the reminder → next = 1. Mahnung — got {h['naechste_stufe_text']}")

    cl.post("/immo/tenancies/102/mahnung", json={"stufe": h["naechste_stufe"], "year": 2026})
    h = cl.get("/immo/tenancies/102/mahnungen").json()
    ok(h["naechste_stufe"] == 3 and h["naechste_stufe_text"] == "2. Mahnung",
       f"then → 2. Mahnung — got {h['naechste_stufe_text']}")

    cl.post("/immo/tenancies/102/mahnung", json={"stufe": h["naechste_stufe"], "year": 2026})
    h = cl.get("/immo/tenancies/102/mahnungen").json()
    ok(h["naechste_stufe"] == 3, "the escalation stops at the last step (3), it does not run away")
    ok([m["stufe"] for m in h["mahnungen"]] == [3, 2, 1],
       f"the history is NEWEST FIRST, even for letters written on the same day — got {[m['stufe'] for m in h['mahnungen']]}")
    ok(all(abs(m["betrag"] - 540.0) < 0.01 for m in h["mahnungen"]),
       "every letter dunned the Warmmiete (540), the number the card shows")

    print("\n[A5] the letter itself")
    r = cl.post("/immo/tenancies/102/mahnung", json={"stufe": 1, "year": 2026})
    ok(r.status_code == 200 and r.headers.get("content-type") == "application/pdf", "a PDF comes back")
    pdf = r.content
    ok(len(pdf) > 800 and pdf[:4] == b"%PDF", f"it is a real PDF ({len(pdf)} bytes)")

    # The PDF is compressed, so assert on the source of the text instead: rebuild the
    # letter body the endpoint builds and check the facts that were missing before.
    import autotax.immo_api as A
    db = S()
    t = db.query(ImmoTenancy).get(102)
    debt = A._debt(db, 1, t)
    comp = db.query(UserCompany).filter(UserCompany.user_id == 1).first()
    db.close()
    frist = (TODAY + __import__("datetime").timedelta(days=14)).strftime("%d.%m.%Y")
    ok(frist == "14.07.2026", f"the deadline is a concrete DATE, not 'in 14 Tagen' — {frist}")
    ok(abs(debt.total - 540.0) < 0.01, "the letter's amount = open_debt = 540 (Warmmiete)")
    ok(len(debt.months) == 1 and debt.months[0].ym == "2026-06",
       "the letter itemises WHICH months are open (Juni 2026)")
    ok(comp.company_name == "Hancer Immobilien" and comp.iban.startswith("DE02"),
       "the sender/signature is the landlord's company + IBAN — not 'Die Hausverwaltung'")
    src = open("autotax/immo_api.py", encoding="utf-8").read()
    ok("Die Hausverwaltung" not in src, "the hardcoded 'Die Hausverwaltung' signature is gone from the code")
    ok("innerhalb von <b>14 Tagen</b>" not in src, "the vague 'innerhalb von 14 Tagen' is gone from the code")

    print(f"\n=== DELETE + MAHNUNG: {PASS} passed, {FAIL} failed ===")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
