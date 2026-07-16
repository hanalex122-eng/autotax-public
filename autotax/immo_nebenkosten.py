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

import json as _json
from calendar import monthrange
from datetime import date
from typing import Optional

from autotax import immo_rules as _rules

CALCULATION_VERSION = 4   # v4 (Sprint 4): Verbrauch by Zählerstände + HeizkostenV Grund/Verbrauch split.
                          # v3: Individuell. v2: Personenzahl. v1: only Wohnfläche/Wohneinheiten.

# ── vocabulary ────────────────────────────────────────────────────────

STATUS_ENTWURF = "entwurf"
STATUS_FINAL = "final"

SCHLUESSEL = ("wohnflaeche", "personenzahl", "wohneinheiten", "verbrauch", "individuell")
SCHLUESSEL_LABEL = {
    "wohnflaeche": "Wohnfläche (m²)", "personenzahl": "Personenzahl",
    "wohneinheiten": "Wohneinheiten", "verbrauch": "Verbrauch", "individuell": "Individuell",
}

# Which allocation methods compute via basis_weight (area/person/units). verbrauch and individuell are
# handled by their OWN branches in verteile (readings / explicit amounts), not basis_weight.
_COMPUTED = ("wohnflaeche", "wohneinheiten", "personenzahl")

# HeizkostenV (§7): heating & hot water must NOT be split 100% by meter — a Grundkosten share (by area)
# and a Verbrauchskosten share (by meter). grund_prozent is 30–50 (Verbrauch = 50–70). Default 30/70.
HEIZKOSTENV_KATEGORIEN = ("heizkosten", "warmwasser")
GRUND_PROZENT_DEFAULT = 30
GRUND_PROZENT_MIN = 30
GRUND_PROZENT_MAX = 50
# a cost line's meter art defaults from its category when verbrauch_art is not set explicitly
_ART_DEFAULT = {"heizkosten": "heizung", "warmwasser": "warmwasser", "wasser": "wasser",
                "abwasser": "wasser", "allgemeinstrom": "strom"}


def clamp_grund(p) -> int:
    try:
        p = int(p)
    except (TypeError, ValueError):
        return GRUND_PROZENT_DEFAULT
    return max(GRUND_PROZENT_MIN, min(GRUND_PROZENT_MAX, p))


def is_heizkostenv(kategorie: str) -> bool:
    return kategorie in HEIZKOSTENV_KATEGORIEN

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


def _eur(x) -> str:
    return "{:,.2f} €".format(float(x or 0)).replace(",", "X").replace(".", ",").replace("X", ".")


def _parse_individuell(raw):
    """Coerce a position's `individuell` field into {tenancy_id(int): betrag(float)}.
    Accepts a dict (tests / already-parsed) or a JSON string (the ORM Text column)."""
    if not raw:
        return {}
    if isinstance(raw, dict):
        src = raw
    else:
        try:
            src = _json.loads(raw)
        except Exception:
            return {}
    out = {}
    if isinstance(src, dict):
        for k, v in src.items():
            try:
                out[int(k)] = float(v)
            except (TypeError, ValueError):
                continue
    return out


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


# ── Verbrauch: consumption from meter readings (Zählerstände) ──────────


def _series(readings, unit_id, art):
    """All readings for one unit + art, sorted by date (readings without a date are ignored — a
    consumption difference needs dated readings)."""
    rr = [r for r in (readings or [])
          if r.get("unit_id") == unit_id and r.get("art") == art and r.get("datum") is not None]
    return sorted(rr, key=lambda r: r["datum"])


def _stand_at(series, when):
    """The meter value at `when`: the last reading with datum ≤ when; before the first reading, the
    first reading's value (so a period that starts before any reading uses the earliest known stand)."""
    if not series:
        return None
    prior = [r for r in series if r["datum"] <= when]
    if prior:
        return float(prior[-1]["stand"])
    return float(series[0]["stand"])


def _verbrauch(series, start, end):
    """Consumption between two dates = Stand(end) − Stand(start). Needs ≥ 2 dated readings to be a
    real measured difference; otherwise None (→ the caller falls the whole line back to Wohnfläche)."""
    if len(series) < 2:
        return None
    s = _stand_at(series, start)
    e = _stand_at(series, end)
    if s is None or e is None:
        return None
    return max(0.0, round(e - s, 4))


