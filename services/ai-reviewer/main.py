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

WICHTIG — JURISTISCH SICHERER TON:

Du gibst KEINE rechtsverbindliche Steueraussage. Du bist ein KI-Assistent.
Vermeide DEFINITIVE Aussagen wie "nicht absetzbar" oder "ist privat".

Verwende stattdessen konditionalen, vorsichtigen Ton:
  ✗ "nicht absetzbar"            → ✓ "wahrscheinlich privat veranlasst"
  ✗ "ist Bewirtung"               → ✓ "wirkt wie eine Bewirtungssituation"
  ✗ "muss aktiviert werden"       → ✓ "sollte ggf. aktiviert werden"
  ✗ "fehlt"                       → ✓ "scheint zu fehlen — bitte prüfen"

Begründe IMMER deine Einschätzung kurz: "Der Beleg enthält überwiegend
Lebensmittel, daher wirkt er privat".

═══════════════════════════════════════════════════════

ANTWORTE NUR ALS JSON (keine Markdown-Wrapper, kein Text außerhalb):

{
  "status": "ok" | "warning" | "error",
  "notes": "Kurze Hauptaussage (konditional), max 200 Zeichen",
  "tax_category": "Bewirtung" | "Geschenk" | "Miete" | "Homeoffice" | "KFZ" | "Reise" | "Lohn" | "Sozialabgaben" | "AfA" | "Buero" | "Versicherung" | "Software" | "Material" | "Andere",
  "absetzbar_pct": 0-100,
  "vorsteuer_abziehbar": true | false,
  "tax_warnings": ["Hinweis 1 (konditional)", "Hinweis 2"],
  "missing_docs": ["scheint zu fehlen: ..."],
  "ki_einschaetzung": "1 Satz konditionale Einschätzung (z.B. 'Wahrscheinlich privat veranlasst')",
  "grund": "1-2 Sätze Begründung — was im Beleg darauf hindeutet",
  "empfehlung": "1 Satz: was sollte der Nutzer tun (z.B. 'Falls betrieblich, Anlass dokumentieren')",
  "confidence": 0.0-1.0
}

REGELN:
- absetzbar_pct: Schätzung der steuerlich abzugsfähigen Summe
  (Bewirtung≈70, Geschenk>50€≈0, normal≈100)
- vorsteuer_abziehbar: nur false bei Kleinunternehmer-Rechnung oder klar Privat
- ki_einschaetzung: KONDITIONAL ("wahrscheinlich/vermutlich/möglicherweise")
- grund: WORAUS schließt du das? OCR-Inhalt, Vendor-Name, Betrag
- empfehlung: KONSTRUKTIV — was kann der Nutzer tun?
- confidence: Wie sicher bist du? <0.5 = unsicher, >0.85 = sehr sicher
- Wenn unklar → status=warning + niedrigeres confidence
- Wenn OCR/Parse-Inkonsistenz → status=error + notes erklärt es

