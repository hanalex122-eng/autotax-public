"""Filename -> vendor guard (P1).

Bug (audit 2026-06-13): generic scanner/camera filenames were stored AS the
vendor — e.g. "Scan2026-06-05_170051.pdf" -> vendor "Scan2026 06 05" (prod
invoices 770/781). The old generic check only caught SHORT names
(len <= prefix+5), so a date-suffixed scan name slipped through.

filename_vendor_guess() returns None for any generic scanner/camera/doc default
so the caller keeps 'Unbekannt' + needs_review instead of a fake vendor. Real
shop names in filenames are preserved.
"""
from autotax.parser import filename_vendor_guess


# --- generic scanner/camera/doc defaults -> None (the bug) ----------------
def test_scan_date_is_not_vendor():
    assert filename_vendor_guess("Scan2026-06-05_170051.pdf") is None


def test_whatsapp_image_is_not_vendor():
    assert filename_vendor_guess("WhatsApp Image 2026-02-21 at 14.20.26.jpg") is None


def test_img_number_is_not_vendor():
    assert filename_vendor_guess("IMG_1234.jpg") is None


def test_image_is_not_vendor():
    assert filename_vendor_guess("image.jpg") is None


def test_document_is_not_vendor():
    assert filename_vendor_guess("document.pdf") is None


def test_rechnung_generic_is_not_vendor():
    assert filename_vendor_guess("rechnung.pdf") is None


def test_empty_is_none():
    assert filename_vendor_guess("") is None
    assert filename_vendor_guess(None) is None


# --- real vendor names in filenames are preserved -------------------------
def test_real_vendor_name_preserved():
    assert filename_vendor_guess("kebabhaus-mueller.jpg") == "Kebabhaus Mueller"


def test_scan_prefixed_real_name_kept():
    # 'scan' + a real word -> residue 'kebabhaus' survives -> keep
    assert filename_vendor_guess("scan-kebabhaus.jpg") == "Scan Kebabhaus"
