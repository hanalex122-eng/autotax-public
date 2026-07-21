"""Sprint 2.1 — Untermieter E2E regresyon testi (Flexible Mietmodelle Faz 2).

Bu testin asıl işi TEK bir güvenceyi kalıcı kilitlemek: bir Untermieter eklemek/bağlamak/
bağı koparmak, Hauptmieter'in Mietkonto'sunu, borcunu ve Mahnung geçmişini DEĞİŞTİRMEZ
(SHA256 snapshot: önce == sonra). Single Ledger + "typ/parent relationship-only".

Senaryo:
  1. Hauptmieter oluştur (Unit 1)
  2. AYRI Unit'te Untermieter oluştur (Unit 2) + Hauptmieter'e bağla
  3. Rozetin beslendiği alanlar feed'de doğru mu (typ + parent_tenancy_id + parent adı çözülebiliyor mu)
  4. Hauptmieter'in Mietkonto / Mahnung / borcu DEĞİŞMEDİ mi (SHA256 snapshot: önce == sonra)
  5. Untermieter bağımsız bir tenancy gibi mi çalışıyor (kendi Mietkonto, kendi borç, kendi Mahnung)

Run: PYTHONIOENCODING=utf-8 PYTHONPATH=. python tests/test_immo_sprint_2_1_e2e.py
"""
import os
import sys
import json
import hashlib
from datetime import date, datetime

os.environ.setdefault("JWT_SECRET", "x" * 44)

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi import FastAPI
from fastapi.testclient import TestClient

from autotax.models import Base, ImmoProperty, ImmoUnit
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
        PASS += 1; print("  PASS  " + m)
    else:
        FAIL += 1; print("  FAIL  " + m)


