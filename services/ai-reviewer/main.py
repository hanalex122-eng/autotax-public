"""AutoTax AI Reviewer — bağımsız mikroservis.

AutoTax-Hub'tan webhook ile gelen fatura için Claude'a "uyumsuzluk var mı?"
diye sorar, sonucu callback ile geri yollar. AutoTax kod tabanına hiç
dokunmaz — sadece HMAC-imzalı POST/POST.

Env:
    ANTHROPIC_API_KEY    Claude API key (sk-ant-...)
    WEBHOOK_SECRET       AutoTax ile paylaşılan HMAC secret (32+ byte)
    MODEL                Claude model adı (default: claude-sonnet-4-6)
    PORT                 Railway tarafından set edilir

Akış:
    AutoTax → POST /review (HMAC-imzalı)
              {invoice_id, user_id, callback_url, ocr_text, parsed}
    → Claude analizi
    → AutoTax callback'i çağır
              {invoice_id, status, notes}

Deploy: Railway'de ayrı service olarak. Bu klasörü ayrı bir GitHub repo
olarak da push edilebilir, ya da monorepo yapısında kalır.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Request

try:
    import anthropic
except ImportError:
    anthropic = None  # boş env'de modül load olmasın

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("ai-reviewer")

app = FastAPI(title="AutoTax AI Reviewer", version="1.0.0")

WEBHOOK_SECRET = (os.environ.get("WEBHOOK_SECRET") or "").strip()
ANTHROPIC_API_KEY = (os.environ.get("ANTHROPIC_API_KEY") or "").strip()
MODEL = (os.environ.get("MODEL") or "claude-sonnet-4-6").strip()

if not WEBHOOK_SECRET:
    logger.warning("WEBHOOK_SECRET env yok — tüm istekler 403 dönecek")
if not ANTHROPIC_API_KEY:
    logger.warning("ANTHROPIC_API_KEY env yok — Claude çağrısı atlanır")

_claude = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY) if (anthropic and ANTHROPIC_API_KEY) else None


SYSTEM_PROMPT = """\
Du bist ein deutscher Steuer- und Buchhaltungsexperte für Kleinunternehmer \
und Selbstständige. Du analysierst Rechnungen, die in AutoTax-Cloud \
hochgeladen werden, und gibst eine vollständige steuerliche Einordnung.

INPUT:
  1. raw_text  — OCR-extrahierter Rohtext der Rechnung
  2. parsed    — vom Backend-Parser strukturierte Felder
                 (vendor, total_amount, vat_rate, date, …)

DEINE AUFGABE: vier Dinge gleichzeitig tun

A) Konsistenzprüfung (Validierung der OCR/Parse-Daten)
B) Steuerliche Kategorisierung (welche Aufwandsart)
C) Absetzbarkeit (wie viel % ist steuerlich abzugsfähig)
D) Hinweise + fehlende Belege

═══════════════════════════════════════════════════════
DEUTSCHE STEUERREGELN (Stand 2026 — Kleinunternehmer & EÜR):
═══════════════════════════════════════════════════════

BEWIRTUNG (Geschäftsessen, Cafés, Restaurants):
  • 70% absetzbar (§4 Abs.5 Nr.2 EStG), 30% nicht abzugsfähig
  • Vorsteuer 100% abziehbar
  • PFLICHT-DOKUMENTE: Bewirtungsbeleg mit Anlass, Teilnehmer, Datum, Ort
  • Trinkgeld nur mit separatem Beleg/Quittung abzugsfähig

GESCHENKE an Geschäftspartner:
  • Bis 50€ pro Person/Jahr: voll abzugsfähig (ab 2024)
  • >50€: gar nicht abzugsfähig (auch nicht teilweise)
  • Vorsteuer entsprechend

MIETE / NEBENKOSTEN (Büro, Lager):
  • 100% absetzbar wenn rein gewerblich
  • Wenn Wohnung gemischt: Privatanteil prüfen → Hinweis nötig
  • Vorsteuer nur wenn Vermieter zur USt optiert hat

HOMEOFFICE-PAUSCHALE:
  • 6€/Tag, max. 1.260€/Jahr (ab 2023)
  • Kein separater Raum nötig
  • Statt: Arbeitszimmer 1.260€/Jahr (Mittelpunkt) oder voll absetzbar

