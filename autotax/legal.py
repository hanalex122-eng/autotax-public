"""Legal/privacy page builders (Phase 2.2 modularization, 2026-05-27).

Constants + HTML builder for multilingual privacy/datenschutz pages.
Route handlers in main.py call _privacy_page() with section data.

Languages supported:
- de (Datenschutzerklärung)
- en (Privacy Policy)
- fr (Politique de Confidentialité)
- es (Política de Privacidad)
- tr (Gizlilik Politikası)
- ar (سياسة الخصوصية)

Extraction approach: file-by-file, smallest-risk first. See ROADMAP.md
Phase 2 (Low-risk modularization).
"""
from __future__ import annotations

from fastapi.responses import HTMLResponse


PRIVACY_CSS = """body{font-family:'DM Sans',sans-serif;max-width:800px;margin:40px auto;padding:20px;background:#050a12;color:#e8edf5;line-height:1.8}
h1{color:#10b981;font-size:28px}h2{color:#00a8cc;margin-top:30px;font-size:18px}strong{color:#f59e0b}
a{color:#10b981}p{margin:12px 0}ul{padding-left:20px}li{margin:6px 0}
.lang-bar{display:flex;gap:10px;margin-bottom:20px;flex-wrap:wrap}
.lang-bar a{padding:6px 14px;border-radius:8px;border:1px solid #2a3548;color:#94a3b8;text-decoration:none;font-size:13px}
.lang-bar a.active{background:#10b981;color:#fff;border-color:#10b981}"""


PRIVACY_LANG_BAR = """<div class="lang-bar">
<a href="/datenschutz" class="{de}">Deutsch</a>
<a href="/privacy" class="{en}">English</a>
<a href="/confidentialite" class="{fr}">Français</a>
<a href="/privacidad" class="{es}">Español</a>
<a href="/gizlilik" class="{tr}">Türkçe</a>
<a href="/khususiyya" class="{ar}">العربية</a>
</div>"""


PRIVACY_THIRD_PARTIES = """<ul>
<li><strong>Railway Inc.</strong> (USA/EU) — Hosting</li>
<li><strong>OCR.space / a9t9 Software GmbH</strong> — OCR {ocr_desc}</li>
<li><strong>Anthropic PBC</strong> (USA) — AI {ai_desc}</li>
<li><strong>Stripe Payments Europe Ltd.</strong> (Irland/EU) — Zahlungsabwicklung (Kreditkarte, SEPA). Verarbeitet Name, E-Mail, IP, Zahlungsdaten gemäß PCI-DSS.</li>
<li><strong>Cloudflare, Inc.</strong> (USA/EU-Frankfurt) — Objektspeicher (R2) für verschlüsselte Datenbank-Backups. Kein Zugriff auf personenbezogene Daten im Klartext.</li>
<li><strong>Resend</strong> (USA) — Transaktionale E-Mails (Rechnungen, Erinnerungen)</li>
<li><strong>Telegram Messenger Inc.</strong> (UK/UAE) — optionale Benachrichtigungen (nur wenn vom Nutzer aktiviert)</li>
</ul>"""


def privacy_page(lang: str, title: str, sections: list) -> HTMLResponse:
    """Render a multilingual privacy/datenschutz page.

    Args:
        lang: ISO code (de/en/fr/es/tr/ar)
        title: page <title> and <h1>
        sections: list of {"h": heading, "c": HTML content} dicts

    Returns:
        FastAPI HTMLResponse ready to be returned from a route handler.
    """
    bar = PRIVACY_LANG_BAR.format(
        de="active" if lang == "de" else "",
        en="active" if lang == "en" else "",
        fr="active" if lang == "fr" else "",
        es="active" if lang == "es" else "",
        tr="active" if lang == "tr" else "",
        ar="active" if lang == "ar" else "",
    )
    direction = ' dir="rtl"' if lang == "ar" else ""
    body = (
        f'<!DOCTYPE html><html lang="{lang}"{direction}><head><meta charset="UTF-8">'
        f'<title>{title}</title>\n'
        f'<style>{PRIVACY_CSS}</style></head><body>{bar}<h1>{title}</h1>\n'
        f'<p><em>AutoTax Cloud — '
        f'{"Stand" if lang == "de" else "Last updated"}: April 2026</em></p>'
    )
    for s in sections:
        body += f'\n<h2>{s["h"]}</h2>\n{s["c"]}'
    body += (
        '\n<p style="margin-top:40px;color:#64748b;font-size:13px">'
        '© 2026 AutoTax Cloud</p></body></html>'
    )
    return HTMLResponse(content=body)


# Backward-compat aliases (main.py historically uses underscore-prefixed names)
_PRIVACY_CSS = PRIVACY_CSS
_PRIVACY_LANG_BAR = PRIVACY_LANG_BAR
_PRIVACY_THIRD_PARTIES = PRIVACY_THIRD_PARTIES
_privacy_page = privacy_page


__all__ = [
    "PRIVACY_CSS", "PRIVACY_LANG_BAR", "PRIVACY_THIRD_PARTIES", "privacy_page",
    "_PRIVACY_CSS", "_PRIVACY_LANG_BAR", "_PRIVACY_THIRD_PARTIES", "_privacy_page",
]