Sei präzise, vorsichtig, hilfreich. Du sparst dem Nutzer Geld OHNE
juristische Falschaussage zu machen.
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
        "ki_einschaetzung": None, "grund": None,
        "empfehlung": None, "confidence": None,
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
        # Yeni 4-bolumlu yapi
        einsch = (result.get("ki_einschaetzung") or "")[:400] or None
        grund = (result.get("grund") or "")[:500] or None
        empfehlung = (result.get("empfehlung") or "")[:400] or None
        try:
            conf = float(result.get("confidence")) if result.get("confidence") is not None else None
            if conf is not None:
                conf = max(0.0, min(1.0, conf))
        except (TypeError, ValueError):
            conf = None
        return {
            "status": status,
            "notes": (result.get("notes") or "")[:500],
            "tax_category": tax_cat,
            "absetzbar_pct": pct,
            "vorsteuer_abziehbar": vs,
            "tax_warnings": warn,
            "missing_docs": miss,
            "ki_einschaetzung": einsch,
            "grund": grund,
            "empfehlung": empfehlung,
            "confidence": conf,
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

    # Callback — Steuerlogik Engine v2: 4-bolumlu yapilar dahil
    callback_payload = {
        "invoice_id": invoice_id,
        "status": result["status"],
        "notes": result["notes"],
        "tax_category": result.get("tax_category"),
        "absetzbar_pct": result.get("absetzbar_pct"),
        "vorsteuer_abziehbar": result.get("vorsteuer_abziehbar"),
        "tax_warnings": result.get("tax_warnings", []),
        "missing_docs": result.get("missing_docs", []),
        "ki_einschaetzung": result.get("ki_einschaetzung"),
        "grund": result.get("grund"),
        "empfehlung": result.get("empfehlung"),
        "confidence": result.get("confidence"),
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


ASK_SYSTEM_PROMPT = """\
Du bist ein deutscher Steuerberater-Assistent fur Kleinunternehmer und \
Selbststandige. Beantworte konkrete Fragen zur Absetzbarkeit, USt-Behandlung, \
zur EuR-Erfassung kurz, prazise und mit Paragraf-Referenz wo moglich \
(z.B. §4 Abs.5 Nr.2 EStG, §15 UStG).

Stil:
- Maximal 4-6 Satze
- Falls die Frage unklar ist: nachfrage
- Bei Streitfallen: konservative Haltung empfehlen
- Bei klar abzugsfahigen Posten: kurz bestatigen + Hinweis auf Pflicht-Belege
- IMMER ein Disclaimer am Ende: "Hinweis: Dies ist keine Steuerberatung. \
Bei rechtsverbindlichen Fragen bitte Steuerberater konsultieren."
"""


VISION_SYSTEM_PROMPT = """\
You are an expert at extracting structured data from German invoices and \
receipts. You will receive an image (PDF page or photo). Read it carefully \
and extract the following fields. Return ONLY a JSON object, no explanation.

REQUIRED FIELDS:
{
  "vendor": "Firma name (exact, as printed)",
  "total_amount": 0.00,           // Brutto total in EUR (the final paid amount)
  "vat_amount": 0.00,             // USt amount in EUR
  "vat_rate": "19%" | "7%" | "0%",
  "date": "YYYY-MM-DD",           // invoice date
  "invoice_number": "string or null",
  "vendor_address": "string or null",
  "vendor_email": "string or null",
  "vendor_phone": "string or null",
  "vendor_iban": "string or null",
  "currency": "EUR",
  "confidence": 0.0-1.0,          // how sure you are
  "is_german": true,
  "notes": "Any uncertainty or notable detail"
}

RULES:
- "total_amount" is the GROSS (Brutto), what was actually paid. Look for "Gesamt", "Summe", "Zu zahlen", "Total", "Endsumme"
- Parse German number format: "1.234,56" = 1234.56 (period=thousands, comma=decimal)
- Parse "19,00 €" or "EUR 19,00" -> 19.00
- If multiple totals appear, take the highest (final after VAT) labeled "Gesamt"/"Brutto"/"Endbetrag"
- Date: convert "27.03.2026" -> "2026-03-27"
- If field is genuinely missing, use null (not empty string)
- Be VERY careful with decimal — €3,77 is THREE euros, not 377
- confidence: 1.0=perfect read, 0.7=mostly clear, 0.4=blurry/unclear

Return JSON only, no markdown, no explanation."""


@app.post("/vision-reocr")
async def vision_reocr(request: Request):
    """PDF veya image base64 alir, Claude Vision ile gercek degerleri okur.
    OCR'in basarisiz oldugu (total=0, garbage text) faturalarda kullanilir.
    """
    body = await request.body()
    sig = request.headers.get("X-Sig", "")
    if not _verify_signature(body, sig):
        raise HTTPException(status_code=403, detail="bad signature")
    try:
        data = json.loads(body)
    except Exception:
        raise HTTPException(status_code=400, detail="bad json")

    image_b64 = data.get("image_b64") or ""
    media_type = data.get("media_type") or "image/jpeg"
    if not image_b64:
        raise HTTPException(status_code=400, detail="image_b64 required")
    if not _claude:
        raise HTTPException(status_code=503, detail="claude not configured")

    # Claude vision messages format
    try:
        msg = _claude.messages.create(
            model=MODEL,
            max_tokens=1000,
            system=VISION_SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": image_b64,
                        },
                    },
                    {
                        "type": "text",
                        "text": "Extract all invoice fields from this image. Return JSON only.",
                    },
                ],
            }],
        )
        raw = msg.content[0].text.strip() if msg.content else "{}"
        # Markdown code fence temizle
        if raw.startswith("```"):
            raw = raw.strip("`").strip()
            if raw.lower().startswith("json"):
                raw = raw[4:].strip()
        result = json.loads(raw)
        return {"ok": True, "model": MODEL, "data": result}
    except json.JSONDecodeError as e:
        logger.exception("Vision JSON parse failed")
        raise HTTPException(status_code=502, detail=f"AI returned invalid JSON: {e}")
    except Exception as e:
        logger.exception("Vision re-OCR failed")
        raise HTTPException(status_code=500, detail=f"AI error: {e}")


@app.post("/ask")
async def ask(request: Request):
    """Kullaniciden gelen serbest soru — 'Bu gider dusulur mu?' tarzi."""
    body = await request.body()
    sig = request.headers.get("X-Sig", "")
    if not _verify_signature(body, sig):
        raise HTTPException(status_code=403, detail="bad signature")
    try:
        data = json.loads(body)
    except Exception:
        raise HTTPException(status_code=400, detail="bad json")

    question = (data.get("question") or "").strip()[:1000]
    context = (data.get("context") or "").strip()[:2000]
    if not question:
        raise HTTPException(status_code=400, detail="question required")
    if not _claude:
        raise HTTPException(status_code=503, detail="claude not configured")

    user_msg = f"Frage: {question}"
    if context:
        user_msg += f"\n\nKontext: {context}"

    try:
        msg = _claude.messages.create(
            model=MODEL,
            max_tokens=600,
            system=[{
                "type": "text",
                "text": ASK_SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }],
            messages=[{"role": "user", "content": user_msg}],
        )
        answer = msg.content[0].text.strip() if msg.content else ""
        return {"answer": answer, "model": MODEL}
    except Exception:
        logger.exception("ask failed")
        raise HTTPException(status_code=500, detail="ai error")
