"""Centralised runtime configuration read from environment variables.

Two Railway services run the same code base:
- **personal** instance (autotaxhub.de) — all flags default ON
- **public niche** instance (app.autotaxhub.de) — some flags OFF for a
  tighter IT-Freelancer / Berater experience.

All flags default to "enabled" so an unconfigured service behaves like
the full product. A public-niche instance sets the `FEAT_*` env vars
to `0` to hide the relevant features (UI level; backend endpoints
remain reachable to avoid breaking existing integrations).
"""
from __future__ import annotations

import json
import os


def _flag(name: str, default: str = "1") -> bool:
    v = os.getenv(name, default).strip().lower()
    return v in ("1", "true", "yes", "on")


# Flags consumed by the SPA (index.html). Exposed as window.FEATURES.
FEATURES: dict[str, bool | str] = {
    # Main entry flows
    "upload":         _flag("FEAT_UPLOAD"),         # PDF/photo upload view
    "tableimport":    _flag("FEAT_TABELLE_IMPORT"), # handwritten Kassenbuch photo
    "beleg_manual":   _flag("FEAT_BELEG_MANUAL"),   # /beleg manual entry
    "editor":         _flag("FEAT_EDITOR"),         # split-view editor
    "email_import":   _flag("FEAT_EMAIL_IMPORT"),   # IMAP sync

    # Optional tools
    "ai_chat":        _flag("FEAT_AI_CHAT"),        # AI chat view
    "handwriting":    _flag("FEAT_HANDWRITING"),    # handwriting OCR mode toggle

    # Niche instance marker (used for landing/pricing copy tweaks)
    "public_niche":   _flag("PUBLIC_NICHE", "0"),
    "niche_name":     os.getenv("NICHE_NAME", ""),
}


def kasse_v2_enabled() -> bool:
    """Backend feature flag for Kasa MVP v2 endpoints (kasse_api router:
    /kasse/dashboard, /kasse/summary/*, /kasse/categories). Default OFF —
    when off the new endpoints return 404. Backend-only (NOT in window.FEATURES
    yet; dashboard UI is Sprint 3). Flip with FEAT_KASSE_V2=1 for pilot."""
    return _flag("FEAT_KASSE_V2", "0")


def tax_engine_v2_enabled() -> bool:
    """Backend-only feature flag for the knowledge-driven tax engine v2 API
    (tax_engine package + /tax/* read-only routers). Default OFF — when off,
    the new endpoints return 404 and behave as if not present. Intentionally
    NOT part of FEATURES / window.FEATURES: no UI/SPA exposure yet."""
    return _flag("TAX_ENGINE_V2_ENABLED", "0")


def features_js_literal() -> str:
    """JSON-serialise the FEATURES dict so it can be embedded into the
    served HTML as `window.FEATURES = {...};`. Adds runtime-resolved
    public values (Turnstile site key) that aren't in the static dict."""
    payload = dict(FEATURES)
    # Public-safe Cloudflare Turnstile site key — needed by the SPA to
    # render the CAPTCHA widget. Site keys are public by design (Cloudflare).
    payload["turnstile_site_key"] = (
        os.getenv("TURNSTILE_SITE_KEY")
        or os.getenv("CLOUDFLARE_TURNSTILE_SITE_KEY")
        or ""
    ).strip()
    return json.dumps(payload, ensure_ascii=False)


# --------------------------- landing copy ------------------------------

_LANDING_GENERIC = {
    "SEO_TITLE":     "AutoTax-HUB — Rechnungen automatisch verbuchen",
    "SEO_DESC":      "Rechnungen fotografieren oder per E-Mail empfangen — AutoTax-HUB erkennt, kategorisiert und exportiert für DATEV. Für Freelancer und kleine Unternehmen in Deutschland.",
    "HERO_BADGE":    "Beta — Jetzt kostenlos testen",
    "HERO_H1":       "Rechnungen <span>automatisch</span>,<br>Buchhaltung <span>einfach</span>",
    "HERO_DESC":     "Fotografieren, hochladen oder per E-Mail empfangen. AutoTax-HUB erkennt Ihre Belege, kategorisiert sie und führt Ihr Kassenbuch DATEV-konform.",
    "CTA_PRIMARY":   "Kostenlos starten",
    "CTA_SECONDARY": "Wie es funktioniert",
    "STAT1_NUM":     "64+",  "STAT1_LABEL": "Länder unterstützt",
    "STAT2_NUM":     "30+",  "STAT2_LABEL": "Währungen",
    "STAT3_NUM":     "350+", "STAT3_LABEL": "Lieferanten erkannt",
    "CTA_H2":        "Bereit, Ihre Buchhaltung zu<br>automatisieren?",
    "CTA_SUB":       "50 Belege kostenlos. Keine Kreditkarte erforderlich.",
}

_LANDING_NICHE_IT_FREELANCER = {
    "SEO_TITLE":     "AutoTax-HUB — Buchhaltung für IT-Freelancer & Berater",
    "SEO_DESC":      "AWS, Stripe, Adobe, GitHub — deine SaaS-Rechnungen per E-Mail automatisch erfasst, sortiert und monatlich als DATEV-Paket an deinen Steuerberater versendet.",
    "HERO_BADGE":    "Für IT-Freelancer & Berater",
    "HERO_H1":       "Dein Rechnungseingang,<br><span>automatisch</span> bereit für den <span>Steuerberater</span>",
    "HERO_DESC":     "AWS, Stripe, Adobe, GitHub und 350+ weitere — deine SaaS-Rechnungen landen per E-Mail, AutoTax-HUB sortiert sie und liefert monatlich ein fertiges DATEV-Paket.",
    "CTA_PRIMARY":   "Jetzt kostenlos testen",
    "CTA_SECONDARY": "Wie es funktioniert",
    "STAT1_NUM":     "350+", "STAT1_LABEL": "SaaS-Lieferanten erkannt",
    "STAT2_NUM":     "XRechnung", "STAT2_LABEL": "& ZUGFeRD nativ",
    "STAT3_NUM":     "1-Klick", "STAT3_LABEL": "DATEV-Export",
    "CTA_H2":        "Fertig mit manueller<br>Rechnungsverwaltung?",
    "CTA_SUB":       "Kostenlos starten. Kein Stress mit Belegen. Steuerberater glücklich.",
}


def landing_copy() -> dict[str, str]:
    """Return the set of placeholder → value mappings appropriate for the
    current instance (generic vs niche)."""
    if FEATURES.get("public_niche") is True:
        name = (FEATURES.get("niche_name") or "").strip().lower()
        if "freelancer" in name or "berater" in name or "it" in name:
            return _LANDING_NICHE_IT_FREELANCER
    return _LANDING_GENERIC


def render_landing_placeholders(html: str) -> str:
    """Replace {{KEY}} placeholders in the given HTML with the copy values
    for the currently configured landing variant."""
    for key, val in landing_copy().items():
        html = html.replace("{{" + key + "}}", val)
    return html
