"""Nebenkostenabrechnung — PURE domain rules (no DB, no HTTP, no ORM).

Sprint 2. The part of a German utility-cost statement (Betriebs-/Nebenkostenabrechnung, §556 BGB)
that can be reasoned about and tested without a database: which costs are umlagefähig, how a cost is
split across tenants (Umlageschlüssel × Zeitanteil), how the vacant-unit share stays with the
landlord, and how the balance (Guthaben/Nachzahlung) comes out.

Binding architecture principles (.claude/nk_architecture.md, CLAUDE.md):
  A. A finalised statement is immutable; the frozen snapshot — not the PDF — is the record of truth.
  B. Finalise = legal lock; a correction needs an explicit Unlock or a new Revision.
  C. Single-Ledger: the Vorauszahlung is computed ONLY from the Mietkonto (immo_rules.monat_nk_soll).
     This module never invents a second advance source.

CALCULATION_VERSION is stamped into every snapshot. Bump it whenever a rule here changes output, so
an old statement never silently re-renders differently.

Extensibility: `schluessel` may be any of the five methods now. Sprint 2 COMPUTES wohnflaeche and
wohneinheiten; personenzahl / verbrauch / individuell are valid stored values that fall back to
wohnflaeche WITH A VISIBLE NOTE until wired in Sprint 3 — never a silent wrong split.

Duck-typed inputs (testable without the ORM):
  unit     : .id .wohnflaeche .mea
  tenancy  : .id .unit_id .mieter_name .von .bis .personenzahl  (+ what monat_nk_soll needs)
"""
from __future__ import annotations

from calendar import monthrange
from datetime import date
from typing import Optional

from autotax import immo_rules as _rules

CALCULATION_VERSION = 2   # v2 (Sprint 3): Personenzahl is computed (v1 fell back to Wohnfläche)

# ── vocabulary ────────────────────────────────────────────────────────

STATUS_ENTWURF = "entwurf"
STATUS_FINAL = "final"

SCHLUESSEL = ("wohnflaeche", "personenzahl", "wohneinheiten", "verbrauch", "individuell")
SCHLUESSEL_LABEL = {
    "wohnflaeche": "Wohnfläche (m²)", "personenzahl": "Personenzahl",
    "wohneinheiten": "Wohneinheiten", "verbrauch": "Verbrauch", "individuell": "Individuell",
}

# Which allocation methods actually compute. verbrauch/individuell still fall back to Wohnfläche
# with a note (Sprint 3+). personenzahl computes since Sprint 3 (this sprint).
_COMPUTED = ("wohnflaeche", "wohneinheiten", "personenzahl")

# BetrKV §2 operating-cost categories + the umlagefähig knowledge (the correctness core).
# `umlagefaehig` False = the landlord must NOT pass this on (the #1 statement-invalidating mistake).
KATEGORIEN = {
    "heizkosten":        {"label": "Heizkosten",           "umlagefaehig": True,  "schluessel": "verbrauch"},
    "warmwasser":        {"label": "Warmwasser",           "umlagefaehig": True,  "schluessel": "verbrauch"},
    "wasser":            {"label": "Wasser (kalt)",        "umlagefaehig": True,  "schluessel": "wohnflaeche"},
    "abwasser":          {"label": "Abwasser",             "umlagefaehig": True,  "schluessel": "wohnflaeche"},
    "muell":             {"label": "Müllabfuhr",           "umlagefaehig": True,  "schluessel": "personenzahl"},
    "grundsteuer":       {"label": "Grundsteuer",          "umlagefaehig": True,  "schluessel": "wohnflaeche"},
    "gebaeudeversicherung": {"label": "Gebäudeversicherung", "umlagefaehig": True, "schluessel": "wohnflaeche"},
    "hausmeister":       {"label": "Hausmeister",          "umlagefaehig": True,  "schluessel": "wohnflaeche"},
    "allgemeinstrom":    {"label": "Allgemeinstrom",       "umlagefaehig": True,  "schluessel": "wohnflaeche"},
    "gartenpflege":      {"label": "Gartenpflege",         "umlagefaehig": True,  "schluessel": "wohnflaeche"},
    "schornsteinfeger":  {"label": "Schornsteinfeger",     "umlagefaehig": True,  "schluessel": "wohnflaeche"},
    "winterdienst":      {"label": "Winterdienst",         "umlagefaehig": True,  "schluessel": "wohnflaeche"},
    "strassenreinigung": {"label": "Straßenreinigung",     "umlagefaehig": True,  "schluessel": "wohnflaeche"},
    "sonstige":          {"label": "Sonstige",             "umlagefaehig": True,  "schluessel": "wohnflaeche"},
    # NOT umlagefähig — defaulted OFF so the landlord cannot silently dun the tenant for these:
    "verwaltung":        {"label": "Verwaltungskosten",    "umlagefaehig": False, "schluessel": "wohnflaeche"},
    "reparatur":         {"label": "Reparatur/Instandhaltung", "umlagefaehig": False, "schluessel": "wohnflaeche"},
    "ruecklage":         {"label": "Instandhaltungsrücklage",  "umlagefaehig": False, "schluessel": "wohnflaeche"},
    "finanzierung":      {"label": "Finanzierung (Zins/Tilgung)", "umlagefaehig": False, "schluessel": "wohnflaeche"},
}


