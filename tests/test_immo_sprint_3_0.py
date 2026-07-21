"""Sprint 3.0 — unit-seviye türetme düzeltmeleri + örtüşme guardrail'i (Faz 3).

Kilitlenen davranışlar:
  * P1/P2  property ve portföy Soll'u AKTİF TENANCY'LERİN TOPLAMI (act[0] değil)
  * Tek tenancy'de her şey BİREBİR eskisi gibi (regresyon)
  * Guardrail = HARD VALIDATION: aynı Unit'te tarih aralığı örtüşen ikinci tenancy 400
    (override yok). Ardışık sözleşme (aynı gün devir) SERBEST.
  * Muhasebe dokunulmadı: bir kiracının ödemesi diğerinin borcunu kapatmaz

Tasarım: docs/design/Sprint_3_0_Technical_Design.md · ADD Rev.3
Run: PYTHONIOENCODING=utf-8 PYTHONPATH=. python tests/test_immo_sprint_3_0.py
"""
import os
import sys
from datetime import date, datetime

os.environ.setdefault("JWT_SECRET", "x" * 44)

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi import FastAPI, HTTPException
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
        PASS += 1; print("  PASS  " + m)
    else:
        FAIL += 1; print("  FAIL  " + m)


D = date


def main():
    # ── U1: örtüşme mantığı (saf fonksiyon) ─────────────────────────────────
    print("[U1] _ranges_overlap — yarı-açık aralık, aynı gün devir serbest")
    ov = immo_api._ranges_overlap
    ok(ov(D(2026, 1, 1), None, D(2026, 3, 1), None), "iki süresiz sözleşme → ÖRTÜŞÜR")
    ok(ov(D(2026, 1, 1), D(2026, 12, 31), D(2026, 6, 1), D(2026, 8, 1)), "tam içine alan → ÖRTÜŞÜR")
    ok(ov(D(2026, 1, 1), D(2026, 6, 30), D(2026, 5, 1), D(2026, 9, 1)), "kısmi → ÖRTÜŞÜR")
    ok(not ov(D(2026, 1, 1), D(2026, 6, 30), D(2026, 6, 30), None), "aynı gün devir (bis == von) → örtüşmez")
    ok(not ov(D(2026, 1, 1), D(2026, 6, 30), D(2026, 7, 1), None), "ardışık → örtüşmez")
    ok(not ov(D(2026, 7, 1), None, D(2026, 1, 1), D(2026, 6, 30)), "ters sıra ardışık → örtüşmez")
    ok(ov(None, None, D(2026, 1, 1), None), "tarihsiz kayıt → ÖRTÜŞÜR (temkinli)")

    # ── Kurulum ─────────────────────────────────────────────────────────────
    e = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=e)
    S = sessionmaker(bind=e)
    db = S()
    db.add(ImmoProperty(id=10, user_id=1, name="Haus", adresse="Str 1"))
    db.add(ImmoUnit(id=1, property_id=10, user_id=1, name="EG", wohnflaeche=80, soll_miete=600))
    db.add(ImmoUnit(id=2, property_id=10, user_id=1, name="2.OG", wohnflaeche=60, soll_miete=300))
    db.add(ImmoTenancy(id=101, unit_id=1, user_id=1, mieter_name="Haupt",
                       von=D(2026, 1, 1), kaltmiete=600, nk_voraus=80))
    db.commit(); db.close()

    immo_api.SessionLocal = S
    app = FastAPI(); app.include_router(immo_api.router)
    app.dependency_overrides[get_current_user] = lambda: {"sub": "1", "email": "o@test.de"}
    cl = TestClient(app)

    # ── I1-I3: guardrail (HARD VALIDATION) ──────────────────────────────────
    print("\n[I1-I3] Guardrail = hard validation (override YOK)")
    r = cl.post("/immo/tenancies", json={"unit_id": 1, "mieter_name": "Zweiter",
                                         "von": "2026-03-01", "kaltmiete": 300})
    ok(r.status_code == 400, "aynı Unit'te örtüşen 2. sözleşme REDDEDİLDİ (%s)" % r.status_code)
    det = (r.json() or {}).get("detail", "")
    ok("bereits vermietet" in det, "hata mesajı durumu söylüyor")
    ok("Auszugsdatum" in det and "eigene Einheit" in det, "hata mesajı İKİ çıkış yolunu gösteriyor")

    r = cl.post("/immo/tenancies", json={"unit_id": 2, "mieter_name": "AndereEinheit",
                                         "von": "2026-03-01", "kaltmiete": 300})
    ok(r.status_code == 200, "farklı Unit → serbest (%s)" % r.status_code)

    cl.patch("/immo/tenancies/101", json={"bis": "2026-06-30"})
    r = cl.post("/immo/tenancies", json={"unit_id": 1, "mieter_name": "Nachmieter",
                                         "von": "2026-06-30", "kaltmiete": 650})
    ok(r.status_code == 200, "aynı gün devir (bis == von) SERBEST (%s)" % r.status_code)
    nach_id = r.json().get("id")

    r = cl.patch("/immo/tenancies/%s" % nach_id, json={"von": "2026-05-01"})
    ok(r.status_code == 400, "PATCH ile örtüşme yaratma REDDEDİLDİ (%s)" % r.status_code)
    still = cl.get("/immo/units/1/tenancies").json()["tenancies"]
    ok([x for x in still if x["id"] == nach_id][0]["von"] == "2026-06-30", "reddedilen PATCH kaydı DEĞİŞTİRMEDİ")

    r = cl.patch("/immo/tenancies/%s" % nach_id, json={"bis": "2027-01-31"})
    ok(r.status_code == 200, "örtüşme yaratmayan PATCH serbest (%s)" % r.status_code)

    # ── I4: mevcut örtüşen kayıt geçmişe dönük doğrulanmaz ──────────────────
    print("\n[I4] Geçmişe dönük doğrulama YOK (mevcut veri dokunulmaz)")
    d2 = S()
    d2.add(ImmoTenancy(id=999, unit_id=1, user_id=1, mieter_name="Altlast",
                       von=D(2026, 1, 1), kaltmiete=100, nk_voraus=0))   # bilerek örtüşen eski kayıt
    d2.commit(); d2.close()
    ok(cl.get("/immo/units/1/tenancies").status_code == 200, "okuma yüzeyi çalışıyor")
    ok(cl.patch("/immo/tenancies/999", json={"mieter_name": "Altlast v2"}).status_code == 200,
       "tarih DIŞI alan güncellemesi engellenmiyor")

    # ── U2-U4: Soll toplamı (P1/P2) ─────────────────────────────────────────
    print("\n[U2-U4] Property/portföy Soll = AKTİF TENANCY'LERİN TOPLAMI (act[0] değil)")
    acc = cl.get("/immo/properties/10/accounting?year=2026").json()
    unit1 = [u for u in acc["units"] if u["unit_id"] == 1][0]
    # Beklenti API'den değil, kuralların kendisinden BAĞIMSIZ türetilir (döngüsel kanıt olmasın)
    from autotax import immo_rules as _r
    d3 = S()
    u_ten = [t for t in d3.query(ImmoTenancy).filter(ImmoTenancy.unit_id == 1).all()]
    beklenen = ilk_act = 0.0
    for m in range(1, 13):
        act = [t for t in u_ten if _r.tenancy_active_in_month(t, 2026, m)]
        beklenen += sum(_r.monat_soll(t, 2026, m) for t in act)
        if act:
            ilk_act += _r.monat_soll(act[0], 2026, m)      # eski (hatalı) davranış
    d3.close()
    ok(abs(unit1["soll"] - round(beklenen, 2)) < 0.01,
       "unit Soll %.2f == tüm aktif tenancy'lerin toplamı %.2f" % (unit1["soll"], beklenen))
    ok(beklenen > ilk_act + 0.01,
       "act[0] olsaydı %.2f çıkardı → %.2f eksik raporlanırdı (P1 gerçekten düzeldi)" % (ilk_act, beklenen - ilk_act))
    ok(acc["summe"]["zahlungsausfall"] <= acc["summe"]["soll_miete"] + 0.01,
       "rapor iç tutarlı: Rückstand <= Soll (P4)")

    # ── R5: muhasebe dokunulmadı ────────────────────────────────────────────
    print("\n[R5] Muhasebe DEĞİŞMEDİ — bir kiracının ödemesi diğerininkini kapatmaz")
    by = {x["tenancy_id"]: x for x in cl.get("/immo/mieter").json()["mieter"]}
    cl.delete("/immo/tenancies/999/monat-bezahlt?jahr=2026&monat=6")
    by2 = {x["tenancy_id"]: x for x in cl.get("/immo/mieter").json()["mieter"]}
    ok(by2[999]["offene_forderung"] > 0, "999 borçlandı (%.2f)" % by2[999]["offene_forderung"])
    ok(by2[101]["offene_forderung"] == by[101]["offene_forderung"], "101'in borcu DEĞİŞMEDİ")
    cl.post("/immo/tenancies/999/monat-bezahlt", json={"jahr": 2026, "monat": 6,
                                                       "datum": "2026-06-05", "betrag": 100})
    by3 = {x["tenancy_id"]: x for x in cl.get("/immo/mieter").json()["mieter"]}
    ok(by3[101]["offene_forderung"] == by[101]["offene_forderung"], "999'a ödeme 101'i ETKİLEMEDİ")

    print("\n=== Sprint 3.0: %d passed, %d failed ===" % (PASS, FAIL))
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
