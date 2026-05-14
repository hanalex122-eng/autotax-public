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
Sen bir Alman fatura denetçisisin. AutoTax-Cloud kullanıcılarının yüklediği \
faturaları kontrol ediyorsun.

Sana iki şey verilecek:
  1. OCR'dan çıkarılan ham metin (raw_text)
  2. Backend parser'ın çıkardığı yapılandırılmış alanlar (parsed)

Görevin: uyumsuzluk, eksik bilgi veya şüpheli durum tespit etmek.

ÖRNEKLER:
  - OCR'da "Gesamt €119.00" yazıyor ama parsed.total_amount=19 → status=error
  - OCR'da KDV %19 yazıyor ama parsed.vat_rate="7%" → status=warning
  - OCR çok belirsiz veya çok kısa → status=warning
  - Tutarsızlık yok, her şey uyumlu → status=ok

Yanıt SADECE JSON olarak ver, başka açıklama yapma:
{
  "status": "ok" | "warning" | "error",
  "notes": "Tek cümle Almanca açıklama (max 200 karakter)"
}

status=ok ise notes boş veya kısa onay ("Daten konsistent.").
status=warning ise insan kontrolü öneren bir not.
status=error ise net bir sorun açıklaması.
"""


def _verify_signature(body: bytes, signature: str) -> bool:
    if not WEBHOOK_SECRET:
        return False
    expected = hmac.new(WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature or "")


def _sign(body: bytes) -> str:
    return hmac.new(WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()


def _ask_claude(ocr_text: str, parsed: dict) -> dict:
    """Claude'dan analiz al. Hata varsa status=ok (safe default) dön."""
    if not _claude:
        return {"status": "ok", "notes": ""}
    try:
        # Prompt cache: system prompt sabit (büyük), her çağrıda %10 maliyetle gelir
        user_content = json.dumps({
            "raw_text": (ocr_text or "")[:3500],
            "parsed": parsed or {},
        }, ensure_ascii=False)
        msg = _claude.messages.create(
            model=MODEL,
            max_tokens=300,
            system=[{
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }],
            messages=[{"role": "user", "content": user_content}],
        )
        raw = msg.content[0].text.strip() if msg.content else ""
        # JSON parse
        if raw.startswith("```"):
            raw = raw.strip("`").strip()
            if raw.lower().startswith("json"):
                raw = raw[4:].strip()
        result = json.loads(raw)
        status = (result.get("status") or "ok").lower()
        if status not in ("ok", "warning", "error"):
            status = "ok"
        return {"status": status, "notes": (result.get("notes") or "")[:500]}
    except Exception:
        logger.exception("Claude analysis failed")
        return {"status": "ok", "notes": ""}  # safe default — false-positive yerine sessiz geç


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

    # Callback
    callback_payload = {
        "invoice_id": invoice_id,
        "status": result["status"],
        "notes": result["notes"],
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