class NkError(ValueError):
    """Business-rule violation (unknown key, editing a final statement, …)."""


def umlagefaehig_default(kategorie: str) -> bool:
    return KATEGORIEN.get(kategorie, {}).get("umlagefaehig", True)


def default_schluessel(kategorie: str) -> str:
    return KATEGORIEN.get(kategorie, {}).get("schluessel", "wohnflaeche")


def kategorie_label(kategorie: str) -> str:
    return KATEGORIEN.get(kategorie, {}).get("label", kategorie)


# ── immutability (Principle B) ────────────────────────────────────────


def is_final(status) -> bool:
    return str(status or "") == STATUS_FINAL


def require_editable(status) -> None:
    """Guard for every write path. A finalised statement is a legal document, not a form."""
    if is_final(status):
        raise NkError("Die Abrechnung ist abgeschlossen (final) und kann nicht geändert werden. "
                      "Für eine Korrektur bitte entsperren oder eine neue Abrechnung anlegen.")


# ── Zeitanteil (mid-year move in/out) ─────────────────────────────────


def _period_months(von: date, bis: date):
    """The list of (year, month) in the settlement period, inclusive."""
    y, m = von.year, von.month
    out = []
    while (y, m) <= (bis.year, bis.month):
        out.append((y, m))
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return out


def zeitanteil(tenancy, von: date, bis: date) -> float:
    """Fraction of the settlement period the tenancy occupied its unit, weighted by the day-share of
    each month (a move-in on the 15th counts ~half that month). 0..1 of the whole period length.

    This is the SAME proration the rent uses (immo_rules.month_proration), so the statement and the
    Mietkonto agree about how long a tenant lived there."""
    months = _period_months(von, bis)
    if not months:
        return 0.0
    occupied = sum(_rules.month_proration(tenancy, y, m) for (y, m) in months)
    return occupied / len(months)


# ── the allocation share per tenant (dispatch on Schlüssel) ───────────


def _computes(schluessel: str) -> bool:
    return schluessel in _COMPUTED


def basis_weight(schluessel: str, unit, tenancy, za: float) -> float:
    """The un-normalised weight of one tenancy for one Schlüssel (before dividing by the sum).
    Computes wohnflaeche, wohneinheiten and personenzahl; verbrauch/individuell fall back to
    wohnflaeche (the caller records a note). Time-weighting by `za` is applied by every key."""
    if schluessel == "wohneinheiten":
        return za                                  # each occupied unit weighs equally, × Zeitanteil
    if schluessel == "personenzahl":
        # A vacant unit (_Dummy, personenzahl None) contributes 0 — there are no persons there, so no
        # invented head count. The missing-data case (an ACTIVE tenant without personenzahl) is caught
        # by _effective_schluessel BEFORE we get here and falls the whole position back to Wohnfläche.
        n = getattr(tenancy, "personenzahl", None)
        return float(n or 0) * za
    # wohnflaeche (default) and every not-yet-wired key use area × Zeitanteil
    return _flaeche(unit) * za


