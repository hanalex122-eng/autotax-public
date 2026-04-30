"""Receipt OCR pipeline — Tesseract-only, layout-aware, deterministic.

Self-contained module. Does NOT import from autotax.ocr or affect the
production OCR / Kassenbuch flows. Function names are namespaced inside
autotax.receipt_ocr so they don't collide with autotax.ocr.

Key insight: receipts often have a label on the LEFT and a value on the
RIGHT of the same line, separated by wide horizontal whitespace or dot
leaders ("Wert .......... 25,00 EUR"). Plain image_to_string() collapses
this into a single line of garbled tokens. We use image_to_data() to keep
positional info, group words into lines by Y, and then pair labels with
right-side numbers on the same line.

Public API:
    process_receipt(image) -> dict          # main pipeline
    preprocess_image(image) -> ndarray      # STEP 1
    is_ocr_valid(text) -> bool              # STEP 7
    extract_numbers(text) -> list[float]    # STEP 4 helper
    extract_total(text) -> float | None     # text-only fallback (STEP 6)

`image` accepts: bytes, PIL.Image, or numpy ndarray.
Pipeline never raises — always returns a dict with `status`.
"""

import io
import re
import logging

logger = logging.getLogger("autotax")


# ─────────────────────────────────────────────────────────────────
# Regex constants
# ─────────────────────────────────────────────────────────────────

# STEP 4 — keyword expansion + word-boundary matching
# \b avoids matching "summe" inside "Zwischensumme"
# Priority order matters: summe (most specific) > total > betrag > wert
_LABEL_PRIORITY = ("summe", "gesamtbetrag", "endbetrag", "rechnungsbetrag",
                   "zahlbetrag", "gesamt", "total", "betrag", "wert")
_TOTAL_LABEL_RE = re.compile(
    r"\b(" + "|".join(_LABEL_PRIORITY) + r")\b",
    re.IGNORECASE,
)

# Numbers with mandatory cents: 12.34 / 12,34 / 1.234,56
_NUMBER_RE = re.compile(r"\d{1,3}(?:[.\s]\d{3})*[.,]\d{2}|\d+[.,]\d{2}")

# Alphabetic-only word, used by quality gate
_ALPHA_WORD_RE = re.compile(r"^[A-Za-zÄÖÜäöüß]+$")

# Tokens that should NEVER be picked as the vendor name
_VENDOR_BLACKLIST = {
    "datum", "uhr", "uhrzeit", "bon", "summe", "total", "betrag", "eur", "euro",
    "tag", "zeit", "kasse", "kassiererin", "kassierer", "mwst", "ust", "tax",
    "nr", "no", "rechnung", "quittung", "beleg", "tisch", "filiale", "tel",
    "fax", "www", "tse", "trans", "transaktion", "bediener",
}

_MIN_AMOUNT = 1.0  # ignore values below this when picking the total


# ─────────────────────────────────────────────────────────────────
# STEP 1 — Image preprocessing
# 2× upscale → grayscale → adaptive threshold → 2x2 dilation
# ─────────────────────────────────────────────────────────────────
def preprocess_image(image):
    """Return single-channel uint8 ndarray ready for Tesseract."""
    import cv2
    import numpy as np
    from PIL import Image, ImageOps

    if isinstance(image, np.ndarray):
        img_bgr = image
    else:
        if isinstance(image, bytes):
            pil = Image.open(io.BytesIO(image))
        else:
            pil = image
        try:
            pil = ImageOps.exif_transpose(pil)
        except Exception:
            pass
        img_bgr = cv2.cvtColor(np.array(pil.convert("RGB")), cv2.COLOR_RGB2BGR)

    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY) if img_bgr.ndim == 3 else img_bgr

    h, w = gray.shape
    gray = cv2.resize(gray, (w * 2, h * 2), interpolation=cv2.INTER_CUBIC)

    binary = cv2.adaptiveThreshold(
        gray, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        blockSize=31, C=10,
    )

    kernel = np.ones((2, 2), dtype=np.uint8)
    dilated = cv2.dilate(binary, kernel, iterations=1)
    return dilated


