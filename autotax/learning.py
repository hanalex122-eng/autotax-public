"""Per-user learning system for AutoTaxHub.

When a user corrects a field (vendor, vat_rate, category) on an invoice,
a rule is saved. On future uploads, rules are applied BEFORE the parser
so known corrections happen instantly — no OCR/parser/LLM needed.

Pipeline order:
  OCR → apply_learning_rules → Parser → LLM fallback → Merge → DB

Simple text matching, no AI, no fuzzy, production-safe.
"""

import logging
from autotax.db import SessionLocal
from autotax.models import LearningRule

logger = logging.getLogger("autotax")

# Fields that can be learned from user corrections
LEARNABLE_FIELDS = {"vendor", "vat_rate", "category", "payment_method", "invoice_type"}

# Default/empty values that indicate "parser didn't find anything useful"
_EMPTY_VALUES = {"Unbekannt", "other", "0%", "", None, "expense"}


def _extract_keyword(ocr_text: str, vendor: str) -> str:
    """Extract a SHORT keyword from OCR text to use as match_text.

    Strategy:
      1. Use the vendor name — first word only if multi-word
         "Bereket Market GmbH" → "bereket"
         "LIDL" → "lidl"
      2. If vendor is empty/Unbekannt, use first meaningful OCR word

    Returns lowercase keyword, 3-30 chars. Short = more matches.
    """
    # Try vendor first — use first significant word for better matching
    if vendor and vendor not in ("Unbekannt", "", None) and len(vendor) >= 3:
        # Split and take first word with 3+ letters
        words = vendor.lower().strip().split()
        for w in words:
            clean = ''.join(c for c in w if c.isalpha())
            if len(clean) >= 3:
                return clean[:30]
        return vendor.lower().strip()[:30]

    # Fallback: first non-empty OCR word with 4+ letters
    if ocr_text:
        for line in ocr_text.splitlines()[:8]:
            for word in line.strip().split():
                clean = ''.join(c for c in word.lower() if c.isalpha())
                if len(clean) >= 4:
                    return clean[:30]

    return ""


def save_learning_rule(user_id: int, ocr_text: str, original: dict, edited: dict) -> int:
    """Compare original vs edited fields. For each changed field, create
    or update a learning rule. Returns count of rules saved.

    Called from _do_update_invoice when user edits an invoice.
    """
    if not user_id or not edited:
        return 0

    keyword = _extract_keyword(ocr_text or "", edited.get("vendor") or original.get("vendor", ""))
    if not keyword:
        return 0

    saved = 0
    db = SessionLocal()
    try:
        for field in LEARNABLE_FIELDS:
            old_val = original.get(field, "")
            new_val = edited.get(field)
            if new_val is None:
                continue  # field not in edit request
            if str(old_val).strip() == str(new_val).strip():
                continue  # no change
            if str(new_val).strip() in _EMPTY_VALUES:
                continue  # don't learn empty/default values

            # Check if rule already exists for this user+keyword+field
            existing = db.query(LearningRule).filter(
                LearningRule.user_id == user_id,
                LearningRule.match_text == keyword,
                LearningRule.field_name == field,
            ).first()

            if existing:
                existing.value = str(new_val).strip()
                existing.use_count += 1
                logger.info("[LEARN] updated rule: user=%d '%s' %s='%s'",
                            user_id, keyword, field, new_val)
            else:
                db.add(LearningRule(
                    user_id=user_id,
                    match_text=keyword,
                    field_name=field,
                    value=str(new_val).strip(),
                ))
                logger.info("[LEARN] new rule: user=%d '%s' %s='%s'",
                            user_id, keyword, field, new_val)
            saved += 1

        db.commit()
    except Exception as e:
        db.rollback()
        logger.warning("[LEARN] save failed: %s", e)
        saved = 0
    finally:
        db.close()

    return saved


def apply_learning_rules(user_id: int, ocr_text: str, data: dict) -> dict:
    """Apply saved learning rules to an invoice before parser runs.

    For each rule: if match_text appears in ocr_text (case-insensitive)
    AND the target field is empty/default → fill it.

    NEVER overwrites existing non-default values.

    Returns the (possibly enriched) data dict.
    """
    if not user_id or not ocr_text:
        return data

    db = SessionLocal()
    try:
        rules = db.query(LearningRule).filter(
            LearningRule.user_id == user_id
        ).all()

        if not rules:
            return data

        text_lower = ocr_text.lower()
        applied = []

        # Sort by match_text length descending (longer = more specific)
        rules.sort(key=lambda r: -len(r.match_text or ""))

        for rule in rules:
            if not rule.match_text or len(rule.match_text) < 3:
                continue
            # Exact substring match first (fast)
            if rule.match_text not in text_lower:
                # Tolerant match: if first 4+ chars of match_text appear
                # as a word start in OCR text, consider it a match.
                # This handles OCR variants like "lyidl" vs learned "lidl":
                # keyword "lidl" won't match "lyidl" exactly, but if the
                # keyword is 5+ chars like "lidl gmbh", the first 5 chars
                # "lidl " might still appear. For short keywords we skip.
                prefix = rule.match_text[:5] if len(rule.match_text) >= 5 else ""
                if not prefix or prefix not in text_lower:
                    continue
            if rule.field_name not in LEARNABLE_FIELDS:
                continue

            current = data.get(rule.field_name, "")
            # Only fill if current value is empty/default
            if str(current).strip() and str(current).strip() not in _EMPTY_VALUES:
                continue

            data[rule.field_name] = rule.value
            rule.use_count += 1
            applied.append(f"{rule.field_name}={rule.value}")

        if applied:
            db.commit()
            logger.info("[LEARN] applied %d rules: %s", len(applied), ", ".join(applied))

    except Exception as e:
        logger.warning("[LEARN] apply failed: %s", e)
    finally:
        db.close()

    return data
