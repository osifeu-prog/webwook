# Telegram Git Bot (Webhook) — Clean setup

מטרה: בוט טלגרם ששומר הודעות בריפו באמצעות webhook.

דרישות ב‑Railway (Settings → Variables):
- BOT_TOKEN
- WEBHOOK_URL (ה‑URL של השירות, כולל https ו‑/ בסוף)
- GIT_REPO_URL

אופציונליים:
- GIT_BRANCH (default: main)
- GIT_USERNAME
- GIT_EMAIL
- SECRET_TOKEN (מומלץ לאבטחה)

פריסה:
1. העתק את הקבצים לפרויקט.
2. העמס את משתני הסביבה ב‑Railway.
3. Redeploy.
4. Railway יריץ את השירות; ספריית git תתפס/תשוכפל ואחרי כן הודעות יישמרו וידחפו לריפו.

פקודות:
- /start
- /help
- /gitstatus
- שלח טקסט רגיל — יישמר כקובץ ב־notes/.
