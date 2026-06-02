import os
import io
import logging
import re
import httpx
from fastapi import UploadFile

logger = logging.getLogger("autotax")

OCR_API_KEY = os.getenv("OCR_API_KEY", "")
OCR_API_URL = "https://api.ocr.space/parse/image"


def _src_enabled(name: str) -> bool:
    """Kill-flag: a source can be disabled via env (default ON) WITHOUT a deploy,
    e.g. QR_ENABLED=0 / OCR_SPACE_ENABLED=0 — if a source starts polluting results."""
    return (os.getenv(name, "1") or "1").strip().lower() not in ("0", "false", "no", "off")


def _header_garbage_score(text: str, sample_chars: int = 250) -> tuple[float, int]:
    """Score the OCR header (first ~250 chars — where logo lives).

    Returns (real_word_ratio, real_word_count).
    A real word = token with >= 3 chars and >= 60% letters.

    Why a header-only scan: receipt logos confuse Tesseract; the corruption
    is concentrated in the first few lines (vendor area). The body (items,
    totals) often comes out fine on the same scan, so a whole-text quality
    score under-reports the vendor problem.
    """
    if not text:
        return 0.0, 0
    sample = text[:sample_chars]
    tokens = [t for t in re.split(r"\s+", sample) if t]
    if not tokens:
        return 0.0, 0
    real = 0
    for t in tokens:
        t_clean = re.sub(r"^[^\w]+|[^\w]+$", "", t)
        n = len(t_clean)
        if n < 3 or n > 30:
            continue
        letters = sum(c.isalpha() for c in t_clean)
        if letters >= n * 0.6 and letters >= 3:
            real += 1
    return real / len(tokens), real


def _deskew_image(img):
    """Detect and correct skew angle. OpenCV first, projection profile fallback."""
    try:
        import numpy as np
        arr_gray = np.array(img.convert("L"))
        try:
            import cv2
            thresh = cv2.threshold(arr_gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
            coords = np.column_stack(np.where(thresh > 0))
            if len(coords) > 100:
                angle = cv2.minAreaRect(coords)[-1]
                if angle < -45:
                    angle = 90 + angle
                elif angle > 45:
                    angle = angle - 90
                if 0.5 < abs(angle) < 15:
                    logger.info("Deskew (OpenCV): %.1f°", angle)
                    img = img.rotate(angle, expand=True, fillcolor=255)
                    return img
        except ImportError:
            pass
        # Fallback: projection profile
        thumb = img.copy()
        thumb.thumbnail((600, 600))
        best_angle, best_score = 0, 0
        for a10 in range(-30, 31, 3):
            angle = a10 / 10.0
            rot = thumb.rotate(angle, expand=False, fillcolor=255)
            row_sums = np.sum(255 - np.array(rot.convert("L")), axis=1)
            score = np.var(row_sums)
            if score > best_score:
                best_score = score
                best_angle = angle
        if abs(best_angle) > 0.3:
            logger.info("Deskew (profile): %.1f°", best_angle)
            img = img.rotate(best_angle, expand=True, fillcolor=255)
    except Exception as e:
        logger.debug("Deskew failed: %s", e)
    return img


def preprocess_image(content: bytes) -> bytes:
    """Standard preprocessing: EXIF → Upscale → Gray → Contrast → Deskew → Resize."""
    try:
        from PIL import Image, ImageEnhance, ImageOps
        img = Image.open(io.BytesIO(content))

        try:
            img = ImageOps.exif_transpose(img)
        except Exception:
            pass

        # Upscale small images
        if max(img.width, img.height) < 1200:
            scale = 1200 / max(img.width, img.height)
            img = img.resize((int(img.width * scale), int(img.height * scale)), Image.LANCZOS)

        # Convert to grayscale
        img = img.convert("L")

        # Resize if needed (OCR.space free max 1MB)
        max_dim = 1800
        if img.width > max_dim or img.height > max_dim:
            img.thumbnail((max_dim, max_dim), Image.LANCZOS)

        # Enhance for OCR
        img = ImageOps.autocontrast(img, cutoff=1)
        img = ImageEnhance.Contrast(img).enhance(1.5)
        img = ImageEnhance.Sharpness(img).enhance(1.8)

        # Deskew
        img = _deskew_image(img)

        # Save as JPEG — always under 1MB for OCR API
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=92)
        processed = buf.getvalue()

        # Shrink if still too large
        if len(processed) > 950000:
            img.thumbnail((1400, 1400), Image.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=88)
            processed = buf.getvalue()

        logger.info("Image preprocessed: %d bytes → %d bytes (%dx%d)", len(content), len(processed), img.width, img.height)
        return processed
    except Exception as e:
        logger.warning("Image preprocessing failed, using original: %s", e)
        return content


def extract_pdf_text(content: bytes) -> str:
    import pdfplumber
    text_parts = []
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        for page in pdf.pages:
            t = page.extract_text()
            if t:
                text_parts.append(t)
    return "\n".join(text_parts)


