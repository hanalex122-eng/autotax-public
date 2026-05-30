"""Steuererklärung (annual tax return) helpers.

MVP scope (2026-05-30):
- Form schema definition (Mantelbogen + Anlage S + Anlage Vorsorgeaufwand).
- Auto-fill helpers from existing user/company/EÜR data.
- Validation rules (required fields, format checks).
- PDF generation skeleton (real layout comes in next iteration).

OUT OF SCOPE for now:
- ELSTER XML/XBRL export
- Anlage KAP / R / V (special situations)
- Multi-year parallel work (only one year at a time)

See `.claude/steuererklaerung_plan.md` for full plan.
"""
from __future__ import annotations

import json
import logging
from datetime import date
from typing import Any, Optional

logger = logging.getLogger("autotax.declaration")


# ───────────────────────────────────────────────────────────────────
# Form schema — single source of truth for field metadata.
# Used by both backend validation and frontend rendering.
# ───────────────────────────────────────────────────────────────────

FORM_SECTIONS = [
    {
        "key": "mantelbogen",
        "title_de": "Mantelbogen (ESt 1 A)",
        "title_tr": "Ana Form (Mantelbogen)",
        "fields": [
            {"key": "steuer_id",      "label_de": "Steuer-ID (11-stellig)",       "label_tr": "Vergi kimlik no (11 hane)",          "type": "text",   "required": True,  "pattern": r"^\d{11}$", "zeile_de": "Zeile 4",
             "hint_de": "Findest du auf jedem Steuerbescheid oder Lohnabrechnung. Beispiel: 12345678901",
             "hint_tr": "Her Steuerbescheid veya Lohnabrechnung'da bulursun. Örnek: 12345678901"},
            {"key": "steuer_nummer",  "label_de": "Steuernummer (optional)",       "label_tr": "Steuernummer (opsiyonel)",            "type": "text",   "required": False, "zeile_de": "Zeile 1",
             "hint_de": "Vom Finanzamt erteilt — anders als Steuer-ID. Format z.B. 040/123/45678",
             "hint_tr": "Finanzamt'tan alınan numara — Steuer-ID'den farklı. Format örn. 040/123/45678"},
            {"key": "vorname",        "label_de": "Vorname",                       "label_tr": "Ad",                                  "type": "text",   "required": True, "zeile_de": "Zeile 6",
             "hint_de": "Wie im Personalausweis",
             "hint_tr": "Kimlik kartındaki gibi"},
            {"key": "nachname",       "label_de": "Nachname",                      "label_tr": "Soyad",                               "type": "text",   "required": True, "zeile_de": "Zeile 6",
             "hint_de": "Wie im Personalausweis",
             "hint_tr": "Kimlik kartındaki gibi"},
            {"key": "geburtsdatum",   "label_de": "Geburtsdatum",                  "label_tr": "Doğum tarihi",                        "type": "date",   "required": True, "zeile_de": "Zeile 8",
             "hint_de": "TT.MM.JJJJ",
             "hint_tr": "GG.AA.YYYY"},
            {"key": "religion",       "label_de": "Religion",                      "label_tr": "Din",                                 "type": "select", "required": True, "zeile_de": "Zeile 10",
             "options": [{"v": "none", "de": "Keine", "tr": "Yok"}, {"v": "ev", "de": "Evangelisch", "tr": "Evanjelik"}, {"v": "rk", "de": "Römisch-katholisch", "tr": "Katolik"}, {"v": "other", "de": "Andere", "tr": "Diğer"}],
             "hint_de": "Nur Kirchensteuer-pflichtige Konfessionen ankreuzen. Muslime / Atheisten → 'Keine'",
             "hint_tr": "Sadece kilise vergisi yükümlü dinler. Müslüman / Ateist → 'Yok'"},
            {"key": "strasse",        "label_de": "Straße + Hausnummer",           "label_tr": "Sokak + ev no",                       "type": "text",   "required": True, "zeile_de": "Zeile 13",
             "hint_de": "Wohnadresse zum 31.12. des Steuerjahres",
             "hint_tr": "Vergi yılı 31.12 itibarıyla ev adresi"},
            {"key": "plz",            "label_de": "PLZ",                           "label_tr": "Posta kodu",                          "type": "text",   "required": True,  "pattern": r"^\d{5}$", "zeile_de": "Zeile 14",
             "hint_de": "5-stellig",
             "hint_tr": "5 hane"},
            {"key": "ort",            "label_de": "Ort",                           "label_tr": "Şehir",                               "type": "text",   "required": True, "zeile_de": "Zeile 14",
             "hint_de": "Stadt / Gemeinde",
             "hint_tr": "Şehir / belediye"},
            {"key": "familienstand",  "label_de": "Familienstand",                 "label_tr": "Medeni hal",                          "type": "select", "required": True, "zeile_de": "Zeile 15",
             "options": [{"v": "ledig", "de": "Ledig", "tr": "Bekar"}, {"v": "verheiratet", "de": "Verheiratet", "tr": "Evli"}, {"v": "geschieden", "de": "Geschieden", "tr": "Boşanmış"}, {"v": "verwitwet", "de": "Verwitwet", "tr": "Dul"}],
             "hint_de": "Status zum 31.12. des Steuerjahres. Verheiratet → Splittingtarif möglich.",
             "hint_tr": "Vergi yılı 31.12 itibarıyla durum. Evli → Splittingtarif olası."},
            {"key": "steuerklasse",   "label_de": "Steuerklasse (1-6)",            "label_tr": "Vergi sınıfı (1-6)",                  "type": "select", "required": False, "zeile_de": "LSB Zeile 7",
             "options": [{"v":"","de":"—","tr":"—"},{"v":"1","de":"I (ledig)","tr":"I (bekar)"},{"v":"2","de":"II (alleinerziehend)","tr":"II (yalnız ebeveyn)"},{"v":"3","de":"III (verh. höherer Verdiener)","tr":"III (evli üst gelir)"},{"v":"4","de":"IV (verh. gleich)","tr":"IV (evli eşit)"},{"v":"5","de":"V (verh. niedrigerer)","tr":"V (evli alt gelir)"},{"v":"6","de":"VI (Zweitjob)","tr":"VI (ikinci iş)"}],
             "hint_de": "Aus deiner Lohnsteuerbescheinigung (Zeile 7). III/V = klassische Ehe-Kombi, IV/IV ähnliche Verdienste.",
             "hint_tr": "Lohnsteuerbescheinigung'dan (Zeile 7). III/V evli klasik kombo, IV/IV eşit gelirlerde."},
            {"key": "iban",           "label_de": "IBAN (Erstattung)",             "label_tr": "IBAN (iade için)",                    "type": "text",   "required": True,  "pattern": r"^DE\d{20}$", "zeile_de": "Zeile 23",
             "hint_de": "Wohin soll das Finanzamt eine Erstattung überweisen? Nur deutsche IBAN.",
             "hint_tr": "Finanzamt iade tutarı nereye gönderecek? Sadece Alman IBAN."},
            {"key": "kontoinhaber",   "label_de": "Kontoinhaber",                  "label_tr": "Hesap sahibi",                        "type": "text",   "required": True, "zeile_de": "Zeile 24",
             "hint_de": "Name auf dem Konto — bei eigenem Konto: dein Name",
             "hint_tr": "Hesap üstündeki isim — kendi hesabınsa: kendi adın"},
        ],
    },
    {
        "key": "anlage_ehepartner",
        "title_de": "Ehepartner (nur bei Zusammenveranlagung)",
        "title_tr": "Eş bilgileri (sadece birlikte beyan için)",
        "conditional_on": {"field": "familienstand", "value": "verheiratet"},
        "fields": [
            {"key": "spouse_vorname",      "label_de": "Vorname Ehepartner",        "label_tr": "Eş adı",                 "type": "text",   "required": False, "zeile_de": "Zeile 18",
             "hint_de": "Wie im Personalausweis des Ehepartners.",
             "hint_tr": "Eşin kimlik kartındaki adı."},
            {"key": "spouse_nachname",     "label_de": "Nachname Ehepartner",       "label_tr": "Eş soyadı",              "type": "text",   "required": False, "zeile_de": "Zeile 18",
             "hint_de": "Wie im Personalausweis.",
             "hint_tr": "Kimlikteki gibi."},
            {"key": "spouse_geburtsdatum", "label_de": "Geburtsdatum Ehepartner",   "label_tr": "Eş doğum tarihi",        "type": "date",   "required": False, "zeile_de": "Zeile 19",
             "hint_de": "TT.MM.JJJJ", "hint_tr": "GG.AA.YYYY"},
            {"key": "spouse_steuer_id",    "label_de": "Steuer-ID Ehepartner (11-stellig)", "label_tr": "Eş vergi kimlik (11 hane)", "type": "text", "required": False, "pattern": r"^\d{11}$", "zeile_de": "Zeile 20",
             "hint_de": "Vom Bundeszentralamt für Steuern erteilt. Aus dem Schreiben oder Lohnsteuerbescheinigung des Partners.",
             "hint_tr": "Bundeszentralamt'tan verilir. Eşin LSB veya Schreiben'inden."},
            {"key": "spouse_religion",     "label_de": "Religion Ehepartner",       "label_tr": "Eş dini",                "type": "select", "required": False, "zeile_de": "Zeile 21",
             "options": [{"v":"none","de":"Keine","tr":"Yok"},{"v":"ev","de":"Evangelisch","tr":"Evanjelik"},{"v":"rk","de":"Römisch-katholisch","tr":"Katolik"},{"v":"other","de":"Andere","tr":"Diğer"}],
             "hint_de": "Für Kirchensteuer-Berechnung.",
             "hint_tr": "Kilise vergisi için."},
            {"key": "spouse_lohn_brutto",  "label_de": "Bruttoarbeitslohn Ehepartner (€)", "label_tr": "Eş brüt maaş (€)", "type": "number", "required": False, "default": 0, "zeile_de": "Zeile 27",
             "hint_de": "Falls Ehepartner angestellt. Aus seiner/ihrer Lohnsteuerbescheinigung Zeile 3.",
             "hint_tr": "Eş bordrolu çalışıyorsa LSB Zeile 3."},
            {"key": "spouse_lohnsteuer",   "label_de": "Lohnsteuer Ehepartner (€)", "label_tr": "Eş Lohnsteuer (€)",     "type": "number", "required": False, "default": 0, "zeile_de": "Zeile 28",
             "hint_de": "Lohnsteuerbescheinigung Zeile 4.",
             "hint_tr": "LSB Zeile 4."},
            {"key": "veranlagungsart",     "label_de": "Veranlagungsart",           "label_tr": "Beyan türü",             "type": "select", "required": False, "zeile_de": "Zeile 24",
             "options": [{"v":"zusammen","de":"Zusammenveranlagung (Splittingtarif)","tr":"Birlikte beyan (Splitting)"},{"v":"einzeln","de":"Einzelveranlagung","tr":"Ayrı beyan"}],
             "hint_de": "Zusammenveranlagung: Splittingtarif → meist günstiger. Einzeln nur in Ausnahmefällen.",
             "hint_tr": "Birlikte beyan: Splitting tarifesi → genelde avantajlı. Ayrı çok ender."},
        ],
    },
    {
        "key": "anlage_s",
        "title_de": "Anlage S — Selbständige Tätigkeit",
        "title_tr": "Anlage S — Serbest meslek",
        "fields": [
            {"key": "taetigkeit",         "label_de": "Tätigkeit (z.B. IT-Consulting)", "label_tr": "Meslek (örn. IT danışmanlık)",  "type": "text",   "required": True, "zeile_de": "Zeile 4",
             "hint_de": "Kurze Beschreibung deiner freiberuflichen Tätigkeit (1-3 Wörter)",
             "hint_tr": "Serbest mesleki faaliyetinin kısa açıklaması (1-3 kelime)"},
            {"key": "gewinn_eur",         "label_de": "Gewinn aus EÜR (€)",             "label_tr": "EÜR kazancı (€)",                "type": "number", "required": True, "auto_fill_from": "eur_profit", "zeile_de": "Zeile 5",
             "hint_de": "Einnahmen minus Ausgaben für das gesamte Jahr. Wir füllen automatisch aus deinen Belegen.",
             "hint_tr": "Yıl boyunca gelirler eksi giderler. Belgelerinden otomatik doldurulur."},
            {"key": "veraeusserungsgewinn", "label_de": "Veräußerungsgewinn (€)",       "label_tr": "Sermaye gain (€)",               "type": "number", "required": False, "default": 0, "zeile_de": "Zeile 21",
             "hint_de": "Verkauf von Praxis / Firma / Wertpapieren. In den meisten Fällen 0.",
             "hint_tr": "Praxis / firma / hisse satışından gelen. Çoğu durumda 0."},
        ],
    },
    {
        "key": "anlage_n",
        "title_de": "Anlage N — Lohn aus Anstellung (optional)",
        "title_tr": "Anlage N — Maaş (varsa, opsiyonel)",
        "fields": [
            {"key": "lohn_brutto", "label_de": "Bruttoarbeitslohn (Jahres)", "label_tr": "Yıllık brüt maaş",     "type": "number", "required": False, "default": 0, "zeile_de": "Zeile 3",
             "hint_de": "Aus deiner Lohnsteuerbescheinigung Zeile 3 (Bruttoarbeitslohn).",
             "hint_tr": "Lohnsteuerbescheinigung Zeile 3'ten al."},
            {"key": "lohnsteuer", "label_de": "Einbehaltene Lohnsteuer (€)", "label_tr": "Kesilen Lohnsteuer (€)", "type": "number", "required": False, "default": 0, "zeile_de": "Zeile 4",
             "hint_de": "Lohnsteuerbescheinigung Zeile 4 (einbehaltene Lohnsteuer).",
             "hint_tr": "Lohnsteuerbescheinigung Zeile 4."},
            {"key": "soli_n",     "label_de": "Solidaritätszuschlag (€)",     "label_tr": "Soli vergisi (€)",       "type": "number", "required": False, "default": 0, "zeile_de": "Zeile 5",
             "hint_de": "Lohnsteuerbescheinigung Zeile 5.", "hint_tr": "Lohnsteuerbescheinigung Zeile 5."},
            {"key": "kirchensteuer", "label_de": "Kirchensteuer (€)",          "label_tr": "Kilise vergisi (€)",     "type": "number", "required": False, "default": 0, "zeile_de": "Zeile 6",
             "hint_de": "Falls religiöse Konfession; sonst 0.", "hint_tr": "Dini mensubiyet varsa; yoksa 0."},
            {"key": "werbungskosten_n", "label_de": "Werbungskosten (Pauschbetrag €1.230 oder höher)", "label_tr": "Werbungskosten (sabit €1.230 veya yüksek)", "type": "number", "required": False, "default": 1230, "zeile_de": "Zeile 31",
             "hint_de": "Arbeitnehmer-Pauschbetrag (2025: €1.230). Höher nur wenn nachgewiesen.",
             "hint_tr": "İşçi sabit indirimi (2025: €1.230). Yüksek için kanıt gerekir."},
            # Pendlerpauschale — Entfernungspauschale Wohnung-Arbeitsstätte
            {"key": "pendler_km",    "label_de": "Entfernung Wohnung-Arbeitsstätte (km, einfache Strecke)", "label_tr": "Ev-iş yeri mesafesi (km, tek yön)", "type": "number", "required": False, "default": 0, "zeile_de": "Zeile 32",
             "hint_de": "Kürzeste Strecke (Google Maps) zwischen Wohnung und erster Tätigkeitsstätte. NUR einfache Strecke, nicht hin-und-zurück.",
             "hint_tr": "Ev ve birinci iş yeri arasındaki EN KISA mesafe (tek yön). Gidiş-dönüş değil."},
            {"key": "pendler_tage",  "label_de": "Arbeitstage pro Jahr (Pendlertage)", "label_tr": "Yıllık iş günü sayısı", "type": "number", "required": False, "default": 220, "zeile_de": "Zeile 33",
             "hint_de": "2024 typisch 220-230 Tage. Krankheit/Urlaub abziehen. Homeoffice-Tage NICHT zählen.",
             "hint_tr": "2024 tipik 220-230 gün. Hastalık/tatil çıkar. Homeoffice günleri SAYMA."},
            {"key": "pendler_mittel", "label_de": "Verkehrsmittel", "label_tr": "Ulaşım türü", "type": "select", "required": False, "zeile_de": "Zeile 34",
             "options": [{"v":"auto","de":"Auto","tr":"Araba"},{"v":"oeffentlich","de":"Öffentliche Verkehrsmittel","tr":"Toplu taşıma"},{"v":"fahrrad","de":"Fahrrad","tr":"Bisiklet"},{"v":"zu_fuss","de":"Zu Fuß","tr":"Yürüyerek"},{"v":"mix","de":"Gemischt","tr":"Karışık"}],
             "hint_de": "Entfernungspauschale gilt für alle Verkehrsmittel gleich (€0.30 bis 20km, €0.38 ab 21km, 2024).",
             "hint_tr": "Entfernungspauschale tüm araçlar için aynı (€0.30 ilk 20km, €0.38 21km üstü, 2024)."},
            {"key": "homeoffice_tage", "label_de": "Homeoffice-Tage (€6/Tag bis €1.260)", "label_tr": "Ev ofis günü (€6/gün, max €1.260)", "type": "number", "required": False, "default": 0, "zeile_de": "Zeile 44",
             "hint_de": "2024: €6/Tag, max 210 Tage = €1.260. Tag mit Homeoffice — keine zusätzliche Pendlerpauschale für denselben Tag.",
             "hint_tr": "2024: günlük €6, max 210 gün = €1.260. Homeoffice günü — aynı gün için Pendlerpauschale ALMA."},
        ],
    },
    {
        "key": "anlage_v",
        "title_de": "Anlage V — Vermietung & Verpachtung (optional)",
        "title_tr": "Anlage V — Kira gelirleri (varsa, opsiyonel)",
        "fields": [
            {"key": "v_adresse",    "label_de": "Adresse Mietobjekt",          "label_tr": "Kiralanan mülk adresi",  "type": "text",   "required": False, "zeile_de": "Zeile 1",
             "hint_de": "Straße + Hausnummer + PLZ + Ort der vermieteten Immobilie.",
             "hint_tr": "Kiralanan mülkün sokak + ev no + PLZ + şehri."},
            {"key": "v_einnahmen", "label_de": "Mieteinnahmen Jahres (€)",     "label_tr": "Yıllık kira geliri (€)",  "type": "number", "required": False, "default": 0, "zeile_de": "Zeile 8",
             "hint_de": "Summe aller Mieteinnahmen ohne Nebenkosten-Vorauszahlungen.",
             "hint_tr": "Tüm kira gelirlerinin toplamı (yan giderler ön ödemeleri hariç)."},
            {"key": "v_nebenkosten", "label_de": "Umlagefähige Nebenkosten erhalten (€)", "label_tr": "Alınan ortak giderler (€)", "type": "number", "required": False, "default": 0, "zeile_de": "Zeile 13",
             "hint_de": "Vorauszahlungen vom Mieter (Wasser, Heizung etc).",
             "hint_tr": "Kiracıdan alınan ön ödemeler (su, ısınma vs.)."},
            {"key": "v_afa",       "label_de": "AfA Gebäude 2% pro Jahr (€)",  "label_tr": "Yıllık bina AfA %2 (€)",   "type": "number", "required": False, "default": 0, "zeile_de": "Zeile 33",
             "hint_de": "Anschaffungskosten Gebäude × 2% (50 Jahre Nutzungsdauer).",
             "hint_tr": "Bina edinme bedeli × %2 (50 yıl kullanım ömrü)."},
            {"key": "v_zinsen",    "label_de": "Schuldzinsen Darlehen (€)",    "label_tr": "Kredi faizleri (€)",       "type": "number", "required": False, "default": 0, "zeile_de": "Zeile 36",
             "hint_de": "Hypothek-Zinsen für die Mietimmobilie.",
             "hint_tr": "Kira mülkü için ipotek faizleri."},
            {"key": "v_erhaltung", "label_de": "Erhaltungsaufwand (Reparatur) (€)", "label_tr": "Bakım/onarım gideri (€)", "type": "number", "required": False, "default": 0, "zeile_de": "Zeile 39",
             "hint_de": "Reparaturen, Instandhaltung (sofort absetzbar). Größere Umbauten sind Herstellungskosten.",
             "hint_tr": "Onarım, bakım (hemen düşülebilir). Büyük tadilatlar Herstellungskosten'dir."},
            {"key": "v_grundsteuer", "label_de": "Grundsteuer + Versicherung (€)", "label_tr": "Emlak vergisi + sigorta (€)", "type": "number", "required": False, "default": 0, "zeile_de": "Zeile 47",
             "hint_de": "Grundsteuer, Wohngebäudeversicherung etc.",
             "hint_tr": "Emlak vergisi, bina sigortası vb."},
            {"key": "v_sonst",     "label_de": "Sonstige Werbungskosten (€)",  "label_tr": "Diğer giderler (€)",       "type": "number", "required": False, "default": 0, "zeile_de": "Zeile 50",
             "hint_de": "Hausverwaltung, Inserate, Anwaltskosten etc.",
             "hint_tr": "Yönetim, ilan, avukat masrafları vs."},
        ],
    },
    {
        "key": "anlage_kind",
        "title_de": "Anlage Kind (optional)",
        "title_tr": "Anlage Kind — Çocuklar (varsa, opsiyonel)",
        "is_repeated_array": True,  # frontend renders dynamic list
        "array_key": "kinder",      # field name in data dict
        "fields": [
            # Per-child schema — used by frontend to render row inputs
            {"key": "vorname",         "label_de": "Vorname",            "label_tr": "Ad",                  "type": "text", "required": True, "zeile_de": "Zeile 4"},
            {"key": "geburtsdatum",    "label_de": "Geburtsdatum",       "label_tr": "Doğum tarihi",        "type": "date", "required": True, "zeile_de": "Zeile 4"},
            {"key": "steuer_id",       "label_de": "Steuer-ID Kind (11-stellig, wichtig für Kinderfreibetrag)", "label_tr": "Çocuk vergi kimlik (11 hane, Kinderfreibetrag için önemli)", "type": "text", "required": False, "pattern": r"^\d{11}$", "zeile_de": "Zeile 7",
             "hint_de": "Aus dem Schreiben des Bundeszentralamts für Steuern oder Geburtsurkunde. Ohne Steuer-ID kein Kinderfreibetrag.",
             "hint_tr": "Bundeszentralamt'tan veya doğum belgesinden. Steuer-ID olmadan Kinderfreibetrag yok."},
            {"key": "kindergeld",      "label_de": "Kindergeld bezogen",  "label_tr": "Kindergeld alındı mı", "type": "select", "required": True, "zeile_de": "Zeile 13",
             "options": [{"v":"ja","de":"Ja","tr":"Evet"},{"v":"nein","de":"Nein","tr":"Hayır"}]},
            {"key": "shared_custody",  "label_de": "Geteiltes Sorgerecht (50/50)", "label_tr": "Ortak velayet (50/50)", "type": "select", "required": False, "zeile_de": "Zeile 17",
             "options": [{"v":"nein","de":"Nein","tr":"Hayır"},{"v":"ja","de":"Ja","tr":"Evet"}]},
            # Behinderung des Kindes — wichtig: kann auf Eltern übertragen werden
            {"key": "behinderung_gdb",  "label_de": "Grad der Behinderung (Kind, %)", "label_tr": "Engelli oranı (çocuk, %)", "type": "select", "required": False, "zeile_de": "Zeile 65",
             "options": [{"v":"","de":"Keine","tr":"Yok"},{"v":"20","de":"20%","tr":"%20"},{"v":"30","de":"30%","tr":"%30"},{"v":"40","de":"40%","tr":"%40"},{"v":"50","de":"50%","tr":"%50"},{"v":"60","de":"60%","tr":"%60"},{"v":"70","de":"70%","tr":"%70"},{"v":"80","de":"80%","tr":"%80"},{"v":"90","de":"90%","tr":"%90"},{"v":"100","de":"100%","tr":"%100"}]},
            {"key": "behinderung_merkmal", "label_de": "Merkzeichen (H/Bl/TBl → erhöhter Pauschbetrag €7.400)", "label_tr": "İşaret (H/Bl/TBl)", "type": "select", "required": False, "zeile_de": "Zeile 66",
             "options": [{"v":"","de":"—","tr":"—"},{"v":"G","de":"G (gehbehindert)","tr":"G"},{"v":"aG","de":"aG (außergewöhnlich gehbehindert)","tr":"aG"},{"v":"H","de":"H (hilflos)","tr":"H"},{"v":"Bl","de":"Bl (blind)","tr":"Bl"},{"v":"TBl","de":"TBl (taubblind)","tr":"TBl"},{"v":"RF","de":"RF (Rundfunkbefreiung)","tr":"RF"}]},
            {"key": "behindert_uebertrag", "label_de": "Pauschbetrag auf Eltern übertragen?", "label_tr": "Pauschbetrag ebeveynlere mi?", "type": "select", "required": False, "zeile_de": "Zeile 67",
             "options": [{"v":"ja","de":"Ja (auf mich übertragen)","tr":"Evet"},{"v":"nein","de":"Nein","tr":"Hayır"}]},
        ],
    },
    {
        "key": "anlage_behinderung",
        "title_de": "Anlage Außergewöhnliche Belastungen — Behinderung (eigene)",
        "title_tr": "Olağanüstü yük — Engellilik (kendin)",
        "fields": [
            {"key": "eigene_gdb", "label_de": "Grad der Behinderung (eigene, %)", "label_tr": "Kendi engelli oranı (%)", "type": "select", "required": False, "zeile_de": "Zeile 4",
             "options": [{"v":"","de":"Keine","tr":"Yok"},{"v":"20","de":"20%","tr":"%20"},{"v":"30","de":"30%","tr":"%30"},{"v":"40","de":"40%","tr":"%40"},{"v":"50","de":"50%","tr":"%50"},{"v":"60","de":"60%","tr":"%60"},{"v":"70","de":"70%","tr":"%70"},{"v":"80","de":"80%","tr":"%80"},{"v":"90","de":"90%","tr":"%90"},{"v":"100","de":"100%","tr":"%100"}],
             "hint_de": "Aus deinem Schwerbehindertenausweis / Bescheid des Versorgungsamts.",
             "hint_tr": "Engellilik kartından / Versorgungsamt belgesinden."},
            {"key": "eigene_merkmal", "label_de": "Merkzeichen (H/Bl/TBl → €7.400)", "label_tr": "İşaret (H/Bl/TBl)", "type": "select", "required": False, "zeile_de": "Zeile 5",
             "options": [{"v":"","de":"—","tr":"—"},{"v":"G","de":"G (gehbehindert)","tr":"G"},{"v":"aG","de":"aG (außergewöhnlich gehbehindert)","tr":"aG"},{"v":"H","de":"H (hilflos)","tr":"H"},{"v":"Bl","de":"Bl (blind)","tr":"Bl"},{"v":"TBl","de":"TBl (taubblind)","tr":"TBl"}],
             "hint_de": "H / Bl / TBl bedeuten erhöhter Pauschbetrag €7.400 unabhängig vom GdB.",
             "hint_tr": "H / Bl / TBl: GdB'den bağımsız €7.400 yüksek tazminat."},
            {"key": "pflege_grad",     "label_de": "Pflegegrad (1-5)",              "label_tr": "Bakım derecesi (1-5)", "type": "select", "required": False, "zeile_de": "Zeile 14",
             "options": [{"v":"","de":"Keiner","tr":"Yok"},{"v":"1","de":"Pflegegrad 1","tr":"Derece 1"},{"v":"2","de":"Pflegegrad 2","tr":"Derece 2"},{"v":"3","de":"Pflegegrad 3","tr":"Derece 3"},{"v":"4","de":"Pflegegrad 4","tr":"Derece 4"},{"v":"5","de":"Pflegegrad 5","tr":"Derece 5"}],
             "hint_de": "Pflegegrad 2-5 berechtigt zum Pflege-Pauschbetrag (€600-€1.800).",
             "hint_tr": "Bakım derecesi 2-5 Pflege-Pauschbetrag hakkı verir (€600-€1.800)."},
        ],
    },
    {
        "key": "anlage_aussergewohnliche",
        "title_de": "Außergewöhnliche Belastungen (Krankheit / Pflege)",
        "title_tr": "Olağanüstü Yük (Hastalık / Bakım)",
        "fields": [
            {"key": "krankheitskosten",   "label_de": "Krankheitskosten (€)",       "label_tr": "Hastalık masrafları (€)", "type": "number", "required": False, "default": 0, "zeile_de": "Zeile 13",
             "hint_de": "Selbst getragene Arzt-, Zahn-, Apothekenkosten (nicht erstattet). Über der zumutbaren Belastung absetzbar.",
             "hint_tr": "Kendi ödediğin doktor, diş, eczane masrafları (geri alınmamış). Makul yük üstü düşülebilir."},
            {"key": "pflegekosten",       "label_de": "Pflegekosten (eigene/Angehörige) (€)", "label_tr": "Bakım masrafları (€)", "type": "number", "required": False, "default": 0, "zeile_de": "Zeile 14",
             "hint_de": "Kosten für Pflegeheim, ambulante Pflege, etc.",
             "hint_tr": "Bakım evi, evde bakım masrafları."},
            {"key": "bestattungskosten", "label_de": "Bestattungskosten (€)",       "label_tr": "Cenaze masrafları (€)", "type": "number", "required": False, "default": 0, "zeile_de": "Zeile 16",
             "hint_de": "Wenn der Nachlass nicht ausreicht, absetzbar.",
             "hint_tr": "Miras yetmezse düşülebilir."},
            {"key": "scheidungskosten",  "label_de": "Scheidungskosten (€, eingeschränkt)", "label_tr": "Boşanma masrafları (€)", "type": "number", "required": False, "default": 0, "zeile_de": "Zeile 18",
             "hint_de": "Seit 2013 stark eingeschränkt absetzbar; nur Existenzgrundlage betreffende Anteile.",
             "hint_tr": "2013'ten sonra çok sınırlı; sadece yaşam gerekliliği kısmı."},
            {"key": "kurkosten",         "label_de": "Kur / Sanatorium (€)",        "label_tr": "Kür / sanatoryum (€)", "type": "number", "required": False, "default": 0, "zeile_de": "Zeile 19",
             "hint_de": "Vorab amtsärztliches Attest erforderlich.",
             "hint_tr": "Önceden Amtsarzt raporu gerekli."},
        ],
    },
    {
        "key": "anlage_kap",
        "title_de": "Anlage KAP — Kapitalerträge (optional)",
        "title_tr": "Anlage KAP — Sermaye gelirleri (varsa, opsiyonel)",
        "fields": [
            {"key": "kap_zinsen",     "label_de": "Zinsen + Dividenden (€)", "label_tr": "Faiz + temettü (€)", "type": "number", "required": False, "default": 0, "zeile_de": "Zeile 7",
             "hint_de": "Aus Steuerbescheinigung der Bank. Über Freistellungsauftrag €1.000 (Single) / €2.000 (verheiratet) hinaus.",
             "hint_tr": "Banka vergi belgesinden. Freistellungsauftrag €1.000 (bekar) / €2.000 (evli) üstü."},
            {"key": "kap_kursgewinn", "label_de": "Kursgewinne / Aktien-Verkauf (€)", "label_tr": "Hisse satış kazancı (€)", "type": "number", "required": False, "default": 0, "zeile_de": "Zeile 8",
             "hint_de": "Realisierte Gewinne aus Aktien / ETF Verkauf.",
             "hint_tr": "Gerçekleşen hisse/ETF satış kazancı."},
            {"key": "kap_quellensteuer", "label_de": "Einbehaltene Kapitalertragsteuer (€)", "label_tr": "Kesilen sermaye vergisi (€)", "type": "number", "required": False, "default": 0, "zeile_de": "Zeile 37",
             "hint_de": "25% Kapitalertragsteuer + Soli + ggf. Kirchensteuer aus Steuerbescheinigung.",
             "hint_tr": "%25 sermaye vergisi + Soli + (varsa) kilise vergisi."},
            {"key": "kap_quellensteuer_ausland", "label_de": "Anrechenbare ausländische Quellensteuer (€)", "label_tr": "Mahsup edilebilir yabancı vergi (€)", "type": "number", "required": False, "default": 0, "zeile_de": "Zeile 41",
             "hint_de": "Z.B. US-Withholding-Tax auf US-Aktien-Dividenden.",
             "hint_tr": "Örn. ABD hisselerinde alınan vergi."},
            {"key": "freistellungsauftrag", "label_de": "Freistellungsauftrag genutzt (€)", "label_tr": "Freistellungsauftrag (€)", "type": "number", "required": False, "default": 0, "zeile_de": "Zeile 12",
             "hint_de": "Sparer-Pauschbetrag 2025: €1.000 Single, €2.000 verheiratet.",
             "hint_tr": "Sparer-Pauschbetrag 2025: bekar €1.000, evli €2.000."},
        ],
    },
    {
        "key": "anlage_sonderausgaben",
        "title_de": "Sonderausgaben & §35a (haushaltsnahe)",
        "title_tr": "Özel giderler + §35a (ev hizmetleri)",
        "fields": [
            {"key": "spenden_geld",    "label_de": "Spenden — Geldspenden gemeinnützig (€)",  "label_tr": "Geldspende (€)",        "type": "number", "required": False, "default": 0, "zeile_de": "Zeile 12",
             "hint_de": "Steuerlich begünstigt bis 20% des Gesamtbetrags der Einkünfte. Spendenbescheinigung Pflicht.",
             "hint_tr": "Toplam gelirin %20'sine kadar düşülebilir. Spendenbescheinigung zorunlu."},
            {"key": "spenden_partei",  "label_de": "Spenden Parteien (€)",                    "label_tr": "Parti bağışı (€)",       "type": "number", "required": False, "default": 0, "zeile_de": "Zeile 16",
             "hint_de": "50% absetzbar bis €825 Single / €1.650 Verheiratet (§34g EStG).",
             "hint_tr": "%50 düşülebilir; bekar €825 / evli €1.650'ye kadar."},
            {"key": "steuerberater",   "label_de": "Steuerberaterkosten (privat) (€)",        "label_tr": "Mali müşavir ücreti (€)", "type": "number", "required": False, "default": 0, "zeile_de": "Anlage SO Zeile 4",
             "hint_de": "Privater Anteil — beruflicher Anteil ist Werbungskosten / Betriebsausgaben.",
             "hint_tr": "Özel kısmı — iş kısmı Werbungskosten/EÜR'de."},
            {"key": "kirchensteuer_so","label_de": "Kirchensteuer (gezahlt) (€)",             "label_tr": "Kilise vergisi (€)",      "type": "number", "required": False, "default": 0, "zeile_de": "Zeile 5",
             "hint_de": "Voll absetzbar als Sonderausgabe (außer auf Kapitalerträge).",
             "hint_tr": "Tam düşülebilir (sermaye gelirlerine ait hariç)."},
            {"key": "handwerker_lohn", "label_de": "Handwerker-Lohnanteil §35a (€)",          "label_tr": "Esnaf işçilik ücreti (€)","type": "number", "required": False, "default": 0, "zeile_de": "Haushaltsnahe Zeile 6",
             "hint_de": "20% absetzbar bis €1.200/Jahr. Nur Lohn (nicht Material). Rechnung + Überweisung Pflicht.",
             "hint_tr": "%20 düşülebilir, yıllık €1.200'e kadar. Sadece işçilik (malzeme değil). Fatura + havale zorunlu."},
            {"key": "haushaltsdienst", "label_de": "Haushaltsnahe Dienstleistungen §35a (€)", "label_tr": "Ev hizmeti (€)",          "type": "number", "required": False, "default": 0, "zeile_de": "Haushaltsnahe Zeile 4",
             "hint_de": "20% absetzbar bis €4.000/Jahr. Reinigung, Gartenpflege, Pflegedienst.",
             "hint_tr": "%20 düşülebilir, yıllık €4.000'e kadar. Temizlik, bahçe, bakım."},
            {"key": "haushaltshilfe_mini", "label_de": "Mini-Job Haushalt §35a (€)",          "label_tr": "Mini-Job ev (€)",         "type": "number", "required": False, "default": 0, "zeile_de": "Haushaltsnahe Zeile 1",
             "hint_de": "20% absetzbar bis €510/Jahr. Geringfügig Beschäftigte im Haushalt.",
             "hint_tr": "%20 düşülebilir, yıllık €510'a kadar. Küçük istihdamlı ev çalışanı."},
        ],
    },
    {
        "key": "anlage_vorsorge",
        "title_de": "Anlage Vorsorgeaufwand",
        "title_tr": "Anlage Vorsorgeaufwand (sigortalar)",
        "fields": [
            {"key": "kv_basis",   "label_de": "Krankenversicherung Basis (€)",       "label_tr": "Temel sağlık sigortası (€)",  "type": "number", "required": True, "zeile_de": "Zeile 11",
             "hint_de": "Jahresbeitrag ohne Wahlleistungen. Aus Bescheinigung der Krankenkasse §10 EStG.",
             "hint_tr": "Yıllık prim, ek hizmetler hariç. Sağlık kasası §10 EStG belgesinden."},
            {"key": "kv_zusatz",  "label_de": "Krankenversicherung Zusatz (€)",      "label_tr": "Ek sağlık sigortası (€)",     "type": "number", "required": False, "default": 0, "zeile_de": "Zeile 12",
             "hint_de": "Krankentagegeld, Chefarzt, Einzelzimmer etc.",
             "hint_tr": "Hastalık günlüğü, baş doktor, tek kişilik oda vs."},
            {"key": "pflege",     "label_de": "Pflegeversicherung (€)",              "label_tr": "Bakım sigortası (€)",         "type": "number", "required": False, "default": 0, "zeile_de": "Zeile 18",
             "hint_de": "Pflichtbeitrag + ggf. Zusatz. Aus Beitragsbescheinigung.",
             "hint_tr": "Zorunlu prim + opsiyonel ek. Beitragsbescheinigung'dan."},
            {"key": "rente_gesetz", "label_de": "Gesetzliche Rentenversicherung (€)", "label_tr": "Yasal emekli sigortası (€)",  "type": "number", "required": False, "default": 0, "zeile_de": "Zeile 4",
             "hint_de": "Eigene Beiträge an Deutsche Rentenversicherung (DRV).",
             "hint_tr": "Deutsche Rentenversicherung'a (DRV) ödenen kendi primler."},
            {"key": "rurup",      "label_de": "Rürup-Rente (€)",                     "label_tr": "Rürup emekliliği (€)",        "type": "number", "required": False, "default": 0, "zeile_de": "Zeile 6",
             "hint_de": "Basis-Rente nach §10 Abs.1 Nr.2 EStG. Aus Jahresbescheinigung.",
             "hint_tr": "§10 Abs.1 Nr.2 EStG'e göre temel emeklilik. Yıllık belge'den."},
            {"key": "bu",         "label_de": "Berufsunfähigkeitsversicherung (€)",  "label_tr": "Maluliyet sigortası (€)",     "type": "number", "required": False, "default": 0, "zeile_de": "Zeile 49",
             "hint_de": "Berufsunfähigkeitsversicherung — meist absetzbar.",
             "hint_tr": "Maluliyet sigortası — genelde düşülebilir."},
        ],
    },
]


