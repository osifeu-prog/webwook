import os
import sys
import logging
import subprocess
import datetime
from flask import Flask, request
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# Environment
BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # must end with '/'
GIT_REPO_URL = os.getenv("GIT_REPO_URL")
GIT_BRANCH = os.getenv("GIT_BRANCH", "main")
GIT_USERNAME = os.getenv("GIT_USERNAME", "telegram-bot")
GIT_EMAIL = os.getenv("GIT_EMAIL", "bot@example.com")
SECRET_TOKEN = os.getenv("SECRET_TOKEN")  # optional
PORT = int(os.getenv("PORT", 5000))

# Minimal required env check
missing = [name for name, val in (("BOT_TOKEN", BOT_TOKEN), ("WEBHOOK_URL", WEBHOOK_URL), ("GIT_REPO_URL", GIT_REPO_URL)) if not val]
if missing:
    print("Missing environment variables:", ", ".join(missing), file=sys.stderr)
    sys.exit(1)

if not WEBHOOK_URL.endswith("/"):
    WEBHOOK_URL += "/"

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

flask_app = Flask(__name__)

class GitHandler:
    def __init__(self, repo_url, repo_path=".git_repo"):
        self.repo_url = repo_url
        self.repo_path = repo_path
        self.branch = GIT_BRANCH
        self._configure_git()
        self._ensure_repo()

    def _run(self, *args, capture_output=False, text=False, check=False):
        kwargs = {}
        if capture_output:
            kwargs["capture_output"] = True
        if text:
            kwargs["text"] = True
        if check:
            kwargs["check"] = True
        return subprocess.run(list(args), **kwargs)

    def _configure_git(self):
        try:
            self._run("git", "config", "--global", "user.name", GIT_USERNAME, check=True)
            self._run("git", "config", "--global", "user.email", GIT_EMAIL, check=True)
            logger.info("Git configured: %s <%s>", GIT_USERNAME, GIT_EMAIL)
        except subprocess.CalledProcessError as e:
            logger.warning("Could not set git config: %s", e)

    def _ensure_repo(self):
        try:
            if os.path.exists(self.repo_path):
                logger.info("Repo exists, pulling latest")
                self._run("git", "-C", self.repo_path, "pull", check=True)
            else:
                logger.info("Cloning repo %s", self.repo_url)
                self._run("git", "clone", self.repo_url, self.repo_path, check=True)
        except subprocess.CalledProcessError as e:
            logger.error("Git repo setup failed: %s", e)

    def repo_ready(self):
        # check if the path exists and is a git repo
        if not os.path.exists(self.repo_path):
            return False
        try:
            res = self._run("git", "-C", self.repo_path, "rev-parse", "--is-inside-work-tree", capture_output=True, text=True, check=True)
            return res.stdout.strip() == "true"
        except subprocess.CalledProcessError:
            return False

    def last_commits(self, n=5):
        try:
            res = self._run("git", "-C", self.repo_path, "log", "--oneline", f"-{n}", capture_output=True, text=True, check=True)
            return res.stdout.strip()
        except subprocess.CalledProcessError as e:
            logger.warning("git log failed: %s", e)
            return None

    def commit_and_push(self, filename, content, message):
        try:
            abs_path = os.path.join(self.repo_path, filename)
            os.makedirs(os.path.dirname(abs_path), exist_ok=True)
            with open(abs_path, "w", encoding="utf-8") as f:
                f.write(content)

            self._run("git", "-C", self.repo_path, "add", filename, check=True)
            status = self._run("git", "-C", self.repo_path, "status", "--porcelain", capture_output=True, text=True)
            if status.stdout.strip() == "":
                logger.info("No changes to commit for %s", filename)
                return True

            self._run("git", "-C", self.repo_path, "commit", "-m", message, check=True)
            self._run("git", "-C", self.repo_path, "push", "origin", self.branch, check=True)
            logger.info("Committed and pushed %s", filename)
            return True
        except subprocess.CalledProcessError as e:
            logger.error("Git operation failed: %s", e)
            return False
        except Exception as e:
            logger.error("Unexpected error: %s", e)
            return False

git = GitHandler(GIT_REPO_URL)

# Telegram handlers
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 שלום! שלח לי טקסט ואשמור אותו בריפו. /help לעזרה.")

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("/start, /help, /gitstatus — שלח טקסט לשמירה כקובץ.")

async def git_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not git.repo_ready():
        await update.message.reply_text("❌ הריפו לא זמין או לא נמצא כאן. וודא שהמשתנה GIT_REPO_URL נכון והשרת הצליח לשכפל את הריפו בעת אתחול.")
        return

    commits = git.last_commits(5)
    if commits is None:
        await update.message.reply_text("❌ לא ניתן לקרוא את ה־git log כרגע. בדוק לוגים בשרת.")
    elif commits.strip() == "":
        await update.message.reply_text("ℹ️ הריפו ריק — לא נמצאו קומיטים עדיין.")
    else:
        await update.message.reply_text("📊 אחרונים:\n" + commits)

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    text = update.message.text or ""
    ts = datetime.datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = f"notes/note_{ts}.txt"
    message = f"Add note from {user.username or user.first_name or user.id} at {ts}Z"
    content = (
        f"From: {user.first_name} ({user.username or 'NA'})\n"
        f"User ID: {user.id}\n"
        f"UTC: {datetime.datetime.utcnow().isoformat()}\n\n"
        f"{text}\n"
    )

    ok = git.commit_and_push(filename, content, message)
    if ok:
        await update.message.reply_text(f"✅ נשמר: {filename}")
    else:
        await update.message.reply_text("❌ שגיאה בשמירה. בדוק לוגים בשרת.")

# Flask endpoints for health
@flask_app.route("/", methods=["GET"])
def index():
    return "OK"

@flask_app.route("/health", methods=["GET"])
def health():
    return "healthy"

def run():
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start_cmd))
    application.add_handler(CommandHandler("help", help_cmd))
    application.add_handler(CommandHandler("gitstatus", git_status))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    webhook_path = BOT_TOKEN
    full_webhook = f"{WEBHOOK_URL}{webhook_path}"
    logger.info("Setting webhook to %s", full_webhook)

    application.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=webhook_path,
        webhook_url=full_webhook,
        secret_token=SECRET_TOKEN
    )

if __name__ == "__main__":
    run()