def extract_pdf_page_as_image(content: bytes) -> bytes:
    """Convert first 1-3 pages of scanned PDF to a single stitched PNG image bytes."""
    try:
        import pdfplumber
        from PIL import Image
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            if pdf.pages:
                # 300 DPI gives noticeably better OCR than 150 on scanned receipts
                imgs = [pdf.pages[i].to_image(resolution=300).original for i in range(min(3, len(pdf.pages)))]
                if len(imgs) == 1:
                    img = imgs[0]
                else:
                    w = max(i.width for i in imgs)
                    h = sum(i.height for i in imgs)
                    img = Image.new("RGB", (w, h), "white")
                    y = 0
                    for i in imgs:
                        img.paste(i, (0, y))
                        y += i.height
                # Resize if too large for OCR API (max ~1MB, aim for <500KB)
                max_dim = 2000
                if img.width > max_dim or img.height > max_dim:
                    img.thumbnail((max_dim, max_dim), Image.LANCZOS)
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=85)
                logger.info("PDF→image: %d bytes, %dx%d (pages=%d)", buf.tell(), img.width, img.height, len(imgs))
                return buf.getvalue()
    except Exception as e:
        logger.warning("PDF→image failed: %s", e)
    return b""


async def _ocr_api_call(client, filename: str, content: bytes, engine: str = "1") -> str:
    """Single OCR API call with given engine."""
    resp = await client.post(
        OCR_API_URL,
        data={"apikey": OCR_API_KEY, "OCREngine": engine},
        files={"file": (filename, content)},
    )
    resp.raise_for_status()
    data = resp.json()
    # --- ADDED START ---
    logger.debug("[OCR] API err=%s msg=%s", data.get("IsErroredOnProcessing"), data.get("ErrorMessage"))
    # --- ADDED END ---
    results = data.get("ParsedResults") or []
    text_len = len((results[0] or {}).get("ParsedText", "")) if results else 0
    logger.info("OCR Engine %s: exit=%s, error=%s, text_len=%d", engine, data.get("OCRExitCode"), data.get("IsErroredOnProcessing"), text_len)
    if data.get("IsErroredOnProcessing"):
        return ""
    if results:
        return ((results[0] or {}).get("ParsedText") or "").strip()
    return ""


async def extract_image_text(content: bytes, filename: str) -> str:
    # --- MODIFIED START ---
    is_pdf = filename and filename.lower().endswith(".pdf")
    try:
        local_text = local_ocr_tesseract(content)
    except Exception as e:
        logger.warning("[OCR] local error: %s", e)
        local_text = ""
    logger.info("[OCR] mode=%s local_length=%d", "PDF" if is_pdf else "IMAGE", len(local_text))

    # OCR.space fallback triggers — TWO independent conditions:
    #
    # 1) Header garbage: Tesseract returns 500+ chars but logo area is
    #    mangled into "5 et Be" / "i AE 4 Een 4" — body fine, vendor line
    #    broken. _header_garbage_score detects this.
    #
    # 2) Single-line collapse: Tesseract concatenates all lines into one
    #    blob ("1m Rotfeld66115 SaarbrwænmpenBarRueckgeld 0,59 ..."). This
    #    happens with PDF-rendered images on Lidl/Aldi style receipts.
    #    Per-line scan in extract_total can't find anchors when there are
    #    no line breaks. OCR.space typically preserves layout newlines.
    if local_text and len(local_text) > 10:
        ratio, real_words = _header_garbage_score(local_text)
        header_bad = (ratio < 0.35 or real_words < 4)
        line_count = local_text.count("\n")
        single_line_collapse = line_count < 3 and len(local_text) > 200

        if (header_bad or single_line_collapse) and OCR_API_KEY:
            reason = "header garbage" if header_bad else "single-line collapse"
            logger.info(
                "[OCR] tesseract %s (ratio=%.2f, words=%d, lines=%d, len=%d) — trying OCR.space",
                reason, ratio, real_words, line_count, len(local_text),
            )
            # fall through to API path below
        elif header_bad or single_line_collapse:
            logger.info(
                "[OCR] tesseract weak (ratio=%.2f, lines=%d) but no OCR_API_KEY — keeping local",
                ratio, line_count,
            )
            return local_text
        else:
            logger.info("[OCR] using local OCR (ratio=%.2f, words=%d, lines=%d)",
                        ratio, real_words, line_count)
            return local_text
    elif is_pdf and local_text and len(local_text) > 50:
        logger.info("[OCR] using local OCR (pdf, short)")
        return local_text
    logger.info("[OCR] fallback to API")
    # --- MODIFIED END ---
    if not _src_enabled("OCR_SPACE_ENABLED"):
        logger.info("[OCR] OCR.space disabled (OCR_SPACE_ENABLED=0) — keeping Tesseract result")
        return local_text or ""
    if not OCR_API_KEY:
        logger.warning("OCR skipped — no API key configured")
        return ""
    logger.info("OCR: processing %s (%d bytes), key=%s...", filename, len(content), OCR_API_KEY[:4])
    processed = preprocess_image(content)
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            # Engine 1: fast
            text = await _ocr_api_call(client, filename, processed, "1")
            # --- ADDED START ---
            logger.debug("[OCR] API engine1 length=%d", len(text) if text else 0)
            # --- ADDED END ---

            # If Engine 1 failed or returned very little text, retry with Engine 2
            if len(text) < 10:
                logger.info("OCR Engine 1 insufficient (%d chars), retrying with Engine 2...", len(text))
                text2 = await _ocr_api_call(client, filename, processed, "2")
                if len(text2) > len(text):
                    text = text2

            # --- ADDED START ---
            if not text:
                engine = "1"
                logger.info("[OCR] retrying with original image")
                try:
                    retry_resp = await client.post(
                        OCR_API_URL,
                        data={"apikey": OCR_API_KEY, "OCREngine": engine},
                        files={"file": (filename, content)}
                    )
                    retry_data = retry_resp.json()
                    parsed = (retry_data.get("ParsedResults") or [])
                    if parsed:
                        text = ((parsed[0] or {}).get("ParsedText") or "").strip()
                except Exception as e:
                    logger.warning("[OCR] retry failed: %s", e)
            # --- ADDED END ---

            # Prefer API output when substantial; else fall back to whatever
            # Tesseract gave (we only entered the API path when Tesseract
            # header looked bad, but its body might still be useful).
            if text and len(text) >= 20:
                return text
            if local_text:
                logger.info("[OCR] API short/empty (%d chars) — keeping Tesseract output", len(text or ""))
                return local_text
            return text
    except Exception as e:
        logger.warning("OCR API failed for %s: %s", filename, e)
        return local_text or ""


