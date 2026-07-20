"""Flexible Mietmodelle — Sprint 2.1 (Untermieter) regression + unit tests.

Kritik güvenceler:
  * typ / parent_tenancy_id RELATIONSHIP-only → muhasebe (monat_soll) DEĞİŞMEZ
  * typ=NULL → 'haupt' (mevcut kiracı birebir aynı)
  * _validate_parent: self / unter-parent / same-unit / not-found REDDEDİLİR (Karar 1=A)
Standalone: `python tests/test_immo_sprint_2_1.py`
"""
import os, sys
os.environ.setdefault("JWT_SECRET", "0123456789012345678901234567890123456789")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
from datetime import date

FAIL = 0
def check(cond, msg):
    global FAIL
    print(("  OK  " if cond else "  FAIL ") + msg)
    if not cond: FAIL += 1

from autotax.immo_rules import monat_soll, monat_nk_soll
from autotax.immo_api import _norm_typ, _validate_parent, _tenancy_dict
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from autotax.models import Base, ImmoTenancy


class MockT:
    def __init__(self, **k):
        self.kaltmiete = k.get("kaltmiete", 0); self.nk_voraus = k.get("nk_voraus", 0)
        self.heizkosten_voraus = k.get("heizkosten_voraus"); self.erstmonat_betrag = None
        self.von = date(2025, 1, 1); self.bis = None; self.miete_historie = None
        self.typ = k.get("typ"); self.parent_tenancy_id = k.get("parent_tenancy_id")


print("== _norm_typ ==")
check(_norm_typ("UNTER") == "unter" and _norm_typ("haupt") == "haupt", "haupt/unter normalize")
check(_norm_typ("xyz") is None and _norm_typ(None) is None, "geçersiz/None -> None (=haupt)")

print("\n== MUHASEBE DEĞİŞMEZ — typ/parent monat_soll'u etkilemez ==")
base = monat_soll(MockT(kaltmiete=500, nk_voraus=100, heizkosten_voraus=45), 2026, 6)
withtyp = monat_soll(MockT(kaltmiete=500, nk_voraus=100, heizkosten_voraus=45,
                           typ="unter", parent_tenancy_id=7), 2026, 6)
check(base == withtyp == 645.0, f"soll typ yokken({base}) == typ=unter+parent({withtyp}) == 645")
check(monat_nk_soll(MockT(kaltmiete=500, nk_voraus=100, typ="unter"), 2026, 6) == 100.0, "nk_soll değişmez")

print("\n== ORM roundtrip + _validate_parent (Karar 1=A) ==")
eng = create_engine("sqlite:///:memory:"); Base.metadata.create_all(eng); S = sessionmaker(bind=eng)()
haupt = ImmoTenancy(unit_id=10, user_id=1, mieter_name="Hauptmieter")          # typ=None=haupt
S.add(haupt); S.commit()
unter = ImmoTenancy(unit_id=20, user_id=1, mieter_name="Untermieter", typ="unter", parent_tenancy_id=haupt.id)
S.add(unter); S.commit()
# geçerli: farklı unit, parent haupt
check(_validate_parent(S, 1, unter.id, 20, haupt.id) == haupt.id, "geçerli parent (farklı unit, haupt) kabul")
# reddet: kendine
try: _validate_parent(S, 1, haupt.id, 10, haupt.id); check(False, "self reddedilmeli")
except HTTPException: check(True, "self bağ REDDEDİLDİ")
# reddet: aynı unit (parent unit=10)
try: _validate_parent(S, 1, None, 10, haupt.id); check(False, "same-unit reddedilmeli")
except HTTPException: check(True, "same-unit REDDEDİLDİ (Karar 1=A)")
# reddet: parent bir Untermieter
try: _validate_parent(S, 1, None, 30, unter.id); check(False, "unter-parent reddedilmeli")
except HTTPException: check(True, "Untermieter'e bağ REDDEDİLDİ (tek seviye)")
# reddet: bulunamayan / başka user
try: _validate_parent(S, 1, None, 30, 9999); check(False, "not-found reddedilmeli")
except HTTPException: check(True, "olmayan parent REDDEDİLDİ")
# None / -1 -> None (temizle)
check(_validate_parent(S, 1, None, 30, None) is None and _validate_parent(S, 1, None, 30, -1) is None, "None/-1 -> None")
# _tenancy_dict yeni alanları döndürür
d = _tenancy_dict(unter)
check(d.get("typ") == "unter" and d.get("parent_tenancy_id") == haupt.id, "_tenancy_dict typ+parent döndürür")
# eski kiracı (haupt): typ None ama dict'te alan var
dh = _tenancy_dict(haupt)
check("typ" in dh and dh["typ"] is None, "haupt: typ=None (mevcut kiracı, kırılmaz)")
S.close()

print("\n" + ("❌ FAIL: %d" % FAIL if FAIL else "✅ TÜM TESTLER GEÇTİ (Sprint 2.1)"))
sys.exit(1 if FAIL else 0)
