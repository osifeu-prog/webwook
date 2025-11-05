import os
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from flask import Flask, request
import subprocess
import datetime

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
GIT_REPO_URL = os.getenv("GIT_REPO_URL")
GIT_BRANCH = os.getenv("GIT_BRANCH", "main")
GIT_USERNAME = os.getenv("GIT_USERNAME", "telegram-bot")
GIT_EMAIL = os.getenv("GIT_EMAIL", "bot@example.com")

app = Flask(__name__)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class GitBot:
    def __init__(self):
        self.repo_path = ".git_repo"
        self.setup_git_config()
        self.setup_repo()

    def setup_git_config(self):
        try:
            subprocess.run(["git", "config", "--global", "user.name", GIT_USERNAME], check=True)
            subprocess.run(["git", "config", "--global", "user.email", GIT_EMAIL], check=True)
            logger.info("Git configuration set successfully")
        except subprocess.CalledProcessError as e:
            logger.error(f"Error setting Git config: {e}")

    def setup_repo(self):
        try:
            if os.path.exists(self.repo_path):
                logger.info("Repository exists, pulling latest changes")
                subprocess.run(["git", "-C", self.repo_path, "pull"], check=True)
            elif GIT_REPO_URL:
                logger.info(f"Cloning repository from {GIT_REPO_URL}")
                subprocess.run(["git", "clone", GIT_REPO_URL, self.repo_path], check=True)
            else:
                raise ValueError("GIT_REPO_URL is not set")
        except Exception as e:
            logger.error(f"Error setting up repository: {e}")

    def commit_and_push(self, filename, content, commit_message):
        try:
            os.makedirs(os.path.dirname(os.path.join(self.repo_path, filename)), exist_ok=True)
            file_path = os.path.join(self.repo_path, filename)
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(content)

            subprocess.run(["git", "-C", self.repo_path, "add", filename], check=True)
            subprocess.run(["git", "-C", self.repo_path, "commit", "-m", commit_message], check=True)
            subprocess.run(["git", "-C", self.repo_path, "push", "origin", GIT_BRANCH], check=True)

            logger.info(f"Successfully pushed {filename} to Git")
            return True
        except Exception as e:
            logger.error(f"Error committing to Git: {e}")
            return False

git_bot = GitBot()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 שלום! אני הבוט שלך לשמירת הודעות ב־Git.\n"
        "שלח לי טקסט ואשמור אותו בקובץ.\n"
        "השתמש ב־/help כדי לראות פקודות נוספות."
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "📘 פקודות זמינות:\n"
        "/start — התחלת הבוט\n"
        "/help — עזרה\n"
        "/gitstatus — סטטוס הריפו\n"
        "שלח טקסט רגיל — יישמר כקובץ עם timestamp"
    )
    await update.message.reply_text(help_text)

async def git_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        result = subprocess.run(
            ["git", "-C", git_bot.repo_path, "log", "--oneline", "-5"],
            capture_output=True, text=True, check=True
        )
        await update.message.reply_text(f"📊 סטטוס ריפו:\n{result.stdout}")
    except Exception as e:
        await update.message.reply_text(f"❌ שגיאה: {e}")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text
    user = update.message.from_user
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"notes/note_{timestamp}.txt"
    commit_message = f"Add note from {user.first_name} at {timestamp}"

    file_content = (
        f"Note from {user.first_name} ({user.username or 'NA'})\n"
        f"Date: {datetime.datetime.now()}\n"
        f"User ID: {user.id}\n\n"
        f"Content:\n{user_text}"
    )

    success = git_bot.commit_and_push(filename, file_content, commit_message)
    if success:
        await update.message.reply_text(f"✅ נשמר בהצלחה!\n📁 {filename}")
    else:
        await update.message.reply_text("❌ שמירה נכשלה. נסה שוב.")

@app.route("/")
def index():
    return "🤖 Git Telegram Bot is running on Railway!"

@app.route("/health")
def health():
    return "✅ Bot is healthy"

@app.route(f"/{BOT_TOKEN}", methods=["POST"])
def webhook():
    if request.method == "POST":
        update = Update.de_json(request.get_json(), application.bot)
        application.update_queue.put(update)
    return "OK"

def main():
    global application
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("gitstatus", git_status))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    application.run_webhook(
        listen="0.0.0.0",
        port=int(os.getenv("PORT", 5000)),
        url_path=BOT_TOKEN,
        webhook_url=f"{WEBHOOK_URL}{BOT_TOKEN}",
        secret_token=os.getenv("SECRET_TOKEN")
    )

if __name__ == "__main__":
    main()