def _effective_schluessel(schluessel: str, active_tenancies) -> tuple:
    """Resolve the key actually used for a position, and any note.

    personenzahl needs a person count for EVERY occupied tenant to be split fairly. If one is missing
    (None or 0), we cannot do an honest per-person split → fall back to Wohnfläche WITH a note (the
    Sprint 0/1 discipline: never a silent wrong number). Returns (effective_schluessel, note_or_None).
    """
    if schluessel == "personenzahl":
        missing = [getattr(t, "mieter_name", "?") for t in active_tenancies
                   if not (getattr(t, "personenzahl", None) and int(getattr(t, "personenzahl")) > 0)]
        if missing:
            return "wohnflaeche", ("Personenzahl fehlt bei: " + ", ".join(missing)
                                   + " — Verteilung nach Wohnfläche.")
        return "personenzahl", None
    if not _computes(schluessel):
        return "wohnflaeche", (f"Schlüssel '{SCHLUESSEL_LABEL.get(schluessel, schluessel)}' wird "
                               f"derzeit nach Wohnfläche verteilt (Verbrauch/Individuell folgt).")
    return schluessel, None


def _flaeche(unit) -> float:
    # an agreed key (mea) overrides Wohnfläche when present (§556a: area is only the DEFAULT)
    mea = getattr(unit, "mea", None)
    if mea is not None:
        return float(mea)
    return float(getattr(unit, "wohnflaeche", 0) or 0)


# ── the distribution engine ───────────────────────────────────────────


def verteile(positionen, units, tenancies, von: date, bis: date):
    """Split every umlagefähige cost position across the tenants.

    Returns {
      per_tenant:   {tenancy_id: {name, summe, positionen:[{kategorie, anteil_betrag, anteil_text}]}},
      leerstand:    float,                    # the vacant-unit share the LANDLORD carries
      umlagefaehige_summe: float,
      hinweise:     [str],                    # e.g. a key that fell back to Wohnfläche, a missing area
    }

    Invariant (asserted by the tests): Σ per_tenant.summe + leerstand == umlagefaehige_summe (to the
    cent). The vacant share is NEVER redistributed to the other tenants (a legal error) — it is a
    separate landlord bucket.
    """
    units_by_id = {u.id: u for u in units}
    # tenancies grouped by unit, with their Zeitanteil in the period
    za = {t.id: zeitanteil(t, von, bis) for t in tenancies}
    active = [t for t in tenancies if za[t.id] > 0 and t.unit_id in units_by_id]

    per_tenant = {t.id: {"name": getattr(t, "mieter_name", ""), "summe": 0.0, "positionen": []}
                  for t in active}
    leerstand = 0.0       # truly vacant time — landlord bears it as a LOSS
    eigennutzung = 0.0    # owner-occupied time — landlord's OWN cost (counted in the split)
    umlagefaehige_summe = 0.0
    hinweise = []
    seen_fallback = set()

    for pos in positionen:
        if not getattr(pos, "umlagefaehig", True):
            continue
        betrag = round(float(getattr(pos, "betrag", 0) or 0) * float(getattr(pos, "umlage_pct", 100) or 100) / 100.0, 2)
        if betrag <= 0:
            continue
        umlagefaehige_summe = round(umlagefaehige_summe + betrag, 2)
        raw_schluessel = getattr(pos, "schluessel", "wohnflaeche") or "wohnflaeche"
        if raw_schluessel not in SCHLUESSEL:
            raise NkError(f"Unbekannter Umlageschlüssel: {raw_schluessel}")
        # resolve the key actually used (personenzahl may fall back on missing data; so may verbrauch)
        schluessel, note = _effective_schluessel(raw_schluessel, active)
        if note and note not in seen_fallback:
            hinweise.append(note)
            seen_fallback.add(note)

        # weights across ALL units in the period. A unit's time not covered by a tenancy is either
        # OWNER-OCCUPIED (Eigennutzung — the owner's persons/area count in the denominator, share is
        # the owner's own cost) or VACANT (Leerstand — landlord's loss). Both stay with the landlord,
        # never redistributed to the tenants, but they are reported separately.
        total_w = 0.0
        occ_w = {}       # tenancy_id -> weight
        owner_w = 0.0    # weight of owner-occupied (Eigennutzung) time
        vacant_w = 0.0   # weight of truly vacant time
        for u in units:
            u_tenancies = [t for t in active if t.unit_id == u.id]
            for t in u_tenancies:
                w = basis_weight(schluessel, u, t, za[t.id])
                occ_w[t.id] = occ_w.get(t.id, 0.0) + w
                total_w += w
            vac_za = _unit_vacant_zeitanteil(u, tenancies, von, bis)
            if vac_za > 0:
                eig = getattr(u, "eigennutzung_personen", None)
                dummy = _Dummy(); dummy.personenzahl = eig     # owner's persons for the person split
                w = basis_weight(schluessel, u, dummy, vac_za)
                total_w += w
                if eig is not None and int(eig) > 0:
                    owner_w += w
                else:
                    vacant_w += w

        if total_w <= 0:
            hinweise.append(f"Position '{kategorie_label(getattr(pos, 'kategorie', ''))}' konnte nicht "
                            f"verteilt werden (keine Wohnfläche/Basis hinterlegt).")
            leerstand = round(leerstand + betrag, 2)      # nothing to split on → landlord carries it
            continue

        assigned = 0.0
        for t in active:
            w = occ_w.get(t.id, 0.0)
            if w <= 0:
                continue
            share = round(betrag * w / total_w, 2)
            assigned = round(assigned + share, 2)
            per_tenant[t.id]["summe"] = round(per_tenant[t.id]["summe"] + share, 2)
            per_tenant[t.id]["positionen"].append({
                "kategorie": getattr(pos, "kategorie", ""),
                "label": kategorie_label(getattr(pos, "kategorie", "")),
                "anteil_betrag": share,
                "schluessel": schluessel,
                "anteil_text": _anteil_text(schluessel, w, total_w),
            })
        # the non-tenant remainder splits between the owner's Eigennutzung and true Leerstand by weight
        rest = round(betrag - assigned, 2)
        eig_share = round(betrag * owner_w / total_w, 2) if owner_w > 0 else 0.0
        eig_share = min(eig_share, rest)
        eigennutzung = round(eigennutzung + eig_share, 2)
        leerstand = round(leerstand + (rest - eig_share), 2)

    return {"per_tenant": per_tenant, "leerstand": round(leerstand, 2),
            "eigennutzung": round(eigennutzung, 2),
            "umlagefaehige_summe": umlagefaehige_summe, "hinweise": hinweise}


