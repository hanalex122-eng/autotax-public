"""Vendor Intelligence System v2 — evidence-based resolver (Phase 1, SHADOW).

PURE + READ-ONLY decision engine. It collects vendor signals from a receipt,
weighs them in log-odds space (weights come from the SignalWeight table), and
returns a structured decision. It NEVER mutates invoice/vendor state — in
Phase 1 it is used ONLY in shadow mode to populate VendorResolutionLog, so it
cannot change any user-visible behavior.

Combination model (Confidence Engine v2 technical design):
    L(v) = PRIOR + Σ_family[ diminishing-discounted weights supporting v ]
    confidence(v) = sigmoid(L(v)), capped at 0.99
Conflict: two STRONG signals pointing to DIFFERENT vendors -> CONFLICT
(force Unbekannt + review; never silently pick a side).

Every public entry point is wrapped so it returns a safe default and never
raises into the caller (the upload path must be unaffected).
"""

import logging
import math
import re
from collections import defaultdict

logger = logging.getLogger("autotax")

PRIOR_LOG_ODDS = -0.85           # logit(0.30): mildly skeptical prior
CONF_CAP = 0.99
FAMILY_DISCOUNT = (1.0, 0.5, 0.25)   # within one family: strongest full, rest discounted
SEPARATION_MARGIN = 1.5          # nats; top must beat runner-up to avoid conflict
STRONG_WEIGHT = 2.5              # effective weight >= this => "strong" signal
ENGINE_VERSION = "v2-shadow-1"

_SCANNER_PREFIXES = ("scan", "img", "image", "photo", "doc", "page",
                     "untitled", "kopie", "copy", "neu", "test", "fis")


def _sigmoid(x):
    if x <= -60:
        return 0.0
    if x >= 60:
        return 1.0
    return 1.0 / (1.0 + math.exp(-x))


def _norm_vendor(v):
    return re.sub(r"[^a-z0-9]", "", (v or "").lower())


def _load_weights():
    """{signal_type: (weight, collision_penalty, family, enabled)} from DB.
    Empty dict on any failure -> resolver still runs, just with 0 weights."""
    try:
        from autotax.db import SessionLocal
        from autotax.models import SignalWeight
        db = SessionLocal()
        try:
            return {
                r.signal_type: (r.weight, r.collision_penalty, r.family, r.enabled)
                for r in db.query(SignalWeight).all()
            }
        finally:
            db.close()
    except Exception as e:
        logger.warning("[VENDOR_V2] weight load failed: %s", e)
        return {}


def _classify_fp_match(matched):
    """Classify a fingerprint hit by its MATCHED TEXT (robust, regex-agnostic)."""
    s = (matched or "").strip()
    digits = sum(c.isdigit() for c in s)
    if digits >= 8 and digits / max(len(s), 1) > 0.6:
        return "barcode_prefix", "brand"
    if re.match(r"^[A-Za-z]{2,4}[-_]\d", s):     # cash-register serial e.g. LDL-0
        return "kasse_prefix", "device"
    return "legal_name", "brand"


def _collect_signals(raw_text, qr_data, filename, user_id):
    """Read-only signal extraction; reuses existing parser/identity helpers.
    Returns list of {signal_type, value, vendor, family}."""
    signals = []
    raw = raw_text or ""

    # 1) Brand fingerprint (barcode / kasse serial / legal name)
    try:
        from autotax.parser import _VENDOR_FINGERPRINT_COMPILED
        for rx, name in _VENDOR_FINGERPRINT_COMPILED:
            m = rx.search(raw)
            if m:
                st, fam = _classify_fp_match(m.group(0))
                signals.append({"signal_type": st, "value": m.group(0)[:40],
                                "vendor": name, "family": fam})
    except Exception as e:
        logger.debug("[VENDOR_V2] fp signals: %s", e)

    # 2) Global USt-ID map + 3) per-user identity match
    try:
        from autotax.vendor_identity import extract_identity_from_text, match_vendor
        from autotax.parser import _TAX_ID_VENDOR_MAP
        idf = extract_identity_from_text(raw) or {}
        ust = idf.get("ust_id")
        if ust and ust in _TAX_ID_VENDOR_MAP:
            signals.append({"signal_type": "ust_id", "value": ust,
                            "vendor": _TAX_ID_VENDOR_MAP[ust], "family": "identity"})
        if user_id:
            vm = match_vendor(user_id, identity_fields=idf)
            if vm and vm.vendor_name:
                fam_map = {"ust_id": "identity", "iban": "identity", "hrb": "identity",
                           "address": "location", "email": "text", "domain": "text",
                           "phone": "location", "name": "text"}
                st = vm.matched_by if vm.matched_by in fam_map else "known_name"
                signals.append({"signal_type": st, "value": "learned:%s" % vm.matched_by,
                                "vendor": vm.vendor_name, "family": fam_map.get(st, "text")})
    except Exception as e:
        logger.debug("[VENDOR_V2] identity signals: %s", e)

    # 4) QR company (machine-readable) -> barcode-grade brand evidence
    try:
        if qr_data and qr_data.get("company"):
            signals.append({"signal_type": "barcode_prefix", "value": "qr",
                            "vendor": qr_data["company"], "family": "brand"})
    except Exception:
        pass

    # 5) Known-name token from OCR head (weak); skip obvious item lines
    try:
        from autotax.parser import extract_vendor
        ev = extract_vendor(raw)
        if ev and ev not in ("Unbekannt", "", None) and len(ev) >= 3 \
                and not re.search(r"\d+[,.]\d{2}", ev):
            signals.append({"signal_type": "known_name", "value": ev[:60],
                            "vendor": ev, "family": "text"})
    except Exception:
        pass

    # 6) Filename hint (brand token) or scanner-default veto marker
    try:
        fn = (filename or "").lower()
        if fn:
            base = re.sub(r"\.[a-z0-9]+$", "", fn)
            residual = re.sub(r"(scan|img|image|photo|doc|page|untitled|kopie|copy|neu|test|fis)", "", base)
            if any(base.startswith(p) for p in _SCANNER_PREFIXES) and not re.search(r"[a-zäöü]{3,}", residual):
                signals.append({"signal_type": "filename_scanner", "value": base[:40],
                                "vendor": None, "family": "hint"})
            else:
                from autotax.parser import VENDOR_CATEGORY_MAP
                for k in VENDOR_CATEGORY_MAP:
                    if len(k) >= 4 and re.search(r"\b" + re.escape(k) + r"\b", base):
                        signals.append({"signal_type": "filename_brand", "value": k,
                                        "vendor": k.upper(), "family": "hint"})
                        break
    except Exception:
        pass

    return signals


