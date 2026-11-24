# Kubota Radar
Monitor for Kubota U10-3 en K008-3 op 2dehands en Marktplaats.

## Telegram instellen
1. Maak een bot via Telegram @BotFather.
2. Start de bot in Telegram.
3. Zoek je chat-ID.
4. GitHub repository → Settings → Secrets and variables → Actions.
5. Maak secrets `TELEGRAM_BOT_TOKEN` en `TELEGRAM_CHAT_ID`.

## Start
Actions → Kubota Radar → Run workflow.
De eerste run registreert links zonder berichten te sturen. Daarna worden nieuwe links gemeld.

RSS: https://raw.githubusercontent.com/ps2list/kubota-radar/main/feed.xml

Websites kunnen HTML of toegangsregels aanpassen; volledigheid en exacte timings zijn niet gegarandeerd. Deze monitor omzeilt geen CAPTCHA/login.
