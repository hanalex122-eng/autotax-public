# AutoTax AI Reviewer

Bağımsız mikroservis — AutoTax-Hub'tan webhook ile gelen fatura için
Claude'a "uyumsuzluk var mı?" diye sorar, sonucu callback ile geri
yollar. AutoTax kod tabanına hiç dokunmaz.

## Mimari

```
[AutoTax-Hub]
    │
    │ invoice oluştu
    │ POST /review (HMAC-imzalı)
    ▼
[Bu servis — autotax-ai-reviewer]
    │
    │ Claude API
    ▼
[Claude]
    │
    │ {status, notes}
    ▼
[Bu servis]
    │
    │ POST /webhooks/ai-review (HMAC-imzalı)
    ▼
[AutoTax-Hub]
    │
    │ Invoice.ai_status, ai_notes, ai_reviewed_at güncellenir
    │ → Frontend banner + Telegram notify (warning/error için)
```

## Faydaları

| | İnline AI (eski plan) | External (bu) |
|---|---|---|
| Kullanıcı bekleme | 5-7 sn | 0 sn |
| AI down olunca | Upload kırılır | AutoTax sorunsuz |
| AutoTax kod | Şişer | Temiz (3 kolon ekle) |
| Anthropic key | AutoTax env | İzole servis |
| Maliyet kontrolü | Karmaşık | Servisin kendi rate limit'i |

## Deploy adımları

### Seçenek A — Aynı Railway projesinde ayrı service

1. Railway → `tranquil-forgiveness` projesinde **+ New Service** → **Empty Service**
2. Service'i `autotax-ai-reviewer` adıyla kaydet
3. **Source** → **GitHub Repo** → `hanalex122-eng/autotax-public` seç
4. **Settings** → **Root Directory** → `services/ai-reviewer` yaz
5. Variables:
   ```
   ANTHROPIC_API_KEY    sk-ant-xxx
   WEBHOOK_SECRET       <openssl rand -hex 32 ile üret>
   MODEL                claude-sonnet-4-6   (opsiyonel)
   ```
6. Deploy bittikten sonra **Settings → Networking → Generate Domain**
7. Domain'i kopyala (örn. `autotax-ai-reviewer-abcd.up.railway.app`)

### Seçenek B — Ayrı GitHub repo (ileride)

`services/ai-reviewer/` klasörünü ayrı repo'ya kopyala, kendi
deploy'unu kur. Bu monorepo yaklaşımı şu an daha basit.

## AutoTax-Hub tarafı bağlantı

`tranquil-forgiveness` → `AutoTax-Hub` service'ine 2 env ekle:

```
AI_REVIEWER_WEBHOOK_URL    https://autotax-ai-reviewer-abcd.up.railway.app/review
AI_REVIEWER_SECRET         <yukarıdaki WEBHOOK_SECRET ile AYNI değer>
```

Bu env'ler set olunca AutoTax otomatik AI'a tetik gönderir; eklenene
kadar `_notify_ai_reviewer()` sessizce skip eder (AutoTax çalışmaya
devam eder).

## Endpoints

### GET /health
Servis durumu, Claude config check.

```json
{
  "status": "ok",
  "service": "autotax-ai-reviewer",
  "claude_configured": true,
  "secret_configured": true,
  "model": "claude-sonnet-4-6"
}
```

### POST /review
AutoTax'tan gelen tetik. Header: `X-Sig: <HMAC-SHA256(body)>`.

Body:
```json
{
  "invoice_id": 123,
  "user_id": 1,
  "callback_url": "https://autotax-public.../webhooks/ai-review",
  "ocr_text": "...",
  "parsed": {"vendor": "...", "total_amount": 19.0, ...}
}
```

İşlenince callback URL'e şu yapı yollanır:
```json
{"invoice_id": 123, "status": "ok|warning|error", "notes": "..."}
```

## Maliyet tahmin

- Railway smallest container: $5/ay
- Anthropic Claude Sonnet 4.6: input $3/1M token, output $15/1M token
  Tipik fatura: 800 in + 200 out ≈ $0.0054 per review
- Prompt cache (%10): ~$0.0006 per review cache hit sonrası

| Plan | Faturalar/ay | Claude maliyeti |
|---|---|---|
| Starter | 250 | $0.15 |
| Pro | 1500 | $0.90 |

Toplam $5-6/ay, gelir margin'i çok yüksek.

## Test

Local'de:

```bash
cd services/ai-reviewer
pip install -r requirements.txt
WEBHOOK_SECRET=test ANTHROPIC_API_KEY=xxx uvicorn main:app --reload --port 9000

# Sonra başka terminalde:
curl -X POST http://localhost:9000/review \
  -H "X-Sig: $(echo -n '{"invoice_id":1,"callback_url":"http://localhost:8080/x"}' | openssl dgst -sha256 -hmac test | awk '{print $2}')" \
  -H "Content-Type: application/json" \
  -d '{"invoice_id":1,"callback_url":"http://localhost:8080/x","ocr_text":"Test","parsed":{}}'
```

## Güvenlik

- Tüm istekler HMAC-SHA256 imzalı (X-Sig header)
- Secret 32+ byte, paylaşılan — replay attack için ileride timestamp +
  nonce eklenebilir
- Servis stateless, DB yok
- Anthropic key SADECE bu servisin env'inde; AutoTax sızsa bile etkilenmez

## Yarınki potansiyel iyileştirmeler

- [ ] Replay attack koruması (timestamp + nonce)
- [ ] Retry queue (Redis) failed callback'ler için
- [ ] Prompt example RAG (AutoTax'tan top-3 correction çekme)
- [ ] Multi-model fallback (Claude unavailable → OpenAI veya local)
- [ ] OCR confidence threshold parametresi (sadece <0.7 confidence'da çağır)
