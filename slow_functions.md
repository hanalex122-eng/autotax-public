# SLOW FUNCTIONS — AutoTax-Cloud

> Son güncelleme: 2026-06-11 · REPAIR MODE Phase 1.
> Aşağıdaki "En Yavaş 10" listesi **kod incelemesinden** (file:line) çıktı.
> Gerçek ms sütunu CANLI enstrümantasyondan (`/admin/perf`, `[TIMING]`, `[SLOWQ]`) doldurulacak.
> Etiketler: **P0 Kritik · P1 Yüksek · P2 Orta**

---

## EN YAVAŞ 10 FONKSİYON (en kötü → en iyi)

| # | Fonksiyon | file:line | Neden yavaş (kanıt) | Öncelik | Gerçek ms (ölçülecek) |
|---|---|---|---|---|---|
| 1 | `extract_text_and_qr` | `ocr.py:340` (blok: `378/386/601`) | async içinde sync pdfplumber + PIL/numpy + pytesseract subprocess | **P0** | … |
| 2 | `upload_invoice` | `main.py:8022` | tüm OCR+parse+DB sync, event-loop blokluyor | **P0** | … (`[PIPE]`) |
| 3 | `local_ocr_tesseract` | `ocr.py:753` | downscale yok, ≤4 tur, bloklayıcı subprocess | **P0** | … (mark `ocr_tesseract`) |
| 4 | `email_invoices_bulk` | `main.py:4343` | async içinde döngüde sync reportlab PDF | P1 | … |
| 5 | `list_vault` (`/vault`) | `main.py:11826` | TÜM invoice + `file_data` BLOB, limit yok | **P0** | … |
| 6 | `calculate_dashboard_metrics` | `main.py:4937` | TÜM invoice Python'da toplanıyor | P1 | … |
| 7 | `chat_endpoint` (`/chat`) | `main.py:12399` | her mesajda TÜM invoice + raw_text | P1 | … |
| 8 | `invoice_summary` (`/invoices/summary`) | `main.py:8874` | dashboard ile aynı tam-tablo hesabı tekrar | P1 | … |
| 9 | `sync_invoices_to_bookkeeping` | `main.py:9939` | O(invoice×entry) Python eşleştirme | P2 | … |
| 10 | `admin_list_users` | `main.py:2394` | N+1 (kullanıcı başına count+all) | P2 | … |

---

## OCR.space ve QR (alt-fonksiyon darboğazları)
| Fonksiyon | file:line | Sorun | Öncelik |
|---|---|---|---|
| OCR.space çağrıları | `ocr.py:264/274/283` | 3 ardışık 30s ağ çağrısı | P1 |
| `decode_qr_from_image` | `qr_reader.py:23/39/52` | upload başına 3×, çift pyzbar geçişi | P1 |

---

## Doldurma talimatı
1. `/admin/perf` → `slowest_endpoints` p95 ile #2/#4/#5/#6/#7/#8/#10 gerçek ms'lerini yaz.
2. `recent_pipelines` → #1/#3 (OCR aşamaları) ms'lerini yaz.
3. `slow_queries` → #5/#6/#7 arkasındaki SQL sürelerini yaz.
4. Ölçüm sonrası bu listeyi **gerçek ms'e göre yeniden sırala** — kod tahmini ≠ gerçek; kanıt kazanır.