# ─────────────────────────────────────────────────────────────────
# STEP 1+2 — Position-aware OCR + line reconstruction
# ─────────────────────────────────────────────────────────────────
def _ocr_words(prepared) -> list:
    """Run pytesseract.image_to_data and return list of word dicts.
    Filters out conf<=0 and empty tokens. Image-coordinate units."""
    import pytesseract
    data = pytesseract.image_to_data(
        prepared,
        lang="deu+eng",
        config="--oem 3 --psm 6",
        output_type=pytesseract.Output.DICT,
    )
    out = []
    n = len(data.get("text", []))
    for i in range(n):
        txt = (data["text"][i] or "").strip()
        if not txt:
            continue
        try:
            conf = int(float(data["conf"][i]))
        except (ValueError, TypeError):
            conf = -1
        if conf <= 0:
            continue
        left = int(data["left"][i])
        top = int(data["top"][i])
        wd = int(data["width"][i])
        ht = int(data["height"][i])
        out.append({
            "text": txt,
            "left": left,
            "top": top,
            "width": wd,
            "height": ht,
            "right": left + wd,
            "cy": top + ht / 2.0,
        })
    return out


def _group_into_lines(words: list) -> list:
    """STEP 2 — Y-cluster words into lines. Returns list of lines, each
    line is a list of words sorted left-to-right.

    Threshold is adaptive (median word height * 0.4) so it works at
    different scales. Anchor-based grouping avoids drift across rows.
    """
    if not words:
        return []
    heights = sorted(w["height"] for w in words)
    median_h = heights[len(heights) // 2]
    line_threshold = max(4, int(median_h * 0.4))

    sorted_by_y = sorted(words, key=lambda w: w["cy"])
    lines = []
    anchors = []
    for w in sorted_by_y:
        if lines and abs(w["cy"] - anchors[-1]) <= line_threshold:
            lines[-1].append(w)
        else:
            lines.append([w])
            anchors.append(w["cy"])

    for line in lines:
        line.sort(key=lambda w: w["left"])
    return lines


# ─────────────────────────────────────────────────────────────────
# STEP 4 (helper) — number extraction
# ─────────────────────────────────────────────────────────────────
def _parse_amount(s: str):
    """Parse a numeric token into float (DE/US format)."""
    s = s.replace(" ", "")
    if "." in s and "," in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def extract_numbers(text: str) -> list:
    """Public helper: return list[float] of all numbers in text."""
    if not text:
        return []
    out = []
    for tok in _NUMBER_RE.findall(text):
        v = _parse_amount(tok)
        if v is not None:
            out.append(v)
    return out


# ─────────────────────────────────────────────────────────────────
# STEP 3 — Layout-aware key/value pairing on a single line
# ─────────────────────────────────────────────────────────────────
def _line_label_and_value(line: list):
    """If a line has a label keyword on the left and a number on the right,
    return (normalized_label, value). Otherwise return None.

    Label and value can be separated by ANY amount of whitespace or dot
    leaders ("Wert .......... 25,00 EUR") because we walk the pre-sorted
    word list left-to-right.
    """
    label_idx = None
    label_text = None
    for i, w in enumerate(line):
        m = _TOTAL_LABEL_RE.search(w["text"])
        if m:
            label_idx = i
            label_text = m.group(1).lower()
            break
    if label_idx is None:
        return None

    # Take the rightmost number AFTER the label (EUR suffix usually trails)
    best_value = None
    for w in line[label_idx + 1:]:
        m = _NUMBER_RE.search(w["text"])
        if m:
            v = _parse_amount(m.group(0))
            if v is not None and v >= _MIN_AMOUNT:
                best_value = v
    if best_value is None:
        return None
    return label_text, best_value


def _collect_label_value_pairs(lines: list) -> dict:
    """STEP 3 — Build {label: value} dict from all reconstructed lines.
    If the same label appears multiple times, keep the MAX value
    (handles 'Summe' appearing on both subtotal + total lines)."""
    pairs: dict = {}
    for line in lines:
        result = _line_label_and_value(line)
        if not result:
            continue
        label, value = result
        if label not in pairs or value > pairs[label]:
            pairs[label] = value
    return pairs


def _find_total_layout_aware(lines: list):
    """STEP 4 priority order: summe > gesamtbetrag > endbetrag > ... > wert.
    Returns the value from the FIRST priority label that has a match.
    Falls back to text-only extract_total() inside process_receipt()."""
    pairs = _collect_label_value_pairs(lines)
    if not pairs:
        return None
    for label in _LABEL_PRIORITY:
        if label in pairs:
            v = pairs[label]
            logger.info("[receipt_ocr] total via priority label %r: %.2f", label, v)
            return v
    return None


# ─────────────────────────────────────────────────────────────────
# STEP 5 — Vendor detection (top 25% rule)
# ─────────────────────────────────────────────────────────────────
def _find_vendor(words: list) -> str:
    """Pick the most prominent text from the top 25% of the image.

    Score = uppercase_bonus + (height_normalized) + (length_bonus)
    Excludes generic receipt vocabulary.
    Returns the line containing the highest-scoring word, joined.
    """
    if not words:
        return ""
    page_h = max(w["top"] + w["height"] for w in words)
    cutoff = page_h * 0.25
    top_words = [w for w in words if w["cy"] <= cutoff]
    if not top_words:
        return ""

    max_h = max((w["height"] for w in top_words), default=1) or 1

    def score(w):
        text = w["text"]
        if text.lower() in _VENDOR_BLACKLIST:
            return -1.0
        if not any(c.isalpha() for c in text):
            return -1.0
        if len(text) < 2:
            return -1.0
        s = 0.0
        # Uppercase bonus — store names usually in CAPS
        if text.isupper() and len(text) >= 3:
            s += 2.0
        # Height bonus — larger font = more important
        s += w["height"] / max_h
        # Longer-word bonus per spec: words >5 chars get extra weight
        if len(text) > 5:
            s += 1.0
        s += min(len(text), 12) * 0.05
        return s

    scored = [(score(w), w) for w in top_words]
    scored.sort(key=lambda t: t[0], reverse=True)
    if not scored or scored[0][0] <= 0:
        return ""

    best = scored[0][1]

    # Words on the SAME horizontal line as the highest-scoring word
    line_h = max(best["height"], 10)

    def _same_line_words(anchor):
        return sorted(
            [w for w in top_words
             if abs(w["cy"] - anchor["cy"]) <= line_h * 0.6
             and w["text"].lower() not in _VENDOR_BLACKLIST],
            key=lambda w: w["left"]
        )

    same_line = _same_line_words(best)
    vendor = " ".join(w["text"] for w in same_line).strip()

    # Optional spec rule: merge with NEXT-best line if vendor is too short
    # (single short word like "DM" or "H&M") or all-lowercase noise
    if len(vendor) < 5 and len(scored) > 1:
        for sc, w in scored[1:5]:
            if sc <= 0:
                break
            if abs(w["cy"] - best["cy"]) <= line_h * 0.6:
                continue  # already on best's line
            extra_line = _same_line_words(w)
            extra = " ".join(x["text"] for x in extra_line).strip()
            if extra and extra != vendor:
                vendor = (vendor + " " + extra).strip()
                break

    logger.info("[receipt_ocr] vendor candidate: %r", vendor)
    return vendor


# ─────────────────────────────────────────────────────────────────
# STEP 7 — Sensitive-data scanner (best-effort, never raises)
# ─────────────────────────────────────────────────────────────────
_SENSITIVE_PATTERNS = (
    ("api_key_stripe",  re.compile(r"\b(?:sk|pk|rk)_(?:live|test)_[A-Za-z0-9]{16,}\b")),
    ("api_key_aws",     re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("api_key_google",  re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("api_key_github",  re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}\b")),
    ("api_key_slack",   re.compile(r"\bxox[bopas]-[A-Za-z0-9-]{10,}\b")),
    ("jwt_token",       re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")),
    ("bearer_token",    re.compile(r"\bBearer\s+[A-Za-z0-9._-]{20,}\b", re.IGNORECASE)),
    ("email",           re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
)


def _mask_secret(s: str) -> str:
    """Mask middle of a secret: 'sk_live_abc123' -> 'sk_l****c123'."""
    if len(s) <= 8:
        return "****"
    return s[:4] + "****" + s[-3:]


def scan_sensitive(text: str) -> dict:
    """Scan text for API keys, tokens, and emails. Returns:
        {"findings": [{"type": str, "masked": str}, ...], "masked_text": str}

    Never raises. The original `text` argument is not modified — `masked_text`
    is a copy with sensitive substrings replaced by their masked form.
    Caller decides whether to use the masked or original text downstream.
    """
    if not text:
        return {"findings": [], "masked_text": text or ""}
    findings = []
    masked = text
    for kind, pat in _SENSITIVE_PATTERNS:
        for m in pat.finditer(text):
            secret = m.group(0)
            mk = _mask_secret(secret)
            findings.append({"type": kind, "masked": mk})
            masked = masked.replace(secret, mk)
    if findings:
        logger.warning("[receipt_ocr] sensitive data found: %d items", len(findings))
    return {"findings": findings, "masked_text": masked}


# ─────────────────────────────────────────────────────────────────
# STEP 6 — OCR quality gate
# ─────────────────────────────────────────────────────────────────
def is_ocr_valid(text: str) -> bool:
    """≥ 5 alphabetic words of length ≥ 3. Garbled OCR fails this gate."""
    if not text:
        return False
    valid = 0
    for w in text.split():
        if len(w) >= 3 and _ALPHA_WORD_RE.match(w):
            valid += 1
    if valid < 5:
        logger.info("[receipt_ocr] OCR rejected: only %d valid words", valid)
        return False
    return True


# ─────────────────────────────────────────────────────────────────
# STEP 6 — text-only fallback (used when no layout data available)
# ─────────────────────────────────────────────────────────────────
def extract_total(text: str):
    """Text-only total extraction (no positional data).

    Priority:
      1. Numbers on lines containing total keywords → max
      2. Fallback: max of all numbers >= MIN_AMOUNT

    NEVER aggregates, sums, or guesses random values.
    """
    if not text:
        return None

    keyword_numbers = []
    for line in text.splitlines():
        if not _TOTAL_LABEL_RE.search(line):
            continue
        for n in extract_numbers(line):
            if n >= _MIN_AMOUNT:
                keyword_numbers.append(n)

    if keyword_numbers:
        winner = max(keyword_numbers)
        logger.info("[receipt_ocr] total via keyword (text): %.2f", winner)
        return winner

    all_numbers = [n for n in extract_numbers(text) if n >= _MIN_AMOUNT]
    if not all_numbers:
        return None
    winner = max(all_numbers)
    logger.info("[receipt_ocr] total via fallback (max): %.2f", winner)
    return winner


# ─────────────────────────────────────────────────────────────────
# Vendor-only detector — bypasses quality gate and total extraction.
# Intended for use as a fallback when the main parser returns garbage.
# ─────────────────────────────────────────────────────────────────
def detect_vendor(image) -> str:
    """Run just the vendor detection pipeline and return the best candidate.

    Skips the is_ocr_valid quality gate and total extraction. Used by
    main.py as a fallback when parser.extract_vendor returns garbage.

    Input: bytes / PIL Image / ndarray.  Returns empty string on failure.
    Accepts image bytes only — for PDFs, caller must render to image first.
    """
    try:
        prepared = preprocess_image(image)
        words = _ocr_words(prepared)
        if not words:
            return ""
        return _find_vendor(words) or ""
    except ImportError:
        return ""
    except Exception as e:
        logger.warning("[receipt_ocr] detect_vendor failed: %s", e)
        return ""


# ─────────────────────────────────────────────────────────────────
# STEP 8 — Main pipeline (layout-aware)
# image → preprocess → image_to_data → lines → pairs → vendor → security
# ─────────────────────────────────────────────────────────────────
def process_receipt(image) -> dict:
    """Run the full receipt pipeline. Never raises.

    Returns on success:
        {"status": "success",
         "total":   float,
         "vendor":  str,
         "raw_text": str,
         "pairs":   {label: value, ...},
         "security": {"findings": [...], "count": int}}

    Returns on failure:
        {"status": "failed", "reason": "<reason>"}
    """
    # STEP 1
    try:
        prepared = preprocess_image(image)
    except ImportError:
        return {"status": "failed", "reason": "deps_missing"}
    except Exception as e:
        logger.warning("[receipt_ocr] preprocess failed: %s", e)
        return {"status": "failed", "reason": "preprocess_error"}

    # STEP 1+2 — position-aware OCR
    try:
        words = _ocr_words(prepared)
    except ImportError:
        return {"status": "failed", "reason": "deps_missing"}
    except Exception as e:
        logger.warning("[receipt_ocr] tesseract failed: %s", e)
        return {"status": "failed", "reason": "ocr_error"}

    if not words:
        return {"status": "failed", "reason": "ocr_empty"}

    # Reconstruct lines + raw_text for downstream
    lines = _group_into_lines(words)
    raw_text = "\n".join(" ".join(w["text"] for w in line) for line in lines).strip()

    # STEP 6 — quality gate
    if not is_ocr_valid(raw_text):
        return {"status": "failed", "reason": "low_quality_ocr"}

    # STEP 3 — collect ALL label/value pairs (for transparency in response)
    pairs = _collect_label_value_pairs(lines)

    # STEP 4 — total: layout-aware (priority order) → text fallback → None
    total = _find_total_layout_aware(lines)
    if total is None:
        total = extract_total(raw_text)
    if total is None:
        return {"status": "failed", "reason": "no_total_found"}

    # STEP 5 — vendor
    vendor = _find_vendor(words)

    # STEP 7 — security scan (best-effort, never blocks success)
    sec = scan_sensitive(raw_text)

    return {
        "status": "success",
        "total": round(total, 2),
        "vendor": vendor,
        "raw_text": raw_text,
        "pairs": {k: round(v, 2) for k, v in pairs.items()},
        "security": {
            "findings": sec["findings"],
            "count": len(sec["findings"]),
        },
    }
