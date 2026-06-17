"""Fix 1 — amount-aware OCR trust + engine chooser (autotax/ocr.py).

Background: is_ocr_valid() only requires >=3 real words in the header, so a scan
whose only readable text is the store logo (e.g. "Aral Tankstelle" + noise, no
prices) passed the gate and the upload path used that garbage instead of calling
the stronger OCR.space engine. These tests pin the stricter trust check and the
score-based chooser.
"""
from autotax.ocr import (
    ocr_quality_score,
    tesseract_trusted,
    pick_best_ocr,
    is_ocr_valid,
)

# A real receipt Tesseract read well: vendor header + price present.
GOOD_TESS = (
    "GLOBUS BAUMARKT\nGlobus Fachmaerkte GmbH & Co KG\n"
    "Malerwalze 29,99\nSumme: 29,99\nMwSt 19%\n"
)
# id 861 via Tesseract: logo readable, but NO price and NO date — useless body.
GARBAGE_TESS_861 = "Aral Tankstelle\n; 16 M FIUIR-A Fi 4\nde . i A RX Z"
# id 861 via OCR.space on the SAME photo: full receipt (date, address, amounts).
RICH_OCRSPACE_861 = (
    "Aral Tankstelle\nSven Meyer\nSt. Johannerstr. 105\n66115 Saarbruecken\n"
    "Beleg-Nr 5218/019/00001 06.06.2026 12:59\nSuper 95  35,00 EUR\n"
    "Summe 35,00 EUR\nMwSt 19% 5,59\n"
)


def test_score_zero_for_empty_or_tiny():
    assert ocr_quality_score("") == 0
    assert ocr_quality_score("ab") == 0


def test_score_monotonic():
    assert ocr_quality_score(GARBAGE_TESS_861) < ocr_quality_score(GOOD_TESS)
    assert ocr_quality_score(GARBAGE_TESS_861) < ocr_quality_score(RICH_OCRSPACE_861)


def test_trusted_requires_an_amount():
    # is_ocr_valid passes (logo gives >=3 words) but there is no price -> NOT trusted,
    # so the caller must fall back to OCR.space.
    assert is_ocr_valid(GARBAGE_TESS_861) is True
    assert tesseract_trusted(GARBAGE_TESS_861) is False
    # A clean receipt with a price stays on the cheap local path.
    assert tesseract_trusted(GOOD_TESS) is True


def test_trusted_rejects_empty_and_logo_only():
    assert tesseract_trusted("") is False
    assert tesseract_trusted("Aral Tankstelle") is False  # 2 words, no price


def test_trusted_is_strictly_stronger_than_valid():
    for t in (GOOD_TESS, GARBAGE_TESS_861, RICH_OCRSPACE_861, "", "x", "Aral Tankstelle"):
        if tesseract_trusted(t):
            assert is_ocr_valid(t), t


def test_pick_prefers_clearly_better_ocrspace():
    # The core bug: logo-only Tesseract must LOSE to the full OCR.space read.
    assert pick_best_ocr(GARBAGE_TESS_861, RICH_OCRSPACE_861) == RICH_OCRSPACE_861


def test_pick_keeps_tess_when_fallback_empty():
    assert pick_best_ocr(GOOD_TESS, "") == GOOD_TESS
    assert pick_best_ocr(GOOD_TESS, "   ") == GOOD_TESS


def test_pick_keeps_tess_when_fallback_worse():
    # A garbage fallback never discards a decent local read.
    assert pick_best_ocr(GOOD_TESS, GARBAGE_TESS_861) == GOOD_TESS


def test_pick_returns_other_when_tess_empty():
    assert pick_best_ocr("", RICH_OCRSPACE_861) == RICH_OCRSPACE_861


def test_pick_keeps_tess_on_tie_within_margin():
    # Identical text -> no margin advantage -> keep Tesseract (already in hand, free).
    assert pick_best_ocr(GOOD_TESS, GOOD_TESS) == GOOD_TESS
