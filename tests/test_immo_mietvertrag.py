"""Sprint 9.0b — Mietvertrag backend: model + endpoint + PDF + write-back.

Kritik güvenceler (kullanıcının 5 dikkat maddesi):
  1. Write-back TEK YÖNLÜ (sözleşme → tenancy); ters yön yok
  2. Snapshot immutable: final PDF master-data değişse de AYNI (Principle A)
  3. Mietkonto'ya İKİNCİ muhasebe yok: write-back yalnız tenancy kolonlarını set eder,
     monat_soll yeniden hesaplanmaz — tenancy'de sözleşme-DIŞI hiçbir şey değişmez
  4. Yeni tablo create_all ile gelir; mevcut tablolar etkilenmez
  5. Regresyon: sözleşme yokken tenancy/Mietkonto çıktısı BİREBİR aynı

Run: PYTHONIOENCODING=utf-8 PYTHONPATH=. python tests/test_immo_mietvertrag.py
"""
import os
import sys
import json
import hashlib
from datetime import date, datetime

os.environ.setdefault("JWT_SECRET", "x" * 44)

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi import FastAPI
from fastapi.testclient import TestClient

from autotax.models import Base, ImmoProperty, ImmoUnit, ImmoTenancy, UserCompany, ImmoMietvertrag
from autotax import immo_api
from autotax.auth import get_current_user
from autotax import immo_rules as R


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


def sha(o):
    return hashlib.sha256(json.dumps(o, sort_keys=True, default=str).encode()).hexdigest()[:16]