class _Dummy:
    """A stand-in tenancy for a unit's vacant time (weight only; never receives a share)."""
    id = None
    personenzahl = None


def _unit_vacant_zeitanteil(unit, tenancies, von: date, bis: date) -> float:
    """The fraction of the period the unit had NO tenant — the landlord's Leerstand."""
    months = _period_months(von, bis)
    if not months:
        return 0.0
    u_tenancies = [t for t in tenancies if t.unit_id == unit.id]
    vacant = 0.0
    for (y, m) in months:
        occ = sum(_rules.month_proration(t, y, m) for t in u_tenancies)
        vacant += max(0.0, 1.0 - min(1.0, occ))
    return vacant / len(months)


def _anteil_text(schluessel: str, w: float, total: float) -> str:
    if total <= 0:
        return ""
    if schluessel == "wohneinheiten":
        return f"{round(w, 2)} / {round(total, 2)} Einheiten-Zeitanteil"
    if schluessel == "personenzahl":
        return f"{round(w, 2)} / {round(total, 2)} Personen-Zeitanteil"
    return f"{round(w, 1)} / {round(total, 1)} m²-Zeitanteil"


# ── Vorauszahlung (Principle C: ONLY from monat_nk_soll) ──────────────


def vorauszahlung(tenancy, von: date, bis: date) -> float:
    """The NK advance the tenant was charged over the period = Σ monat_nk_soll for each month.

    This is the ONLY source of the advance (Single-Ledger Principle). It is exactly what the Mietkonto
    charged as the NK part of the rent — the statement and the Mietkonto can never disagree."""
    total = 0.0
    for (y, m) in _period_months(von, bis):
        total += _rules.monat_nk_soll(tenancy, y, m)
    return round(total, 2)


# ── result (Guthaben / Nachzahlung) ───────────────────────────────────


