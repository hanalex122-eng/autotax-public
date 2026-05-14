# Telegram Bot Kurulumu (Per-User Notifications)

Sprint 2B sonrası backend Telegram bot bind akışını tam destekliyor. Bu
rehber bot'u BotFather'da oluşturmak ve Railway env vars'ı doğru ayarlamak
içindir.

## 1. BotFather'da bot oluştur

1. Telegram'da `@BotFather` aç
2. `/newbot` yaz
3. Bot adı: `AutoTax Cloud Bot` (kullanıcıya görünür)
4. Bot username: `AutoTaxCloudBot` veya `autotax_cloud_bot` (sonu `bot`/`Bot` olmalı)
5. BotFather sana **token** verir: `1234567890:AAH...` (saklı tut, paylaşma)

## 2. Railway env vars

`autotax-public` service'ine git → Variables:

```
TELEGRAM_BOT_TOKEN       = 1234567890:AAH...   (BotFather'dan)
TELEGRAM_BOT_USERNAME    = AutoTaxCloudBot      (https://t.me/<bu> URL'i için)
TELEGRAM_WEBHOOK_SECRET  = <rastgele 32-64 char> (örn. openssl rand -hex 32)
TELEGRAM_CHAT_ID         = <admin chat id>      (opsiyonel — global fallback)
```

`TELEGRAM_TOKEN` (eski) varsa kalabilir; backend ikisini de okur.

## 3. Webhook'u Telegram'a kaydet

Backend deploy bittikten sonra bir defaya mahsus şu komutu çalıştır:

```bash
TOKEN="1234567890:AAH..."
SECRET="<rastgele secret>"
URL="https://autotax-public-production-3f2a.up.railway.app/telegram/webhook"

curl "https://api.telegram.org/bot$TOKEN/setWebhook" \
  -F "url=$URL" \
  -F "secret_token=$SECRET" \
  -F "allowed_updates=[\"message\"]"
```

Beklenen yanıt:
```json
{"ok": true, "result": true, "description": "Webhook was set"}
```

## 4. Test

1. AutoTax web → giriş yap
2. Profil ikonu → **Benachrichtigungen**
3. **Telegram-Bot verbinden** butonu
4. Yeni sekme açılır: `t.me/AutoTaxCloudBot?start=<token>`
5. Bot sayfasında **START** butonuna tıkla
6. Bot otomatik mesaj yollar: **Verbunden mit Konto your@email.com**
7. AutoTax sayfasında **F5** — artık "Verbunden" badge'i görünür

## 5. Bot komutları (Telegram tarafında)

| Komut | Etki |
|---|---|
| `/start <token>` | Hesabı bağla (deeplink ile tetiklenir) |
| `/stop` | Hesabı bağlamayı kaldır |
| `/status` | Bağlı mı, hangi email? |
| `/help` | Kısa rehber |

## 6. BotFather ipuçları

```
/setdescription      → "Get tax deadlines, dunning notices, ..."
/setabouttext        → kısa about
/setcommands         → menu'ye komutları ekle:
    start - Account verbinden (mit Token-Link)
    stop - Verbindung trennen
    status - Verbindungsstatus
    help - Hilfe
/setuserpic          → AutoTax logo (200x200 PNG)
```

## 7. Routing — kim hangi chat'i alır?

Backend `send_telegram(text, user_id, kind)` çağrısında:

1. **User-specific:** `User.telegram_chat_id` set + `telegram_notify_pref[kind] = True` → user'ın kendi chat'ine
2. **Webhook fallback:** `NOTIFY_WEBHOOK_URL` env varsa → uptime-bot benzeri proxy
3. **Global admin fallback:** `TELEGRAM_CHAT_ID` env → tüm admin uyarıları

Tüm gönderimler `sent_notifications` tablosuna kayıt → audit trail.

## 8. Sorun giderme

| Belirti | Sebep / Çözüm |
|---|---|
| Bot mesajları görmüyor | Webhook URL doğru mu? `curl https://api.telegram.org/bot$TOKEN/getWebhookInfo` |
| Token expired (15 dk) | Account → Telegram verbinden tekrar tıkla, yeni token |
| User bağlı görünmüyor ama mesaj gelmiyor | `SELECT telegram_chat_id, telegram_notify_pref FROM users WHERE id = X;` |
| BotFather diyor "Bot already exists" | username sonunu `_bot` ekle veya farklı isim |
| Webhook 403 | `TELEGRAM_WEBHOOK_SECRET` env Railway'de değil veya yanlış |
