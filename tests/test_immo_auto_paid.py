"""AUTO-PAID (Dauerzahlung) model — default 'paid', debt only from offene_monate.

A tenant set up once (von/Kaltmiete) shows NO debt by default; the landlord enters
NOTHING monthly. Only a month explicitly in offene_monate becomes debt. Verified on
_accounting (the Immobilien Übersicht screen). today pinned 2026-06-23.
Run:  PYTHONIOENCODING=utf-8 PYTHONPATH=. python tests/test_immo_auto_paid.py
"""
import os
import sys
from datetime import date

os.environ.setdefault("JWT_SECRET", "x" * 44)

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from autotax.models import Base, ImmoProperty, ImmoUnit, ImmoTenancy
from autotax import immo_api


class _FakeDate(date):
    @classmethod
    def today(cls):
        return date(2026, 6, 23)


immo_api.date = _FakeDate
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
    immo_api.SessionLocal = S
    db = S()
    db.add(ImmoProperty(id=10, user_id=1, name="Haus"))
    db.add(ImmoUnit(id=1, property_id=10, user_id=1, name="EG", soll_miete=470))
    db.add(ImmoTenancy(id=101, unit_id=1, user_id=1, mieter_name="VANELLE", von=date(2026, 6, 15), kaltmiete=470, nk_voraus=70))
    db.commit()
    t = db.query(ImmoTenancy).get(101)

    print("\n[default = auto-paid] kiracı kurulur, aylık giriş YOK → borç 0")
    ok(t.auto_paid in (True, None), f"auto_paid default True (got {t.auto_paid})")
    ok(immo_api._arrears_auto(db, 1, t, 2026) == 0, "_arrears_auto = 0 (assumed paid)")
    acc = immo_api._accounting(db, 1, 10, 2026)
    tr = acc["tenancies"][0]
    print(f"       Übersicht: soll={tr['soll']} ist={tr['ist']} rueckstand={tr['rueckstand']} | zahlungsausfall={acc['summe']['zahlungsausfall']}")
    ok(tr["rueckstand"] == 0, "Übersicht Rückstand = 0 (eskiden 470 sahte borç)")
    ok(acc["summe"]["zahlungsausfall"] == 0, "Mietrückstand banner = 0")
    ok(tr["ist"] == tr["soll"] and tr["soll"] == 470, "Ist = Soll = 470 (ödendi varsayıldı → zarar yok)")

    print("\n[istisna: Haziran ödenmedi işaretle]")
    t.offene_monate = '["2026-06"]'; db.commit()
    ok(immo_api._arrears_auto(db, 1, t, 2026) == 470, f"_arrears_auto = 470 (1 ay borç) (got {immo_api._arrears_auto(db,1,t,2026)})")
    acc2 = immo_api._accounting(db, 1, 10, 2026)
    ok(acc2["tenancies"][0]["rueckstand"] == 470, "Übersicht Rückstand = 470")
    ok(acc2["summe"]["zahlungsausfall"] == 470, "banner = 470")

    print("\n[gelecek ay işaretlense bile borç değil]")
    t.offene_monate = '["2026-09"]'; db.commit()
    ok(immo_api._arrears_auto(db, 1, t, 2026) == 0, "Eylül (gelecek) → due-to-date dışı → 0")

    print("\n[auto_paid=False → klasik manuel (Soll−Ist)]")
    t.offene_monate = None; t.auto_paid = False; db.commit()
    ok(immo_api._arrears_auto(db, 1, t, 2026) == 470, "manuel mod: 1 ay Soll 470 − Ist 0 = 470")

    print(f"\n=== AUTO-PAID: {PASS} passed, {FAIL} failed ===")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