def ergebnis(verteilung, tenancies, von: date, bis: date):
    """Per tenant: umlage (share of costs), vorauszahlung (from the Mietkonto), saldo.
    saldo > 0 → Guthaben (landlord owes tenant); saldo < 0 → Nachzahlung (tenant owes landlord)."""
    by_id = {t.id: t for t in tenancies}
    rows = []
    for tid, data in verteilung["per_tenant"].items():
        t = by_id.get(tid)
        umlage = round(data["summe"], 2)
        voraus = vorauszahlung(t, von, bis) if t is not None else 0.0
        saldo = round(voraus - umlage, 2)
        rows.append({
            "tenancy_id": tid, "name": data["name"],
            "personenzahl": (getattr(t, "personenzahl", None) if t is not None else None),
            "umlage": umlage, "vorauszahlung": voraus, "saldo": saldo,
            "typ": "guthaben" if saldo > 0.005 else ("nachzahlung" if saldo < -0.005 else "ausgeglichen"),
            "positionen": data["positionen"],
        })
    rows.sort(key=lambda r: (r["name"] or ""))
    return {"tenants": rows, "leerstand": verteilung["leerstand"],
            "eigennutzung": verteilung.get("eigennutzung", 0.0),
            "umlagefaehige_summe": verteilung["umlagefaehige_summe"], "hinweise": verteilung["hinweise"]}


# ── 12-month deadline (§556 III) ──────────────────────────────────────


def frist_ueberschritten(zeitraum_bis: date, as_of: Optional[date] = None) -> bool:
    """True if the statement is being finalised later than 12 months after the period end.
    After that a Nachforderung is barred (a Guthaben is still owed) — a warning, not a block."""
    as_of = as_of or date.today()
    y, m = zeitraum_bis.year + 1, zeitraum_bis.month
    dim = monthrange(y, m)[1]
    deadline = date(y, m, min(zeitraum_bis.day, dim))
    return as_of > deadline


# ── the immutable snapshot (Principle A) ──────────────────────────────


def build_snapshot(abrechnung_meta, property_meta, units, tenancies, positionen, von, bis, as_of=None):
    """Freeze EVERYTHING used in the calculation, so the statement re-produces years later even if the
    master data changed. The snapshot — not the PDF — is the record of truth. Stored at finalise on
    NkAbrechnung.ergebnis_snapshot; every read of a FINAL statement derives from this, never from live
    master data."""
    v = verteile(positionen, units, tenancies, von, bis)
    e = ergebnis(v, tenancies, von, bis)
    return {
        "calculation_version": CALCULATION_VERSION,
        "settlement_id": abrechnung_meta.get("id"),
        "abrechnungsperiode": {"von": str(von), "bis": str(bis), "jahr": abrechnung_meta.get("jahr")},
        "property": property_meta,
        "units": [{"id": u.id, "name": getattr(u, "name", ""),
                   "wohnflaeche": getattr(u, "wohnflaeche", None), "mea": getattr(u, "mea", None)}
                  for u in units],
        "tenants": [{"tenancy_id": t.id, "name": getattr(t, "mieter_name", ""),
                     "unit_id": t.unit_id, "von": str(t.von) if t.von else None,
                     "bis": str(t.bis) if t.bis else None,
                     "personenzahl": getattr(t, "personenzahl", None),
                     "zeitanteil": round(zeitanteil(t, von, bis), 4)} for t in tenancies],
        "cost_lines": [{"kategorie": getattr(p, "kategorie", ""), "label": kategorie_label(getattr(p, "kategorie", "")),
                        "betrag": float(getattr(p, "betrag", 0) or 0),
                        "umlagefaehig": bool(getattr(p, "umlagefaehig", True)),
                        "umlage_pct": int(getattr(p, "umlage_pct", 100) or 100),
                        "schluessel": getattr(p, "schluessel", "wohnflaeche")} for p in positionen],
        "allocation": e["tenants"],          # per tenant: shares (allocation_ratios in anteil_text) + saldo
        "leerstand_share": e["leerstand"],
        "eigennutzung_share": e.get("eigennutzung", 0.0),
        "umlagefaehige_summe": e["umlagefaehige_summe"],
        "final_result": [{"tenancy_id": r["tenancy_id"], "name": r["name"], "saldo": r["saldo"],
                          "typ": r["typ"]} for r in e["tenants"]],
        "hinweise": e["hinweise"],
        "frist_ueberschritten": frist_ueberschritten(bis, as_of),
    }
