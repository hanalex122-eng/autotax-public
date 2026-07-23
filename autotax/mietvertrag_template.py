"""Mietvertrag — PURE template engine (no DB, no HTTP, no ORM).

Sprint 9.0a. Assembles a German Wohnraummietvertrag from structured choices (`vertrag_json`)
by dispatching on `vertrag_typ` through a REGISTRY, so adding a new contract type
(Indexmiete, befristet, Gewerbe, Garage, Stellplatz, later WG) is a new registry +
catalogue entry — `render()` and existing types are not touched. (Design §1.1.)

`render(vertrag_json) -> {blocks, warnings, template_version}`. The API/PDF layer turns
`blocks` into reportlab flowables; it does not embed clause text itself.

TEMPLATE_VERSION is stamped into every finalised contract so an old contract re-produces
identically even if this template later changes.

DRAFT NOTICE: the German clause texts below are parametric data, pending professional
Mietrecht review (H9). They MUST NOT go to production unreviewed.

Duck-typed input: `vertrag_json` is a plain dict (see design §1). No DB, no I/O here.
"""
from __future__ import annotations

from typing import Optional

TEMPLATE_VERSION = 1

# Legal safety rail (§551): Kaution is capped at this multiple of the Nettokaltmiete.
KAUTION_MAX_FAKTOR = 3

DISCLAIMER = ("Muster ohne Gewähr; keine Rechtsberatung. Im Zweifel Mietrecht-Fachanwalt "
              "oder Haus & Grund. Der Vermieter versendet eigenverantwortlich.")


def _eur(v) -> str:
    try:
        return ("%.2f" % float(v)).replace(".", ",") + " €"
    except (TypeError, ValueError):
        return "—"


def _g(d: dict, *path, default=None):
    cur = d
    for k in path:
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    return cur


# ── Clause catalogue — parametric text (DRAFT, pending Mietrecht review) ─────────────
# Each builder returns (ueberschrift, [absatz, ...]) or a dict block for tables.
# NOTE: technical structure only; no legal interpretation is asserted in code.

def _c_parteien(vj):
    verm = _g(vj, "parteien", "vermieter", default={})
    miet = _g(vj, "parteien", "mieter", default={})
    vname = verm.get("name") or "—"
    vadr = verm.get("adresse") or ""
    mname = miet.get("name") or "—"
    madr = miet.get("adresse") or ""
    return ("Vertragsparteien", [
        f"Zwischen {vname}{(', ' + vadr) if vadr else ''} (nachfolgend „Vermieter“) und "
        f"{mname}{(', ' + madr) if madr else ''} (nachfolgend „Mieter“) wird der folgende "
        f"Mietvertrag über Wohnraum geschlossen."])


def _c_mietobjekt(vj):
    o = _g(vj, "objekt", default={})
    adr = o.get("adresse") or "—"
    whg = o.get("wohnung") or ""
    flae = o.get("wohnflaeche")
    zus = []
    if o.get("zimmer"):
        zus.append(f"{o['zimmer']} Zimmer")
    for key, label in (("keller", "Keller"), ("stellplatz", "Stellplatz")):
        if o.get(key):
            zus.append(label)
    extras = ("Mitvermietet: " + ", ".join(zus) + ".") if zus else ""
    schl = f" Übergeben werden {o['schluessel']} Schlüssel." if o.get("schluessel") else ""
    flae_txt = f" mit einer Wohnfläche von {flae} m²" if flae is not None else ""
    return ("Mietobjekt", [
        f"Vermietet wird die Wohnung in {adr}{(', ' + whg) if whg else ''}{flae_txt}. "
        f"{extras}{schl}".strip()])


def _c_mietzeit_unbefristet(vj):
    beginn = _g(vj, "mietzeit", "beginn") or "—"
    return ("Mietzeit", [
        f"Das Mietverhältnis beginnt am {beginn} und läuft auf unbestimmte Zeit. "
        f"Die Kündigung richtet sich nach den gesetzlichen Vorschriften; die Kündigungsfristen "
        f"des § 573c BGB gelten zugunsten des Mieters und werden nicht verkürzt."])


def _c_mietzeit_staffel(vj):
    beginn = _g(vj, "mietzeit", "beginn") or "—"
    schritte = _g(vj, "mietzeit", "staffel_schritte", default=[]) or []
    rows = [["ab", "Nettokaltmiete"]]
    rows += [[str(s.get("ab", "—")), _eur(s.get("kaltmiete"))] for s in schritte]
    return ("Mietzeit (Staffelmiete)", [
        f"Das Mietverhältnis beginnt am {beginn} und läuft auf unbestimmte Zeit. "
        f"Es wird eine Staffelmiete vereinbart; zwischen zwei Staffeln liegt jeweils mindestens "
        f"ein Jahr:",
        {"art": "tabelle", "rows": rows},
        "Die Kündigungsfristen des § 573c BGB gelten zugunsten des Mieters."])


