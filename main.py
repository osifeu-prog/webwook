import os
import logging
import subprocess
import datetime
from flask import Flask, request
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# --- קריאה למשתני סביבה שהוגדרו ב-Railway ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
GIT_REPO_URL = os.getenv("GIT_REPO_URL")
GIT_BRANCH = os.getenv("GIT_BRANCH", "main")
GIT_USERNAME = os.getenv("GIT_USERNAME", "telegram-bot")
GIT_EMAIL = os.getenv("GIT_EMAIL", "bot@example.com")
PORT = int(os.getenv("PORT", 5000))

# --- מזהה משתמש מורשה בלבד ---
AUTHORIZED_USER_ID = 224223270

# --- בדיקה בסיסית ---
if not BOT_TOKEN or not WEBHOOK_URL or not GIT_REPO_URL:
    raise SystemExit("❌ Missing required environment variables. Please check BOT_TOKEN, WEBHOOK_URL, GIT_REPO_URL.")

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
                run(["git", "-C", self.repo_path, "pull"], check=True)
                logger.info("Pulled latest changes")
                return
            except subprocess.CalledProcessError:
                logger.warning("Pull failed")
        try:
            run(["git", "clone", self.repo_url, self.repo_path], check=True)
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
    return user_id == AUTHORIZED_USER_ID

# --- פקודות טלגרם ---
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        return
    await update.message.reply_text("👋 שלום! שלח לי טקסט ואשמור אותו בריפו. /help לעזרה.")

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        return
    await update.message.reply_text("/start, /help, /gitstatus — שלח טקסט לשמירה כקובץ.")

async def git_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        return
    commits = git.last_commits(5)
    if not commits:
        await update.message.reply_text("ℹ️ אין קומיטים או שהריפו לא מוכן.")
    else:
        await update.message.reply_text("📊 קומיטים אחרונים:\n" + commits)

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        return
    user = update.message.from_user
    text = update.message.text or ""
    ts = datetime.datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = f"notes/note_{ts}.txt"
    commit_message = f"note from {user.username or user.first_name or user.id} at {ts}Z"
    content = (
        f"From: {user.first_name} ({user.username or 'NA'})\n"
        f"User ID: {user.id}\n"
        f"UTC: {datetime.datetime.utcnow().isoformat()}\n\n"
        f"{text}\n"
    )
    ok = git.commit_and_push(filename, content, commit_message)
    if ok:
        await update.message.reply_text(f"✅ נשמר: {filename}")
    else:
        await update.message.reply_text("❌ שגיאה בשמירה. בדוק לוגים.")

# --- Flask endpoints ---
@app.route("/", methods=["GET"])
def index():
    return "OK"

@app.route("/health", methods=["GET"])
def health():
    return "healthy"

# --- הפעלת הבוט עם webhook ---
def main():
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start_cmd))
    application.add_handler(CommandHandler("help", help_cmd))
    application.add_handler(CommandHandler("gitstatus", git_status))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    webhook_path = BOT_TOKEN
    if not WEBHOOK_URL.endswith("/"):
        webhook_url = WEBHOOK_URL + webhook_path
    else:
        webhook_url = WEBHOOK_URL + webhook_path

    logger.info("Setting webhook to %s", webhook_url)
    application.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=webhook_path,
        webhook_url=webhook_url
    )

if __name__ == "__main__":
    main()