KFZ (Auto, Tankquittung, Werkstatt):
  • 100% wenn rein gewerblich
  • Privatanteil: 1%-Regelung (1% Bruttolistenpreis/Monat) ODER Fahrtenbuch
  • Tankquittung allein → fragen ob privat genutzt
  • Vorsteuer nach betrieblichem Anteil

REISEKOSTEN:
  • Übernachtung: 100% absetzbar (mit Beleg) + Frühstück abziehen (5,60€/Tag)
  • Verpflegungspauschale: Inland 14€ (8-24h), 28€ (>24h), Tag der An/Abreise 14€
  • Bahn/Flug/Taxi: 100% mit Beleg, Vorsteuer voll

MINI-JOB / LOHN:
  • 538€/Monat Grenze (2024+)
  • Pauschalabgaben ~31% an Knappschaft Bahn-See
  • PFLICHT-DOKUMENTE: Arbeitsvertrag, Lohnabrechnung, A1-Bescheinigung
  • Sozialversicherung-Anmeldung muss vorliegen

SOZIALABGABEN (Krankenkasse, Rentenversicherung):
  • Eigene Beiträge: in Sonderausgaben, NICHT als Betriebsausgabe
  • Mitarbeiterbeiträge: AG-Anteil 100% absetzbar

ABSCHREIBUNG (AfA) — Anschaffungen >800€ netto:
  • Bis 800€ netto: GWG — sofort 100% absetzbar
  • 800–1000€: optional GWG-Pool über 5 Jahre
  • >1000€: AfA-Tabelle (PC 3 Jahre, Möbel 13, Auto 6, etc.)
  • Hinweis bei >800€ netto: Aktivierung empfohlen

BÜROMATERIAL / KLEININVENTAR:
  • <800€ netto: sofort 100% absetzbar
  • Vorsteuer voll

VERSICHERUNGEN:
  • Betriebshaftpflicht, Berufshaftpflicht: 100% absetzbar
  • Private Versicherungen (BU, Lebens, KV-Anteil): Sonderausgaben

FORTBILDUNG / SOFTWARE / ABO:
  • Berufliche Fortbildung: 100% absetzbar
  • Software-Abos, Cloud, KI-Tools: 100% mit Vorsteuer

═══════════════════════════════════════════════════════

ANTWORTE NUR ALS JSON, KEINE WEITERE ERKLÄRUNG:

{
  "status": "ok" | "warning" | "error",
  "notes": "Kurze Hauptaussage Deutsch, max 200 Zeichen",
  "tax_category": "Bewirtung" | "Geschenk" | "Miete" | "Homeoffice" | "KFZ" | "Reise" | "Lohn" | "Sozialabgaben" | "AfA" | "Buero" | "Versicherung" | "Software" | "Material" | "Andere",
  "absetzbar_pct": 0-100,
  "vorsteuer_abziehbar": true | false,
  "tax_warnings": ["Warnung 1", "Warnung 2"],
  "missing_docs": ["Fehlendes Dokument 1"]
}

REGELN:
- absetzbar_pct: Prozentsatz der steuerlich abzugsfähigen Summe (Bewirtung=70, Geschenk>50€=0, sonst meist 100)
- vorsteuer_abziehbar: nur false wenn Kleinunternehmer-Rechnung oder reiner Privat-Posten
- tax_warnings: Hinweise wie "Privatanteil prüfen", "Aktivierung nötig"
- missing_docs: Pflichtdokumente die fehlen (z.B. "Bewirtungsbeleg mit Teilnehmern")
- Wenn unklar → status=warning + konkreter Hinweis in tax_warnings
- Wenn OCR/Parse-Tutarsızlık → status=error + notes erklärt das