def _t_span(t, von, bis):
    """A tenant's interval clamped to the statement period."""
    tv = getattr(t, "von", None) or von
    tb = getattr(t, "bis", None) or bis
    return (tv if tv > von else von), (tb if tb < bis else bis)


def _verbrauch_weights(units, active, tenancies, readings, art, von, bis):
    """Consumption weights per tenant, plus the owner (Eigennutzung) and vacancy remainder of each
    unit's total consumption. Returns (occ_w, owner_w, vacant_w, total, ok). ok=False when a unit that
    is occupied in the period has no usable readings → the caller falls the line back to Wohnfläche."""
    occ_w = {}
    owner_w = 0.0
    vacant_w = 0.0
    total = 0.0
    ok = True
    for u in units:
        series = _series(readings, u.id, art)
        u_tenancies = [t for t in active if t.unit_id == u.id]
        u_total = _verbrauch(series, von, bis)
        if u_total is None:
            # no measured consumption for this unit. Only a problem if the unit is occupied/relevant.
            if u_tenancies or getattr(u, "eigennutzung_personen", None) is not None:
                ok = False
            continue
        assigned_c = 0.0
        for t in u_tenancies:
            ts, te = _t_span(t, von, bis)
            c = _verbrauch(series, ts, te) or 0.0
            occ_w[t.id] = occ_w.get(t.id, 0.0) + c
            total += c
            assigned_c += c
        rem = max(0.0, round(u_total - assigned_c, 4))   # owner/vacant part of this unit's consumption
        eig = getattr(u, "eigennutzung_personen", None)
        if eig is not None and int(eig) > 0:
            owner_w += rem
        else:
            vacant_w += rem
        total += rem
    return occ_w, owner_w, vacant_w, round(total, 4), ok


def _verb_text(w, total, art):
    unit = {"wasser": "m³", "warmwasser": "m³", "heizung": "kWh", "gas": "m³", "strom": "kWh"}.get(art, "")
    return f"{round(w, 2)} / {round(total, 2)} {unit}".strip()


# ── shared weight/assignment machinery (area & person keys, and HeizkostenV Grund part) ──


def _area_person_weights(schluessel, units, active, tenancies, za, von, bis):
    """occ_w per tenant + owner_w + vacant_w for the area/person/units keys (basis_weight × Zeitanteil)."""
    occ_w = {}
    owner_w = 0.0
    vacant_w = 0.0
    total_w = 0.0
    for u in units:
        for t in [t for t in active if t.unit_id == u.id]:
            w = basis_weight(schluessel, u, t, za[t.id])
            occ_w[t.id] = occ_w.get(t.id, 0.0) + w
            total_w += w
        vac_za = _unit_vacant_zeitanteil(u, tenancies, von, bis)
        if vac_za > 0:
            eig = getattr(u, "eigennutzung_personen", None)
            dummy = _Dummy(); dummy.personenzahl = eig
            w = basis_weight(schluessel, u, dummy, vac_za)
            total_w += w
            if eig is not None and int(eig) > 0:
                owner_w += w
            else:
                vacant_w += w
    return occ_w, owner_w, vacant_w, total_w


def _assign_line(per_tenant, active, betrag, occ_w, owner_w, total_w, kategorie, schluessel_row, anteil_text_fn):
    """Split `betrag` across the tenants by their weights; append a per-position row to each. Returns
    (eigennutzung_share, leerstand_share) for the non-tenant remainder. total_w must be > 0."""
    assigned = 0.0
    for t in active:
        w = occ_w.get(t.id, 0.0)
        if w <= 0:
            continue
        share = round(betrag * w / total_w, 2)
        assigned = round(assigned + share, 2)
        per_tenant[t.id]["summe"] = round(per_tenant[t.id]["summe"] + share, 2)
        per_tenant[t.id]["positionen"].append({
            "kategorie": kategorie, "label": kategorie_label(kategorie),
            "anteil_betrag": share, "schluessel": schluessel_row,
            "anteil_text": anteil_text_fn(w, total_w),
        })
    rest = round(betrag - assigned, 2)
    eig = round(betrag * owner_w / total_w, 2) if owner_w > 0 else 0.0
    eig = min(eig, rest)
    return eig, round(rest - eig, 2)


