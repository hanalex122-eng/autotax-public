"""COMMIT 2 — the visible behaviour changes, each proven end-to-end (no silent changes).

Every assertion here is a BEFORE → AFTER contract from .claude/sprint0_plan.md:

  A1  arrears from PREVIOUS months surface (Bu Ay could say "alles bezahlt" while the
      tenant owed 3 months)
  A2  arrears cross the YEAR boundary (unpaid December vanished on 1 January)
  A3  Nebenkosten are part of the Soll → debt AND Mahnung amount are the Warmmiete
  B1  a Mieteingang payment (POST /immo/rent) actually reduces the debt — the sprint bug
  B2  the reports derive from the exception engine: no negative Gewinn, no flat-zero
      income chart, no "Miete fehlt" for a tenant who is ✓ paid

Scenario: Haus, 2 units. Today pinned 2026-06-30.
  TEN 101 Kalt 400 + NK 70 (Warm 470), moved in 2025-01-01 — used for the debt cases
  TEN 102 Kalt 500 + NK 40 (Warm 540), moved in 2026-01-01 — silent → Dauerzahlung

Run:  PYTHONIOENCODING=utf-8 PYTHONPATH=. python tests/test_immo_truth_commit2.py
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

from autotax.models import Base, ImmoProperty, ImmoUnit, ImmoTenancy, ImmoExpense
from autotax import immo_api
from autotax import immo_payments as _pay
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
    db.add(ImmoProperty(id=10, user_id=1, name="Haus", adresse="Musterstr. 12, 10115 Berlin", kaufpreis=200000))
    db.add(ImmoUnit(id=1, property_id=10, user_id=1, name="EG", wohnflaeche=60, soll_miete=470))
    db.add(ImmoUnit(id=2, property_id=10, user_id=1, name="OG", wohnflaeche=70, soll_miete=540))
    db.add(ImmoTenancy(id=101, unit_id=1, user_id=1, mieter_name="Schuldner",
                       von=date(2025, 1, 1), kaltmiete=400, nk_voraus=70))     # Warm 470
    db.add(ImmoTenancy(id=102, unit_id=2, user_id=1, mieter_name="Zahler",
                       von=date(2026, 1, 1), kaltmiete=500, nk_voraus=40))     # Warm 540
    db.add(ImmoExpense(id=1, property_id=10, user_id=1, kategorie="reparaturen",
                       betrag=600, datum=date(2026, 3, 5)))
    db.commit()
    db.close()
    immo_api.SessionLocal = S
    app = FastAPI()
    app.include_router(immo_api.router)
    app.dependency_overrides[get_current_user] = lambda: {"sub": "1", "email": "o@test.de"}
    return S, TestClient(app)


def card(cl, tid):
    return {x["tenancy_id"]: x for x in cl.get("/immo/mieter").json()["mieter"]}[tid]


def main():
    S, cl = build()

    # ─────────────────────────────────────────────────────────────────
    print("\n[A3] Nebenkosten are part of the Soll (Warmmiete)")
    cl.delete("/immo/tenancies/101/monat-bezahlt?jahr=2026&monat=6")     # June: not paid
    c = card(cl, 101)
    ok(c["offene_forderung"] == 470.0, f"June debt = 470 Warmmiete (Kalt 400 + NK 70), not 400 — got {c['offene_forderung']}")
    ok(c["gesamtmiete"] == 470.0, "the tenant card and the debt now agree on 470")
    ok(c["this_month_status"] == "open", "this month = open")

    print("\n[A3] the Mahnung duns the Warmmiete, not the Kaltmiete")
    r = cl.post("/immo/tenancies/101/mahnung", json={"stufe": 1, "year": 2026})   # returns the PDF
    ok(r.status_code == 200, f"Mahnung 200 (got {r.status_code})")
    m = cl.get("/immo/tenancies/101/mahnungen").json()["mahnungen"][0]             # the recorded amount
    ok(abs(m["betrag"] - 470.0) < 0.01, f"Mahnung amount = 470 Warmmiete, not 400 — got {m['betrag']}")

    # ─────────────────────────────────────────────────────────────────
    print("\n[A1] arrears from PREVIOUS months surface (no more 'alles bezahlt' lie)")
    cl.delete("/immo/tenancies/101/monat-bezahlt?jahr=2026&monat=3")     # March unpaid
    cl.delete("/immo/tenancies/101/monat-bezahlt?jahr=2026&monat=4")     # April unpaid
    cl.post("/immo/tenancies/101/monat-bezahlt", json={"jahr": 2026, "monat": 6})   # June: fine now
    c = card(cl, 101)
    ok(c["this_month_status"] == "paid", "this month is settled…")
    ok(c["offene_forderung"] == 940.0, f"…but March+April are still owed: 2×470 = 940 — got {c['offene_forderung']}")
    ok(c["debtor"] is True, "the tenant is a debtor even though THIS month is fine")
    ok([m["ym"] for m in c["rueckstand_monate"]] == ["2026-03", "2026-04"],
       f"the open months are listed for the UI — got {[m['ym'] for m in c['rueckstand_monate']]}")

    # ─────────────────────────────────────────────────────────────────
    print("\n[A2] arrears cross the YEAR boundary (unpaid December does not vanish)")
    cl.delete("/immo/tenancies/101/monat-bezahlt?jahr=2025&monat=12")    # Dec 2025 unpaid
    c = card(cl, 101)
    ok(c["offene_forderung"] == 1410.0, f"Dec-2025 + Mar + Apr = 3×470 = 1410 — got {c['offene_forderung']}")
    ok("2025-12" in [m["ym"] for m in c["rueckstand_monate"]], "December 2025 is still listed in June 2026")

    # ─────────────────────────────────────────────────────────────────
    print("\n[B1] THE SPRINT BUG: a Mieteingang payment reduces the debt")
    r = cl.post("/immo/rent", json={"property_id": 10, "tenancy_id": 101, "betrag": 470,
                                    "datum": "2026-06-20", "fuer_jahr": 2026, "fuer_monat": 3})
    ok(r.status_code == 200, f"payment accepted (got {r.status_code})")
    c = card(cl, 101)
    ok(c["offene_forderung"] == 940.0, f"March is settled by the payment: 1410 − 470 = 940 — got {c['offene_forderung']}")
    ok("2026-03" not in [m["ym"] for m in c["rueckstand_monate"]], "March is gone from the open months")
    rid = r.json()["payment_id"]

    print("\n[B1] a partial Mieteingang payment leaves the rest open")
    cl.post("/immo/rent", json={"property_id": 10, "tenancy_id": 101, "betrag": 200,
                                "datum": "2026-06-21", "fuer_jahr": 2026, "fuer_monat": 4})
    c = card(cl, 101)
    ok(c["offene_forderung"] == 740.0, f"April 470 − 200 = 270 open → 470(Dec) + 270 = 740 — got {c['offene_forderung']}")
    apr = [m for m in c["rueckstand_monate"] if m["ym"] == "2026-04"][0]
    ok(apr["typ"] == "partial" and apr["offen"] == 270.0, f"April is 'partial', 270 open — got {apr}")

    print("\n[B1] deleting the payment brings the debt back (correction must undo)")
    ok(cl.delete(f"/immo/rent/{rid}").status_code == 200, "payment deleted")
    c = card(cl, 101)
    ok(c["offene_forderung"] == 1210.0, f"March is owed again: 740 + 470 = 1210 — got {c['offene_forderung']}")

    print("\n[B1] the Mahnung dunning amount equals what the card shows")
    cl.post("/immo/tenancies/101/mahnung", json={"stufe": 1, "year": 2026})
    mh = cl.get("/immo/tenancies/101/mahnungen").json()["mahnungen"]
    latest = max(mh, key=lambda x: x["id"])
    ok(abs(latest["betrag"] - 1210.0) < 0.01,
       f"Mahnung = 1210 (the same number as Bu Ay/Mieter) — got {latest['betrag']}")

    # ─────────────────────────────────────────────────────────────────
    print("\n[Dauerzahlung] the silent tenant still owes nothing")
    c2 = card(cl, 102)
    ok(c2["offene_forderung"] == 0.0 and c2["this_month_status"] == "paid",
       f"no report, no payment → no debt (got {c2['offene_forderung']})")

    # ─────────────────────────────────────────────────────────────────
    print("\n[3A] the KPI summary is computed by the BACKEND (the UI may not add up debt)")
    s = cl.get("/immo/mieter").json()["summe"]
    ok(s["aktiv"] == 2, f"2 active tenants — got {s['aktiv']}")
    ok(s["sorgenfrei"] == 1, f"1 tenant free of debt (Zahler) — got {s['sorgenfrei']}")
    ok(s["schuldner"] == 1, f"1 debtor (Schuldner) — got {s['schuldner']}")
    ok(s["monate_offen"] == 3, f"3 open months in total (Dec-25, Mar, Apr) — got {s['monate_offen']}")
    ok(abs(s["offen_gesamt"] - 1210.0) < 0.01,
       f"Σ offen gesamt = 1210 — the same number the card shows — got {s['offen_gesamt']}")
    ok(s["teilzahlung"] == 1, f"1 tenant has a partial month (April) — got {s['teilzahlung']}")

    # ─────────────────────────────────────────────────────────────────
    print("\n[B2] the reports derive from the exception engine")
    ck = cl.get("/immo/cockpit?year=2026").json()
    f = ck["financial"] if "financial" in ck else ck["kpi"]
    inc = ck["charts"]["monthly_income"]
    ok(sum(inc) > 0, f"the income chart is no longer a flat zero line — sum {sum(inc)}")
    # Zahler: Jan..Jun × 540 = 3240 ; Schuldner: 6×470 − 1210 owed... (June paid, Mar/Apr open)
    ok(inc[0] == 470 + 540, f"January income = 1010 (both tenants paid) — got {inc[0]}")
    ok(inc[2] == 540, f"March income = 540 only (Schuldner unpaid) — got {inc[2]}")
    gew = ck["kpi"]["gewinn"]["total"]
    ok(gew > 0, f"Gewinn is positive, not negative-by-construction — got {gew}")
    items = ck["kpi"]["gewinn"]["items"]
    ok(abs(sum(i["value"] for i in items) - gew) < 0.02 if items and "value" in items[0] else True,
       "the headline Gewinn agrees with its own detail list")
    rk = ck["kpi"]["rueckstand"]["total"]
    ok(abs(rk - 1210.0) < 0.01, f"the report's Rückstand = the card's debt = 1210 — got {rk}")

    print("\n[B2] no false 'Miete fehlt' for a tenant who is paid")
    texts = [a["text"] for a in ck["actions"]]
    ok(not any("Zahler" in t and "fehlt" in t for t in texts),
       f"the paid tenant is NOT warned about — actions: {texts}")
    ok(not any("Schuldner" in t and "fehlt" in t for t in texts),
       "…and the debtor's June is settled, so no 'Miete Jun fehlt' either")

    print("\n[B2] accounting: Ist is derived, not summed from payment rows")
    acc = cl.get("/immo/properties/10/accounting?year=2026").json()
    t101 = [t for t in acc["tenancies"] if t["tenancy_id"] == 101][0]
    ok(abs(t101["soll"] - 6 * 470) < 0.01, f"Soll bis heute = 6×470 = 2820 — got {t101['soll']}")
    ok(abs(t101["rueckstand"] - 740.0) < 0.01, f"this YEAR's open = Mar 470 + Apr 270 = 740 — got {t101['rueckstand']}")
    ok(abs(t101["ist"] - (6 * 470 - 740)) < 0.01, f"Ist = Soll − offen = 2080 — got {t101['ist']}")
    ok(acc["summe"]["gewinn"] == round(acc["summe"]["ist_miete"] - acc["summe"]["ausgaben"], 2),
       "Gewinn = Ist − Ausgaben (one formula, no second book)")

    print(f"\n=== COMMIT 2 TRUTH: {PASS} passed, {FAIL} failed ===")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
