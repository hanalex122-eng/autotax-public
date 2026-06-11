# PERFORMANCE LOGS — AutoTax-Cloud

> Son güncelleme: 2026-06-11 · REPAIR MODE Phase 1.
> Bu dosya **gerçek ölçüm çıktıları** içindir. Enstrümantasyon CANLI; aşağıdaki tablolar gerçek trafikten doldurulacak.

---

## Enstrümantasyon nasıl çalışıyor (kanıt kaynağı)
| Sinyal | Nereden | Log prefix'i |
|---|---|---|
| Her HTTP isteğinin toplam süresi | `_perf_timing_mw` middleware (`main.py`) | `[TIMING] METHOD path -> status Xms` |
| OCR pipeline aşamaları | `PipelineTimer` (`profiling.py`) | `[PIPE] upload_invoice total=Xms {stages}` |
| Yavaş DB sorguları (>200ms) | SQLAlchemy event (`setup_db_profiling`) | `[SLOWQ] Xms <sql>` |
| Frontend ilk render | `index.html` (boot→render) | console `[TIMING] frontend first render Xms` |

## Sayıları görmenin 3 yolu
1. **Yanıt içinde:** Fiş yükle → JSON'da `_timings: {total_ms, stages}`.
2. **Admin uç (Railway log'u gerekmez):**
   `curl -s https://autotax.cloud/admin/perf -H "Authorization: Bearer <ADMIN_TOKEN>" | python -m json.tool`
   → `slowest_endpoints` (p50/p95/max), `pipeline_aggregates`, `recent_pipelines`, `slow_queries`.
3. **Railway logs:** `[TIMING]` / `[PIPE]` / `[SLOWQ]` greple.

## Eşikler
- Yavaş istek: **> 1000 ms** (WARNING'e yükselir)
- Yavaş sorgu: **> 200 ms** (kaydedilir)

---

## ÖLÇÜM SONUÇLARI (gerçek trafikle doldurulacak)

### A. Frontend ilk render (boot→mount, Babel dahil)
| Ortam | firstRenderMs | Tarih |
|---|---|---|
| _(DevTools console `window.__perf` veya `[TIMING] frontend first render`)_ | … | … |

### B. OCR pipeline (upload_invoice) — gerçek aşama ms
| Tarih | Dosya tipi | upload_read | ocr_tesseract | pdf_text | ocr_fallback_qr | parser | identity_db_post | **TOTAL** |
|---|---|---|---|---|---|---|---|---|
| … | jpg 4MP | … | … | … | … | … | … | … |
| … | pdf | … | … | … | … | … | … | … |

> Hedef: TOTAL < 15.000 ms (PHASE 2).

### C. En yavaş endpoint'ler (GET /admin/perf → slowest_endpoints)
| method | path | count | p50 | p95 | max |
|---|---|---|---|---|---|
| … | … | … | … | … | … |

### D. Yavaş sorgular (>200ms)
| ms | sql (kısalt) | not |
|---|---|---|
| … | … | … |

---

## Ölçüm prosedürü (tekrarlanabilir)
1. Deploy sonrası 5-10 gerçek fiş yükle (farklı tip: net foto, bulanık foto, PDF, QR'lı).
2. `GET /admin/perf` çek → B/C/D tablolarını doldur.
3. Frontend: uygulamayı aç, DevTools console'da `window.__perf.firstRenderMs` → A tablosu.
4. En baskın aşamayı işaretle → `slow_functions.md` ve `PERFORMANCE_AUDIT.md`'yi güncelle.
5. PHASE 2: o aşamayı düzelt, tekrar ölç, **önce/sonra** kaydet.