async def extract_handwriting_text(content: bytes, filename: str) -> str:
    if not OCR_API_KEY:
        return ""
    processed = preprocess_image(content)
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                OCR_API_URL,
                data={"apikey": OCR_API_KEY, "OCREngine": "2"},
                files={"file": (filename, processed)},
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("IsErroredOnProcessing"):
                return ""
            results = data.get("ParsedResults", [])
            if results:
                return results[0].get("ParsedText", "").strip()
            return ""
    except Exception as e:
        logger.warning("OCR handwriting API failed: %s", e)
        return ""


async def extract_text(file: UploadFile, handwriting: bool = False, file_bytes: bytes = None) -> str:
    # deprecated — use extract_text_and_qr
    text, _ = await extract_text_and_qr(file, handwriting=handwriting, file_bytes=file_bytes)
    return text


async def extract_text_and_qr(file: UploadFile, handwriting: bool = False, file_bytes: bytes = None) -> tuple[str, dict]:
    """Extract both OCR text and QR code data from a file.
    Returns (ocr_text, qr_data_dict).
    If file_bytes is provided, uses that instead of reading from file (avoids seek issues).
    """
    content = file_bytes if file_bytes is not None else await file.read()
    filename = (file.filename or "").lower()
    content_type = (file.content_type or "").lower()
    logger.info("extract_text_and_qr: file=%s, type=%s, content_len=%d, from_bytes=%s", filename, content_type, len(content), file_bytes is not None)

    # QR code extraction (use original image — binarization can break QR)
    qr_data = {}
    if _src_enabled("QR_ENABLED"):
        try:
            from autotax.qr_reader import extract_qr_data
            qr_data = extract_qr_data(content, content_type)
        except Exception:
            pass  # QR reading is optional, don't break upload if it fails
    else:
        logger.info("QR disabled (QR_ENABLED=0) — skipping QR extraction")

    # Convert HEIC/HEIF to JPEG (iPhone camera format — not supported by OCR API)
    if "heic" in content_type or "heif" in content_type or filename.endswith((".heic", ".heif")):
        try:
            from PIL import Image
            img = Image.open(io.BytesIO(content))
            buf = io.BytesIO()
            img.convert("RGB").save(buf, format="JPEG", quality=90)
            content = buf.getvalue()
            content_type = "image/jpeg"
            logger.info("Converted HEIC→JPEG: %d bytes", len(content))
        except Exception as e:
            logger.warning("HEIC conversion failed: %s", e)

    # OCR text extraction (uses preprocessed image internally)
    if handwriting:
        ocr_text = await extract_handwriting_text(content, file.filename or "upload.png")
    elif content_type == "application/pdf" or filename.endswith(".pdf"):
        ocr_text = extract_pdf_text(content)
        _pdf_len = len(ocr_text.strip()) if ocr_text else 0
        logger.info("[PDF] text length=%d", _pdf_len)
        if _pdf_len <= 30:
            img_bytes = extract_pdf_page_as_image(content)
            if img_bytes:
                ocr_text = await extract_image_text(img_bytes, "scanned.png")
    elif content_type.startswith("image/") or filename.endswith((".jpg", ".jpeg", ".png", ".tiff", ".heic", ".heif")):
        ocr_text = await extract_image_text(content, file.filename or "upload.png")
    else:
        ocr_text = content.decode("utf-8", errors="ignore")

    return ocr_text, qr_data


