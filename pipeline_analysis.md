# OCR PIPELINE ANALYSIS — AutoTax-Cloud

> Son güncelleme: 2026-06-11 · REPAIR MODE Phase 1.
> Endpoint: `POST /invoices/upload` → `upload_invoice()` (`autotax/main.py:8022`).
> Enstrümantasyon: `autotax/profiling.py` `PipelineTimer` + `_pt.mark(...)` çağrıları (CANLI).

---

## Hat akışı (kaynak önceliği: Tesseract → PDF-text → OCR.space → QR-only)

```
[upload_read]      content = await file.read()              main.py:8028
   │  (ZIP ise ayrı batch yol — main.py:8035-8084)
   │  (hard-duplicate md5 kontrol — main.py:8093)
[ocr_tesseract]    image ise local_ocr_tesseract(content)   main.py:8127  (ocr.py:753)
   │               + valid ise QR (extract_qr_data)          main.py:8135
[pdf_text]         PDF ise extract_pdf_text(content)         main.py:8150  (pdfplumber)
   │               + QR                                       main.py:8157
[ocr_fallback_qr]  ikisi de yoksa extract_text_and_qr (OCR.space, 45s timeout) main.py:8165
   │               + QR-only fallback                         main.py:8175
   │  (learning rules — main.py:8187)
[parser]           parse_invoice(raw_text)                   main.py:8195  (parser.py:2421)
   │  (vendor identity match, soft-duplicate, save_invoice,
   │   auto_create_cash_entry, auto-income, audit, ai_reviewer)
[identity_db_post] yukarıdaki DB+post bloğu                  main.py:8215-8660
   │
[finish]           _pt.finish() → response._timings           main.py:return
```

## Mark etiketleri (gerçek ms bunlara düşer)
| Mark | Kapsam | Beklenen darboğaz |
|---|---|---|
| `upload_read` | dosya belleğe okuma | düşük |
| `ocr_tesseract` | Tesseract (≤4 tur) + QR | **YÜKSEK** (downscale yok, P0-3) |
| `pdf_text` | pdfplumber metin katmanı | orta (büyük PDF) |
| `ocr_fallback_qr` | OCR.space (≤3 ağ çağrısı) + QR-only | **YÜKSEK** (zayıf Tesseract'ta, P1-2) |
| `parser` | regex/heuristik (~15 alt-extractor) | düşük-orta |
| `identity_db_post` | vendor match + 5 DB session + audit + ai-reviewer | orta |

## Bilinen mimari sorunlar (PERFORMANCE_AUDIT ile bağ)
- **P0-2:** Tüm bu hat `async def` içinde **bloklayıcı** → event-loop'u dondurur.
- **P0-3:** `ocr_tesseract` ana yolda downscale yok (`ocr.py:789`).
- **P1-2:** `ocr_fallback_qr` 3 ardışık 30s OCR.space çağrısı (`ocr.py:264/274/283`).
- **P1-3:** QR upload başına 3× (`main.py:8135/8157/8175`).

## Nasıl okunur
1. Bir fiş yükle → yanıt JSON'unda **`_timings`** alanı gelir: `{total_ms, stages:{...}}`.
2. Railway log: `[PIPE] upload_invoice total=... {upload_read:.., ocr_tesseract:..}`.
3. Toplu: `GET /admin/perf` → `recent_pipelines` + `pipeline_aggregates` (p50/p95/max).

## Hedef
**OCR sonucu kullanıcıya < 15 sn** (PHASE 2). Önce bu mark'larla hangi aşamanın baskın olduğunu **ölç**, sonra o aşamayı düzelt (büyük ihtimal `ocr_tesseract` downscale + threadpool).
