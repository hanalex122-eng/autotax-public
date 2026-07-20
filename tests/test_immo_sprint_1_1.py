"""Flexible Mietmodelle — Sprint 1.1 regression + unit tests.

Kapsam: heizkosten_voraus + zahler + Warmmiete. Kritik güvenceler:
  * Single-Ledger invariant: monat_soll == monat_kalt_soll + monat_nk_soll + monat_heiz_soll
  * NK izolasyonu: monat_nk_soll heiz İÇERMEZ (NK-Abrechnung Faz 1'de değişmez)
  * heiz=0 (None) -> davranış eski sürümle BYTE-IDENTICAL
Standalone çalışır: `python tests/test_immo_sprint_1_1.py`
"""
import os, sys
os.environ.setdefault("JWT_SECRET", "0123456789012345678901234567890123456789")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
from datetime import date

from autotax.immo_rules import (monat_soll, monat_kalt_soll, monat_nk_soll,
                                monat_heiz_soll, month_proration)

FAIL = 0
def check(cond, msg):
    global FAIL
    print(("  OK  " if cond else "  FAIL ") + msg)
    if not cond:
        FAIL += 1


class MockT:
    """Duck-typed tenancy (immo_rules DB-free çalışır)."""
    def __init__(self, kaltmiete=0, nk_voraus=0, heizkosten_voraus=None,
                 erstmonat_betrag=None, von=date(2025, 1, 1), bis=None):
        self.kaltmiete = kaltmiete; self.nk_voraus = nk_voraus
        self.heizkosten_voraus = heizkosten_voraus; self.erstmonat_betrag = erstmonat_betrag
        self.von = von; self.bis = bis; self.miete_historie = None


def invariant(t, y, m):
    s = monat_soll(t, y, m); k = monat_kalt_soll(t, y, m)
    n = monat_nk_soll(t, y, m); h = monat_heiz_soll(t, y, m)
    return s, k, n, h, abs(s - (k + n + h)) < 0.005


print("== UNIT: Single-Ledger invariant (soll == kalt+nk+heiz) ==")
for kk, nn, hh, tag in [(500, 100, None, "heiz=None"), (500, 100, 0, "heiz=0"),
                        (500, 100, 45, "heiz=45"), (570, 100, 45, "full"),
                        (0, 0, 0, "hepsi 0"), (999.99, 0.01, 0.01, "cent")]:
    s, k, n, h, ok = invariant(MockT(kk, nn, hh), 2026, 6)
    check(ok, f"{tag}: {s} == {k}+{n}+{h}")

print("\n== UNIT: Warmmiete = Kalt + NK + Heiz ==")
s, k, n, h, _ = invariant(MockT(500, 100, 45), 2026, 6)
check(s == 645.0, f"500+100+45 = 645 (got {s})")
check(h == 45.0, f"monat_heiz_soll = 45 (got {h})")

print("\n== UNIT: NK izolasyonu — heiz monat_nk_soll'a SIZMAZ ==")
n0 = monat_nk_soll(MockT(500, 100, 0), 2026, 6)
n45 = monat_nk_soll(MockT(500, 100, 45), 2026, 6)
check(n0 == n45 == 100.0, f"nk_soll heiz=0 ({n0}) == heiz=45 ({n45}) == 100")

print("\n== REGRESSION: heiz=0 (None) BYTE-IDENTICAL (eski davranış) ==")
for kk, nn in [(500, 100), (333.33, 66.67), (450, 0), (1000, 199.99), (612.5, 87.5)]:
    t = MockT(kk, nn, None); p = month_proration(t, 2026, 6)
    old_soll = round((kk + nn) * p, 2); old_kalt = round(kk * p, 2)
    old_nk = round(old_soll - old_kalt, 2)
    check(monat_soll(t, 2026, 6) == old_soll and monat_kalt_soll(t, 2026, 6) == old_kalt
          and monat_nk_soll(t, 2026, 6) == old_nk,
          f"kalt={kk} nk={nn}: soll/kalt/nk eski ile aynı")

print("\n== UNIT: Erstmonat (gross) — NK/Heiz üste eklenmez ==")
s, k, n, h, ok = invariant(MockT(500, 100, 45, erstmonat_betrag=650, von=date(2026, 6, 1)), 2026, 6)
check(s == 650.0 and n == 100.0 and h == 45.0 and ok,
      f"em=650 gross; split {k}+{n}+{h}; invariant {ok}")

print("\n== UNIT: Kısmi ay (von=15.06, Tagesanteil<1) invariant ==")
_, _, _, _, ok = invariant(MockT(570, 100, 45, von=date(2026, 6, 15)), 2026, 6)
check(ok, "partial month invariant korunur")

# ── INTEGRATION: ORM roundtrip (model -> rules -> serializer) ──
print("\n== INTEGRATION: ORM ImmoTenancy roundtrip ==")
try:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from autotax.models import Base, ImmoTenancy
    from autotax.immo_api import _tenancy_dict, _norm_zahler
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    S = sessionmaker(bind=eng)();
    t = ImmoTenancy(unit_id=1, user_id=1, mieter_name="Sohn", von=date(2026, 3, 1),
                    kaltmiete=290, nk_voraus=70, heizkosten_voraus=45,
                    zahler_typ=_norm_zahler("SOZIALAMT"), zahler_name="Sozialamt Krefeld", personenzahl=4)
    S.add(t); S.commit(); t2 = S.query(ImmoTenancy).first()
    check(t2.heizkosten_voraus == 45 and t2.zahler_typ == "sozialamt", "kolonlar persist edildi")
    s = monat_soll(t2, 2026, 6)
    check(s == 405.0, f"Warmmiete 290+70+45 = 405 (got {s})")
    check(monat_nk_soll(t2, 2026, 6) == 70.0, "nk_soll = 70 (heiz hariç)")
    d = _tenancy_dict(t2)
    check(d["heizkosten_voraus"] == 45 and d["zahler_typ"] == "sozialamt"
          and d["zahler_name"] == "Sozialamt Krefeld", "_tenancy_dict yeni alanları döndürür")
    S.close()
except Exception as e:
    check(False, f"INTEGRATION exception: {e}")

print("\n" + ("❌ FAIL: %d" % FAIL if FAIL else "✅ TÜM TESTLER GEÇTİ (Sprint 1.1)"))
sys.exit(1 if FAIL else 0)