def main():
    e = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=e)
    # (4) create_all yeni tabloyu kurdu
    ok("immo_mietvertrag" in inspect(e).get_table_names(), "create_all → immo_mietvertrag tablosu (mevcutlar etkilenmez)")
    S = sessionmaker(bind=e)
    db = S()
    db.add(UserCompany(id=1, user_id=1, company_name="Çağrı Immobilien GmbH",
                       address="Königsweg 3, Krefeld", iban="DE12 3456", is_default=True))
    db.add(ImmoProperty(id=10, user_id=1, name="Wiesenstr. 10", adresse="Wiesenstr. 10, Saarbrücken"))
    db.add(ImmoUnit(id=1, property_id=10, user_id=1, name="EG links", wohnflaeche=72, soll_miete=700))
    db.add(ImmoTenancy(id=101, unit_id=1, user_id=1, mieter_name="Ayşe Öztürk",
                       von=date(2026, 1, 1), kaltmiete=700, nk_voraus=90, heizkosten_voraus=45, kaution=1400))
    db.commit(); db.close()

    immo_api.SessionLocal = S
    app = FastAPI(); app.include_router(immo_api.router)
    app.dependency_overrides[get_current_user] = lambda: {"sub": "1", "email": "o@test.de"}
    cl = TestClient(app)

    # ── (5) BASELINE: sözleşme yokken tenancy + Mietkonto ──────────────────
    d0 = S()
    t0 = d0.query(ImmoTenancy).get(101)
    base_soll = R.monat_soll(t0, 2026, 6)
    base_tenancy = {"kalt": t0.kaltmiete, "nk": t0.nk_voraus, "heiz": t0.heizkosten_voraus,
                    "kaution": t0.kaution, "von": str(t0.von), "hist": t0.miete_historie}
    d0.close()
    base_mk = cl.get("/immo/tenancies/101/mietkonto?year=2026").json()
    s_mk = sha(base_mk)
    print("\n[baseline] soll=%.2f · mk=%s" % (base_soll, s_mk))

    # ── create (auto-fill) ────────────────────────────────────────────────
    print("\n[create] auto-fill")
    r = cl.post("/immo/tenancies/101/mietvertrag", json={})
    ok(r.status_code == 200, "create 200 (%s)" % r.status_code)
    mid = r.json()["id"]
    vj = r.json()["vertrag_json"]
    ok(vj["parteien"]["vermieter"]["name"] == "Çağrı Immobilien GmbH", "Vermieter auto-fill (UserCompany)")
    ok(vj["parteien"]["mieter"]["name"] == "Ayşe Öztürk", "Mieter auto-fill (Türkçe ad)")
    ok(vj["miete"]["kaltmiete"] == 700 and vj["kaution"]["betrag"] == 1400, "mali auto-fill tenancy'den")
    ok(r.json()["status"] == "entwurf", "status entwurf")

    # create SIRASINDA tenancy/Mietkonto DEĞİŞMEDİ (henüz finalize yok)
    ok(sha(cl.get("/immo/tenancies/101/mietkonto?year=2026").json()) == s_mk, "create → Mietkonto DEĞİŞMEDİ")

    # ── patch: kullanıcı Kaltmiete + Kaution'u sözleşmede değiştiriyor ─────
    print("\n[patch] kullanıcı değerleri değiştiriyor + disclaimer_ack")
    vj["miete"]["kaltmiete"] = 750
    vj["kaution"]["betrag"] = 5000            # 5000 > 3×750 → cap 2250 beklenir
    vj["disclaimer_ack"] = True
    r = cl.patch("/immo/mietvertrag/%s" % mid, json={"vertrag_json": vj})
    ok(r.status_code == 200, "patch 200")
    # patch de tenancy'yi DEĞİŞTİRMEZ (write-back yalnız finalize'de)
    d1 = S(); t1 = d1.query(ImmoTenancy).get(101)
    ok(t1.kaltmiete == 700 and t1.kaution == 1400, "patch → tenancy DEĞİŞMEDİ (write-back yalnız finalize)")
    d1.close()

    # ── finalize: snapshot + lock + WRITE-BACK ────────────────────────────
    print("\n[finalize] snapshot + lock + write-back")
    r = cl.post("/immo/mietvertrag/%s/finalisieren" % mid)
    ok(r.status_code == 200 and r.json()["status"] == "final", "finalize → final")
    ok(r.json()["hat_snapshot"], "snapshot donduruldu (Principle A)")

    # (1) WRITE-BACK TEK YÖNLÜ: tenancy artık sözleşmedeki değerlerde (cap uygulanmış)
    d2 = S(); t2 = d2.query(ImmoTenancy).get(101)
    ok(t2.kaltmiete == 750, "write-back: kaltmiete 700→750")
    ok(t2.kaution == 2250, "write-back: Kaution 5000 → cap 2250 (3×750)")
    ok(t2.nk_voraus == 90 and t2.heizkosten_voraus == 45, "write-back dokunmadığı alanlar aynı")
    d2.close()

    # (3) İKİNCİ MUHASEBE YOK: monat_soll yalnız tenancy alanlarından türedi
    d3 = S(); t3 = d3.query(ImmoTenancy).get(101)
    yeni_soll = R.monat_soll(t3, 2026, 6)
    ok(abs(yeni_soll - (750 + 90 + 45)) < 0.01, "monat_soll = 750+90+45 = 885 (tenancy'den türedi, ikinci defter yok)")
    d3.close()

    # (2) SNAPSHOT IMMUTABLE — VERİ DÜZEYİNDE (PDF byte'ları reportlab zaman damgası yüzünden
    # deterministik değil; asıl güvence: final okuma DONMUŞ snapshot'tan, canlı master-data'dan değil).
    pdf1 = cl.get("/immo/mietvertrag/%s/pdf" % mid).content
    ok(pdf1[:4] == b"%PDF", "final PDF üretildi")

    def _snap_of(mv_id):
        dd = S(); row = dd.query(ImmoMietvertrag).get(mv_id); s = row.vertrag_snapshot; dd.close()
        return s
    snap_before = _snap_of(mid)
    ok('"kaltmiete": 750' in snap_before or "750" in snap_before, "snapshot kaltmiete 750 içeriyor")
    # tenancy'yi elle boz → snapshot DEĞİŞMEZ (final canlı veriden okumaz)
    dX = S(); tX = dX.query(ImmoTenancy).get(101); tX.kaltmiete = 9999; dX.commit(); dX.close()
    ok(_snap_of(mid) == snap_before, "master-data bozulsa da SNAPSHOT byte-identical (canlı okunmuyor)")
    ok("9999" not in _snap_of(mid), "snapshot bozulan 9999'u ASLA almadı (tek yönlü, donmuş)")
    # geri al
    dY = S(); tY = dY.query(ImmoTenancy).get(101); tY.kaltmiete = 750; dY.commit(); dY.close()

    # finalize sonrası PATCH reddedilir (lock)
    ok(cl.patch("/immo/mietvertrag/%s" % mid, json={"vertrag_json": vj}).status_code == 409, "final → PATCH 409 (lock)")

    # ── revision: yeni taslak, eski dokunulmaz ────────────────────────────
    print("\n[revision]")
    r = cl.post("/immo/mietvertrag/%s/revision" % mid)
    ok(r.status_code == 200 and r.json()["revision"] == 2 and r.json()["status"] == "entwurf", "revision v2 entwurf")
    ok(r.json()["supersedes_id"] == mid, "supersedes_id = v1")
    # v1 hâlâ final ve PDF'lenebilir; snapshot'ı revision'dan etkilenmedi
    ok(cl.get("/immo/mietvertrag/%s" % mid).json()["status"] == "final", "v1 dokunulmadı (final)")
    ok(_snap_of(mid) == snap_before, "revision v1 snapshot'ını değiştirmedi")
    ok(cl.get("/immo/mietvertrag/%s/pdf" % mid).content[:4] == b"%PDF", "v1 PDF hâlâ üretilebiliyor")

    # liste en güncel revision'ı önce verir
    lst = cl.get("/immo/mietvertraege?tenancy_id=101").json()["mietvertraege"]
    ok(lst[0]["revision"] == 2, "liste max-revision önce")

    # ── disclaimer_ack olmadan finalize reddedilir ────────────────────────
    r = cl.post("/immo/tenancies/101/mietvertrag", json={"vertrag_json": {"vertrag_typ": "wohnraum_unbefristet",
                "miete": {"kaltmiete": 700}, "kaution": {"betrag": 1000}}})
    mid2 = r.json()["id"]
    ok(cl.post("/immo/mietvertrag/%s/finalisieren" % mid2).status_code == 400, "disclaimer_ack yok → finalize 400")

    # ── (5) REGRESYON: bu tenancy'nin Mietkonto YAPISI bozulmadı ──────────
    # (soll write-back nedeniyle 750'ye çıktı — bu BEKLENEN; yapı/şema/derivasyon aynı)
    d4 = S(); t4 = d4.query(ImmoTenancy).get(101)
    ok(R.monat_soll(t4, 2026, 6) == 885.0, "Mietkonto derivasyonu sağlam (750+90+45)")
    d4.close()

    print("\n=== Sprint 9.0b: %d passed, %d failed ===" % (PASS, FAIL))
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