def resolve_vendor_v2(raw_text, qr_data=None, filename=None, user_id=None):
    """Evidence-based vendor decision. READ-ONLY — never mutates state.

    Returns:
        {vendor, confidence, status, evidence[], candidates[], conflicts[],
         engine_version}
    status ∈ locked|accepted|provisional|unknown|conflict|error
    """
    try:
        weights = _load_weights()
        raw_signals = _collect_signals(raw_text, qr_data, filename, user_id)

        evidence = []
        for s in raw_signals:
            w_info = weights.get(s["signal_type"])
            if w_info is None:
                eff, enabled = 0.0, True
            else:
                weight, pen, fam, enabled = w_info
                eff = weight - (pen or 0.0)
                if fam:
                    s["family"] = fam
            if not enabled:
                continue
            s["weight"] = round(eff, 3)
            evidence.append(s)

        # Group supporting signals by normalized vendor
        by_vendor = defaultdict(list)
        for s in evidence:
            if s.get("vendor"):
                by_vendor[_norm_vendor(s["vendor"])].append(s)

        candidates = []
        for _nv, sigs in by_vendor.items():
            fam_groups = defaultdict(list)
            for s in sigs:
                fam_groups[s["family"]].append(s["weight"])
            total = PRIOR_LOG_ODDS
            for _fam, ws in fam_groups.items():
                for i, w in enumerate(sorted(ws, reverse=True)):
                    disc = FAMILY_DISCOUNT[i] if i < len(FAMILY_DISCOUNT) else 0.1
                    total += w * disc
            conf = min(_sigmoid(total), CONF_CAP)
            candidates.append({
                "vendor": sigs[0]["vendor"],
                "log_odds": round(total, 3),
                "confidence": round(conf * 100, 1),
                "strong": any(s["weight"] >= STRONG_WEIGHT for s in sigs),
                "signal_count": len(sigs),
            })
        candidates.sort(key=lambda c: c["log_odds"], reverse=True)

        vendor, confidence, status, conflicts = "Unbekannt", 0.0, "unknown", []
        if candidates:
            top = candidates[0]
            runner = candidates[1] if len(candidates) > 1 else None
            strong_cands = [c for c in candidates if c["strong"]]
            in_conflict = (
                len(strong_cands) >= 2
                or (runner and top["strong"] and runner["strong"]
                    and (top["log_odds"] - runner["log_odds"]) < SEPARATION_MARGIN)
            )
            if in_conflict:
                status = "conflict"
                conflicts = [c["vendor"] for c in (strong_cands or candidates)[:3]]
            elif top["confidence"] >= 90:
                vendor, confidence, status = top["vendor"], top["confidence"], "locked"
            elif top["confidence"] >= 70:
                vendor, confidence, status = top["vendor"], top["confidence"], "accepted"
            elif top["confidence"] >= 50:
                vendor, confidence, status = top["vendor"], top["confidence"], "provisional"
            else:
                status = "unknown"

        return {
            "vendor": vendor, "confidence": confidence, "status": status,
            "evidence": evidence, "candidates": candidates, "conflicts": conflicts,
            "engine_version": ENGINE_VERSION,
        }
    except Exception as e:
        logger.warning("[VENDOR_V2] resolve failed: %s", e)
        return {"vendor": "Unbekannt", "confidence": 0.0, "status": "error",
                "evidence": [], "candidates": [], "conflicts": [],
                "engine_version": ENGINE_VERSION}