def _c_miete(vj):
    m = _g(vj, "miete", default={})
    kalt = m.get("kaltmiete") or 0
    nk = m.get("nk_voraus") or 0
    heiz = m.get("heizkosten_voraus") or 0
    summe = (float(kalt) if kalt else 0) + (float(nk) if nk else 0) + (float(heiz) if heiz else 0)
    termin = m.get("zahlungstermin") or "3."
    bank = m.get("bankverbindung") or "—"
    rows = [["Nettokaltmiete", _eur(kalt)],
            ["Betriebskostenvorauszahlung", _eur(nk)],
            ["Heizkostenvorauszahlung", _eur(heiz)],
            ["Gesamtmiete", _eur(summe)]]
    return ("Miete", [
        "Die monatliche Miete setzt sich wie folgt zusammen:",
        {"art": "tabelle", "rows": rows},
        f"Die Miete ist monatlich im Voraus, spätestens am {termin} Werktag eines Monats, "
        f"auf folgendes Konto zu zahlen: {bank}."])


def _c_betriebskosten(vj):
    umlage = _g(vj, "betriebskosten_umlage", default=[]) or []
    liste = ", ".join(umlage) if umlage else "die in der Betriebskostenverordnung genannten Kostenarten"
    return ("Betriebskosten", [
        "Der Mieter trägt die Betriebskosten im Sinne der Betriebskostenverordnung (BetrKV) "
        "durch Vorauszahlung mit jährlicher Abrechnung. Umgelegt werden: " + liste + ".",
        "Über die Vorauszahlungen wird jährlich abgerechnet."])


def _c_kaution(vj):
    betrag = _g(vj, "kaution", "betrag")
    return ("Kaution", [
        f"Der Mieter leistet eine Barkaution in Höhe von {_eur(betrag)}. Der Vermieter legt die "
        f"Kaution getrennt von seinem Vermögen zu üblichen Zinsen an; die Zinsen stehen dem Mieter zu."])


def _c_schoenheitsreparaturen(vj):
    variant = _g(vj, "klauseln", "schoenheitsrep", default="keine")
    if variant == "bgh_gueltig":
        txt = ("Der Mieter übernimmt die Schönheitsreparaturen nach tatsächlichem Bedarf, ohne "
               "starren Fristenplan und ohne feste Quoten. Wird die Wohnung unrenoviert übergeben, "
               "entfällt die Verpflichtung, soweit kein angemessener Ausgleich vereinbart ist.")
    else:
        txt = ("Schönheitsreparaturen werden nicht auf den Mieter abgewälzt; sie verbleiben beim "
               "Vermieter.")
    return ("Schönheitsreparaturen", [txt])


def _c_kleinreparaturen(vj):
    kr = _g(vj, "klauseln", "kleinrep", default={})
    if not kr or not kr.get("aktiv"):
        return ("Kleinreparaturen", [
            "Eine Kostenbeteiligung des Mieters an Kleinreparaturen wird nicht vereinbart."])
    einzel = kr.get("einzel_cap") or 100
    jahr = kr.get("jahres_cap")
    jahr_txt = f", höchstens jedoch {_eur(jahr)} pro Jahr" if jahr else ", höchstens 8 % der jährlichen Nettokaltmiete pro Jahr"
    return ("Kleinreparaturen", [
        f"Der Mieter trägt die Kosten kleiner Instandhaltungen an Teilen, die seinem häufigen "
        f"Zugriff unterliegen, bis {_eur(einzel)} je Einzelfall{jahr_txt}."])


def _c_tierhaltung(vj):
    return ("Tierhaltung", [
        "Die Haltung von Kleintieren ist ohne besondere Erlaubnis gestattet. Für Hunde und Katzen "
        "ist die Zustimmung des Vermieters erforderlich, die nicht unbillig verweigert werden darf."])


def _c_untervermietung(vj):
    return ("Untervermietung", [
        "Eine Überlassung des Wohnraums an Dritte bedarf der Erlaubnis des Vermieters "
        "(§ 553 BGB)."])


def _c_schluss(vj):
    return ("Schlussbestimmungen", [
        "Änderungen und Ergänzungen dieses Vertrages bedürfen der Schriftform. Sollte eine "
        "Bestimmung unwirksam sein oder werden, bleibt der Vertrag im Übrigen wirksam."])


def _c_unterschriften(vj):
    return ("Unterschriften", [{"art": "unterschrift"}])