# --- ADDED START: Table-specific OCR preprocessing ---
def preprocess_table_image(content: bytes) -> bytes:
    """Aggressive preprocessing for handwritten tables.
    Steps: EXIF → Upscale → Gray → Shadow removal → Contrast → Deskew → Threshold → Denoise."""
    try:
        from PIL import Image, ImageEnhance, ImageOps, ImageFilter
        import numpy as np
        img = Image.open(io.BytesIO(content))

        # EXIF fix
        try:
            img = ImageOps.exif_transpose(img)
        except Exception:
            pass

        # Upscale small images (handwriting needs detail)
        if max(img.width, img.height) < 1200:
            scale = 1400 / max(img.width, img.height)
            img = img.resize((int(img.width * scale), int(img.height * scale)), Image.LANCZOS)

        # Grayscale
        img = img.convert("L")

        # Resize large (max 2200px for tables)
        max_dim = 2200
        if img.width > max_dim or img.height > max_dim:
            img.thumbnail((max_dim, max_dim), Image.LANCZOS)

        # Shadow removal: divide by blurred background
        arr_f = np.array(img, dtype=np.float32)
        bg = np.array(img.filter(ImageFilter.GaussianBlur(radius=50)), dtype=np.float32)
        bg[bg == 0] = 1
        no_shadow = np.clip(arr_f * 255.0 / bg, 0, 255).astype(np.uint8)
        img = Image.fromarray(no_shadow)

        # Contrast + sharpen
        img = ImageOps.autocontrast(img, cutoff=2)
        img = ImageEnhance.Contrast(img).enhance(2.0)
        img = ImageEnhance.Sharpness(img).enhance(2.0)

        # Deskew (after contrast — clearer edges)
        img = _deskew_image(img)

        # Adaptive threshold: binarize for clean text
        arr = np.array(img)
        blur_arr = np.array(img.filter(ImageFilter.GaussianBlur(radius=15)))
        binary = np.where(arr < blur_arr - 18, 0, 255).astype(np.uint8)
        img = Image.fromarray(binary)

        # Denoise
        img = img.filter(ImageFilter.MedianFilter(size=3))

        # Save as JPEG
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=92)
        processed = buf.getvalue()

        if len(processed) > 950000:
            img.thumbnail((1600, 1600), Image.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=88)
            processed = buf.getvalue()

        logger.info("Table image preprocessed: %d bytes → %d bytes (%dx%d)", len(content), len(processed), img.width, img.height)
        img.close()
        return processed
    except Exception as e:
        logger.warning("Table preprocessing failed, using standard: %s", e)
        return preprocess_image(content)


async def extract_table_text(content: bytes, filename: str) -> str:
    """OCR for handwritten tables — tries aggressive preprocessing, then standard.
    Does NOT replace extract_handwriting_text — used only for table import."""
    if not OCR_API_KEY:
        return ""
    logger.info("Table OCR: processing %s (%d bytes)", filename, len(content))

    # Attempt 1: aggressive table preprocessing + Engine 2 (handwriting)
    processed = preprocess_table_image(content)
    best_text = ""
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            best_text = await _ocr_api_call(client, filename, processed, "2")
            logger.info("Table OCR attempt 1 (table_preprocess+E2): %d chars", len(best_text))

            # Attempt 2: if insufficient, try standard preprocess + Engine 2
            if len(best_text) < 40:
                processed_std = preprocess_image(content)
                text2 = await _ocr_api_call(client, filename, processed_std, "2")
                logger.info("Table OCR attempt 2 (standard+E2): %d chars", len(text2))
                if len(text2) > len(best_text):
                    best_text = text2

            return best_text
    except Exception as e:
        logger.warning("Table OCR failed: %s", e)
        return best_text
# --- ADDED END ---


# --- ADDED START: Auto-rotate table OCR (try 4 rotations) ---
async def extract_table_text_autorotate(content: bytes, filename: str) -> str:
    """Try 4 rotations (0, 90, 180, 270) and pick the one with most OCR text.
    Wraps extract_table_text — does NOT replace it."""
    if not OCR_API_KEY:
        return ""
    from PIL import Image, ImageOps

    logger.info("Table OCR autorotate: processing %s (%d bytes)", filename, len(content))

    img = Image.open(io.BytesIO(content))
    try:
        img = ImageOps.exif_transpose(img)
    except Exception:
        pass

    best_text = ""
    best_rot = 0

    async with httpx.AsyncClient(timeout=30) as client:
        for rot in [0, 90]:
            # Rotate image
            if rot == 0:
                rotated = img
            else:
                rotated = img.rotate(-rot, expand=True, fillcolor=255)

            # To bytes
            buf = io.BytesIO()
            rotated.save(buf, format="JPEG", quality=90)
            rot_bytes = buf.getvalue()

            # Preprocess + OCR
            processed = preprocess_table_image(rot_bytes)
            text = await _ocr_api_call(client, filename, processed, "2")
            logger.info("Table autorotate %d°: %d chars", rot, len(text))

            if len(text) > len(best_text):
                best_text = text
                best_rot = rot

            # Good enough — stop
            if len(best_text) >= 100:
                break

        logger.info("Table autorotate best: %d° with %d chars", best_rot, len(best_text))

        # Fallback: standard preprocess if still bad
        if len(best_text) < 40:
            processed_std = preprocess_image(content)
            text2 = await _ocr_api_call(client, filename, processed_std, "2")
            if len(text2) > len(best_text):
                best_text = text2
                logger.info("Table autorotate fallback: standard %d chars", len(text2))

    return best_text
