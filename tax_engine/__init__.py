"""AutoTax tax_engine — additive, read-only knowledge-driven services.

This package layers a knowledge-base-driven engine (form detection,
questionnaire runtime, declaration builder) on top of the existing
`autotax` backend WITHOUT modifying any existing module, endpoint,
database schema, or deployment.

Design constraints (intentional, see tax_engine/IMPLEMENTATION.md):
- No database access here. All inputs are plain dicts; all knowledge is
  loaded from tax_engine/knowledge/*.json (read-only).
- No new third-party dependencies (stdlib only).
- Existing `autotax.declaration` and its endpoints are untouched.

Public surface:
- loader            — cached JSON loaders + accessors (Phase A)
- detection         — FormDetectionEngine (Phase B)
- questionnaire     — QuestionnaireRuntime (Phase C)
- builder           — DeclarationBuilder (Phase D)
"""

__all__ = ["loader", "detection", "questionnaire", "builder"]
