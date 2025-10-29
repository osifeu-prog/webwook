import os
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from flask import Flask, request
import git
from git import Repo
import subprocess

# Configuration
BOT_TOKEN = os.environ.get('BOT_TOKEN')
WEBHOOK_URL = os.environ.get('WEBHOOK_URL')
GIT_REPO_URL = os.environ.get('GIT_REPO_URL')
GIT_BRANCH = os.environ.get('GIT_BRANCH', 'main')

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
        self.setup_repo()
    
    def setup_repo(self):
        """Setup or clone Git repository"""
        try:
            if os.path.exists(self.repo_path):
                self.repo = Repo(self.repo_path)
                origin = self.repo.remotes.origin
                origin.pull()
            else:
                self.repo = Repo.clone_from(GIT_REPO_URL, self.repo_path)
                logger.info(f"Repository cloned successfully to {self.repo_path}")
        except Exception as e:
            logger.error(f"Error setting up repository: {e}")
    
    def commit_and_push(self, filename, content, commit_message):
        """Commit and push changes to Git"""
        try:
            # Write file
            file_path = os.path.join(self.repo_path, filename)
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            
            # Git operations
            self.repo.git.add(file_path)
            self.repo.index.commit(commit_message)
            origin = self.repo.remotes.origin
            origin.push()
            
            logger.info(f"Successfully pushed {filename} to Git")
            return True
        except Exception as e:
            logger.error(f"Error committing to Git: {e}")
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
        repo = git_bot.repo
        active_branch = repo.active_branch
        last_commit = repo.head.commit
        commit_time = last_commit.committed_datetime
        
        status_msg = f"""
📊 Git Repository Status:
📍 Branch: {active_branch}
🕒 Last Commit: {commit_time}
💬 Message: {last_commit.message}
👤 Author: {last_commit.author}
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
    filename = f"notes/note_{update.message.date.strftime('%Y%m%d_%H%M%S')}.txt"
    commit_message = f"Add note from {user.first_name} at {update.message.date}"
    
    file_content = f"""Note from: {user.first_name} ({user.username})
Date: {update.message.date}
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
        await update.message.reply_text("❌ Failed to save to Git. Please check logs.")

async def save_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Save text to specific filename"""
    if not context.args:
        await update.message.reply_text("Usage: /save <filename>")
        return
    
    filename = context.args[0]
    
    # Ask for content
    context.user_data['awaiting_content'] = filename
    await update.message.reply_text(f"Please send the content for file '{filename}':")

async def handle_file_content(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle file content after /save command"""
    if 'awaiting_content' in context.user_data:
        filename = context.user_data['awaiting_content']
        content = update.message.text
        
        commit_message = f"Add file {filename} via bot"
        success = git_bot.commit_and_push(filename, content, commit_message)
        
        if success:
            await update.message.reply_text(f"✅ Successfully saved to {filename} in Git!")
        else:
            await update.message.reply_text("❌ Failed to save file.")
        
        # Clear the state
        del context.user_data['awaiting_content']

def setup_bot():
    """Setup Telegram bot application"""
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("gitstatus", git_status))
    application.add_handler(CommandHandler("save", save_file))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    
    # Set webhook
    application.run_webhook(
        listen="0.0.0.0",
        port=5000,
        url_path=BOT_TOKEN,
        webhook_url=f"{WEBHOOK_URL}/{BOT_TOKEN}"
    )
    
    return application

@app.route('/')
def index():
    return "🤖 Git Telegram Bot is running!"

@app.route('/health')
def health():
    return "✅ Bot is healthy"

if __name__ == '__main__':
    # Start the bot
    setup_bot()
