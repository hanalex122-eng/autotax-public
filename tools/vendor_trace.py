#!/usr/bin/env python3
"""READ-ONLY diagnostic: trace vendor extraction for a given raw OCR text.

NOT a product change. NOT a fix. Imports the REAL parser functions/regexes
and prints, step by step, what happens BEFORE and DURING vendor selection:

  1) raw OCR text (as stored)
  2) vendor candidates generated (extract_vendor's line loop)
  3) fingerprint match (detect_vendor_from_fingerprint — runs FIRST in prod)
  4) final vendor + source + confidence (parse_invoice)
  5) why a given expected vendor (e.g. ACTION) was / was not selected

Usage:
    python tools/vendor_trace.py path/to/raw.txt            # from file
    python tools/vendor_trace.py - < raw.txt                # from stdin
    EXPECT=ACTION python tools/vendor_trace.py raw.txt       # check a vendor

The raw text must be the EXACT raw_text stored for the invoice (full text,
not the 200-char ocr_snippet) — fingerprint scans the whole receipt.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from autotax.parser import (  # noqa: E402
    detect_vendor_from_fingerprint,
    extract_vendor,
    _clean_vendor_name,
    parse_invoice,
    _SKIP_PATTERNS,
    _ITEM_LINE_RE,
    _TOTAL_LINE_RE,
    _VENDOR_SUFFIX_RE,
    VENDOR_CATEGORY_MAP,
    _VENDOR_FINGERPRINT_COMPILED,
)

# Mirror of extract_vendor's local footer regex (e968059) — kept verbatim so
# the candidate trace matches production. If extract_vendor changes, update.
_FOOTER_NOISE = re.compile(
    r"^(danke|vielen\s+dank|auf\s+wiedersehen|tsch[üu]ss|sch[öo]nen\s+(?:tag|abend)|"
    r"bis\s+bald|ihr\s+team|wir\s+danken|besuchen\s+sie|[öo]ffnungszeit|r[üu]ckgeld|"
    r"kundenbeleg|h[äa]ndlerbeleg|zwischensumme|kartenzahlung|ec[-\s]?karte)\b",
    re.IGNORECASE,
)


def trace_candidates(raw_text):
    """Replays extract_vendor's candidate loop, annotating WHY each line is
    kept or dropped. Uses the SAME imported regex objects as production."""
    lines = raw_text.strip().split("\n")
    print("\n--- [2] CANDIDATE SCAN (first 20 lines) ---")
    kept = []
    for idx, line in enumerate(lines[:20]):
        c = line.strip()
        reason = None
        if not c or len(c) < 2:
            reason = "empty/too-short"
        elif re.match(r"^[\d\s\.\-\/,€%:;#*+]+$", c):
            reason = "numbers/symbols only"
        elif _SKIP_PATTERNS.match(c):
            reason = "SKIP_PATTERN (header noise)"
        elif _ITEM_LINE_RE.match(c):
            reason = "item line (text+price)"
        elif _TOTAL_LINE_RE.match(c):
            reason = "total/payment line"
        elif _FOOTER_NOISE.match(c):
            reason = "FOOTER noise (Danke/Rueckgeld/...)"
        elif len(c) > 60:
            reason = "too long (addr/desc)"
        if reason:
            print(f"  L{idx:<2} DROP  [{reason:<28}] {c!r}")
        else:
            kept.append(c)
            print(f"  L{idx:<2} KEEP                              {c!r}")
    print(f"\n  => {len(kept)} candidate(s): {kept}")
    return kept


def explain_selection(candidates):
    print("\n--- [5] SELECTION PRIORITY WALK ---")
    if not candidates:
        print("  no candidates -> returns 'Unbekannt'")
        return
    # P1: legal suffix in first 5
    for c in candidates[:5]:
        if _VENDOR_SUFFIX_RE.search(c):
            print(f"  P1 HIT  legal suffix in: {c!r} -> {_clean_vendor_name(c)!r}")
            return
    print("  P1 miss (no GmbH/AG/... in first 5 candidates)")
    # P2: known vendor
    skip = {"netto", "total", "penny", "tankstelle", "taxi", "apotheke",
            "pharmacy", "pharmacie", "hit", "basic", "combi", "star",
            "real", "coop", "alex", "jet"}
    for c in candidates[:5]:
        cl = c.lower()
        if re.search(r"\b(netto|brutto|mwst|ust|inkl\.?|steuer)\b[:\s]", cl):
            continue
        for kv in VENDOR_CATEGORY_MAP:
            if kv in skip or len(kv) < 3:
                continue
            if re.search(r"\b" + re.escape(kv) + r"\b", cl):
                print(f"  P2 HIT  known vendor '{kv}' in: {c!r} -> {_clean_vendor_name(c)!r}")
                return
    print("  P2 miss (no known brand word in first 5 candidates)")
    # P3: first non-address
    print(f"  P3 -> first non-address candidate: {_clean_vendor_name(candidates[0])!r} (or later if addr-like)")


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else "-"
    raw = sys.stdin.read() if src == "-" else open(src, encoding="utf-8").read()
    expect = os.getenv("EXPECT", "").strip()

    print("=" * 70)
    print("--- [1] RAW OCR TEXT (%d chars, %d lines) ---" % (len(raw), raw.count("\n") + 1))
    print(raw)

    print("\n--- [3] FINGERPRINT (runs FIRST in parse_invoice, scans WHOLE text) ---")
    fp = detect_vendor_from_fingerprint(raw)
    print(f"  detect_vendor_from_fingerprint() = {fp!r}")
    if expect:
        # show which pattern(s) for EXPECT exist and whether they'd match
        pats = [(rx.pattern, name) for rx, name in _VENDOR_FINGERPRINT_COMPILED
                if name.upper() == expect.upper()]
        print(f"  patterns for EXPECT={expect!r}: {pats}")
        for pat, name in pats:
            hit = re.search(pat, raw, re.IGNORECASE)
            print(f"    {'MATCH ' if hit else 'no    '} {pat!r}"
                  + (f"  -> {hit.group(0)!r}" if hit else ""))

    cands = trace_candidates(raw)
    print(f"\n--- extract_vendor() (primary) = {extract_vendor(raw)!r} ---")
    explain_selection(cands)

    print("\n--- [4] FINAL parse_invoice() ---")
    r = parse_invoice(raw)
    print(f"  vendor            = {r.get('vendor')!r}")
    print(f"  vendor_source     = {r.get('vendor_source')!r}")
    print(f"  vendor_confidence = {r.get('vendor_confidence')!r}")
    if expect:
        ok = expect.lower() in str(r.get("vendor", "")).lower()
        print(f"\n  EXPECT={expect!r} -> {'SELECTED' if ok else 'NOT SELECTED'}")
    print("=" * 70)


if __name__ == "__main__":
    main()