# --- ADDED END ---


# --- ADDED START: PDF text extraction with OCR fallback (token-saving) ---
def extract_pdf_text_smart(content: bytes) -> str | None:
    """Try direct text extraction. Returns text if >50 chars, else None.
    Saves OCR API tokens when PDF already has text layer."""
    try:
        import pdfplumber
        text_parts = []
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            for page in pdf.pages:
                t = page.extract_text()
                if t:
                    text_parts.append(t)
        result = "\n".join(text_parts).strip()
        if len(result) > 50:
            logger.info("PDF text used (%d chars) — OCR skipped, tokens saved", len(result))
            return result
        logger.info("PDF text too short (%d chars) — falling back to OCR", len(result))
        return None
    except Exception as e:
        logger.warning("PDF text extraction failed: %s", e)
        return None


async def extract_pdf_smart(content: bytes, filename: str = "doc.pdf") -> str:
    """Smart PDF handler: try text first (saves tokens), fallback to OCR (first page only)."""
    text = extract_pdf_text_smart(content)
    if text:
        return text
    logger.info("OCR used for PDF: %s", filename)
    img_bytes = extract_pdf_page_as_image(content)
    if img_bytes:
        return await extract_image_text(img_bytes, filename)
    return ""
# --- ADDED END ---


# --- ADDED START: OCR fallback strategy — local first, paid as backup ---
def is_ocr_valid(text: str) -> bool:
    """Validate OCR result quality. Returns True if text is non-empty."""
    return bool(text and text.strip())


def try_local_ocr(content: bytes, lang: str = "deu+eng") -> str:
    """Run local Tesseract OCR. Returns text or empty string if unavailable/failed."""
    try:
        import pytesseract
        from PIL import Image
        img = Image.open(io.BytesIO(content))
        text = pytesseract.image_to_string(img, lang=lang)
        return text.strip()
    except ImportError:
        logger.warning("pytesseract not installed — local OCR unavailable")
        return ""
    except Exception as e:
        logger.warning("Local OCR failed: %s", e)
        return ""


async def extract_with_fallback(content: bytes, filename: str = "upload.png", force_paid_ocr: bool = False) -> str:
    """Try local OCR first, fallback to paid OCR if result is invalid.
    Wraps existing extract_image_text — does not modify it.

    NOTE: Currently no local OCR engine is installed (Tesseract not available).
    When local OCR is added, insert it here as the first attempt."""
    if force_paid_ocr:
        logger.info("Fallback OCR used (forced): %s", filename)
        return await extract_image_text(content, filename)

    # Try local Tesseract first (free, offline)
    local_text = try_local_ocr(content)
    if is_ocr_valid(local_text):
        logger.info("Local OCR used: %s (%d chars)", filename, len(local_text))
        return local_text

    # Fallback to paid OCR.space
    logger.info("Fallback OCR used (paid): %s", filename)
    paid_text = await extract_image_text(content, filename)
    return paid_text
# --- ADDED END ---


# ════════════════════════════════════════════════════════════════
# TABLE CELL OCR — OpenCV grid detection + per-cell OCR
# ════════════════════════════════════════════════════════════════