Sei präzise und kurz. Du sparst dem Nutzer Geld und Steuerprüfungs-Stress.
"""


def _verify_signature(body: bytes, signature: str) -> bool:
    if not WEBHOOK_SECRET:
        return False
    expected = hmac.new(WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature or "")


def _sign(body: bytes) -> str:
    return hmac.new(WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()


def _ask_claude(ocr_text: str, parsed: dict) -> dict:
    """Claude'dan analiz al. Hata varsa status=ok (safe default) dön.
    Yanit: {status, notes, tax_category, absetzbar_pct, vorsteuer_abziehbar,
             tax_warnings, missing_docs}
    """
    empty_result = {
        "status": "ok", "notes": "",
        "tax_category": None, "absetzbar_pct": None,
        "vorsteuer_abziehbar": None,
        "tax_warnings": [], "missing_docs": [],
    }
    if not _claude:
        return empty_result
    try:
        # Prompt cache: system prompt sabit (büyük), her çağrıda %10 maliyetle gelir
        user_content = json.dumps({
            "raw_text": (ocr_text or "")[:3500],
            "parsed": parsed or {},
        }, ensure_ascii=False)
        msg = _claude.messages.create(
            model=MODEL,
            max_tokens=600,
            system=[{
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }],
            messages=[{"role": "user", "content": user_content}],
        )
        raw = msg.content[0].text.strip() if msg.content else ""
        # JSON parse — markdown code fence olabilir
        if raw.startswith("```"):
            raw = raw.strip("`").strip()
            if raw.lower().startswith("json"):
                raw = raw[4:].strip()
        result = json.loads(raw)
        status = (result.get("status") or "ok").lower()
        if status not in ("ok", "warning", "error"):
            status = "ok"
        # tax_category validation
        tax_cat = result.get("tax_category")
        if tax_cat and not isinstance(tax_cat, str):
            tax_cat = None
        # absetzbar_pct validation
        pct = result.get("absetzbar_pct")
        try:
            pct = int(pct) if pct is not None else None
            if pct is not None and (pct < 0 or pct > 100):
                pct = None
        except (TypeError, ValueError):
            pct = None
        # bool validation
        vs = result.get("vorsteuer_abziehbar")
        vs = bool(vs) if vs is not None else None
        # list validation
        warn = result.get("tax_warnings") or []
        if not isinstance(warn, list):
            warn = []
        warn = [str(x)[:300] for x in warn[:5]]
        miss = result.get("missing_docs") or []
        if not isinstance(miss, list):
            miss = []
        miss = [str(x)[:300] for x in miss[:5]]
        return {
            "status": status,
            "notes": (result.get("notes") or "")[:500],
            "tax_category": tax_cat,
            "absetzbar_pct": pct,
            "vorsteuer_abziehbar": vs,
            "tax_warnings": warn,
            "missing_docs": miss,
        }
    except Exception:
        logger.exception("Claude analysis failed")
        return empty_result  # safe default — false-positive yerine sessiz geç


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "autotax-ai-reviewer",
        "claude_configured": bool(_claude),
        "secret_configured": bool(WEBHOOK_SECRET),
        "model": MODEL,
    }


@app.post("/review")
async def review(request: Request):
    """AutoTax'tan gelen tetik. Claude'a sor, callback'e yolla."""
    body = await request.body()
    sig = request.headers.get("X-Sig", "")
    if not _verify_signature(body, sig):
        logger.warning("Bad signature from %s", request.client.host if request.client else "?")
        raise HTTPException(status_code=403, detail="bad signature")

    try:
        data = json.loads(body)
    except Exception:
        raise HTTPException(status_code=400, detail="bad json")

    invoice_id = data.get("invoice_id")
    callback_url = data.get("callback_url")
    if not invoice_id or not callback_url:
        raise HTTPException(status_code=400, detail="invoice_id + callback_url required")

    # Claude analizi
    result = _ask_claude(
        ocr_text=data.get("ocr_text") or "",
        parsed=data.get("parsed") or {},
    )

    # Callback — Steuerlogik Engine v1: vergi alanlari dahil
    callback_payload = {
        "invoice_id": invoice_id,
        "status": result["status"],
        "notes": result["notes"],
        "tax_category": result.get("tax_category"),
        "absetzbar_pct": result.get("absetzbar_pct"),
        "vorsteuer_abziehbar": result.get("vorsteuer_abziehbar"),
        "tax_warnings": result.get("tax_warnings", []),
        "missing_docs": result.get("missing_docs", []),
    }
    callback_body = json.dumps(callback_payload).encode()
    callback_sig = _sign(callback_body)
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(
                callback_url,
                content=callback_body,
                headers={"X-Sig": callback_sig, "Content-Type": "application/json"},
            )
            if r.status_code >= 400:
                logger.warning("Callback %s: %s %s", callback_url, r.status_code, r.text[:200])
    except Exception:
        logger.exception("Callback to %s failed", callback_url)

    logger.info("Reviewed invoice %s: status=%s", invoice_id, result["status"])
    return {"ok": True, "status": result["status"]}