# ───────────────────────────────────────────────────────────────────
# Expense Category Guide — "Wo gehören meine Belege hin?"
# User feedback (2026-05-30): "benzin parasi elbise verbung nereye yazacagiz"
# Frontend renders this as a help panel users can open from any section.
# ───────────────────────────────────────────────────────────────────

# ───────────────────────────────────────────────────────────────────
# Behindertenpauschbetrag table per § 33b EStG (2024+ version).
# Used for self + carry-forward from child.
# ───────────────────────────────────────────────────────────────────

BEHINDERTEN_PAUSCHBETRAG = {
    20: 384,
    30: 620,
    40: 860,
    50: 1140,
    60: 1440,
    70: 1780,
    80: 2120,
    90: 2460,
    100: 2840,
}
# Special markers (Merkzeichen):
# - H (Hilflos) or Bl (Blind): €7.400 erhöhter Pauschbetrag (Hilflos/Blind/Taubblind)
# - TBl (Taubblind): €7.400
BEHINDERTEN_PAUSCHBETRAG_ERHOEHT = 7400


def pendlerpauschale(entfernung_km: float | None,
                     arbeitstage: int | None) -> float:
    """Compute Entfernungspauschale 2024:
    - First 20 km: €0.30/km/day
    - Above 20 km: €0.38/km/day (befristet bis 2026)
    Total = (20 × 0.30 + max(0, km-20) × 0.38) × days
    """
    if not entfernung_km or not arbeitstage:
        return 0.0
    try:
        km = float(entfernung_km)
        tage = int(arbeitstage)
    except (TypeError, ValueError):
        return 0.0
    if km <= 0 or tage <= 0:
        return 0.0
    first_20 = min(km, 20) * 0.30
    above_20 = max(0, km - 20) * 0.38
    return round((first_20 + above_20) * tage, 2)


