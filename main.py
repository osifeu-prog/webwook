import os
import sys
import logging
import subprocess
import datetime
from flask import Flask, request
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# Env
BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
GIT_REPO_URL = os.getenv("GIT_REPO_URL")
GIT_TOKEN = os.getenv("GIT_TOKEN")  # optional: personal access token for private repos
GIT_BRANCH = os.getenv("GIT_BRANCH", "main")
GIT_USERNAME = os.getenv("GIT_USERNAME", "telegram-bot")
GIT_EMAIL = os.getenv("GIT_EMAIL", "bot@example.com")
SECRET_TOKEN = os.getenv("SECRET_TOKEN")
PORT = int(os.getenv("PORT", 5000))

# Required check
missing = [name for name, val in (("BOT_TOKEN", BOT_TOKEN), ("WEBHOOK_URL", WEBHOOK_URL), ("GIT_REPO_URL", GIT_REPO_URL)) if not val]
if missing:
    print("Missing environment variables:", ", ".join(missing), file=sys.stderr)
    sys.exit(1)

if not WEBHOOK_URL.endswith("/"):
    WEBHOOK_URL += "/"

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

flask_app = Flask(__name__)

def run(cmd, **kwargs):
    logger.debug("RUN: %s", " ".join(cmd))
    return subprocess.run(cmd, **kwargs)

class GitHandler:
    def __init__(self, repo_url, repo_path=".git_repo", token=None):
        self.repo_url = repo_url
        self.repo_path = repo_path
        self.branch = GIT_BRANCH
        self.token = token
        self._configure_git()
        self._prepare_repo()

    def _configure_git(self):
        try:
            run(["git", "config", "--global", "user.name", GIT_USERNAME], check=True)
            run(["git", "config", "--global", "user.email", GIT_EMAIL], check=True)
            logger.info("Git configured: %s <%s>", GIT_USERNAME, GIT_EMAIL)
        except subprocess.CalledProcessError as e:
            logger.warning("Could not set git config: %s", e)

    def _repo_remote_url(self):
        # if token provided and repo is https github.com, embed token
        if self.token and self.repo_url.startswith("https://"):
            parts = self.repo_url.split("https://", 1)[1]
            return f"https://{self.token}@{parts}"
        return self.repo_url

    def _prepare_repo(self):
        if os.path.exists(self.repo_path) and os.path.isdir(os.path.join(self.repo_path, ".git")):
            logger.info("Repo already exists locally, pulling latest")
            try:
                run(["git", "-C", self.repo_path, "pull"], check=True)
            except subprocess.CalledProcessError as e:
                logger.warning("git pull failed: %s", e)
            return

        # try clone
        try:
            logger.info("Cloning repo %s", self.repo_url)
            run(["git", "clone", self._repo_remote_url(), self.repo_path], check=True)
            logger.info("Clone succeeded")
            return
        except subprocess.CalledProcessError as e:
            logger.warning("Clone failed: %s", e)

        # if clone failed, init empty repo and add remote (may require push permissions to succeed later)
        try:
            logger.info("Initializing new local repo at %s", self.repo_path)
            os.makedirs(self.repo_path, exist_ok=True)
            run(["git", "-C", self.repo_path, "init"], check=True)
            # add remote if possible
            try:
                run(["git", "-C", self.repo_path, "remote", "add", "origin", self._repo_remote_url()], check=True)
                logger.info("Added remote origin -> %s", self.repo_url)
            except subprocess.CalledProcessError:
                logger.warning("Could not add remote origin")
        except Exception as e:
            logger.error("Failed to initialize local repo: %s", e)

    def repo_ready(self):
        return os.path.isdir(os.path.join(self.repo_path, ".git"))

    def last_commits(self, n=5):
        if not self.repo_ready():
            return None, "repo_not_ready"
        try:
            res = run(["git", "-C", self.repo_path, "log", "--oneline", f"-{n}"], capture_output=True, text=True, check=True)
            return res.stdout.strip(), None
        except subprocess.CalledProcessError as e:
            logger.warning("git log failed: %s", e)
            return None, "git_error"

    def commit_and_push(self, filename, content, message):
        if not self.repo_ready():
            logger.error("Repository not ready for commit")
            return False, "repo_not_ready"

        abs_path = os.path.join(self.repo_path, filename)
        try:
            os.makedirs(os.path.dirname(abs_path), exist_ok=True)
            with open(abs_path, "w", encoding="utf-8") as f:
                f.write(content)
        except Exception as e:
            logger.error("Failed to write file: %s", e)
            return False, "write_error"

        try:
            run(["git", "-C", self.repo_path, "add", filename], check=True)
            status = run(["git", "-C", self.repo_path, "status", "--porcelain"], capture_output=True, text=True)
            if status.stdout.strip() == "":
                logger.info("No changes to commit for %s", filename)
                return True, None
            run(["git", "-C", self.repo_path, "commit", "-m", message], check=True)
            # push (remote must exist and credentials must allow push)
            try:
                run(["git", "-C", self.repo_path, "push", "origin", self.branch], check=True)
                return True, None
            except subprocess.CalledProcessError as e:
                logger.warning("git push failed: %s", e)
                return False, "push_failed"
        except subprocess.CalledProcessError as e:
            logger.error("Git operation failed: %s", e)
            return False, "git_failed"
        except Exception as e:
            logger.error("Unexpected error: %s", e)
            return False, "unknown"

git = GitHandler(GIT_REPO_URL, token=GIT_TOKEN)

# Telegram handlers
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 שלום! שלח לי טקסט ואשמור אותו בריפו. /help לעזרה.")

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("/start, /help, /gitstatus — שלח טקסט לשמירה כקובץ.")

async def git_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    commits, err = git.last_commits(5)
    if err == "repo_not_ready":
        await update.message.reply_text("❌ הריפו לא זמין כאן (לא הועתק בהצלחה). ודא ש‑GIT_REPO_URL נכון והשרת יכול לגשת אליו.")
    elif err == "git_error":
        await update.message.reply_text("❌ קרתה שגיאת git בזמן קריאת ה‑log. בדוק לוגים.")
    elif commits is None or commits.strip() == "":
        await update.message.reply_text("ℹ️ אין קומיטים לשנות כרגע.")
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

    ok, err = git.commit_and_push(filename, content, message)
    if ok:
        await update.message.reply_text(f"✅ נשמר: {filename}")
    else:
        if err == "repo_not_ready":
            await update.message.reply_text("❌ לא ניתן לשמור — הריפו לא הוגדר כראוי. בדוק GIT_REPO_URL וההרשאות.")
        elif err == "push_failed":
            await update.message.reply_text("❌ התנגשות ב‑push או אין הרשאות push. בדוק הרשאות/GIT_TOKEN.")
        else:
            await update.message.reply_text("❌ שגיאה בשמירה. בדוק לוגים בשרת.")

# Flask endpoints
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

    # run_webhook will call setWebhook internally; requires python-telegram-bot[webhooks] in requirements
    application.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=webhook_path,
        webhook_url=full_webhook,
        secret_token=SECRET_TOKEN
    )

if __name__ == "__main__":
    run()
