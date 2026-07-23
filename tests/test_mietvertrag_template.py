"""Sprint 9.0a — Mietvertrag şablon motoru + Unicode font birim testleri.

Kilitlenen davranışlar:
  * Registry dispatch: yeni tip = yeni sözlük girdisi; render() değişmez
  * Kaution 3× cap PER-TYPE (rails tipe bağlı, global değil)
  * Geçersiz kloz ÜRETİLEMEZ (picker'da yok = katalogda yok)
  * Staffel adımları → tablo bloğu
  * Mietpreisbremse: karar verilmez, nötr uyarı toplanır
  * TEMPLATE_VERSION damgası deterministik
  * DejaVu/Vera Unicode font Türkçe glyph basıyor (.notdef yok)

Standalone: PYTHONIOENCODING=utf-8 PYTHONPATH=. python tests/test_mietvertrag_template.py
"""
import os
import sys

os.environ.setdefault("JWT_SECRET", "x" * 44)

from autotax import mietvertrag_template as T

FAIL = 0


def check(cond, msg):
    global FAIL
    print(("  OK  " if cond else "  FAIL ") + msg)
    if not cond:
        FAIL += 1


def _base(typ="wohnraum_unbefristet", **over):
    vj = {
        "vertrag_typ": typ,
        "parteien": {"vermieter": {"name": "Çağrı Şahin GmbH", "adresse": "Königsweg 3, Krefeld"},
                     "mieter": {"name": "Ayşe Öztürk", "adresse": "Güllü Sok. 5"}},
        "objekt": {"adresse": "Wiesenstr. 10, Saarbrücken", "wohnung": "EG links",
                   "wohnflaeche": 72, "zimmer": 3, "keller": True, "schluessel": 3},
        "mietzeit": {"beginn": "2026-09-01"},
        "miete": {"kaltmiete": 700, "nk_voraus": 90, "heizkosten_voraus": 45,
                  "zahlungstermin": "3.", "bankverbindung": "DE12 3456 ..."},
        "kaution": {"betrag": 2100, "art": "bar"},
        "betriebskosten_umlage": ["Wasser", "Müll", "Grundsteuer"],
        "klauseln": {"schoenheitsrep": "keine", "kleinrep": {"aktiv": False}},
    }
    vj.update(over)
    return vj


def _texts(res):
    return " ".join(b.get("text", "") for b in res["blocks"] if b.get("art") in ("absatz", "ueberschrift", "titel"))


print("== Registry / dispatch ==")
check(set(T.supported_types()) == {"wohnraum_unbefristet", "wohnraum_staffel"},
      "supported_types = 2 v1 tipi")
r = T.render(_base())
check(r["template_version"] == T.TEMPLATE_VERSION == 1, "TEMPLATE_VERSION damgası")
check(r["blocks"][0]["art"] == "titel", "ilk blok başlık")
# Registry dispatch kanıtı: bilinmeyen tip render'ı değiştirmeden ValueError
try:
    T.render({"vertrag_typ": "gewerbe"}); check(False, "bilinmeyen tip reddedilmeli")
except ValueError:
    check(True, "bilinmeyen vertrag_typ → ValueError (dispatch registry'den)")

print("\n== Kaution 3× cap (rail PER-TYPE) ==")
r = T.render(_base(kaution={"betrag": 5000}))   # 5000 > 3×700=2100
capped = any("Höchstmaß" in w for w in r["warnings"])
check(capped, "Kaution 5000 > 3×700 → cap + uyarı")
check("2.100,00 €" in _texts(r) or "2100" in str(r["blocks"]), "metinde cap'lenmiş 2100 görünür")
r2 = T.render(_base(kaution={"betrag": 1400}))  # 1400 < 2100
check(not any("Höchstmaß" in w for w in r2["warnings"]), "1400 < cap → uyarı yok")
# rail tipe bağlı: registry'de global sabit değil, tipin rails'inde
check("kaution_max_faktor" in T.VERTRAG_TYPEN["wohnraum_unbefristet"]["rails"],
      "cap faktörü tipin rails'inde (global değil)")

print("\n== Geçersiz kloz ÜRETİLEMEZ ==")
# Schönheitsreparaturen: yalnız 'keine' | 'bgh_gueltig' — geçersiz varyant istense bile katalog
# yalnız iki geçerli metinden birini basar (starrer Fristenplan üretilemez).
r_bad = T.render(_base(klauseln={"schoenheitsrep": "starrer_fristenplan_quote"}))
sr = " ".join(b.get("text", "") for b in r_bad["blocks"])
check("Fristenplan" not in sr or "ohne starren Fristenplan" in sr,
      "geçersiz Schönheitsrep varyantı starrer Fristenplan ÜRETMEZ")
check("nicht auf den Mieter abgewälzt" in sr, "tanınmayan varyant → güvenli default (keine)")
# Kleinreparaturen yalnız cap'lerle geçerli
r_kr = T.render(_base(klauseln={"kleinrep": {"aktiv": True, "einzel_cap": 100, "jahres_cap": 300}}))
krt = " ".join(b.get("text", "") for b in r_kr["blocks"])
check("100,00 €" in krt and "300,00 €" in krt, "Kleinrep aktif → einzel+jahres cap metinde")

print("\n== Staffel ==")
rs = T.render(_base(typ="wohnraum_staffel",
                    mietzeit={"beginn": "2026-09-01",
                              "staffel_schritte": [{"ab": "2026-09-01", "kaltmiete": 700},
                                                   {"ab": "2027-09-01", "kaltmiete": 730}]}))
tab = [b for b in rs["blocks"] if b.get("art") == "tabelle"]
check(any(["2027-09-01", "730,00 €"] in t["rows"] for t in tab), "Staffel adımları tablo bloğunda")

print("\n== Mietpreisbremse: karar verilmez, uyarı toplanır ==")
r = T.render(_base())
mpb = [w for w in r["warnings"] if "Mietpreisbremse" in w]
check(mpb and "keine Aussage" in mpb[0], "Mietpreisbremse nötr uyarı (motor karar vermiyor)")

print("\n== Disclaimer her sözleşmede ==")
check(any(b.get("art") == "disclaimer" for b in T.render(_base())["blocks"]), "disclaimer bloğu var")

print("\n== Unicode font — Türkçe glyph (T1) ==")
from autotax.pdf_fonts import register_unicode_font, FONT_NAME
fn = register_unicode_font()
check(fn == FONT_NAME, "font kaydı FONT_NAME döndürür")
check(register_unicode_font() == FONT_NAME, "idempotent (ikinci çağrı sorunsuz)")
# gerçek glyph kapsamı: kayıtlı fontun face'inde Türkçe karakterler var mı
from reportlab.pdfbase import pdfmetrics
face = pdfmetrics.getFont(FONT_NAME).face
missing = [c for c in "şŞğĞıİçÇöÖüÜ€³" if ord(c) not in face.charToGlyph]
check(not missing, "kayıtlı Unicode font tüm Türkçe+€³ glyph'lerini içeriyor (eksik: %s)" % missing)

print("\n" + ("❌ FAIL: %d" % FAIL if FAIL else "✅ TÜM TESTLER GEÇTİ (Sprint 9.0a)"))
sys.exit(1 if FAIL else 0)
