"""Step 2c — Untermieter (Flexible Mietmodelle Faz 2 / Sprint 2.1).

Üzerinde uzlaşılan mimari (Karar 1=A, 2026-07-20):
  * typ = haupt | unter (NULL = haupt, mevcut kiracı birebir aynı)
  * Untermieter AYRI bir Unit'te (paylaşımlı daire Faz 3/4)
  * HER tenancy KENDİ Mietkonto/borç/Mahnung akışına sahip (Single Ledger korunur)
  * typ/parent RELATIONSHIP/INFO — muhasebeyi etkilemez
  * _validate_parent: self / unter-parent / same-unit REDDEDİLİR

Run:  PYTHONIOENCODING=utf-8 PYTHONPATH=. python tests/test_immo_untermieter.py
"""
import os
import sys
from datetime import date, datetime

os.environ.setdefault("JWT_SECRET", "x" * 44)

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi import FastAPI
from fastapi.testclient import TestClient

from autotax.models import Base, ImmoProperty, ImmoUnit, ImmoTenancy
from autotax import immo_api
from autotax.auth import get_current_user


class _FakeDate(date):
    @classmethod
    def today(cls):
        return date(2026, 6, 23)


class _FakeDT(datetime):
    @classmethod
    def now(cls, tz=None):
        return datetime(2026, 6, 23, tzinfo=tz)


immo_api.date = _FakeDate
immo_api.datetime = _FakeDT

PASS = FAIL = 0


def ok(c, m):
    global PASS, FAIL
    if c:
        PASS += 1; print(f"  PASS  {m}")
    else:
        FAIL += 1; print(f"  FAIL  {m}")


def main():
    e = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=e)
    S = sessionmaker(bind=e)

    cols = [c["name"] for c in inspect(e).get_columns("immo_tenancy")]
    ok("typ" in cols and "parent_tenancy_id" in cols, "columns exist (typ, parent_tenancy_id)")

    db = S()
    db.add(ImmoProperty(id=10, user_id=1, name="Haus", adresse="Str 1"))
    db.add(ImmoUnit(id=1, property_id=10, user_id=1, name="EG", wohnflaeche=80, soll_miete=600))
    db.add(ImmoUnit(id=2, property_id=10, user_id=1, name="2.OG", wohnflaeche=60, soll_miete=300))  # Karar 1=A: ayrı Unit
    # Hauptmieter (Unit 1) — typ=NULL=haupt (mevcut kiracı deseni), ödenmemiş → borçlu
    db.add(ImmoTenancy(id=101, unit_id=1, user_id=1, mieter_name="Haupt", von=date(2026, 6, 1), kaltmiete=600, nk_voraus=80))
    db.commit(); db.close()

    immo_api.SessionLocal = S
    app = FastAPI(); app.include_router(immo_api.router)
    app.dependency_overrides[get_current_user] = lambda: {"sub": "1", "email": "o@test.de"}
    cl = TestClient(app)

    print("\n[create Untermieter — AYRI Unit (Karar 1=A)]")
    r = cl.post("/immo/tenancies", json={"unit_id": 2, "mieter_name": "Unter", "typ": "unter",
                                         "parent_tenancy_id": 101, "von": "2026-06-01",
                                         "kaltmiete": 300, "nk_voraus": 40})
    ok(r.status_code == 200 and r.json().get("typ") == "unter", f"created typ=unter (got {r.status_code})")
    ok(r.json().get("parent_tenancy_id") == 101, "parent_tenancy_id = 101")
    unter_id = r.json().get("id")

    print("\n[validation — AYNI Unit reddedilir (Karar 1=A)]")
    r2 = cl.post("/immo/tenancies", json={"unit_id": 1, "mieter_name": "UnterBad", "typ": "unter",
                                          "parent_tenancy_id": 101, "von": "2026-06-01"})
    ok(r2.status_code == 400, f"same-unit Untermieter REDDEDİLDİ (got {r2.status_code})")

    print("\n[typ/parent + AYRI Unit]")
    data = cl.get("/immo/mieter").json()["mieter"]
    by = {x["mieter_name"]: x for x in data}
    ok(len(data) == 2, f"2 rows (got {len(data)})")
    h, u = by["Haupt"], by["Unter"]
    ok(h.get("typ") in (None, "haupt"), "Hauptmieter typ=haupt/None (mevcut kiracı, kırılmaz)")
    ok(u.get("typ") == "unter" and u.get("parent_tenancy_id") == 101, "Untermieter typ=unter + parent=101")
    ok(u["unit_id"] == 2 and u["unit_id"] != h["unit_id"], "Untermieter AYRI Unit (Karar 1=A)")
    ok(u["gesamtmiete"] == 340.0, f"Untermieter Warmmiete 300+40=340 (got {u['gesamtmiete']})")

    print("\n[Single Ledger — her tenancy KENDİ Mietkonto/borcu]")
    # Exception Engine: kira varsayılan ÖDENMİŞ; borç için ay 'ödenmedi' işaretlenir.
    # Untermieter'in Haziran'ını ödenmedi işaretle → SADECE onun borcu artmalı.
    cl.delete("/immo/tenancies/%s/monat-bezahlt?jahr=2026&monat=6" % unter_id)
    by2 = {x["mieter_name"]: x for x in cl.get("/immo/mieter").json()["mieter"]}
    ok(by2["Unter"]["offene_forderung"] == 340.0, f"Untermieter kendi borcu 340 (got {by2['Unter']['offene_forderung']})")
    ok(by2["Haupt"]["offene_forderung"] == 0.0, f"Hauptmieter ETKİLENMEDİ = 0 (got {by2['Haupt']['offene_forderung']}) — ayrı Mietkonto")

    print(f"\n=== Step 2c Untermieter (Karar 1=A): {PASS} passed, {FAIL} failed ===")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
