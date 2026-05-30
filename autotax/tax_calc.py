"""Tax estimation engine — live ESt + Soli + KiSt calculation.

User feedback (2026-05-30): "ne kadar alacagiz ne kadar vergi verecegiz
bu wiso da canli görünüyor"

Hesaplama §32a EStG Einkommensteuertarif (2024/2025).
NOT: Tahmindir, gerçek vergi her zaman Bescheid sonrası kesinleşir.
Splittingtarif (verheiratet zusammen): ESt(zvE/2) × 2.
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


# ───────────────────────────────────────────────────────────────────
# §32a EStG — Grundtarif (per single person).
# ───────────────────────────────────────────────────────────────────

def grundtarif_2024(zve: float) -> float:
    """Einkommensteuer-Grundtarif 2024 (§ 32a EStG)."""
    if zve <= 11604:
        return 0.0
    elif zve <= 17005:
        y = (zve - 11604) / 10000
        return round((922.98 * y + 1400) * y, 2)
    elif zve <= 66760:
        z = (zve - 17005) / 10000
        return round((181.19 * z + 2397) * z + 1025.38, 2)
    elif zve <= 277825:
        return round(0.42 * zve - 10602.13, 2)
    else:
        return round(0.45 * zve - 18936.88, 2)


def grundtarif_2025(zve: float) -> float:
    """Einkommensteuer-Grundtarif 2025 (geschätzt). Grundfreibetrag 12.096€."""
    if zve <= 12096:
        return 0.0
    elif zve <= 17443:
        y = (zve - 12096) / 10000
        return round((932.30 * y + 1400) * y, 2)
    elif zve <= 68480:
        z = (zve - 17443) / 10000
        return round((176.64 * z + 2397) * z + 1015.13, 2)
    elif zve <= 277825:
        return round(0.42 * zve - 10911.92, 2)
    else:
        return round(0.45 * zve - 19246.67, 2)


def estimate_est(zve: float, year: int = 2024,
                 verheiratet_zusammen: bool = False) -> float:
    """Einkommensteuer Estimator. Splittingtarif → zvE/2 → ESt × 2."""
    if zve <= 0:
        return 0.0
    tarif = grundtarif_2025 if year >= 2025 else grundtarif_2024
    if verheiratet_zusammen:
        return round(tarif(zve / 2) * 2, 2)
    return tarif(zve)


# ───────────────────────────────────────────────────────────────────
# Solidaritätszuschlag (2024+ only above Freigrenze).
# ───────────────────────────────────────────────────────────────────

def estimate_soli(est: float, year: int = 2024,
                  verheiratet_zusammen: bool = False) -> float:
    """Soli 2024+: kein Soli unter Freigrenze. Milderungszone linear.

    2024 Freigrenze (single): €18.130 ESt = ~€67.000 Bruttoeinkommen
    2025 Freigrenze (single): €19.451 ESt
    Verheiratet: 2× Freigrenze.
    """
    if est <= 0:
        return 0.0
    base_freigrenze = 19451 if year >= 2025 else 18130
    freigrenze = base_freigrenze * 2 if verheiratet_zusammen else base_freigrenze
    if est <= freigrenze:
        return 0.0
    full_soli = est * 0.055
    # Milderungszone: linear interpolation up to ~5.5%
    obergrenze = freigrenze * 1.0594  # approximation
    if est >= obergrenze:
        return round(full_soli, 2)
    # Linear ramp
    return round((est - freigrenze) * 0.119, 2)


# ───────────────────────────────────────────────────────────────────
# Kirchensteuer (8% BY/BW, 9% other Bundesländer).
# ───────────────────────────────────────────────────────────────────

def estimate_kist(est: float, religion: str | None,
                  bundesland_byBw: bool = False) -> float:
    """KiSt nur bei religiöser Konfession. BY/BW: 8%, sonst 9%."""
    if not religion or religion in ("none", "other"):
        return 0.0
    rate = 0.08 if bundesland_byBw else 0.09
    return round(est * rate, 2)


# ───────────────────────────────────────────────────────────────────
# Full estimator — declaration data → tax summary.
# ───────────────────────────────────────────────────────────────────

def _f(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def estimate_full(data: dict, year: int = 2024) -> dict:
    """Compute full tax summary from declaration data.

    Returns dict with:
    - einkommen.{selbst, lohn, vermietung, kapital, spouse_lohn, gesamt}
    - abzuege.{werbungskosten, sonderausgaben, vorsorge, behindert, krankheit, total}
    - zvE: zu versteuerndes Einkommen
    - einkommensteuer, soli, kirchensteuer, gesamt_steuer
    - bereits_gezahlt
    - differenz (positive=Erstattung, negative=Nachzahlung)
    - erstattung / nachzahlung (always >= 0)
    """
    from autotax.declaration import pauschbetrag_for_gdb, pendlerpauschale

    is_zusammen = (
        data.get("familienstand") == "verheiratet"
        and (data.get("veranlagungsart") or "zusammen") == "zusammen"
    )

    # ── Einkommen ──
    einkommen_s = _f(data.get("gewinn_eur"))
    einkommen_n = _f(data.get("lohn_brutto"))
    spouse_lohn = _f(data.get("spouse_lohn_brutto")) if is_zusammen else 0.0

    # Vermietung: Einnahmen + Nebenkosten - alle Kosten
    v_brutto = _f(data.get("v_einnahmen")) + _f(data.get("v_nebenkosten"))
    v_kosten = (_f(data.get("v_afa")) + _f(data.get("v_zinsen"))
                + _f(data.get("v_erhaltung")) + _f(data.get("v_grundsteuer"))
                + _f(data.get("v_sonst")))
    einkommen_v = max(0, v_brutto - v_kosten)

    # KAP: minus Sparer-Pauschbetrag (€1.000 Single, €2.000 verh)
    kap_total = _f(data.get("kap_zinsen")) + _f(data.get("kap_kursgewinn"))
    sparer_pb = (2000 if is_zusammen else 1000)
    used_freistellung = _f(data.get("freistellungsauftrag"))
    effective_pb = max(0, sparer_pb - used_freistellung)
    einkommen_kap = max(0, kap_total - effective_pb)

    gesamt_einkuenfte = einkommen_s + einkommen_n + einkommen_v + einkommen_kap + spouse_lohn

    # ── Werbungskosten (Anlage N) ──
    arbeitnehmer_pb = 1230  # 2024+
    pendler_p = pendlerpauschale(data.get("pendler_km"), data.get("pendler_tage"))
    ho_p = min(_f(data.get("homeoffice_tage")) * 6, 1260)
    custom_wk = _f(data.get("werbungskosten_n"))
    # User can override: use max(custom, pauschbetrag + Pendler + HO)
    werbungskosten = max(custom_wk, arbeitnehmer_pb + pendler_p + ho_p)

    # ── Sonderausgaben ──
    sonderausgaben = (
        _f(data.get("spenden_geld"))
        + _f(data.get("spenden_partei")) * 0.5  # 50% absetzbar
        + _f(data.get("kirchensteuer_so"))
        + _f(data.get("steuerberater"))
    )

    # ── Vorsorgeaufwand ──
    # Krankenversicherung Basis: voll absetzbar
    # Zusatz: voll (Krankentagegeld nicht)
    # Pflege: voll
    # Rente: 100% absetzbar ab 2023
    vorsorge = (
        _f(data.get("kv_basis"))
        + _f(data.get("kv_zusatz"))
        + _f(data.get("pflege"))
        + _f(data.get("rente_gesetz"))  # 100% 2023+
        + _f(data.get("rurup"))
        + _f(data.get("bu"))
    )

    # ── Behindertenpauschbetrag (eigene + Kind via Übertragung) ──
    eigene_gdb_val = data.get("eigene_gdb")
    behindert_eigene = pauschbetrag_for_gdb(
        int(eigene_gdb_val) if eigene_gdb_val else 0,
        data.get("eigene_merkmal"),
    )
    behindert_kind = 0
    for k in (data.get("kinder") or []):
        if not isinstance(k, dict):
            continue
        if k.get("behindert_uebertrag") == "ja":
            k_gdb = k.get("behinderung_gdb")
            behindert_kind += pauschbetrag_for_gdb(
                int(k_gdb) if k_gdb else 0,
                k.get("behinderung_merkmal"),
            )
    behindert_total = behindert_eigene + behindert_kind

    # ── Außergewöhnliche Belastungen ──
    aussergewohnliche = (
        _f(data.get("krankheitskosten")) + _f(data.get("pflegekosten"))
        + _f(data.get("bestattungskosten")) + _f(data.get("scheidungskosten"))
        + _f(data.get("kurkosten"))
    )
    # Zumutbare Belastung — vereinfachte ~3% Gesamteinkünfte
    zumutbar = gesamt_einkuenfte * 0.03
    aussergewohnliche_effective = max(0, aussergewohnliche - zumutbar)

    # ── Kinderfreibetrag (2024: €6.612 / Kind bei zusammen, €3.306 single) ──
    kinder_count = sum(1 for k in (data.get("kinder") or [])
                       if isinstance(k, dict) and k.get("vorname"))
    kinderfreibetrag = kinder_count * (6612 if is_zusammen else 3306)
    # ABER: Günstigerprüfung — Finanzamt vergleicht Kindergeld vs Freibetrag,
    # nimmt was günstiger ist. Hier vereinfacht: Freibetrag immer angesetzt.

    abzuege_total = (werbungskosten + sonderausgaben + vorsorge
                     + behindert_total + aussergewohnliche_effective
                     + kinderfreibetrag)

    # ── zu versteuerndes Einkommen ──
    zve = max(0, gesamt_einkuenfte - abzuege_total)

    # ── Steuer ──
    est = estimate_est(zve, year, verheiratet_zusammen=is_zusammen)
    soli = estimate_soli(est, year, verheiratet_zusammen=is_zusammen)
    kist = estimate_kist(est, data.get("religion"))
    gesamt_steuer = est + soli + kist

    # ── Bereits gezahlt ──
    bereits = (
        _f(data.get("lohnsteuer"))
        + _f(data.get("soli_n"))
        + _f(data.get("kirchensteuer"))  # this is Lohn-KiSt
        + _f(data.get("kap_quellensteuer"))
    )

    diff = round(bereits - gesamt_steuer, 2)

    return {
        "einkommen": {
            "selbst": round(einkommen_s, 2),
            "lohn": round(einkommen_n, 2),
            "spouse_lohn": round(spouse_lohn, 2),
            "vermietung": round(einkommen_v, 2),
            "kapital": round(einkommen_kap, 2),
            "gesamt": round(gesamt_einkuenfte, 2),
        },
        "abzuege": {
            "werbungskosten": round(werbungskosten, 2),
            "sonderausgaben": round(sonderausgaben, 2),
            "vorsorge": round(vorsorge, 2),
            "behindert_eigene": round(behindert_eigene, 2),
            "behindert_kind": round(behindert_kind, 2),
            "aussergewohnliche": round(aussergewohnliche_effective, 2),
            "kinderfreibetrag": round(kinderfreibetrag, 2),
            "pendlerpauschale": round(pendler_p, 2),
            "homeoffice_pauschale": round(ho_p, 2),
            "gesamt": round(abzuege_total, 2),
        },
        "zvE": round(zve, 2),
        "einkommensteuer": round(est, 2),
        "soli": round(soli, 2),
        "kirchensteuer": round(kist, 2),
        "gesamt_steuer": round(gesamt_steuer, 2),
        "bereits_gezahlt": round(bereits, 2),
        "differenz": diff,
        "erstattung": round(max(0, diff), 2),
        "nachzahlung": round(max(0, -diff), 2),
        "is_zusammen": is_zusammen,
        "year": year,
        "kinder_count": kinder_count,
        "disclaimer": ("Schätzung gemäß § 32a EStG. Tatsächlicher Bescheid "
                       "kann abweichen — keine rechtsverbindliche "
                       "Steuerberatung."),
    }


__all__ = [
    "estimate_full",
    "estimate_est",
    "estimate_soli",
    "estimate_kist",
    "grundtarif_2024",
    "grundtarif_2025",
]
