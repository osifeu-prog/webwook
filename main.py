import os
import logging
import subprocess
import datetime
from flask import Flask, request
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# --- קריאה למשתני סביבה שהוגדרו ב-Railway ---
BOT_TOKEN = os.getenv("TELEGRAM_TOKEN") or os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
GIT_REPO_URL = os.getenv("GIT_REPO_URL")
GIT_BRANCH = os.getenv("GIT_BRANCH", "main")
GIT_USERNAME = os.getenv("GIT_USERNAME", "telegram-bot")
GIT_EMAIL = os.getenv("GIT_EMAIL", "bot@example.com")
PORT = int(os.getenv("PORT", 8080))  # Railway uses 8080

# --- רשימת משתמשים מורשים (הוסף את ה-ID שלך ושל תלמידיך) ---
AUTHORIZED_USER_IDS = [int(x.strip()) for x in os.getenv("AUTHORIZED_USER_IDS", "224223270").split(",") if x.strip()]

# --- בדיקה בסיסית ---
if not BOT_TOKEN:
    raise SystemExit("❌ Missing required environment variable: BOT_TOKEN or TELEGRAM_TOKEN.")
if not WEBHOOK_URL:
    raise SystemExit("❌ Missing required environment variable: WEBHOOK_URL.")
if not GIT_REPO_URL:
    raise SystemExit("❌ Missing required environment variable: GIT_REPO_URL.")

# --- לוגים ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# --- Flask עבור Railway ---
app = Flask(__name__)

def run(cmd, **kwargs):
    logger.debug("RUN: %s", " ".join(cmd))
    return subprocess.run(cmd, **kwargs)

class GitHandler:
    def __init__(self, repo_url, repo_path=".git_repo"):
        self.repo_url = repo_url
        self.repo_path = repo_path
        self.branch = GIT_BRANCH
        self._configure_git()
        self._prepare_repo()

    def _configure_git(self):
        try:
            run(["git", "config", "--global", "user.name", GIT_USERNAME], check=True)
            run(["git", "config", "--global", "user.email", GIT_EMAIL], check=True)
            logger.info("Git configured: %s <%s>", GIT_USERNAME, GIT_EMAIL)
        except subprocess.CalledProcessError as e:
            logger.warning("Git config failed: %s", e)

    def _prepare_repo(self):
        if os.path.isdir(os.path.join(self.repo_path, ".git")):
            try:
                run(["git", "-C", self.repo_path, "pull", "origin", self.branch], check=True)
                logger.info("Pulled latest changes")
                return
            except subprocess.CalledProcessError as e:
                logger.warning("Pull failed: %s", e)
        try:
            run(["git", "clone", "-b", self.branch, self.repo_url, self.repo_path], check=True)
            logger.info("Cloned repository")
        except subprocess.CalledProcessError as e:
            logger.error("Clone failed: %s", e)

    def repo_ready(self):
        return os.path.isdir(os.path.join(self.repo_path, ".git"))

    def last_commits(self, n=5):
        if not self.repo_ready():
            return None
        try:
            res = run(["git", "-C", self.repo_path, "log", "--oneline", f"-{n}"], capture_output=True, text=True, check=True)
            return res.stdout.strip()
        except subprocess.CalledProcessError:
            return None

    def commit_and_push(self, filename, content, message):
        if not self.repo_ready():
            return False
        abs_path = os.path.join(self.repo_path, filename)
        try:
            os.makedirs(os.path.dirname(abs_path), exist_ok=True)
            with open(abs_path, "w", encoding="utf-8") as f:
                f.write(content)
            run(["git", "-C", self.repo_path, "add", filename], check=True)
            status = run(["git", "-C", self.repo_path, "status", "--porcelain"], capture_output=True, text=True)
            if status.stdout.strip() == "":
                return True
            run(["git", "-C", self.repo_path, "commit", "-m", message], check=True)
            run(["git", "-C", self.repo_path, "push", "origin", self.branch], check=True)
            return True
        except Exception as e:
            logger.error("Git operation failed: %s", e)
            return False

git = GitHandler(GIT_REPO_URL)

# --- בדיקת הרשאה ---
def is_authorized(user_id):
    return user_id in AUTHORIZED_USER_IDS

