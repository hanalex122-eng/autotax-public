"""VAT rate sanity — reject OCR-garbage rates that are invalid for the country.

Bug (prod id 828, mtb Tankstelle, total 96.53): pure OCR word-salad contained a
stray '4 %'. _extract_vat_rates accepted 4.0 (it fetched KNOWN_VAT_RATES but never
filtered by it), and extract_vat_info Branch 4 fabricated VAT = 96.53*4/104 = 3.71.
4% is NOT a German rate (valid DE: 19/7); it IS valid for IT/ES — so the fix must
filter per-country, not by tightening the regex. A second fabrication path (Branch 5
defaulting to 19% on a bare '%' with no tax keyword) is closed too.
"""
import base64
from autotax.parser import (
    extract_vat_info,
    _extract_vat_rates,
    normalize,
    normalize_amount_text,
)


def _norm(s: str) -> str:
    return normalize_amount_text(normalize(s))


# Real prod OCR fixture — invoice id 828 (garbage scan, stray '4 %' + '0%').
_RAW_828_B64 = (
    "LSB5IEkgeWUgaHkgaWEKSCBFdSB1IDEgQmV5CnJzIMKjfSDigJwgYXJlCuKAmCAtIDsgfiAxMS0w"
    "IDAwNSBGaSAtYXBlYWUKPSIgKiBpIDcgb28g4oCdIEJMIEJVbm54dTIgQWNrICt0UzcyeWFnemly"
    "IE9SVEUKaW4gRE8gSklQRVp5cmVCSExGQU4gTgp+fiDigJkgNjExIENPTkdDT01GIDE1NDI5IGts"
    "aWVldGFucyBhZQo0IOKAnFNJIExQVVJGQVQgSSBBemQgdG9uZSByYmF5IGFlCn4gNCBlZQo6IDIg"
    "RXIgPSDigJTigJTigJQga2MgcHMKfiBOIHdvISA1IFNlIGEKfCBpIEVSCjsgZWUsIEJhZSAwJQpp"
    "4oCZIGFlIMKlCmYgQmFzIGEgQmU7IGllIHQK4oCcLiBpIDQgXyByaQolIEZpICMgZnIgPiIgbmUs"
    "IOKAnQrigJggOiAqIG0gaWUgYmUgJQpXdCA1IDIgZ2UsICoK4oCcIOKAmCB1IFJpOyBHRSwgYSBn"
    "ZXIKfCBoID4gaWUgb2UKSiBhLiAuCmogcnMgQWggNCAkICoKeCBKYWcgQSBlZQp8IFByIGEgQWkg"
    "YSA+Cm1lICcgJSBhOgphIGggbm0KaWlzIG9lICoKTiB6LCBpZSB5CjIgNCBEZWUgRXUgOyB1CkJl"
    "LgpcIFJSLiA1CjIgMiAyIGdhPwoxIG9uIGFlIDIgQmkg4oCYSgo6ICMgPSBhIFJ5CisyIFBpCjsg"
    "LCB0ID0gYWdlIDQgJSAiClwgaXQsIGNlCmEgd2EgZCA3Ck4gbW4g4oCccGVlcyBCZXI6CjIgPSBI"
    "QiAzIHgKQSB2ZQojIGEK4oCYfCA+IHgg4oCcCuKAlApSbiBmaXMuCmYgfSBJLiBlZSAtCiogRmki"
    "IHByIGFlIHUgNApSIFIgOyBSaWUgaQ=="
)
RAW_828 = base64.b64decode(_RAW_828_B64).decode("utf-8")


# --- Main bug: 828 garbage must yield NO VAT ------------------------------
def test_828_garbage_no_vat():
    rates, amount = extract_vat_info(RAW_828, 96.53, "DE")
    assert amount == 0.0, f"expected 0.0, got {amount}"
    assert rates in ([0.0], [], [0]), f"expected no real rate, got {rates}"


# --- Per-country rate validity --------------------------------------------
def test_de_4pct_rejected():
    # 4% is not a valid German VAT rate -> must be dropped
    assert 4.0 not in _extract_vat_rates(_norm("Bar 4 % Total 100,00"), "DE")


def test_it_4pct_accepted():
    # 4% IS a valid Italian rate -> must be kept (fix is per-country, not regex)
    assert 4.0 in _extract_vat_rates(_norm("Aliquota 4 % Totale 100,00"), "IT")


def test_de_19pct_accepted():
    assert 19.0 in _extract_vat_rates(_norm("MwSt 19% 19,00"), "DE")


def test_de_7pct_accepted():
    assert 7.0 in _extract_vat_rates(_norm("inkl. 7 % MwSt"), "DE")


# --- Fix #2: keyword-default behaviour must be preserved ------------------
def test_keyword_default_preserved():
    # Real DE receipt with a VAT keyword but no parseable rate/amount must still
    # fall back to the country default (19%). This path must NOT be broken by
    # removing the weak bare-'%' signal.
    rates, amount = extract_vat_info("Summe 119,00 inkl. MwSt", 119.00, "DE")
    assert amount == 19.0, f"expected 19.0 default, got {amount}"
    assert 19.0 in rates


# --- Fix #2: a bare '%' with no tax keyword must NOT fabricate VAT --------
def test_bare_percent_no_keyword_no_vat():
    rates, amount = extract_vat_info("random noise 0% blah blah", 100.00, "DE")
    assert amount == 0.0, f"expected 0.0, got {amount}"