def extract_table_cells(content: bytes) -> list[list[str]]:
    """Detect table grid using OpenCV, extract each cell, OCR individually.
    Returns list of rows, each row is list of cell texts."""
    try:
        import cv2
        import numpy as np
        from PIL import Image, ImageOps

        # Load image
        arr = np.frombuffer(content, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            pil = Image.open(io.BytesIO(content)).convert("RGB")
            pil = ImageOps.exif_transpose(pil)
            img = cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        h, w = gray.shape

        # Adaptive threshold for line detection
        thresh = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                        cv2.THRESH_BINARY_INV, 15, 10)

        # Detect horizontal lines
        h_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (max(w // 8, 40), 1))
        h_lines = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, h_kernel)

        # Detect vertical lines
        v_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(h // 8, 40)))
        v_lines = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, v_kernel)

        # Combine lines → grid
        grid = cv2.add(h_lines, v_lines)

        # Find contours of cells
        contours, _ = cv2.findContours(grid, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)

        # Get bounding boxes, filter small ones
        boxes = []
        min_cell_w = w * 0.03
        min_cell_h = h * 0.015
        for cnt in contours:
            x, y, bw, bh = cv2.boundingRect(cnt)
            if bw > min_cell_w and bh > min_cell_h and bw < w * 0.95 and bh < h * 0.95:
                boxes.append((x, y, bw, bh))

        if len(boxes) < 4:
            logger.info("Table cell detection: only %d cells found, not a grid", len(boxes))
            return []

        # Sort boxes into rows (by Y) then columns (by X)
        boxes.sort(key=lambda b: (b[1], b[0]))

        # Group into rows — boxes with similar Y are same row
        rows_of_boxes = []
        current_row = [boxes[0]]
        for box in boxes[1:]:
            if abs(box[1] - current_row[0][1]) < min_cell_h * 2:
                current_row.append(box)
            else:
                current_row.sort(key=lambda b: b[0])  # sort by X
                rows_of_boxes.append(current_row)
                current_row = [box]
        if current_row:
            current_row.sort(key=lambda b: b[0])
            rows_of_boxes.append(current_row)

        logger.info("Table grid: %d rows, %d total cells", len(rows_of_boxes), len(boxes))

        # OCR each cell
        result_rows = []
        for row_boxes in rows_of_boxes:
            row_texts = []
            for (x, y, bw, bh) in row_boxes:
                # Crop cell with small padding
                pad = 3
                cell = gray[max(0,y+pad):min(h,y+bh-pad), max(0,x+pad):min(w,x+bw-pad)]
                if cell.size == 0:
                    row_texts.append("")
                    continue
                # OCR cell
                try:
                    import pytesseract
                    cell_pil = Image.fromarray(cell)
                    text = pytesseract.image_to_string(cell_pil, lang="deu+eng",
                        config="--oem 3 --psm 7").strip()  # PSM 7 = single line
                    row_texts.append(text)
                except Exception:
                    row_texts.append("")
            if any(t.strip() for t in row_texts):
                result_rows.append(row_texts)

        logger.info("Table cell OCR: %d rows extracted", len(result_rows))
        return result_rows

    except ImportError as e:
        logger.warning("Table cell OCR requires cv2+pytesseract: %s", e)
        return []
    except Exception as e:
        logger.warning("Table cell OCR failed: %s", e)
        return []


def table_cells_to_text(cells: list[list[str]]) -> str:
    """Convert cell grid to structured text that parser can understand."""
    if not cells:
        return ""
    lines = []
    for row in cells:
        line = "\t".join(row)
        lines.append(line)
    return "\n".join(lines)


# --- ADDED START: Tesseract DE-only wrapper + pipeline integration ---
def local_ocr_tesseract(image):
    """Run local Tesseract OCR with OpenCV preprocessing. Accepts PIL Image or bytes."""
    try:
        import pytesseract
        from PIL import Image, ImageOps
        import numpy as np
        import cv2
        # CRITIC: Once cv2.imdecode kullaniliyordu — iPhone EXIF rotation
        # flag'ini gormez. Yan cekilen fotograf yan kalir, Tesseract bozuk
        # metin uretir. Cozum: once PIL ile ac, exif_transpose uygula
        # (gorseli dogru yone cevirir), sonra OpenCV'ye gec.
        if isinstance(image, bytes):
            try:
                pil_img = Image.open(io.BytesIO(image))
                pil_img = ImageOps.exif_transpose(pil_img)  # iPhone yan foto fix
                pil_img = pil_img.convert("RGB")
                img_cv = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
            except Exception:
                # PIL acamadiysa cv2 fallback
                arr = np.frombuffer(image, dtype=np.uint8)
                img_cv = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                if img_cv is None:
                    return ""
        else:
            try:
                pil_img = ImageOps.exif_transpose(image)
            except Exception:
                pil_img = image
            img_cv = cv2.cvtColor(np.array(pil_img.convert("RGB")), cv2.COLOR_RGB2BGR)
        gray = cv2.cvtColor(img_cv, cv2.COLOR_BGR2GRAY)
        h, w = gray.shape[:2]

        # Conditional 2x upscale — only useful for small/zoomed-out shots.
        # Modern phone fishler are 1200-3000px wide and don't gain accuracy
        # from upscaling, but Tesseract is ~4x slower on a 4x area image.
        # Threshold 1500: covers iPhone Portrait (1290), legacy 720p, etc.
        if w < 1500:
            work = cv2.resize(gray, (w * 2, h * 2), interpolation=cv2.INTER_CUBIC)
            _scale_note = "2x"
        else:
            work = gray
            _scale_note = "1x"
        tess_cfg = "--oem 3 --psm 6"
        text = pytesseract.image_to_string(work, lang="deu+eng", config=tess_cfg)
        text = text.strip() if text else ""
        logger.info("[OCR] tesseract rot=0 length=%d scale=%s wh=%dx%d", len(text), _scale_note, w, h)

        # Safe retry only when first pass returned almost no text (clearly
        # rotated 90/180/270). Threshold lowered 80 -> 30: 30+ chars means
        # Tesseract is reading SOMETHING — multi-rotation is 3x extra OCR
        # passes and rarely helps when the body is already partially readable.
        # Rotation passes use the SAME image (no extra upscaling) for speed.
        if len(text) < 30:
            best_text, best_rot = text, 0
            for rot_code, rot_deg in (
                (cv2.ROTATE_90_CLOCKWISE, 90),
                (cv2.ROTATE_180, 180),
                (cv2.ROTATE_90_COUNTERCLOCKWISE, 270),
            ):
                try:
                    rot_img = cv2.rotate(work, rot_code)
                    t = pytesseract.image_to_string(rot_img, lang="deu+eng", config=tess_cfg)
                    t = t.strip() if t else ""
                    logger.info("[OCR] tesseract rot=%d length=%d", rot_deg, len(t))
                    if len(t) > len(best_text):
                        best_text, best_rot = t, rot_deg
                except Exception as e:
                    logger.debug("[OCR] tesseract rot=%d failed: %s", rot_deg, e)
            if best_rot != 0:
                logger.info("[OCR] tesseract using rot=%d (length=%d)", best_rot, len(best_text))
            text = best_text

        return text
    except ImportError:
        logger.warning("pytesseract/cv2 not installed")
        return ""
    except Exception as e:
        logger.warning("Tesseract OCR failed: %s", e)
        return ""


async def extract_image_text_with_tesseract(content: bytes, filename: str = "upload.png") -> str:
    """Tesseract first, OCR.space fallback. Modular — wraps existing extract_image_text."""
    # Try Tesseract
    tess_text = local_ocr_tesseract(content)
    if is_ocr_valid(tess_text):
        logger.info("Tesseract used: %s (%d chars)", filename, len(tess_text))
        return tess_text
    # Fallback to OCR.space
    logger.info("Fallback to OCR.space: %s", filename)
    return await extract_image_text(content, filename)
# --- ADDED END ---


# --- ADDED START: Layout-aware Tesseract reader (positional row reconstruction) ---
def extract_structured_text(image) -> list[str]:
    """Reconstruct table rows from Tesseract positional data.

    Same preprocessing + tesseract config as local_ocr_tesseract, but uses
    image_to_data() to get per-word bounding boxes, then groups words by Y
    coordinate to rebuild rows that survive column misalignment from
    image_to_string().

    Grouping logic:
      1. Drop words with conf <= 0 or empty text (Tesseract noise rows).
      2. Compute each word's vertical center: cy = top + height/2.
      3. Sort words by cy (top → bottom).
      4. Walk the sorted list. A word joins the current row if its cy is
         within `line_threshold` of the row's average cy; otherwise it
         starts a new row. Threshold is adaptive: max(10, median_height/2)
         — robust to font size and the 2× upscale.
      5. Inside each row, sort words left → right by `left` and join with
         a single space.

    Returns: list[str] — one entry per visual row, in top-to-bottom order.
    Returns [] on any error (does not raise; caller can fall back).
    """
    try:
        import pytesseract
        from PIL import Image
        import numpy as np
        import cv2

        # --- identical preprocessing to local_ocr_tesseract ---
        if isinstance(image, bytes):
            arr = np.frombuffer(image, dtype=np.uint8)
            img_cv = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            if img_cv is None:
                pil_img = Image.open(io.BytesIO(image)).convert("RGB")
                img_cv = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
        else:
            img_cv = cv2.cvtColor(np.array(image.convert("RGB")), cv2.COLOR_RGB2BGR)
        gray = cv2.cvtColor(img_cv, cv2.COLOR_BGR2GRAY)
        h, w = gray.shape[:2]
        resized = cv2.resize(gray, (w * 2, h * 2), interpolation=cv2.INTER_CUBIC)

        # --- positional OCR ---
        data = pytesseract.image_to_data(
            resized,
            lang="deu+eng",
            config="--oem 3 --psm 6",
            output_type=pytesseract.Output.DICT,
        )

        # --- collect valid words ---
        words = []
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
            words.append({
                "text": txt,
                "left": int(data["left"][i]),
                "top": int(data["top"][i]),
                "width": int(data["width"][i]),
                "height": int(data["height"][i]),
            })

        if not words:
            logger.info("[OCR] structured: no words found")
            return []

        # --- adaptive row threshold from median word height ---
        heights = sorted(w["height"] for w in words)
        median_h = heights[len(heights) // 2]
        line_threshold = max(10, median_h // 2)

        # --- group by vertical center ---
        for w in words:
            w["cy"] = w["top"] + w["height"] / 2.0
        words.sort(key=lambda w: w["cy"])

        rows = []          # list[list[word]]
        row_centers = []   # parallel list of running average cy per row
        for w in words:
            if rows and abs(w["cy"] - row_centers[-1]) <= line_threshold:
                rows[-1].append(w)
                # update running average so drift stays bounded
                row_centers[-1] = sum(x["cy"] for x in rows[-1]) / len(rows[-1])
            else:
                rows.append([w])
                row_centers.append(w["cy"])

        # --- sort each row left→right and join ---
        result = []
        for row in rows:
            row.sort(key=lambda w: w["left"])
            result.append(" ".join(w["text"] for w in row))

        logger.info("[OCR] structured: %d rows, %d words, line_thr=%d", len(result), len(words), line_threshold)
        return result

    except ImportError:
        logger.warning("[OCR] structured: pytesseract/cv2 not installed")
        return []
    except Exception as e:
        logger.warning("[OCR] structured extraction failed: %s", e)
        return []
# --- ADDED END ---


# --- ADDED START: OCR timeout protection wrapper ---
OCR_TIMEOUT_SECONDS = 10


async def extract_image_text_safe(content: bytes, filename: str = "upload.png") -> dict:
    """Wrap extract_image_text with 10s timeout + safe error response.
    Returns dict: {success, text, error, filename}."""
    import asyncio as _asyncio
    try:
        text = await _asyncio.wait_for(
            extract_image_text(content, filename),
            timeout=OCR_TIMEOUT_SECONDS
        )
        return {"success": True, "text": text or "", "error": None, "filename": filename}
    except _asyncio.TimeoutError:
        logger.warning("OCR timeout (>%ds): %s", OCR_TIMEOUT_SECONDS, filename)
        return {"success": False, "text": "", "error": "ocr_timeout", "filename": filename}
    except Exception as e:
        logger.warning("OCR safe wrapper failed for %s: %s", filename, e)
        return {"success": False, "text": "", "error": str(e)[:100], "filename": filename}


async def extract_handwriting_text_safe(content: bytes, filename: str = "upload.png") -> dict:
    """Timeout-protected handwriting OCR."""
    import asyncio as _asyncio
    try:
        text = await _asyncio.wait_for(
            extract_handwriting_text(content, filename),
            timeout=OCR_TIMEOUT_SECONDS * 2
        )
        return {"success": True, "text": text or "", "error": None, "filename": filename}
    except _asyncio.TimeoutError:
        logger.warning("Handwriting OCR timeout: %s", filename)
        return {"success": False, "text": "", "error": "ocr_timeout", "filename": filename}
    except Exception as e:
        logger.warning("Handwriting OCR safe wrapper failed for %s: %s", filename, e)
        return {"success": False, "text": "", "error": str(e)[:100], "filename": filename}


async def batch_ocr_safe(files_with_names: list) -> list:
    """Process multiple files with timeout protection.
    Continues even if one file fails.
    files_with_names: list of (content_bytes, filename) tuples.
    Returns: list of result dicts."""
    results = []
    for content, filename in files_with_names:
        result = await extract_image_text_safe(content, filename)
        results.append(result)
        if result["error"]:
            logger.info("Batch OCR continuing after error: %s (%s)", filename, result["error"])
    return results
# --- ADDED END ---


# ─── Long-image chunked OCR (Tabellen-Import) ─────────────────────────
# Kullanici 32 satirli Kassenbuch fotografi yukleyince OCR.space resmin
# alt yarisini siklikla bos donduruyor (uzun resim downscale ediliyor,
# kucuk yazi/cizgi kayboluyor). Bu helper uzun resmi N parcaya boler,
# her parcayi ayri OCR yapar, text'leri birlestirir.

async def extract_table_text_chunked(content: bytes, filename: str = "table.jpg",
                                      threshold_height: int = 1500,
                                      max_chunks: int = 4,
                                      overlap_px: int = 80) -> str:
    """Uzun bir tablo resmini dik olarak parcalara bolup her birini OCR.

    - Resmin yuksekligi `threshold_height` altinda ise direkt
      extract_table_text_autorotate kullanir (tek pass).
    - Daha uzun ise yuksekligi parca basina ~1200px olacak sekilde 2-4
      parcaya boler (max_chunks ile sinirli). Komsu parcalar arasinda
      `overlap_px` ust uste binme — bir satirin yarisinin kesilip
      kaybolmasini onlemek icin.
    - Her parcanin text'i birlestirilir (\\n ile).

    Output, dogrudan import_image_table'in beklendigi format (raw text).
    """
    try:
        from PIL import Image, ImageOps
        img = Image.open(io.BytesIO(content))
        try:
            img = ImageOps.exif_transpose(img)
        except Exception:
            pass
        w, h = img.size
    except Exception as e:
        logger.warning("chunked OCR: PIL open failed (%s) — falling back to single pass", e)
        return await extract_table_text_autorotate(content, filename)

    if h <= threshold_height or w < 100:
        # Tek pass yeterli
        return await extract_table_text_autorotate(content, filename)

    # Hedef parca yuksekligi ~1200px — kabaca 25-30 tablo satiri
    target_chunk_h = 1200
    n_chunks = max(2, min(max_chunks, (h + target_chunk_h - 1) // target_chunk_h))
    chunk_h = h // n_chunks

    logger.info("Chunked OCR: %dx%d → %d chunks of ~%dpx (overlap %dpx)",
                w, h, n_chunks, chunk_h, overlap_px)

    texts: list[str] = []
    for i in range(n_chunks):
        top = max(0, i * chunk_h - (overlap_px if i > 0 else 0))
        bottom = min(h, (i + 1) * chunk_h + (overlap_px if i < n_chunks - 1 else 0))
        if bottom - top < 100:
            continue
        try:
            crop = img.crop((0, top, w, bottom))
            buf = io.BytesIO()
            crop.save(buf, format="JPEG", quality=90)
            chunk_bytes = buf.getvalue()
            chunk_fn = f"chunk{i+1}of{n_chunks}_{filename}"
            chunk_text = await extract_table_text_autorotate(chunk_bytes, chunk_fn)
            logger.info("Chunked OCR chunk %d/%d (y=%d-%d): %d chars",
                        i + 1, n_chunks, top, bottom,
                        len(chunk_text.strip()) if chunk_text else 0)
            if chunk_text:
                texts.append(chunk_text.strip())
        except Exception as e:
            logger.warning("Chunked OCR chunk %d/%d failed: %s", i + 1, n_chunks, e)
            continue

    if not texts:
        # Tum chunk'lar bos — son care: tek pass
        logger.warning("Chunked OCR: all chunks empty — falling back to single pass")
        return await extract_table_text_autorotate(content, filename)

    return "\n".join(texts)
