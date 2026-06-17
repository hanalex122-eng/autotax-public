"""Vision fallback — escalate only weak/suspicious cheap-OCR results (ai_ocr.py).

Pure unit tests: trigger logic, date guard, and the merge policy (with a fake
ai_extract_invoice — no network).
"""
import asyncio
import autotax.ai_ocr as ai
from autotax.ai_ocr import vision_should_fire, _vision_date_ok


# ---- trigger ----------------------------------------------------------------

def test_clean_receipt_does_not_fire():
    fire, _ = vision_should_fire({"total_amount": 29.99, "vendor": "Globus", "date": "2025-09-08"})
    assert fire is False


def test_total_zero_fires():
    assert vision_should_fire({"total_amount": 0, "vendor": "ARAL", "date": "2025-09-08"})[0] is True


def test_empty_date_fires():
    assert vision_should_fire({"total_amount": 19.51, "vendor": "Auchan", "date": ""})[0] is True


def test_missing_vendor_fires():
    assert vision_should_fire({"total_amount": 5.0, "vendor": "Unbekannt", "date": "2025-09-08"})[0] is True


def test_suspicious_high_total_fires():
    # receipt 882: 1610,13 stored on a 12,95 receipt
    fire, reason = vision_should_fire({"total_amount": 1610.13, "vendor": "ARAL", "date": "2025-09-08"})
    assert fire is True and "suspicious_total" in reason


# ---- date guard -------------------------------------------------------------

def test_date_guard_accepts_plausible_past():
    assert _vision_date_ok("2023-06-06") is True


def test_date_guard_rejects_far_future_and_garbage():
    assert _vision_date_ok("2030-01-01") is False   # out of year range
    assert _vision_date_ok("2026-13-40") is False    # invalid calendar
    assert _vision_date_ok("") is False
    assert _vision_date_ok("16 juin 2026") is False  # not ISO


# ---- merge policy (fake vision, no network) ---------------------------------

def _fake_vision(result):
    async def _f(*a, **k):
        return result
    return _f


def _run(parsed, vis):
    orig = ai.ai_extract_invoice
    ai.ai_extract_invoice = _fake_vision(vis)
    try:
        return asyncio.run(ai.maybe_vision_enhance(parsed, b"\xff\xd8img", "image/jpeg", "r.jpg", "raw"))
    finally:
        ai.ai_extract_invoice = orig


def test_merge_fixes_zero_total_and_vendor():
    out = _run({"total_amount": 0.0, "vendor": "ARAL", "date": ""},
               {"vendor": "Aral AG", "total_amount": 35.0, "date": "2023-06-06"})
    assert out["total_amount"] == 35.0 and out["vendor"] == "Aral AG" and out["date"] == "2023-06-06"
    assert out.get("vision_fallback_used") is True


def test_merge_overrides_suspicious_total():
    # 882: cheap 1610,13 → vision 12,95
    out = _run({"total_amount": 1610.13, "vendor": "ARAL", "date": ""},
               {"vendor": "dm-drogerie markt", "total_amount": 12.95, "date": "2023-06-06"})
    assert out["total_amount"] == 12.95 and out["vendor"] == "dm-drogerie markt"


def test_merge_keeps_correct_total_when_vision_matches():
    # 846: cheap 29,99 (date empty fires) → vision also 29,99 → unchanged total, date filled
    out = _run({"total_amount": 29.99, "vendor": "Netto", "date": ""},
               {"vendor": "Globus", "total_amount": 29.99, "date": "2023-06-06"})
    assert out["total_amount"] == 29.99 and out["vendor"] == "Globus" and out["date"] == "2023-06-06"


def test_merge_rejects_bad_vision_date():
    # 851: cheap date empty, vision returns a swapped future date → date stays empty
    out = _run({"total_amount": 96.53, "vendor": "MTB", "date": ""},
               {"vendor": "MTB Tankstelle", "total_amount": 96.53, "date": "2099-10-06"})
    assert out["date"] == ""   # bad vision date not applied


def test_clean_receipt_skips_vision_call():
    # must NOT call vision for a clean receipt (cost + regression guard)
    def _boom(*a, **k):
        raise AssertionError("vision must not be called for a clean receipt")
    orig = ai.ai_extract_invoice
    ai.ai_extract_invoice = _boom
    try:
        parsed = {"total_amount": 29.99, "vendor": "Globus", "date": "2025-09-08"}
        out = asyncio.run(ai.maybe_vision_enhance(parsed, b"img", "image/jpeg", "r.jpg"))
        assert out == parsed and "vision_fallback_used" not in out
    finally:
        ai.ai_extract_invoice = orig


def test_vision_failure_keeps_cheap():
    out = _run({"total_amount": 0.0, "vendor": "ARAL", "date": ""}, None)
    assert out["total_amount"] == 0.0 and out["vendor"] == "ARAL"
    assert "vision_fallback_used" not in out