# ── the distribution engine ───────────────────────────────────────────


def verteile(positionen, units, tenancies, von: date, bis: date, readings=None):
    """Split every umlagefähige cost position across the tenants.

    `readings` (optional) is a list of meter readings [{unit_id, art, stand, datum}] used by the
    Verbrauch key (and the HeizkostenV Verbrauchskosten part). Omitted / insufficient → Verbrauch lines
    fall back to Wohnfläche with a note.

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

        # ── Individuell: the landlord assigns an EXACT amount per tenant (e.g. sub-meter readings).
        # No weighting, no Zeitanteil — the entered euro is final. Any part of the invoice NOT assigned
        # stays with the landlord (common share). If the entries exceed the invoice (user error) they
        # are scaled down proportionally so a tenant is never billed more than the cost, and a note is
        # emitted. Invariant Σ per_tenant + leerstand == betrag is preserved either way.
        if raw_schluessel == "individuell":
            ind = _parse_individuell(getattr(pos, "individuell", None))
            entered = {t.id: round(float(ind.get(t.id, ind.get(str(t.id), 0)) or 0), 2)
                       for t in active}
            entered = {tid: v for tid, v in entered.items() if v > 0}
            summe_entered = round(sum(entered.values()), 2)
            factor = 1.0
            if summe_entered > betrag and summe_entered > 0:
                factor = betrag / summe_entered
                hinweise.append(
                    f"Individuelle Beträge für '{kategorie_label(getattr(pos, 'kategorie', ''))}' "
                    f"übersteigen den Rechnungsbetrag — anteilig auf {_eur(betrag)} gekürzt.")
            assigned = 0.0
            for tid, amt in entered.items():
                share = round(amt * factor, 2)
                if share <= 0:
                    continue
                assigned = round(assigned + share, 2)
                per_tenant[tid]["summe"] = round(per_tenant[tid]["summe"] + share, 2)
                per_tenant[tid]["positionen"].append({
                    "kategorie": getattr(pos, "kategorie", ""),
                    "label": kategorie_label(getattr(pos, "kategorie", "")),
                    "anteil_betrag": share,
                    "schluessel": "individuell",
                    "anteil_text": "Individuell (fester Betrag)",
                })
            if not entered:
                hinweise.append(
                    f"'{kategorie_label(getattr(pos, 'kategorie', ''))}': Individuell gewählt, aber "
                    f"keine Beträge erfasst — Position bleibt beim Vermieter.")
            leerstand = round(leerstand + round(betrag - assigned, 2), 2)
            continue

        kategorie = getattr(pos, "kategorie", "")

        # ── Verbrauch: split by MEASURED consumption (Zählerstände). Heating/hot water additionally
        # obey HeizkostenV (§7): a Grundkosten share by Wohnfläche + a Verbrauchskosten share by meter.
        if raw_schluessel == "verbrauch":
            art = getattr(pos, "verbrauch_art", None) or _ART_DEFAULT.get(kategorie)
            occ_c, owner_c, vacant_c, total_c, ok = _verbrauch_weights(
                units, active, tenancies, readings, art, von, bis)
            if ok and total_c > 0:
                if is_heizkostenv(kategorie):
                    gp = getattr(pos, "grund_prozent", None)
                    grund = clamp_grund(gp if gp is not None else GRUND_PROZENT_DEFAULT)
                    grund_amt = round(betrag * grund / 100.0, 2)
                    verb_amt = round(betrag - grund_amt, 2)
                    ao, aow, avc, atot = _area_person_weights("wohnflaeche", units, active, tenancies, za, von, bis)
                    if atot > 0:
                        e1, l1 = _assign_line(per_tenant, active, grund_amt, ao, aow, atot, kategorie, "wohnflaeche",
                                              lambda w, tt, g=grund: f"Grundkosten {g}% · {_anteil_text('wohnflaeche', w, tt)}")
                    else:
                        e1, l1 = 0.0, grund_amt
                    e2, l2 = _assign_line(per_tenant, active, verb_amt, occ_c, owner_c, total_c, kategorie, "verbrauch",
                                          lambda w, tt, g=grund, a=art: f"Verbrauch {100 - g}% · {_verb_text(w, tt, a)}")
                    eigennutzung = round(eigennutzung + e1 + e2, 2)
                    leerstand = round(leerstand + l1 + l2, 2)
                else:
                    e, l = _assign_line(per_tenant, active, betrag, occ_c, owner_c, total_c, kategorie, "verbrauch",
                                        lambda w, tt, a=art: _verb_text(w, tt, a))
                    eigennutzung = round(eigennutzung + e, 2)
                    leerstand = round(leerstand + l, 2)
                continue
            # insufficient readings → fall back to Wohnfläche WITH a note (never a silent wrong number)
            note = (f"„{kategorie_label(kategorie)}“: Verbrauchsabrechnung nicht möglich "
                    f"(Zählerstände unvollständig) — nach Wohnfläche verteilt.")
            if note not in seen_fallback:
                hinweise.append(note)
                seen_fallback.add(note)
            schluessel = "wohnflaeche"
        else:
            # resolve the key actually used (personenzahl may fall back on missing data)
            schluessel, note = _effective_schluessel(raw_schluessel, active)
            if note and note not in seen_fallback:
                hinweise.append(note)
                seen_fallback.add(note)

        # generic area / person / units path (and the Verbrauch fallback). A unit's non-tenant time is
        # Eigennutzung (owner) or Leerstand (vacant) — both stay with the landlord, reported separately.
        occ_w, owner_w, vacant_w, total_w = _area_person_weights(schluessel, units, active, tenancies, za, von, bis)
        if total_w <= 0:
            hinweise.append(f"Position '{kategorie_label(kategorie)}' konnte nicht verteilt werden "
                            f"(keine Wohnfläche/Basis hinterlegt).")
            leerstand = round(leerstand + betrag, 2)      # nothing to split on → landlord carries it
            continue
        e_share, l_share = _assign_line(per_tenant, active, betrag, occ_w, owner_w, total_w, kategorie, schluessel,
                                        lambda w, tt, s=schluessel: _anteil_text(s, w, tt))
        eigennutzung = round(eigennutzung + e_share, 2)
        leerstand = round(leerstand + l_share, 2)

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


def build_snapshot(abrechnung_meta, property_meta, units, tenancies, positionen, von, bis, as_of=None, readings=None):
    """Freeze EVERYTHING used in the calculation, so the statement re-produces years later even if the
    master data changed. The snapshot — not the PDF — is the record of truth. Stored at finalise on
    NkAbrechnung.ergebnis_snapshot; every read of a FINAL statement derives from this, never from live
    master data. `readings` freezes the meter values so a Verbrauch/HeizkostenV line re-produces too."""
    v = verteile(positionen, units, tenancies, von, bis, readings)
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
                        "schluessel": getattr(p, "schluessel", "wohnflaeche"),
                        "verbrauch_art": getattr(p, "verbrauch_art", None),
                        "grund_prozent": (clamp_grund(getattr(p, "grund_prozent", None))
                                          if is_heizkostenv(getattr(p, "kategorie", "")) else None),
                        "individuell": _parse_individuell(getattr(p, "individuell", None)) or None}
                       for p in positionen],
        "readings": [{"unit_id": r.get("unit_id"), "art": r.get("art"), "stand": r.get("stand"),
                      "datum": str(r.get("datum")) if r.get("datum") else None}
                     for r in (readings or [])],
        "allocation": e["tenants"],          # per tenant: shares (allocation_ratios in anteil_text) + saldo
        "leerstand_share": e["leerstand"],
        "eigennutzung_share": e.get("eigennutzung", 0.0),
        "umlagefaehige_summe": e["umlagefaehige_summe"],
        "final_result": [{"tenancy_id": r["tenancy_id"], "name": r["name"], "saldo": r["saldo"],
                          "typ": r["typ"]} for r in e["tenants"]],
        "hinweise": e["hinweise"],
        "frist_ueberschritten": frist_ueberschritten(bis, as_of),
    }
