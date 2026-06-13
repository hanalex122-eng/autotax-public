"""VAT extraction — P0 tax-critical (guard-first, fixture-based).

Real OCR fixtures from prod invoices where the parser produced vat_rate=0.0% /
vat_amount=0 despite VAT being present (audit 2026-06-13). The German
'Typ Netto USt Brutto' tax-class summary table (fuel/POS receipts) was not parsed.

Guard mandate: NEVER fabricate VAT. When the table can't be validated
(netto+steuer≈brutto, rate snaps to a known DE rate, brutto≈total) the old
behaviour must be preserved.
"""
from autotax.parser import (
    extract_vat_info,
    _extract_vat_from_tax_table,
    normalize,
    normalize_amount_text,
)


def _norm(s: str) -> str:
    return normalize_amount_text(normalize(s))


# Real OCR fixture — prod invoice id 774/763 (ARAL fuel receipt).
# Tax table: class A, Netto 16,81 | Steuer 3,19 | Brutto 20,00 (= 19%).
ARAL_RAW = """ec-Chip 20,00 EUR |
Typ Netto Hust Brutto
| A:19, 008 16.81 3,19 20,00 |
Betrag EUR 20.00 fo
F Legende der Steuernummer (n) |"""


# --- Case 1: ARAL tax table recovers the real VAT --------------------------
def test_aral_tax_table_recovers_vat():
    rates, amount = extract_vat_info(ARAL_RAW, 20.00, "DE")
    assert amount == 3.19, f"expected 3.19, got {amount}"
    assert 19 in rates or 19.0 in rates, f"expected 19% in {rates}"


def test_aral_table_function_direct():
    res = _extract_vat_from_tax_table(_norm(ARAL_RAW), 20.00)
    assert res is not None
    rates, amount = res
    assert amount == 3.19
    assert 19.0 in rates


# --- Case 2: German comma decimals normalize to dot ------------------------
def test_comma_decimal_normalized():
    assert normalize_amount_text("3,19") == "3.19"
    assert normalize_amount_text("16,81 3,19 20,00") == "16.81 3.19 20.00"


# --- Case 3: OCR-broken table must NOT produce false VAT -------------------
def test_tax_table_guard_rejects_inconsistent():
    # netto + steuer (16.81 + 3.19 = 20.00) != brutto (25.00) -> reject
    bad = "Typ Netto USt Brutto | A 16,81 3,19 25,00"
    assert _extract_vat_from_tax_table(_norm(bad), 25.00) is None


def test_tax_table_requires_header():
    # three decimals that happen to sum, but NO tax header -> not a table
    # (prevents item-line false positives like price columns)
    noheader = "Apfel 16,81 Brot 3,19 Summe 20,00"
    assert _extract_vat_from_tax_table(_norm(noheader), 20.00) is None


def test_tax_table_brutto_must_match_total():
    # valid table arithmetic but brutto (20.00) != receipt total (99.00) -> reject
    other_total = "Typ Netto USt Brutto | A 16,81 3,19 20,00"
    assert _extract_vat_from_tax_table(_norm(other_total), 99.00) is None


# --- Case 4: guard failure preserves old behaviour (no crash, no fabrication)
def test_guard_failure_falls_back():
    bad = "Typ Netto USt Brutto | A 16,81 3,19 25,00"
    # extract_vat_info must not crash and must not return the bogus 3.19 from the
    # broken table (it may apply its own legacy default, but not the table value).
    rates, amount = extract_vat_info(bad, 25.00, "DE")
    assert amount != 3.19


# --- Case 5: genuine no-VAT receipt stays 0% ------------------------------
def test_no_vat_receipt_preserved():
    us = "Topaz Labs\nInvoice TS-10892490 $279.00\nThank you"
    rates, amount = extract_vat_info(us, 279.00, "DE")
    assert amount == 0.0