# --- פקודות טלגרם ---
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        await update.message.reply_text("❌ אין לך הרשאה להשתמש בבוט זה.")
        return
    await update.message.reply_text(
        "👋 שלום! אני בוט הלימוד שלך.\n\n"
        "פקודות זמינות:\n"
        "/start - הודעה זו\n"
        "/help - עזרה\n"
        "/gitstatus - מצב הריפו\n"
        "/myfolder - פתיחת תיקיה אישית\n\n"
        "שלח טקסט רגיל ואשמור אותו בתיקיה האישית שלך."
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        return
    await update.message.reply_text(
        "📖 עזרה:\n\n"
        "• שלח טקסט רגיל - יישמר בתיקיה האישית שלך\n"
        "• /gitstatus - מציג את הקומיטים האחרונים\n"
        "• /myfolder - פותח תיקיה אישית חדשה\n"
        "• כל השינויים נשמרים אוטומטית ב-Git"
    )

async def git_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        return
    commits = git.last_commits(5)
    if not commits:
        await update.message.reply_text("ℹ️ אין קומיטים או שהריפו לא מוכן.")
    else:
        await update.message.reply_text("📊 קומיטים אחרונים:\n" + commits)

async def myfolder_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        return
    
    user = update.effective_user
    user_folder = f"students/{user.id}"
    welcome_file = f"{user_folder}/welcome.txt"
    
    welcome_content = f"""ברוך הבא לתיקיה האישית שלך!

מידע תלמיד:
• שם: {user.first_name} {user.last_name or ''}
• שם משתמש: @{user.username or 'לא צוין'}
• ID: {user.id}
• תאריך יצירה: {datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}

בתיקיה זו תוכל לשמור:
• תרגילים
• שאלות
• פרויקטים
• סיכומים

שלח טקסט רגיל ואשמור אותו כאן!
"""
    
    ok = git.commit_and_push(welcome_file, welcome_content, f"Create personal folder for {user.first_name} ({user.id})")
    if ok:
        await update.message.reply_text(f"✅ תיקיה אישית נוצרה: {user_folder}/\n\nכעת תוכל לשלוח טקסט ואשמור אותו בתיקיה שלך.")
    else:
        await update.message.reply_text("❌ שגיאה ביצירת תיקיה אישית. בדוק לוגים.")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        return
    
    user = update.effective_user
    text = update.message.text or ""
    
    if not text.strip():
        await update.message.reply_text("❌ אנא שלח טקסט לשמירה.")
        return
    
    # יצירת תיקיית student אם לא קיימת
    user_folder = f"students/{user.id}"
    ts = datetime.datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = f"{user_folder}/note_{ts}.txt"
    
    content = f"""מידע תלמיד:
• שם: {user.first_name} {user.last_name or ''}
• שם משתמש: @{user.username or 'לא צוין'}
• ID: {user.id}
• תאריך: {datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}

תוכן:
{text}
"""
    
    commit_message = f"Note from {user.first_name} ({user.id}) at {ts}"
    ok = git.commit_and_push(filename, content, commit_message)
    
    if ok:
        await update.message.reply_text(f"✅ נשמר בהצלחה!\n📁 תיקיה: {user_folder}/\n📄 קובץ: note_{ts}.txt")
    else:
        await update.message.reply_text("❌ שגיאה בשמירה. בדוק לוגים.")

# --- Flask endpoints ---
@app.route("/", methods=["GET"])
def index():
    return "🚀 Telegram Git Bot is running!"

@app.route("/health", methods=["GET"])
def health():
    return "✅ Healthy"

@app.route("/webhook/" + (BOT_TOKEN or ""), methods=["POST"])
def webhook():
    if BOT_TOKEN:
        application = Application.builder().token(BOT_TOKEN).build()
        update = Update.de_json(request.get_json(), application.bot)
        application.process_update(update)
    return "OK"

# --- הפעלת הבוט עם webhook ---
def main():
    application = Application.builder().token(BOT_TOKEN).build()
    
    # הוספת handlers
    application.add_handler(CommandHandler("start", start_cmd))
    application.add_handler(CommandHandler("help", help_cmd))
    application.add_handler(CommandHandler("gitstatus", git_status))
    application.add_handler(CommandHandler("myfolder", myfolder_cmd))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    # הגדרת webhook
    webhook_path = f"/webhook/{BOT_TOKEN}"
    webhook_url = f"{WEBHOOK_URL.rstrip('/')}{webhook_path}"
    
    logger.info("Setting webhook to: %s", webhook_url)
    
    try:
        application.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=webhook_path,
            webhook_url=webhook_url,
            secret_token=os.getenv("SECRET_TOKEN")
        )
        logger.info("Bot started successfully with webhook")
    except Exception as e:
        logger.error("Failed to start bot: %s", e)
        raise

if __name__ == "__main__":
    main()