def pauschbetrag_for_gdb(gdb: int, merkmal: str | None = None) -> int:
    """Return Behindertenpauschbetrag in € for given Grad der Behinderung
    + Merkmal. H/Bl/TBl override regular GdB table."""
    if not gdb:
        return 0
    if merkmal and merkmal.upper() in ("H", "BL", "TBL"):
        return BEHINDERTEN_PAUSCHBETRAG_ERHOEHT
    try:
        gdb_int = int(gdb)
    except (TypeError, ValueError):
        return 0
    # Round down to nearest 10
    bucket = (gdb_int // 10) * 10
    return BEHINDERTEN_PAUSCHBETRAG.get(bucket, 0)


EXPENSE_GUIDE = [
    {
        "category": "fuel",
        "label_de": "Benzin / Diesel",
        "label_tr": "Benzin / Mazot",
        "explanation_de": "Geht in die EÜR als 'KFZ-Kosten'. Wird automatisch in 'Gewinn aus EÜR' (Anlage S) eingerechnet, sobald du den Beleg hochlädst.",
        "explanation_tr": "EÜR'de 'KFZ-Kosten' olarak gider. Belgeyi yüklediğinde otomatik 'Anlage S → Gewinn aus EÜR'e dahil olur.",
        "where_de": "Anlage S → Gewinn aus EÜR (automatisch)",
        "where_tr": "Anlage S → EÜR Gewinn (otomatik)",
        "requirements_de": "Fahrtenbuch oder 1%-Regel. Privatanteil herausrechnen.",
        "requirements_tr": "Fahrtenbuch veya %1 kuralı. Özel pay düşülmeli.",
    },
    {
        "category": "advertising",
        "label_de": "Werbung / Marketing",
        "label_tr": "Reklam / Pazarlama",
        "explanation_de": "Voll absetzbar als Betriebsausgabe. Google Ads, Facebook, Visitenkarten, Inserate.",
        "explanation_tr": "Tam düşülebilir işletme gideri. Google Ads, Facebook, kartvizit, ilan.",
        "where_de": "Anlage S → Gewinn aus EÜR (automatisch)",
        "where_tr": "Anlage S → EÜR Gewinn (otomatik)",
    },
    {
        "category": "clothing",
        "label_de": "Kleidung",
        "label_tr": "Giyim",
        "explanation_de": "NUR absetzbar wenn typische Berufskleidung (Sicherheitsschuhe, Friseur-Schürze, Arzt-Kittel) ODER mit Firmenlogo. Normale Kleidung NICHT.",
        "explanation_tr": "SADECE tipik iş kıyafeti (güvenlik ayakkabısı, kuaför önlüğü, doktor önlüğü) VEYA firma logosuyla varsa düşülebilir. Normal kıyafet HAYIR.",
        "where_de": "Anlage S → Gewinn aus EÜR (wenn berufsspezifisch)",
        "where_tr": "Anlage S → EÜR Gewinn (iş için ise)",
        "requirements_de": "Bei privater Mischverwendung: NICHT absetzbar.",
        "requirements_tr": "Özel karışık kullanımda: düşülemez.",
    },
    {
        "category": "entertainment",
        "label_de": "Bewirtung / Geschäftsessen",
        "label_tr": "İş yemeği / İkram",
        "explanation_de": "70% absetzbar bei Geschäftsessen mit Kunden. Vorsteuer (MwSt) 100%. Anlass + Teilnehmer + Datum auf Beleg notieren.",
        "explanation_tr": "Müşteri ile iş yemeğinde %70 düşülebilir. Vergi (KDV) %100. Vesile + katılımcı + tarih belgede yazılmalı.",
        "where_de": "Anlage S → Gewinn aus EÜR (automatisch)",
        "where_tr": "Anlage S → EÜR Gewinn (otomatik)",
    },
    {
        "category": "travel",
        "label_de": "Reisekosten",
        "label_tr": "Seyahat masrafları",
        "explanation_de": "Hotel, Bahn, Flug, Verpflegungsmehraufwand bei Geschäftsreisen. Voll absetzbar.",
        "explanation_tr": "Otel, tren, uçak, iş seyahatinde günlük yemek tazminatı. Tam düşülebilir.",
        "where_de": "Anlage S → Gewinn aus EÜR (automatisch)",
        "where_tr": "Anlage S → EÜR Gewinn (otomatik)",
    },
    {
        "category": "office",
        "label_de": "Büromaterial / Arbeitsmittel",
        "label_tr": "Ofis malzemesi / İş aleti",
        "explanation_de": "Stifte, Drucker, Papier: sofort absetzbar. >€800 netto: AfA über 3-5 Jahre.",
        "explanation_tr": "Kalem, yazıcı, kağıt: hemen düşülebilir. >€800 net: 3-5 yıl AfA.",
        "where_de": "Anlage S → Gewinn aus EÜR (kleine sofort, große AfA)",
        "where_tr": "Anlage S → EÜR Gewinn (küçük hemen, büyük AfA)",
    },
    {
        "category": "homeoffice",
        "label_de": "Homeoffice-Tagespauschale",
        "label_tr": "Ev ofis günlük tazminat",
        "explanation_de": "€6 pro Tag (max 1.260€/Jahr = 210 Tage). NUR wenn überwiegend zu Hause gearbeitet. Anlage N für Arbeitnehmer.",
        "explanation_tr": "Günlük €6 (yıllık max €1.260 = 210 gün). SADECE çoğunlukla evde çalışmışsan. Anlage N işçi için.",
        "where_de": "Anlage N → Werbungskosten",
        "where_tr": "Anlage N → Werbungskosten",
    },
    {
        "category": "krankenkasse",
        "label_de": "Krankenversicherung",
        "label_tr": "Sağlık sigortası",
        "explanation_de": "Beiträge Basisabsicherung voll absetzbar als Sonderausgabe. Aus Beitragsbescheinigung der Krankenkasse.",
        "explanation_tr": "Temel teminat primleri özel gider olarak tam düşülebilir. Sağlık kasası belgesinden.",
        "where_de": "Anlage Vorsorgeaufwand → KV Basis",
        "where_tr": "Anlage Vorsorgeaufwand → KV Basis",
    },
    {
        "category": "donation",
        "label_de": "Spenden",
        "label_tr": "Bağış",
        "explanation_de": "An gemeinnützige Vereine. Bis 20% des Gesamteinkommens. Spendenbescheinigung Pflicht.",
        "explanation_tr": "Hayır kurumlarına. Toplam gelirin %20'sine kadar. Spendenbescheinigung zorunlu.",
        "where_de": "Sonderausgaben → Spenden Geld",
        "where_tr": "Sonderausgaben → Spende",
    },
    {
        "category": "handwerker",
        "label_de": "Handwerker (privat)",
        "label_tr": "Esnaf (özel)",
        "explanation_de": "20% des Lohnanteils absetzbar bis €1.200/Jahr. NUR Lohn, nicht Material. Rechnung + Überweisung Pflicht.",
        "explanation_tr": "İşçilik bedelinin %20'si, yıllık €1.200'e kadar. SADECE işçilik (malzeme yok). Fatura + havale zorunlu.",
        "where_de": "Sonderausgaben → §35a Handwerker",
        "where_tr": "Sonderausgaben → §35a Handwerker",
    },
    {
        "category": "hausrenovierung",
        "label_de": "Hausrenovierung / Tamir-Rechnung",
        "label_tr": "Ev tamir / yenileme faturası",
        "explanation_de": "Hängt von der Immobilie ab: (1) Eigenes Heim → Handwerker §35a (20% Lohnanteil, max €1.200). (2) Vermietetes Objekt → Anlage V → Erhaltungsaufwand (voll absetzbar). (3) Neubau / Kauf → NICHT absetzbar (Anschaffungskosten).",
        "explanation_tr": "Mülke göre değişir: (1) Kendi evin → Handwerker §35a (%20 işçilik, max €1.200). (2) Kiraya verdiğin → Anlage V → Erhaltungsaufwand (tam düşülebilir). (3) Yeni alım/inşaat → düşülemez (Anschaffungskosten).",
        "where_de": "Eigene = Sonderausgaben §35a · Vermietet = Anlage V Erhaltungsaufwand",
        "where_tr": "Kendi = Sonderausgaben §35a · Kira = Anlage V Erhaltungsaufwand",
        "requirements_de": "Rechnung + Banküberweisung Pflicht (Bargeld NICHT). Material und Lohn getrennt ausgewiesen.",
        "requirements_tr": "Fatura + banka havalesi zorunlu (nakit YOK). Malzeme ve işçilik ayrı belirtilmeli.",
    },
    {
        "category": "pendler",
        "label_de": "Pendlerpauschale (Weg zur Arbeit)",
        "label_tr": "Pendlerpauschale (işe gidiş yolu)",
        "explanation_de": "€0,30 pro km (erste 20km) + €0,38 pro km (ab 21km, befristet bis 2026). Multipliziert mit Arbeitstagen. Pro km Entfernungspauschale unabhängig vom Verkehrsmittel.",
        "explanation_tr": "Km başına €0,30 (ilk 20km) + €0,38 (21km üstü, 2026'ya kadar). İş günü ile çarpılır. Ulaşım türünden bağımsız.",
        "where_de": "Anlage N → Pendlerpauschale (Zeile 32-34)",
        "where_tr": "Anlage N → Pendlerpauschale (Zeile 32-34)",
    },
]


def _flat_fields() -> list[dict]:
    """Flat list of fields for validation — SKIPS repeated-array sections
    (those are validated per-row by the frontend)."""
    out: list[dict] = []
    for section in FORM_SECTIONS:
        if section.get("is_repeated_array"):
            continue
        for f in section["fields"]:
            out.append({**f, "section": section["key"]})
    return out


# ───────────────────────────────────────────────────────────────────
# Insurance detection — vendor + raw_text patterns for Vorsorge fields.
# ───────────────────────────────────────────────────────────────────

# Krankenkassen patterns (gesetzlich). Each tuple = (key, pattern).
_KRANKENKASSE_PATTERNS = [
    "tk", "techniker krankenkasse", "aok", "barmer", "dak", "ikk",
    "kkh", "hkk", "bkk", "knappschaft", "siemens-betriebskrankenkasse",
    "viactiv", "mobil krankenkasse", "audi bkk",
]

# Privat Krankenversicherung (basis) — wenn vendor PKV insurance gibt
_PKV_PATTERNS = [
    "debeka", "allianz private", "axa krankenversicherung", "ergo direkt kranken",
    "huk-coburg krankenversicherung", "barmenia kranken", "central kranken",
    "continentale kranken", "dkv", "gothaer kranken", "hallesche", "hanse merkur",
    "inter krankenversicherung", "nuernberger kranken", "signal iduna kranken",
    "uniVersa kranken",
]

_PFLEGE_PATTERNS = ["pflegeversicherung", "pflege-pflichtversicherung"]
_RENTE_PATTERNS = ["deutsche rentenversicherung", "drv ", "drv-bund",
                   "rentenversicherung bund", "gesetzliche rente"]
_RURUP_PATTERNS = ["rürup", "rurup", "basisrente", "basis-rente"]
_BU_PATTERNS = ["berufsunfähigkeit", "berufsunfaehigkeit", "berufsunfäh",
                "bu-versicherung", "bu versicherung"]


def _match_any(text: str, patterns: list) -> bool:
    t = (text or "").lower()
    return any(p in t for p in patterns)


def detect_insurance_amounts(db, user_id: int, year: int) -> dict:
    """Scan year's invoices, group expense amounts by Vorsorge category.

    Heuristic: vendor name + raw_text matched against pattern lists.
    Returns dict with keys matching form fields (kv_basis, pflege, etc.).
    Only sums (no field gets overwritten if already partial).
    """
    out: dict[str, float] = {}
    try:
        # Import models locally to avoid circular import at module load time.
        from autotax.models import Invoice
        from sqlalchemy import func as _func
        year_prefix = f"{year}-"
        rows = db.query(Invoice).filter(
            Invoice.user_id == user_id,
            Invoice.invoice_type == "expense",
            Invoice.is_deleted.is_(False),
            Invoice.date.like(f"{year_prefix}%"),
        ).all()
        for inv in rows:
            vendor = (inv.vendor or "")
            raw = (inv.raw_text or "")[:2000]  # cap to limit work
            amt = float(inv.total_amount or 0)
            if amt <= 0:
                continue
            combined = f"{vendor} {raw}".lower()
            if _match_any(combined, _KRANKENKASSE_PATTERNS) or \
               _match_any(combined, _PKV_PATTERNS):
                out["kv_basis"] = out.get("kv_basis", 0.0) + amt
            if _match_any(combined, _PFLEGE_PATTERNS):
                out["pflege"] = out.get("pflege", 0.0) + amt
            if _match_any(combined, _RENTE_PATTERNS):
                out["rente_gesetz"] = out.get("rente_gesetz", 0.0) + amt
            if _match_any(combined, _RURUP_PATTERNS):
                out["rurup"] = out.get("rurup", 0.0) + amt
            if _match_any(combined, _BU_PATTERNS):
                out["bu"] = out.get("bu", 0.0) + amt
    except Exception:
        logger.exception("detect_insurance_amounts failed")
    # Round 2 decimals
    return {k: round(v, 2) for k, v in out.items()}


# ───────────────────────────────────────────────────────────────────
# Auto-fill from user/company/invoice data.
# ───────────────────────────────────────────────────────────────────

def autofill_from_user_data(user, companies: list, eur_profit: float,
                            *, insurance_amounts: Optional[dict] = None) -> dict:
    """Pre-populate form with data we already have from the app.

    Caller passes already-loaded User + UserCompany list + computed
    EÜR profit (sum of income - sum of expenses for the year).
    Optional `insurance_amounts` dict (from detect_insurance_amounts) is
    merged into Anlage Vorsorgeaufwand fields.
    """
    out: dict[str, Any] = {}

    # Mantelbogen: from User profile
    full_name = ""
    if user:
        full_name = (getattr(user, "full_name", "") or "").strip()
        if full_name:
            parts = full_name.split(" ", 1)
            if len(parts) >= 1:
                out["vorname"] = parts[0]
            if len(parts) >= 2:
                out["nachname"] = parts[1]

    # Mantelbogen: from primary UserCompany (address)
    if companies:
        primary = next((c for c in companies if getattr(c, "is_default", False)), companies[0])
        out["strasse"] = (getattr(primary, "company_address", "") or "").strip()
        # PLZ + Ort would need separate fields in UserCompany — skip for now
        # IBAN from UserCompany
        iban = (getattr(primary, "company_iban", "") or "").strip().replace(" ", "").upper()
        if iban:
            out["iban"] = iban
            out["kontoinhaber"] = (getattr(primary, "company_name", "") or full_name or "").strip()

    # Anlage S: from EÜR profit
    if eur_profit is not None:
        out["gewinn_eur"] = round(float(eur_profit), 2)

    # Anlage Vorsorgeaufwand: from detected insurance payments
    if insurance_amounts:
        for k, v in insurance_amounts.items():
            if v > 0:
                out[k] = v

    return out


# ───────────────────────────────────────────────────────────────────
# Validation.
# ───────────────────────────────────────────────────────────────────

def _validate_iban_de(iban: str) -> bool:
    """DE IBAN checksum (mod 97). DE + 20 digits, total 22 chars."""
    iban = iban.replace(" ", "").upper()
    if not iban.startswith("DE") or len(iban) != 22:
        return False
    if not iban[2:].isdigit():
        return False
    # Move first 4 chars to end, replace letters with digits (A=10..Z=35)
    rearranged = iban[4:] + iban[:4]
    converted = ""
    for ch in rearranged:
        if ch.isdigit():
            converted += ch
        else:
            converted += str(ord(ch) - ord("A") + 10)
    try:
        return int(converted) % 97 == 1
    except ValueError:
        return False


def _validate_steuer_id(sid: str) -> bool:
    """Steuer-ID 11 digits with check-digit rule (Faktorenverfahren).
    One digit appears 2x or 3x in first 10 (rest unique). The 11th digit
    is the check digit computed via mod 11 on first 10."""
    sid = "".join(c for c in sid if c.isdigit())
    if len(sid) != 11:
        return False
    # Count digit frequency in first 10
    counts: dict[str, int] = {}
    for d in sid[:10]:
        counts[d] = counts.get(d, 0) + 1
    # Must have exactly one digit appearing 2x or 3x and others 1x.
    twos = sum(1 for v in counts.values() if v == 2)
    threes = sum(1 for v in counts.values() if v == 3)
    if not ((twos == 1 and threes == 0) or (twos == 0 and threes == 1)):
        return False
    # Check digit (mod 11/10 algorithm — ISO 7064 variant used by BZSt)
    product = 10
    for d in sid[:10]:
        s = (int(d) + product) % 10
        if s == 0:
            s = 10
        product = (2 * s) % 11
    check = (11 - product) % 10
    return check == int(sid[10])


def validate(data: dict) -> dict:
    """Return {field_key: error_message} for invalid/missing fields.

    Multi-level checks: required + regex pattern + semantic (IBAN checksum,
    Steuer-ID check digit). Labels in German for matching UI tone.
    """
    import re as _re
    errors: dict[str, str] = {}
    for f in _flat_fields():
        key = f["key"]
        value = data.get(key)
        # Required check
        if f.get("required") and (value is None or value == ""):
            errors[key] = f"Pflichtfeld fehlt ({f['label_de']})"
            continue
        # Pattern check (raw regex)
        pat = f.get("pattern")
        if pat and value:
            if not _re.match(pat, str(value)):
                errors[key] = f"Format ungültig ({f['label_de']})"
                continue
        # Semantic checks for specific fields
        if value:
            if key == "iban":
                if not _validate_iban_de(str(value)):
                    errors[key] = "IBAN ungültig (Prüfziffer)"
            elif key == "steuer_id":
                if not _validate_steuer_id(str(value)):
                    errors[key] = "Steuer-ID ungültig (Prüfziffer)"
    return errors


# ───────────────────────────────────────────────────────────────────
# Data serialization.
# ───────────────────────────────────────────────────────────────────

def serialize_data(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True)


def deserialize_data(raw: Optional[str]) -> dict:
    if not raw:
        return {}
    try:
        d = json.loads(raw)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


# ───────────────────────────────────────────────────────────────────
# PDF generation — SKELETON only. Real layout next iteration.
# ───────────────────────────────────────────────────────────────────

def _human_value(value, options: list | None = None, lang: str = "de") -> str:
    """Format raw form value for display (Religion → 'Keine', etc)."""
    if value in (None, ""):
        return "—"
    if options:
        for o in options:
            if str(o.get("v")) == str(value):
                return o.get(lang) or o.get("de") or str(value)
    return str(value)


def generate_pdf_skeleton(declaration, user, companies: list) -> bytes:
    """Render declaration as ESt 1 A-inspired PDF.

    Structure mimics official ELSTER form:
    - Header band: "Einkommensteuererklärung YYYY" + tax office (Finanzamt)
      placeholder + Steuernummer/Steuer-ID boxes.
    - Numbered Zeilen (lines) like real form (Zeile 1, 2, 3 ...).
    - 2-column field layout where it fits.
    - Checkbox-style options for select fields (Familienstand, Religion).
    - Section dividers with title bands.
    - Summary block + Anlagen tick list at end.
    - Footer disclaimer.
    """
    import io
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas as pdf_canvas
    from reportlab.lib.units import cm
    from reportlab.lib.colors import HexColor

    NAVY = HexColor("#0f1a2e")
    INK = HexColor("#1a2d4a")
    MUTED = HexColor("#7a8ba8")
    DIM = HexColor("#9aa5b5")
    ACCENT = HexColor("#10b981")
    BAND_BG = HexColor("#eaeff5")
    LIGHT_BG = HexColor("#f7f9fc")
    BORDER = HexColor("#c5cfdb")
    BOX_BORDER = HexColor("#9aa5b5")
    LINE_NUM = HexColor("#788599")

    buf = io.BytesIO()
    c = pdf_canvas.Canvas(buf, pagesize=A4)
    w, h = A4
    data = deserialize_data(declaration.data)

    margin_l = 1.5 * cm
    margin_r = 1.5 * cm
    content_w = w - margin_l - margin_r
    col_gap = 0.5 * cm
    col_w = (content_w - col_gap) / 2

    line_counter = [1]

    def draw_footer(pageno: int):
        c.setFillColor(MUTED)
        c.setFont("Helvetica", 7)
        c.drawString(margin_l, 1.3 * cm,
                     f"AutoTax.Cloud · Entwurf · Erstellt {date.today().strftime('%d.%m.%Y')}")
        c.drawString(margin_l, 0.95 * cm,
                     "Keine rechtsverbindliche Steuerberatung — bitte vor ELSTER-Übermittlung prüfen.")
        c.drawRightString(w - margin_r, 0.95 * cm,
                          f"Seite {pageno} · ESt {declaration.year}")

    page_no = [1]

    def new_page():
        draw_footer(page_no[0])
        c.showPage()
        page_no[0] += 1
        # Slim header band on continuation pages
        c.setFillColor(NAVY)
        c.rect(0, h - 1.4 * cm, w, 1.4 * cm, fill=1, stroke=0)
        c.setFillColor(HexColor("#ffffff"))
        c.setFont("Helvetica-Bold", 11)
        c.drawString(margin_l, h - 0.95 * cm,
                     f"Einkommensteuererklärung {declaration.year} (Fortsetzung)")
        c.setFont("Helvetica", 9)
        c.setFillColor(HexColor("#a8b8d0"))
        c.drawRightString(w - margin_r, h - 0.95 * cm,
                          f"{user.email if user else ''}")
        return h - 2.2 * cm

    def ensure_space(y, needed):
        if y - needed < 2 * cm:
            return new_page()
        return y

    def draw_line_num(y, x=None):
        if x is None:
            x = margin_l - 0.0 * cm
        c.setFillColor(LINE_NUM)
        c.setFont("Helvetica-Bold", 7)
        c.drawString(x - 0.7 * cm, y, f"{line_counter[0]}")
        line_counter[0] += 1

    def draw_field_box(x, y, box_w, label, value, *, show_line_num=False):
        """Single field: tiny uppercase label above a bordered value box."""
        if show_line_num:
            draw_line_num(y)
        c.setFillColor(LIGHT_BG)
        c.setStrokeColor(BOX_BORDER)
        c.setLineWidth(0.5)
        c.roundRect(x, y - 0.95 * cm, box_w, 0.85 * cm, 0.08 * cm, fill=1, stroke=1)
        c.setFillColor(MUTED)
        c.setFont("Helvetica", 6.5)
        c.drawString(x + 0.18 * cm, y - 0.2 * cm, label.upper())
        c.setFillColor(INK)
        c.setFont("Helvetica-Bold" if value and value != "—" else "Helvetica", 10.5)
        c.drawString(x + 0.18 * cm, y - 0.7 * cm, str(value)[:60])

    def draw_checkbox_row(x, y, options, selected, lang="de"):
        """Render select field as horizontal checkbox row (ELSTER style)."""
        cur_x = x
        for o in options:
            is_sel = str(o.get("v")) == str(selected)
            # Box
            c.setStrokeColor(BOX_BORDER)
            c.setLineWidth(0.5)
            c.setFillColor(INK if is_sel else HexColor("#ffffff"))
            c.rect(cur_x, y - 0.32 * cm, 0.32 * cm, 0.32 * cm, fill=1, stroke=1)
            if is_sel:
                c.setStrokeColor(HexColor("#ffffff"))
                c.setLineWidth(1.4)
                c.line(cur_x + 0.06 * cm, y - 0.16 * cm,
                       cur_x + 0.13 * cm, y - 0.26 * cm)
                c.line(cur_x + 0.13 * cm, y - 0.26 * cm,
                       cur_x + 0.27 * cm, y - 0.05 * cm)
            c.setFillColor(INK)
            c.setFont("Helvetica-Bold" if is_sel else "Helvetica", 9)
            label = o.get(lang) or o.get("de") or o.get("v")
            c.drawString(cur_x + 0.45 * cm, y - 0.22 * cm, label)
            cur_x += 0.45 * cm + c.stringWidth(label, "Helvetica", 9) + 0.6 * cm

    # ─────────────────────────────────────────────────────────
    # PAGE 1 — HEADER + Steuerpflichtige (Mantelbogen part 1)
    # ─────────────────────────────────────────────────────────

    # Top header band
    c.setFillColor(NAVY)
    c.rect(0, h - 3.5 * cm, w, 3.5 * cm, fill=1, stroke=0)
    c.setFillColor(HexColor("#ffffff"))
    c.setFont("Helvetica-Bold", 19)
    c.drawString(margin_l, h - 1.7 * cm, "Einkommensteuererklärung")
    c.setFont("Helvetica-Bold", 14)
    c.drawString(margin_l, h - 2.5 * cm, str(declaration.year))
    c.setFont("Helvetica", 9)
    c.setFillColor(HexColor("#a8b8d0"))
    c.drawString(margin_l, h - 3.1 * cm,
                 "Entwurf, erstellt mit AutoTax.Cloud — kein offizielles ELSTER-Formular")

    # Status badge top-right
    status_label = "ABGESCHLOSSEN" if declaration.status == "finalized" else "ENTWURF"
    badge_color = ACCENT if declaration.status == "finalized" else HexColor("#f59e0b")
    badge_w = 3.2 * cm
    c.setFillColor(badge_color)
    c.roundRect(w - margin_r - badge_w, h - 2.4 * cm, badge_w, 0.7 * cm,
                0.15 * cm, fill=1, stroke=0)
    c.setFillColor(NAVY)
    c.setFont("Helvetica-Bold", 9)
    c.drawCentredString(w - margin_r - badge_w / 2, h - 2.2 * cm, status_label)

    # Steuernummer / Steuer-ID boxes
    c.setFillColor(HexColor("#ffffff"))
    box_y = h - 3.2 * cm
    c.setFont("Helvetica", 7)
    c.drawRightString(w - margin_r - 4.7 * cm, box_y + 0.5 * cm, "Steuer-ID")
    c.setFont("Helvetica-Bold", 10)
    c.drawRightString(w - margin_r, box_y + 0.5 * cm,
                      data.get("steuer_id", "—"))

    y = h - 4.2 * cm

    # ─── Section: STEUERPFLICHTIGE / Wohnanschrift ───
    def section_band(title, y_pos):
        c.setFillColor(BAND_BG)
        c.rect(margin_l, y_pos - 0.65 * cm, content_w, 0.7 * cm, fill=1, stroke=0)
        c.setStrokeColor(INK)
        c.setLineWidth(0.6)
        c.line(margin_l, y_pos - 0.65 * cm,
               margin_l + content_w, y_pos - 0.65 * cm)
        c.setFillColor(INK)
        c.setFont("Helvetica-Bold", 10)
        c.drawString(margin_l + 0.2 * cm, y_pos - 0.45 * cm, title.upper())
        return y_pos - 1.1 * cm

    y = section_band("A — Steuerpflichtige Person", y)

    # Row 1: Vorname | Nachname (2 cols)
    draw_field_box(margin_l, y, col_w, "Vorname",
                   _human_value(data.get("vorname"), None, "de"), show_line_num=True)
    draw_field_box(margin_l + col_w + col_gap, y, col_w, "Nachname",
                   _human_value(data.get("nachname"), None, "de"))
    y -= 1.25 * cm

    # Row 2: Geburtsdatum | Steuernummer
    draw_field_box(margin_l, y, col_w, "Geburtsdatum",
                   _human_value(data.get("geburtsdatum"), None, "de"), show_line_num=True)
    draw_field_box(margin_l + col_w + col_gap, y, col_w, "Steuernummer",
                   _human_value(data.get("steuer_nummer"), None, "de"))
    y -= 1.25 * cm

    # Religion — checkbox row (with Zeile number)
    draw_line_num(y - 0.1 * cm)
    c.setFillColor(MUTED)
    c.setFont("Helvetica", 7)
    c.drawString(margin_l + 0.18 * cm, y, "RELIGION (KIRCHENSTEUER)")
    religion_options = next((f["options"] for f in FORM_SECTIONS[0]["fields"]
                            if f["key"] == "religion"), [])
    draw_checkbox_row(margin_l + 0.18 * cm, y - 0.55 * cm,
                      religion_options, data.get("religion"))
    y -= 1.4 * cm

    # Familienstand — checkbox row
    draw_line_num(y - 0.1 * cm)
    c.setFillColor(MUTED)
    c.setFont("Helvetica", 7)
    c.drawString(margin_l + 0.18 * cm, y, "FAMILIENSTAND")
    fs_options = next((f["options"] for f in FORM_SECTIONS[0]["fields"]
                      if f["key"] == "familienstand"), [])
    draw_checkbox_row(margin_l + 0.18 * cm, y - 0.55 * cm,
                      fs_options, data.get("familienstand"))
    y -= 1.7 * cm

    # ─── Section: WOHNANSCHRIFT ───
    y = ensure_space(y, 4 * cm)
    y = section_band("B — Wohnanschrift (Stand 31.12.)", y)

    # Strasse (full width) — Zeile
    draw_field_box(margin_l, y, content_w, "Straße + Hausnummer",
                   _human_value(data.get("strasse"), None, "de"), show_line_num=True)
    y -= 1.25 * cm
    # PLZ (kurz) + Ort (rest)
    plz_w = 3.5 * cm
    ort_w = content_w - plz_w - col_gap
    draw_field_box(margin_l, y, plz_w, "PLZ",
                   _human_value(data.get("plz"), None, "de"), show_line_num=True)
    draw_field_box(margin_l + plz_w + col_gap, y, ort_w, "Ort",
                   _human_value(data.get("ort"), None, "de"))
    y -= 1.6 * cm

    # ─── Section: BANKVERBINDUNG (Erstattung) ───
    y = ensure_space(y, 4 * cm)
    y = section_band("C — Bankverbindung für Erstattung", y)

    draw_field_box(margin_l, y, content_w, "IBAN",
                   _human_value(data.get("iban"), None, "de"), show_line_num=True)
    y -= 1.25 * cm
    draw_field_box(margin_l, y, content_w, "Kontoinhaber",
                   _human_value(data.get("kontoinhaber"), None, "de"), show_line_num=True)
    y -= 1.6 * cm

    # ─── Section: EHEPARTNER (only if verheiratet) ───
    if data.get("familienstand") == "verheiratet" and (
        data.get("spouse_vorname") or data.get("spouse_steuer_id")
    ):
        y = ensure_space(y, 6 * cm)
        y = section_band("D — Ehepartner (Zusammenveranlagung)", y)
        # Row 1: Vorname / Nachname
        draw_field_box(margin_l, y, col_w, "Vorname Ehepartner",
                       _human_value(data.get("spouse_vorname"), None, "de"),
                       show_line_num=True)
        draw_field_box(margin_l + col_w + col_gap, y, col_w, "Nachname Ehepartner",
                       _human_value(data.get("spouse_nachname"), None, "de"))
        y -= 1.25 * cm
        # Row 2: Geburtsdatum / Steuer-ID
        draw_field_box(margin_l, y, col_w, "Geburtsdatum",
                       _human_value(data.get("spouse_geburtsdatum"), None, "de"),
                       show_line_num=True)
        draw_field_box(margin_l + col_w + col_gap, y, col_w, "Steuer-ID Ehepartner",
                       _human_value(data.get("spouse_steuer_id"), None, "de"))
        y -= 1.25 * cm
        # Row 3: Brutto / Lohnsteuer
        sb = data.get("spouse_lohn_brutto")
        sl = data.get("spouse_lohnsteuer")
        sb_str = f"{float(sb):.2f} €" if sb else "—"
        sl_str = f"{float(sl):.2f} €" if sl else "—"
        draw_field_box(margin_l, y, col_w, "Bruttoarbeitslohn EP", sb_str,
                       show_line_num=True)
        draw_field_box(margin_l + col_w + col_gap, y, col_w, "Lohnsteuer EP", sl_str)
        y -= 1.25 * cm
        # Veranlagungsart bold
        va = data.get("veranlagungsart") or "zusammen"
        c.setFillColor(INK)
        c.setFont("Helvetica-Bold", 10)
        va_lbl = "Zusammenveranlagung (Splittingtarif)" if va == "zusammen" else "Einzelveranlagung"
        c.drawString(margin_l + 0.3 * cm, y, f"Veranlagungsart: {va_lbl}")
        y -= 0.8 * cm

    # ─── Section: ANLAGE S ───
    y = ensure_space(y, 5 * cm)
    y = section_band("E — Anlage S (Selbständige Tätigkeit)", y)

    # Tätigkeit full width
    draw_field_box(margin_l, y, content_w, "Tätigkeit",
                   _human_value(data.get("taetigkeit"), None, "de"), show_line_num=True)
    y -= 1.25 * cm
    # Gewinn (left) + Veräußerungsgewinn (right)
    eur_w = (content_w - col_gap) / 2
    gewinn_val = data.get("gewinn_eur")
    gewinn_str = f"{float(gewinn_val):.2f} €" if gewinn_val not in (None, "") else "—"
    vg_val = data.get("veraeusserungsgewinn")
    vg_str = f"{float(vg_val):.2f} €" if vg_val not in (None, "") else "—"
    draw_field_box(margin_l, y, eur_w, "Gewinn aus EÜR",
                   gewinn_str, show_line_num=True)
    draw_field_box(margin_l + eur_w + col_gap, y, eur_w,
                   "Veräußerungsgewinn", vg_str)
    y -= 1.6 * cm

    # ─── Section: ANLAGE N (Lohnsteuer — falls vorhanden) ───
    anlage_n = data.get("lohn_brutto") or data.get("lohnsteuer") or data.get("pendler_km")
    if anlage_n:
        y = ensure_space(y, 8 * cm)
        y = section_band("E — Anlage N (Lohn aus Anstellung)", y)
        n_rows = [
            ("lohn_brutto", "Bruttoarbeitslohn (Jahres)"),
            ("lohnsteuer", "Einbehaltene Lohnsteuer"),
            ("soli_n", "Solidaritätszuschlag"),
            ("kirchensteuer", "Kirchensteuer"),
            ("werbungskosten_n", "Werbungskosten (Pauschbetrag)"),
            ("pendler_km", "Entfernung Wohnung-Arbeit (km)"),
            ("pendler_tage", "Arbeitstage / Jahr"),
            ("homeoffice_tage", "Homeoffice-Tage (€6/Tag)"),
        ]
        for i in range(0, len(n_rows), 2):
            y = ensure_space(y, 2.5 * cm)
            for j, (key, label) in enumerate(n_rows[i:i + 2]):
                x = margin_l + j * (eur_w + col_gap)
                val = data.get(key)
                if key in ("pendler_km", "pendler_tage", "homeoffice_tage"):
                    val_str = f"{val}" if val not in (None, "") else "—"
                else:
                    val_str = f"{float(val):.2f} €" if val not in (None, "") else "—"
                draw_field_box(x, y, eur_w, label, val_str,
                               show_line_num=(j == 0))
            y -= 1.25 * cm
        # Auto-compute Pendlerpauschale + HO-Pauschale
        pp = pendlerpauschale(data.get("pendler_km"), data.get("pendler_tage"))
        ho_p = min(float(data.get("homeoffice_tage") or 0) * 6, 1260)
        if pp > 0 or ho_p > 0:
            c.setFillColor(INK)
            c.setFont("Helvetica-Bold", 10)
            if pp > 0:
                c.drawString(margin_l + 0.3 * cm, y,
                             f"Pendlerpauschale: {pp:.2f} € (Werbungskosten zusätzlich)")
                y -= 0.55 * cm
            if ho_p > 0:
                c.drawString(margin_l + 0.3 * cm, y,
                             f"Homeoffice-Pauschale: {ho_p:.2f} € (Werbungskosten zusätzlich)")
                y -= 0.55 * cm
        y -= 0.3 * cm

    # ─── Section: ANLAGE V (Vermietung — falls vorhanden) ───
    anlage_v = data.get("v_einnahmen") or data.get("v_adresse")
    if anlage_v:
        y = ensure_space(y, 10 * cm)
        y = section_band("F — Anlage V (Vermietung & Verpachtung)", y)
        # Adresse full-width
        draw_field_box(margin_l, y, content_w, "Adresse Mietobjekt",
                       _human_value(data.get("v_adresse"), None, "de"),
                       show_line_num=True)
        y -= 1.25 * cm
        v_rows = [
            ("v_einnahmen", "Mieteinnahmen"),
            ("v_nebenkosten", "Umlagef. Nebenkosten erhalten"),
            ("v_afa", "AfA Gebäude 2%"),
            ("v_zinsen", "Schuldzinsen"),
            ("v_erhaltung", "Erhaltungsaufwand"),
            ("v_grundsteuer", "Grundsteuer + Versicherung"),
            ("v_sonst", "Sonstige Werbungskosten"),
        ]
        for i in range(0, len(v_rows), 2):
            y = ensure_space(y, 2.5 * cm)
            for j, (key, label) in enumerate(v_rows[i:i + 2]):
                x = margin_l + j * (eur_w + col_gap)
                val = data.get(key)
                val_str = f"{float(val or 0):.2f} €"
                draw_field_box(x, y, eur_w, label, val_str,
                               show_line_num=(j == 0))
            y -= 1.25 * cm
        # V net calculation
        v_net = (
            float(data.get("v_einnahmen") or 0)
            + float(data.get("v_nebenkosten") or 0)
            - float(data.get("v_afa") or 0)
            - float(data.get("v_zinsen") or 0)
            - float(data.get("v_erhaltung") or 0)
            - float(data.get("v_grundsteuer") or 0)
            - float(data.get("v_sonst") or 0)
        )
        c.setFillColor(INK)
        c.setFont("Helvetica-Bold", 10)
        c.drawString(margin_l + 0.3 * cm, y,
                     f"Überschuss Vermietung: {v_net:.2f} €")
        y -= 0.8 * cm

    # ─── Section: ANLAGE KIND (children) ───
    kinder = data.get("kinder") or []
    if isinstance(kinder, list) and kinder:
        y = ensure_space(y, 4 + 1.5 * len(kinder))
        y = section_band("Anlage Kind — Kinder", y)
        c.setFillColor(MUTED)
        c.setFont("Helvetica", 8)
        c.drawString(margin_l + 0.3 * cm, y,
                     f"{len(kinder)} Kind(er) — Kindergeld/Kinderfreibetrag")
        y -= 0.7 * cm
        for i, k in enumerate(kinder, 1):
            if not isinstance(k, dict):
                continue
            y = ensure_space(y, 1.8 * cm)
            name = f"{k.get('vorname','')} ({k.get('geburtsdatum','—')})"
            kg = "✓" if (k.get("kindergeld") == "ja") else "—"
            sc = "✓" if (k.get("shared_custody") == "ja") else "—"
            c.setFillColor(INK)
            c.setFont("Helvetica-Bold", 9)
            c.drawString(margin_l + 0.3 * cm, y, f"{i}. {name}")
            c.setFont("Helvetica", 9)
            c.drawString(margin_l + 9 * cm, y, f"Kindergeld: {kg}")
            c.drawString(margin_l + 13 * cm, y, f"Geteilt: {sc}")
            # Behinderung des Kindes
            k_gdb = k.get("behinderung_gdb")
            k_merk = k.get("behinderung_merkmal")
            k_ueb = k.get("behindert_uebertrag")
            if k_gdb or k_merk:
                k_pb = pauschbetrag_for_gdb(int(k_gdb) if k_gdb else 0, k_merk)
                y -= 0.45 * cm
                c.setFillColor(MUTED)
                c.setFont("Helvetica-Oblique", 8)
                ueb_txt = "✓ auf Eltern übertragen" if k_ueb == "ja" else ""
                c.drawString(margin_l + 0.5 * cm, y,
                             f"   Behinderung: GdB {k_gdb}% "
                             f"{('Merkmal '+k_merk) if k_merk else ''} "
                             f"→ Pauschbetrag {k_pb} € {ueb_txt}")
            y -= 0.55 * cm
        y -= 0.3 * cm

    # ─── Section: ANLAGE KAP (Kapitalerträge, only if filled) ───
    kap_keys = ("kap_zinsen", "kap_kursgewinn", "kap_quellensteuer",
                "kap_quellensteuer_ausland", "freistellungsauftrag")
    has_kap = any(data.get(k) for k in kap_keys)
    if has_kap:
        y = ensure_space(y, 6 * cm)
        y = section_band("Anlage KAP — Kapitalerträge", y)
        kap_rows = [
            ("kap_zinsen", "Zinsen + Dividenden"),
            ("kap_kursgewinn", "Kursgewinne / Aktien"),
            ("kap_quellensteuer", "Kapitalertragsteuer einbehalten"),
            ("kap_quellensteuer_ausland", "Ausländische Quellensteuer"),
            ("freistellungsauftrag", "Freistellungsauftrag genutzt"),
        ]
        for i in range(0, len(kap_rows), 2):
            y = ensure_space(y, 2.5 * cm)
            for j, (key, label) in enumerate(kap_rows[i:i + 2]):
                x = margin_l + j * (eur_w + col_gap)
                val = data.get(key)
                val_str = f"{float(val or 0):.2f} €"
                draw_field_box(x, y, eur_w, label, val_str,
                               show_line_num=(j == 0))
            y -= 1.25 * cm
        y -= 0.3 * cm

    # ─── Section: ANLAGE BEHINDERUNG (eigene, only if GdB set) ───
    eigene_gdb = data.get("eigene_gdb")
    eigene_merkmal = data.get("eigene_merkmal")
    pflege_grad = data.get("pflege_grad")
    has_beh = bool(eigene_gdb or eigene_merkmal or pflege_grad)
    if has_beh:
        y = ensure_space(y, 4 * cm)
        y = section_band("Anlage Außergewöhnl. Belastungen — Behinderung (eigene)", y)
        pb = pauschbetrag_for_gdb(int(eigene_gdb) if eigene_gdb else 0, eigene_merkmal)
        beh_rows = [
            ("eigene_gdb", "GdB (%)", f"{eigene_gdb or '—'} %" if eigene_gdb else "—"),
            ("eigene_merkmal", "Merkzeichen", eigene_merkmal or "—"),
            ("pflege_grad", "Pflegegrad", pflege_grad or "—"),
        ]
        for key, label, val in beh_rows:
            y = ensure_space(y, 1.3 * cm)
            draw_field_box(margin_l, y, content_w, label, val, show_line_num=True)
            y -= 1.25 * cm
        if pb > 0:
            c.setFillColor(INK)
            c.setFont("Helvetica-Bold", 10)
            c.drawString(margin_l + 0.3 * cm, y,
                         f"Behindertenpauschbetrag (§ 33b EStG): {pb:.2f} €")
            y -= 0.7 * cm

    # ─── Section: ANLAGE AUSSERGEWÖHNLICHE BELASTUNGEN ───
    ab_keys = ("krankheitskosten", "pflegekosten", "bestattungskosten",
               "scheidungskosten", "kurkosten")
    has_ab = any(data.get(k) for k in ab_keys)
    if has_ab:
        y = ensure_space(y, 5 * cm)
        y = section_band("Außergewöhnliche Belastungen", y)
        ab_rows = [
            ("krankheitskosten", "Krankheitskosten"),
            ("pflegekosten", "Pflegekosten"),
            ("bestattungskosten", "Bestattungskosten"),
            ("scheidungskosten", "Scheidungskosten"),
            ("kurkosten", "Kur / Sanatorium"),
        ]
        for i in range(0, len(ab_rows), 2):
            y = ensure_space(y, 2.5 * cm)
            for j, (key, label) in enumerate(ab_rows[i:i + 2]):
                x = margin_l + j * (eur_w + col_gap)
                val = data.get(key)
                val_str = f"{float(val or 0):.2f} €"
                draw_field_box(x, y, eur_w, label, val_str,
                               show_line_num=(j == 0))
            y -= 1.25 * cm
        y -= 0.3 * cm

    # ─── Section: ANLAGE SONDERAUSGABEN (only if any field filled) ───
    so_keys = ("spenden_geld", "spenden_partei", "steuerberater",
               "kirchensteuer_so", "handwerker_lohn", "haushaltsdienst",
               "haushaltshilfe_mini")
    has_so = any(data.get(k) for k in so_keys)
    section_counter = ord("E")  # E is base after mandatory sections
    if anlage_n:
        section_counter += 1
    if anlage_v:
        section_counter += 1
    if has_so:
        letter_so = chr(section_counter)
        y = ensure_space(y, 6 * cm)
        y = section_band(f"{letter_so} — Sonderausgaben & §35a", y)
        so_rows = [
            ("spenden_geld", "Spenden Gemeinnützig"),
            ("spenden_partei", "Spenden Parteien"),
            ("steuerberater", "Steuerberater (privat)"),
            ("kirchensteuer_so", "Kirchensteuer gezahlt"),
            ("handwerker_lohn", "Handwerker §35a"),
            ("haushaltsdienst", "Haushaltsdienst §35a"),
            ("haushaltshilfe_mini", "Mini-Job Haushalt §35a"),
        ]
        for i in range(0, len(so_rows), 2):
            y = ensure_space(y, 2.5 * cm)
            for j, (key, label) in enumerate(so_rows[i:i + 2]):
                x = margin_l + j * (eur_w + col_gap)
                val = data.get(key)
                val_str = f"{float(val or 0):.2f} €"
                draw_field_box(x, y, eur_w, label, val_str,
                               show_line_num=(j == 0))
            y -= 1.25 * cm
        # §35a savings calculation
        so_handwerker = float(data.get("handwerker_lohn") or 0)
        so_haushalt = float(data.get("haushaltsdienst") or 0)
        so_mini = float(data.get("haushaltshilfe_mini") or 0)
        so_savings = (
            min(so_handwerker * 0.20, 1200)
            + min(so_haushalt * 0.20, 4000)
            + min(so_mini * 0.20, 510)
        )
        if so_savings > 0:
            c.setFillColor(INK)
            c.setFont("Helvetica-Bold", 10)
            c.drawString(margin_l + 0.3 * cm, y,
                         f"§35a Steuerermäßigung (geschätzt): {so_savings:.2f} €")
            y -= 0.8 * cm
        section_counter += 1

    # ─── Section: ANLAGE VORSORGEAUFWAND ───
    next_letter = chr(section_counter)
    y = ensure_space(y, 8 * cm)
    y = section_band(f"{next_letter} — Anlage Vorsorgeaufwand", y)

    vorsorge_rows = [
        ("kv_basis", "Krankenversicherung Basis"),
        ("kv_zusatz", "Krankenversicherung Zusatz"),
        ("pflege", "Pflegeversicherung"),
        ("rente_gesetz", "Gesetzliche Rente"),
        ("rurup", "Rürup-Rente"),
        ("bu", "Berufsunfähigkeit"),
    ]
    # 2-column layout for these
    for i in range(0, len(vorsorge_rows), 2):
        y = ensure_space(y, 2.5 * cm)
        for j, (key, label) in enumerate(vorsorge_rows[i:i + 2]):
            x = margin_l + j * (eur_w + col_gap)
            val = data.get(key)
            val_str = f"{float(val):.2f} €" if val not in (None, "") else "—"
            draw_field_box(x, y, eur_w, label, val_str,
                           show_line_num=(j == 0))
        y -= 1.25 * cm
    y -= 0.4 * cm

    # ─── Section: SUMMARY + Anlagen tick list ───
    y = ensure_space(y, 6 * cm)
    c.setStrokeColor(INK)
    c.setLineWidth(0.8)
    c.setFillColor(BAND_BG)
    c.rect(margin_l, y - 4.5 * cm, content_w, 4.5 * cm, fill=1, stroke=1)
    c.setFillColor(INK)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(margin_l + 0.3 * cm, y - 0.6 * cm,
                 f"ZUSAMMENFASSUNG — VERANLAGUNG {declaration.year}")

    c.setFont("Helvetica", 9)
    rows = [
        ("Gewinn aus selbständiger Tätigkeit (Anlage S)", gewinn_str),
        ("Krankenversicherung Basis (§10 Abs.1 Nr.3 EStG)",
         f"{float(data.get('kv_basis') or 0):.2f} €"),
        ("Krankenversicherung Zusatz",
         f"{float(data.get('kv_zusatz') or 0):.2f} €"),
        ("Pflegeversicherung",
         f"{float(data.get('pflege') or 0):.2f} €"),
        ("Gesetzliche Rentenversicherung",
         f"{float(data.get('rente_gesetz') or 0):.2f} €"),
        ("Rürup-Rente / Berufsunfähigkeitsversicherung",
         f"{float(data.get('rurup') or 0) + float(data.get('bu') or 0):.2f} €"),
    ]
    row_y = y - 1.2 * cm
    for label, val in rows:
        c.setFillColor(INK)
        c.setFont("Helvetica", 9)
        c.drawString(margin_l + 0.4 * cm, row_y, label)
        c.setFont("Helvetica-Bold", 9)
        c.drawRightString(margin_l + content_w - 0.4 * cm, row_y, val)
        row_y -= 0.5 * cm
    y -= 5.0 * cm

    # Anlagen tick list
    y = ensure_space(y, 3 * cm)
    c.setFillColor(MUTED)
    c.setFont("Helvetica-Bold", 8)
    c.drawString(margin_l, y, "ABGEGEBENE ANLAGEN")
    y -= 0.45 * cm
    anlagen = ["Anlage S", "Anlage EÜR", "Anlage Vorsorgeaufwand"]
    ax = margin_l
    c.setFont("Helvetica", 9)
    for a in anlagen:
        c.setFillColor(INK)
        c.rect(ax, y - 0.3 * cm, 0.3 * cm, 0.3 * cm, fill=1, stroke=1)
        c.setStrokeColor(HexColor("#ffffff"))
        c.setLineWidth(1.3)
        c.line(ax + 0.05 * cm, y - 0.15 * cm, ax + 0.12 * cm, y - 0.25 * cm)
        c.line(ax + 0.12 * cm, y - 0.25 * cm, ax + 0.25 * cm, y - 0.04 * cm)
        c.setFillColor(INK)
        c.setStrokeColor(BOX_BORDER)
        c.setFont("Helvetica-Bold", 9)
        c.drawString(ax + 0.45 * cm, y - 0.2 * cm, a)
        ax += 0.45 * cm + c.stringWidth(a, "Helvetica-Bold", 9) + 0.8 * cm

    draw_footer(page_no[0])
    c.save()
    buf.seek(0)
    return buf.getvalue()


# ───────────────────────────────────────────────────────────────────
# Year-over-year copy — Permanent + Semi fields are carried forward,
# Annual fields are reset to default. Maps from architecture doc.
# ───────────────────────────────────────────────────────────────────

# Permanent: rarely change (one-time set, may need confirmation)
_PERMANENT_FIELDS = {
    "steuer_id", "steuer_nummer", "vorname", "nachname",
    "geburtsdatum", "religion",
    # Behinderung: once recognized rarely changes
    "eigene_gdb", "eigene_merkmal",
    # Spouse identity
    "spouse_vorname", "spouse_nachname", "spouse_geburtsdatum",
    "spouse_steuer_id", "spouse_religion",
}

# Semi-permanent: yearly confirmation prompted in UI
_SEMI_PERMANENT_FIELDS = {
    "strasse", "plz", "ort", "familienstand", "steuerklasse",
    "iban", "kontoinhaber", "taetigkeit",
    # Rental property identity (per-property)
    "v_adresse",
    # Pflegegrad may be reassessed yearly
    "pflege_grad",
    # Spouse veranlagungsart usually stable
    "veranlagungsart",
    # Commute distance — usually stable unless job change
    "pendler_km", "pendler_mittel",
}

# Everything else is Annual — reset to default each year.


def carry_forward_fields(prev_data: dict) -> dict:
    """Filter prev year's data to only Permanent + Semi-Permanent fields.
    Returns dict suitable for prefilling a new TaxDeclaration."""
    if not prev_data:
        return {}
    keep = _PERMANENT_FIELDS | _SEMI_PERMANENT_FIELDS
    return {k: v for k, v in prev_data.items() if k in keep and v not in (None, "")}


# ───────────────────────────────────────────────────────────────────
# ELSTER XML export — SKELETON only.
# Real ELSTER ERiC integration (Java/C++ library + certificate +
# Finanzamt server) is out of MVP scope. This produces an ELSTER-style
# XML body so the user can inspect the data structure. Direct submission
# requires ERiC; this output is for manual review or DATEV import.
# ───────────────────────────────────────────────────────────────────

def _xml_escape(s: str) -> str:
    if s is None:
        return ""
    return (str(s)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;"))


def generate_elster_xml(declaration, user) -> str:
    """Render TaxDeclaration as ELSTER-style ESt 1 A XML.

    NOT a real ELSTER submission — that requires ERiC library + cert.
    This is a structured XML dump customers can use for:
    - Manual review of structured data
    - Import into other tax software (DATEV, lexware)
    - Future ELSTER ERiC integration (Phase 10)
    """
    data = deserialize_data(declaration.data)
    year = declaration.year

    def field(tag: str, value, indent: int = 4) -> str:
        if value in (None, ""):
            return ""
        return f"{' ' * indent}<{tag}>{_xml_escape(value)}</{tag}>\n"

    def amount(tag: str, value, indent: int = 4) -> str:
        if value in (None, ""):
            return ""
        try:
            v = float(value)
            if v == 0:
                return ""
            return f"{' ' * indent}<{tag}>{v:.2f}</{tag}>\n"
        except Exception:
            return ""

    kinder_xml = ""
    kinder = data.get("kinder") or []
    if isinstance(kinder, list) and kinder:
        kinder_xml = "  <Kinder>\n"
        for k in kinder:
            if not isinstance(k, dict):
                continue
            kinder_xml += "    <Kind>\n"
            kinder_xml += field("Vorname", k.get("vorname"), 6)
            kinder_xml += field("Geburtsdatum", k.get("geburtsdatum"), 6)
            kinder_xml += field("SteuerID", k.get("steuer_id"), 6)
            kinder_xml += field("Kindergeld", k.get("kindergeld"), 6)
            kinder_xml += field("GeteiltesSorgerecht", k.get("shared_custody"), 6)
            kinder_xml += "    </Kind>\n"
        kinder_xml += "  </Kinder>\n"

    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<!-- AutoTax.Cloud Entwurf — KEIN OFFIZIELLES ELSTER-XML -->',
        '<!-- Generated for user review; not submittable to Finanzamt without ERiC -->',
        f'<Steuererklaerung jahr="{year}" formular="ESt_1_A" version="autotax-1.0">',
        '  <Erstellt>',
        f'    <Datum>{date.today().isoformat()}</Datum>',
        f'    <Quelle>AutoTax.Cloud</Quelle>',
        f'    <Kunde>{_xml_escape(user.email if user else "")}</Kunde>',
        '  </Erstellt>',
        '',
        '  <Mantelbogen>',
    ]
    parts.append(field("SteuerID", data.get("steuer_id")))
    parts.append(field("Steuernummer", data.get("steuer_nummer")))
    parts.append(field("Vorname", data.get("vorname")))
    parts.append(field("Nachname", data.get("nachname")))
    parts.append(field("Geburtsdatum", data.get("geburtsdatum")))
    parts.append(field("Religion", data.get("religion")))
    parts.append(field("Familienstand", data.get("familienstand")))
    parts.append(field("Steuerklasse", data.get("steuerklasse")))
    parts.append('    <Wohnanschrift>')
    parts.append(field("Strasse", data.get("strasse"), 6))
    parts.append(field("PLZ", data.get("plz"), 6))
    parts.append(field("Ort", data.get("ort"), 6))
    parts.append('    </Wohnanschrift>')
    parts.append('    <Bankverbindung>')
    parts.append(field("IBAN", data.get("iban"), 6))
    parts.append(field("Kontoinhaber", data.get("kontoinhaber"), 6))
    parts.append('    </Bankverbindung>')
    parts.append('  </Mantelbogen>')

    # Ehepartner XML — only when verheiratet + data exists
    if data.get("familienstand") == "verheiratet" and (
        data.get("spouse_vorname") or data.get("spouse_steuer_id")
    ):
        parts.append('')
        parts.append('  <Ehepartner>')
        parts.append(field("Vorname", data.get("spouse_vorname")))
        parts.append(field("Nachname", data.get("spouse_nachname")))
        parts.append(field("Geburtsdatum", data.get("spouse_geburtsdatum")))
        parts.append(field("SteuerID", data.get("spouse_steuer_id")))
        parts.append(field("Religion", data.get("spouse_religion")))
        parts.append(amount("Bruttoarbeitslohn", data.get("spouse_lohn_brutto")))
        parts.append(amount("Lohnsteuer", data.get("spouse_lohnsteuer")))
        parts.append(field("Veranlagungsart", data.get("veranlagungsart") or "zusammen"))
        parts.append('  </Ehepartner>')
    parts.append('')

    if kinder_xml:
        parts.append(kinder_xml.rstrip("\n"))
        parts.append('')

    parts.append('  <AnlageS>')
    parts.append(field("Taetigkeit", data.get("taetigkeit")))
    parts.append(amount("GewinnAusEUR", data.get("gewinn_eur")))
    parts.append(amount("Veraeusserungsgewinn", data.get("veraeusserungsgewinn")))
    parts.append('  </AnlageS>')

    if data.get("lohn_brutto") or data.get("lohnsteuer") or data.get("pendler_km"):
        parts.append('')
        parts.append('  <AnlageN>')
        parts.append(amount("Bruttoarbeitslohn", data.get("lohn_brutto")))
        parts.append(amount("Lohnsteuer", data.get("lohnsteuer")))
        parts.append(amount("Solidaritaetszuschlag", data.get("soli_n")))
        parts.append(amount("Kirchensteuer", data.get("kirchensteuer")))
        parts.append(amount("Werbungskosten", data.get("werbungskosten_n")))
        if data.get("pendler_km"):
            pp = pendlerpauschale(data.get("pendler_km"), data.get("pendler_tage"))
            parts.append(field("EntfernungKm", data.get("pendler_km")))
            parts.append(field("Arbeitstage", data.get("pendler_tage")))
            parts.append(field("Verkehrsmittel", data.get("pendler_mittel")))
            parts.append(amount("Entfernungspauschale", pp))
        if data.get("homeoffice_tage"):
            ho_p = min(float(data.get("homeoffice_tage") or 0) * 6, 1260)
            parts.append(field("HomeofficeTage", data.get("homeoffice_tage")))
            parts.append(amount("HomeofficePauschale", ho_p))
        parts.append('  </AnlageN>')

    if data.get("v_einnahmen") or data.get("v_adresse"):
        parts.append('')
        parts.append('  <AnlageV>')
        parts.append(field("Mietobjekt", data.get("v_adresse")))
        parts.append(amount("Mieteinnahmen", data.get("v_einnahmen")))
        parts.append(amount("NebenkostenErhalten", data.get("v_nebenkosten")))
        parts.append(amount("AfA", data.get("v_afa")))
        parts.append(amount("Schuldzinsen", data.get("v_zinsen")))
        parts.append(amount("Erhaltungsaufwand", data.get("v_erhaltung")))
        parts.append(amount("Grundsteuer", data.get("v_grundsteuer")))
        parts.append(amount("SonstigeWerbungskosten", data.get("v_sonst")))
        parts.append('  </AnlageV>')

    kap_keys = ("kap_zinsen", "kap_kursgewinn", "kap_quellensteuer",
                "kap_quellensteuer_ausland", "freistellungsauftrag")
    if any(data.get(k) for k in kap_keys):
        parts.append('')
        parts.append('  <AnlageKAP>')
        parts.append(amount("ZinsenDividenden", data.get("kap_zinsen")))
        parts.append(amount("Kursgewinne", data.get("kap_kursgewinn")))
        parts.append(amount("KESt", data.get("kap_quellensteuer")))
        parts.append(amount("AuslQuellensteuer", data.get("kap_quellensteuer_ausland")))
        parts.append(amount("Freistellungsauftrag", data.get("freistellungsauftrag")))
        parts.append('  </AnlageKAP>')

    if data.get("eigene_gdb") or data.get("eigene_merkmal"):
        parts.append('')
        parts.append('  <AnlageBehinderung>')
        parts.append(field("GdB", data.get("eigene_gdb")))
        parts.append(field("Merkzeichen", data.get("eigene_merkmal")))
        parts.append(field("Pflegegrad", data.get("pflege_grad")))
        pb = pauschbetrag_for_gdb(int(data.get("eigene_gdb") or 0),
                                   data.get("eigene_merkmal"))
        parts.append(amount("Pauschbetrag", pb))
        parts.append('  </AnlageBehinderung>')

    ab_keys = ("krankheitskosten", "pflegekosten", "bestattungskosten",
               "scheidungskosten", "kurkosten")
    if any(data.get(k) for k in ab_keys):
        parts.append('')
        parts.append('  <AussergewoehnlicheBelastungen>')
        parts.append(amount("Krankheitskosten", data.get("krankheitskosten")))
        parts.append(amount("Pflegekosten", data.get("pflegekosten")))
        parts.append(amount("Bestattungskosten", data.get("bestattungskosten")))
        parts.append(amount("Scheidungskosten", data.get("scheidungskosten")))
        parts.append(amount("Kurkosten", data.get("kurkosten")))
        parts.append('  </AussergewoehnlicheBelastungen>')

    so_keys = ("spenden_geld", "spenden_partei", "steuerberater",
               "kirchensteuer_so", "handwerker_lohn", "haushaltsdienst",
               "haushaltshilfe_mini")
    if any(data.get(k) for k in so_keys):
        parts.append('')
        parts.append('  <Sonderausgaben>')
        parts.append(amount("SpendenGeld", data.get("spenden_geld")))
        parts.append(amount("SpendenPartei", data.get("spenden_partei")))
        parts.append(amount("Steuerberater", data.get("steuerberater")))
        parts.append(amount("KirchensteuerGezahlt", data.get("kirchensteuer_so")))
        parts.append(amount("HandwerkerLohn35a", data.get("handwerker_lohn")))
        parts.append(amount("Haushaltsdienst35a", data.get("haushaltsdienst")))
        parts.append(amount("HaushaltshilfeMini35a", data.get("haushaltshilfe_mini")))
        parts.append('  </Sonderausgaben>')

    vorsorge_keys = ("kv_basis", "kv_zusatz", "pflege", "rente_gesetz",
                     "rurup", "bu")
    if any(data.get(k) for k in vorsorge_keys):
        parts.append('')
        parts.append('  <AnlageVorsorgeaufwand>')
        parts.append(amount("KrankenversicherungBasis", data.get("kv_basis")))
        parts.append(amount("KrankenversicherungZusatz", data.get("kv_zusatz")))
        parts.append(amount("Pflegeversicherung", data.get("pflege")))
        parts.append(amount("GesetzlicheRente", data.get("rente_gesetz")))
        parts.append(amount("RuerupRente", data.get("rurup")))
        parts.append(amount("Berufsunfaehigkeit", data.get("bu")))
        parts.append('  </AnlageVorsorgeaufwand>')

    parts.append('</Steuererklaerung>')
    # Filter empty lines from amount() returning "" (no value)
    return "".join(p if p.endswith("\n") else p + "\n" for p in parts if p != "")


__all__ = [
    "FORM_SECTIONS",
    "autofill_from_user_data",
    "validate",
    "serialize_data",
    "deserialize_data",
    "generate_pdf_skeleton",
    "carry_forward_fields",
    "detect_insurance_amounts",
    "generate_elster_xml",
]