def sha(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()[:16]


def main():
    e = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=e)
    S = sessionmaker(bind=e)
    db = S()
    db.add(ImmoProperty(id=10, user_id=1, name="Musterstr. 12", adresse="Musterstr. 12, Krefeld"))
    db.add(ImmoUnit(id=1, property_id=10, user_id=1, name="EG links", wohnflaeche=80, soll_miete=600))
    db.add(ImmoUnit(id=2, property_id=10, user_id=1, name="2.OG", wohnflaeche=45, soll_miete=300))
    db.commit(); db.close()

    immo_api.SessionLocal = S
    app = FastAPI(); app.include_router(immo_api.router)
    app.dependency_overrides[get_current_user] = lambda: {"sub": "1", "email": "o@test.de"}
    cl = TestClient(app)

    print("\n[1] Hauptmieter oluştur (Unit 1, hiçbir yeni alan gönderilmeden — mevcut müşteri deseni)")
    r = cl.post("/immo/tenancies", json={"unit_id": 1, "mieter_name": "Ahmet Yilmaz",
                                         "von": "2026-01-01", "kaltmiete": 600, "nk_voraus": 80})
    ok(r.status_code == 200, "Hauptmieter oluştu (%s)" % r.status_code)
    haupt_id = r.json()["id"]
    ok(r.json().get("typ") is None, "typ=NULL (eski davranış: haupt)")

    # Hauptmieter'e gerçek bir geçmiş ver: Mart ödenmedi -> borç + Mahnung
    cl.delete("/immo/tenancies/%s/monat-bezahlt?jahr=2026&monat=3" % haupt_id)

    print("\n[4a] Hauptmieter SNAPSHOT (Untermieter'den ÖNCE)")
    mk_before = cl.get("/immo/tenancies/%s/mietkonto?year=2026" % haupt_id).json()
    feed_before = [x for x in cl.get("/immo/mieter").json()["mieter"] if x["tenancy_id"] == haupt_id][0]
    mah_before = cl.get("/immo/tenancies/%s/mahnungen" % haupt_id).json()
    s_mk, s_offen, s_mah = sha(mk_before), feed_before["offene_forderung"], sha(mah_before)
    print("      mietkonto=%s · offen=%s · mahnungen=%s" % (s_mk, s_offen, s_mah))
    ok(s_offen > 0, "Hauptmieter'in gerçek bir borcu var (%s) — test anlamlı" % s_offen)

    print("\n[2] AYRI Unit'te Untermieter oluştur + Hauptmieter'e bağla")
    r = cl.post("/immo/tenancies", json={"unit_id": 2, "mieter_name": "Maria Müller", "typ": "unter",
                                         "parent_tenancy_id": haupt_id, "von": "2026-04-01",
                                         "kaltmiete": 300, "nk_voraus": 40, "heizkosten_voraus": 30})
    ok(r.status_code == 200, "Untermieter oluştu (%s)" % r.status_code)
    unter_id = r.json()["id"]
    ok(r.json().get("typ") == "unter" and r.json().get("parent_tenancy_id") == haupt_id,
       "typ=unter + parent=%s" % haupt_id)

    print("\n[2b] Kural ihlalleri REDDEDİLİYOR (Karar/Seçenek B)")
    ok(cl.post("/immo/tenancies", json={"unit_id": 1, "mieter_name": "X", "typ": "unter",
                                        "parent_tenancy_id": haupt_id}).status_code == 400,
       "aynı Unit REDDEDİLDİ")
    ok(cl.post("/immo/tenancies", json={"unit_id": 1, "mieter_name": "Y", "typ": "unter",
                                        "parent_tenancy_id": unter_id}).status_code == 400,
       "Untermieter'e bağlama REDDEDİLDİ (tek seviye)")
    ok(cl.patch("/immo/tenancies/%s" % unter_id,
                json={"typ": "unter", "parent_tenancy_id": unter_id}).status_code == 400,
       "kendine bağlama REDDEDİLDİ")

    print("\n[3] Rozetin beslendiği alanlar (frontend hmName/rozet mantığının aynısı)")
    rows = cl.get("/immo/mieter").json()["mieter"]
    by = {x["tenancy_id"]: x for x in rows}
    u = by[unter_id]
    ok(u["typ"] == "unter" and u["parent_tenancy_id"] == haupt_id, "feed: typ=unter + parent")
    parent_name = next((x["mieter_name"] for x in rows if x["tenancy_id"] == u["parent_tenancy_id"]), None)
    ok(parent_name == "Ahmet Yilmaz", "rozet metni: 🔗 Untermieter → %s" % parent_name)
    ok(by[haupt_id].get("typ") in (None, "haupt"), "Hauptmieter'de rozet YOK (typ=%r)" % by[haupt_id].get("typ"))
    # Form B aday filtresinin aynısı: aynı bina · farklı Unit · typ!=unter · kendisi değil
    cands = [x for x in rows if x["tenancy_id"] != unter_id and x["unit_id"] != u["unit_id"]
             and x.get("typ") != "unter"
             and (x["property_name"], x["property_address"]) == (u["property_name"], u["property_address"])]
    ok([c["tenancy_id"] for c in cands] == [haupt_id], "aday listesi = sadece Hauptmieter %s" % [c["mieter_name"] for c in cands])

    print("\n[4b] Hauptmieter DEĞİŞMEDİ mi? (snapshot karşılaştırması)")
    mk_after = cl.get("/immo/tenancies/%s/mietkonto?year=2026" % haupt_id).json()
    feed_after = [x for x in cl.get("/immo/mieter").json()["mieter"] if x["tenancy_id"] == haupt_id][0]
    mah_after = cl.get("/immo/tenancies/%s/mahnungen" % haupt_id).json()
    ok(sha(mk_after) == s_mk, "Mietkonto SHA256 birebir aynı (%s)" % sha(mk_after))
    ok(feed_after["offene_forderung"] == s_offen, "borç aynı (%s)" % feed_after["offene_forderung"])
    ok(feed_after["rueckstand_monate"] == feed_before["rueckstand_monate"], "açık aylar listesi aynı")
    ok(sha(mah_after) == s_mah, "Mahnung geçmişi aynı")

    print("\n[5] Untermieter bağımsız tenancy mi?")
    mk_u = cl.get("/immo/tenancies/%s/mietkonto?year=2026" % unter_id).json()
    ok(mk_u.get("tenancy_id") == unter_id, "kendi Mietkonto'su var")
    cl.delete("/immo/tenancies/%s/monat-bezahlt?jahr=2026&monat=6" % unter_id)
    by2 = {x["tenancy_id"]: x for x in cl.get("/immo/mieter").json()["mieter"]}
    ok(by2[unter_id]["offene_forderung"] == 370.0,
       "kendi borcu 300+40+30=370 (got %s)" % by2[unter_id]["offene_forderung"])
    ok(by2[haupt_id]["offene_forderung"] == s_offen,
       "Untermieter borçlanınca Hauptmieter'in borcu HÂLÂ %s" % by2[haupt_id]["offene_forderung"])
    r = cl.post("/immo/tenancies/%s/mahnung" % unter_id, json={"stufe": 1, "year": 2026})
    ok(r.status_code == 200, "Untermieter'e kendi Mahnung'u üretilebiliyor (%s)" % r.status_code)
    ok(len(cl.get("/immo/tenancies/%s/mahnungen" % unter_id).json().get("mahnungen", [])) == 1,
       "Mahnung Untermieter'in dosyasında")
    ok(sha(cl.get("/immo/tenancies/%s/mahnungen" % haupt_id).json()) == s_mah,
       "Hauptmieter'in Mahnung geçmişi HÂLÂ değişmedi")

    print("\n[6] Bağı koparma (K4/K5) — muhasebe yine değişmez")
    cl.patch("/immo/tenancies/%s" % unter_id, json={"typ": "haupt", "parent_tenancy_id": -1})
    by3 = {x["tenancy_id"]: x for x in cl.get("/immo/mieter").json()["mieter"]}
    ok(by3[unter_id]["typ"] == "haupt" and by3[unter_id]["parent_tenancy_id"] is None, "bağ koptu, rozet kaybolur")
    ok(by3[unter_id]["offene_forderung"] == 370.0, "borç aynı kaldı (%s)" % by3[unter_id]["offene_forderung"])
    ok(by3[haupt_id]["offene_forderung"] == s_offen, "Hauptmieter yine etkilenmedi")

    print("\n=== Sprint 2.1 E2E: %d passed, %d failed ===" % (PASS, FAIL))
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