_KATALOG = {
    "parteien": _c_parteien,
    "mietobjekt": _c_mietobjekt,
    "mietzeit_unbefristet": _c_mietzeit_unbefristet,
    "mietzeit_staffel": _c_mietzeit_staffel,
    "miete": _c_miete,
    "betriebskosten": _c_betriebskosten,
    "kaution": _c_kaution,
    "schoenheitsreparaturen": _c_schoenheitsreparaturen,
    "kleinreparaturen": _c_kleinreparaturen,
    "tierhaltung": _c_tierhaltung,
    "untervermietung": _c_untervermietung,
    "schluss": _c_schluss,
    "unterschriften": _c_unterschriften,
}

# ── Registry: type → clause order + rails (data, not code). Design §1.1. ─────────────
_COMMON_TAIL = ["miete", "betriebskosten", "kaution", "schoenheitsreparaturen",
                "kleinreparaturen", "tierhaltung", "untervermietung", "schluss", "unterschriften"]

VERTRAG_TYPEN = {
    "wohnraum_unbefristet": {
        "titel": "Mietvertrag über Wohnraum",
        "klausel_ids": ["parteien", "mietobjekt", "mietzeit_unbefristet"] + _COMMON_TAIL,
        "rails": {"kaution_max_faktor": KAUTION_MAX_FAKTOR, "mietpreisbremse_hinweis": True},
    },
    "wohnraum_staffel": {
        "titel": "Mietvertrag über Wohnraum (Staffelmiete)",
        "klausel_ids": ["parteien", "mietobjekt", "mietzeit_staffel"] + _COMMON_TAIL,
        "rails": {"kaution_max_faktor": KAUTION_MAX_FAKTOR, "mietpreisbremse_hinweis": True},
    },
}


def supported_types():
    return sorted(VERTRAG_TYPEN.keys())


def apply_rails(vertrag_json: dict) -> tuple[dict, list]:
    """Enforce legal safety rails PER TYPE (not global). Returns (normalised_json, warnings).
    Never raises for user data; caps/normalises and collects neutral warnings."""
    vj = dict(vertrag_json or {})
    typ = VERTRAG_TYPEN.get(vj.get("vertrag_typ"))
    warnings: list = []
    if typ is None:
        return vj, warnings
    rails = typ.get("rails", {})

    # Kaution cap (per-type; e.g. a future Gewerbe type would carry no cap)
    faktor = rails.get("kaution_max_faktor")
    if faktor:
        kalt = _g(vj, "miete", "kaltmiete")
        betrag = _g(vj, "kaution", "betrag")
        try:
            if kalt and betrag and float(betrag) > faktor * float(kalt):
                cap = round(faktor * float(kalt), 2)
                vj.setdefault("kaution", {})["betrag"] = cap
                warnings.append(
                    f"Die Kaution wurde auf das gesetzlich zulässige Höchstmaß von {faktor} "
                    f"Nettokaltmieten ({_eur(cap)}) begrenzt.")
        except (TypeError, ValueError):
            pass

    # Mietpreisbremse — collect attention, never rule.
    if rails.get("mietpreisbremse_hinweis"):
        warnings.append(
            "In Gebieten mit Mietpreisbremse gilt eine Obergrenze für die zulässige Miete. "
            "Bitte prüfen Sie, ob Ihre Wohnung betroffen ist — dieses Muster trifft dazu keine Aussage.")

    return vj, warnings


def render(vertrag_json: dict) -> dict:
    """Assemble the contract into ordered blocks + warnings. Pure; dispatch via registry.
    Raises ValueError only for an unknown vertrag_typ (a programming/config error)."""
    vj = dict(vertrag_json or {})
    typ_key = vj.get("vertrag_typ")
    typ = VERTRAG_TYPEN.get(typ_key)
    if typ is None:
        raise ValueError("Unbekannter vertrag_typ: %r (bekannt: %s)" % (typ_key, supported_types()))

    vj, warnings = apply_rails(vj)

    blocks = [{"art": "titel", "text": typ["titel"]}]
    for nr, cid in enumerate(typ["klausel_ids"], start=1):
        builder = _KATALOG.get(cid)
        if builder is None:
            continue
        ueberschrift, absaetze = builder(vj)
        blocks.append({"art": "ueberschrift", "nr": nr, "text": f"§ {nr} {ueberschrift}"})
        for a in absaetze:
            if isinstance(a, dict):
                blocks.append(a)
            else:
                blocks.append({"art": "absatz", "text": a})

    blocks.append({"art": "disclaimer", "text": DISCLAIMER})
    return {"blocks": blocks, "warnings": warnings, "template_version": TEMPLATE_VERSION,
            "vertrag_typ": typ_key}
