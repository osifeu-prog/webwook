import os
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from flask import Flask, request
import subprocess
import datetime

# Configuration
BOT_TOKEN = os.environ.get('BOT_TOKEN')
WEBHOOK_URL = os.environ.get('WEBHOOK_URL')
GIT_REPO_URL = os.environ.get('GIT_REPO_URL')
GIT_BRANCH = os.environ.get('GIT_BRANCH', 'main')
GIT_USERNAME = os.environ.get('GIT_USERNAME', 'telegram-bot')
GIT_EMAIL = os.environ.get('GIT_EMAIL', 'bot@example.com')

# Initialize Flask app
app = Flask(__name__)

# Set up logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class GitBot:
    def __init__(self):
        self.repo_path = "./git_repo"
        self.setup_git_config()
        self.setup_repo()
    
    def setup_git_config(self):
        """Configure Git user settings"""
        try:
            subprocess.run(['git', 'config', '--global', 'user.name', GIT_USERNAME], check=True)
            subprocess.run(['git', 'config', '--global', 'user.email', GIT_EMAIL], check=True)
            logger.info("Git configuration set successfully")
        except subprocess.CalledProcessError as e:
            logger.error(f"Error setting Git config: {e}")
    
    def setup_repo(self):
        """Setup or clone Git repository using subprocess"""
        try:
            if os.path.exists(self.repo_path):
                logger.info("Repository exists, pulling latest changes")
                subprocess.run(['git', '-C', self.repo_path, 'pull'], check=True)
            else:
                logger.info(f"Cloning repository from {GIT_REPO_URL}")
                subprocess.run(['git', 'clone', GIT_REPO_URL, self.repo_path], check=True)
        except subprocess.CalledProcessError as e:
            logger.error(f"Error setting up repository: {e}")
    
    def commit_and_push(self, filename, content, commit_message):
        """Commit and push changes to Git using subprocess"""
        try:
            # Create directory if it doesn't exist
            os.makedirs(os.path.dirname(os.path.join(self.repo_path, filename)), exist_ok=True)
            
            # Write file
            file_path = os.path.join(self.repo_path, filename)
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            
            # Git operations using subprocess
            subprocess.run(['git', '-C', self.repo_path, 'add', filename], check=True)
            subprocess.run(['git', '-C', self.repo_path, 'commit', '-m', commit_message], check=True)
            subprocess.run(['git', '-C', self.repo_path, 'push', 'origin', GIT_BRANCH], check=True)
            
            logger.info(f"Successfully pushed {filename} to Git")
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"Error committing to Git: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            return False

# Initialize bot and Git handler
git_bot = GitBot()

# Telegram bot handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send a message when the command /start is issued."""
    await update.message.reply_text(
        '👋 Hello! I am your Git Bot!\n\n'
        'Send me text and I will save it to your Git repository.\n'
        'Use /help to see available commands.'
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send a message when the command /help is issued."""
    help_text = """
Available commands:
/start - Start the bot
/help - Show this help message
/gitstatus - Check Git repository status
/save <filename> - Save following text to specified file

Just send text to save it as a note with timestamp.
"""
    await update.message.reply_text(help_text)

async def git_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Check Git repository status"""
    try:
        result = subprocess.run(
            ['git', '-C', git_bot.repo_path, 'log', '--oneline', '-5'],
            capture_output=True, text=True, check=True
        )
        
        status_msg = f"""
📊 Git Repository Status:
📍 Branch: {GIT_BRANCH}
🔄 Last 5 commits:
{result.stdout}
"""
        await update.message.reply_text(status_msg)
    except Exception as e:
        await update.message.reply_text(f"❌ Error checking Git status: {e}")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle incoming text messages"""
    user_text = update.message.text
    
    # Skip if it's a command
    if user_text.startswith('/'):
        return
    
    user = update.message.from_user
    timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f"notes/note_{timestamp}.txt"
    commit_message = f"Add note from {user.first_name} at {timestamp}"
    
    file_content = f"""Note from: {user.first_name} ({user.username if user.username else 'N/A'})
Date: {datetime.datetime.now()}
User ID: {user.id}

Content:
{user_text}
"""
    
    success = git_bot.commit_and_push(filename, file_content, commit_message)
    
    if success:
        await update.message.reply_text(
            f"✅ Successfully saved your note to Git!\n"
            f"📁 File: {filename}\n"
            f"💬 Commit: {commit_message}"
        )
    else:
        await update.message.reply_text("❌ Failed to save to Git. Please try again later.")

@app.route('/')
def index():
    return "🤖 Git Telegram Bot is running on Railway!"

@app.route('/health')
def health():
    return "✅ Bot is healthy"

@app.route(f'/{BOT_TOKEN}', methods=['POST'])
def webhook():
    """Webhook endpoint for Telegram"""
    if request.method == "POST":
        update = Update.de_json(request.get_json(), application.bot)
        application.update_queue.put(update)
    return "OK"

def main():
    """Main function to start the bot"""
    # Create Telegram application
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("gitstatus", git_status))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    
    # Set webhook for Railway
    application.run_webhook(
        listen="0.0.0.0",
        port=int(os.environ.get('PORT', 5000)),
        url_path=BOT_TOKEN,
        webhook_url=f"{WEBHOOK_URL}/{BOT_TOKEN}",
        secret_token=os.environ.get('SECRET_TOKEN')
    )

if __name__ == '__main__':
    main()
