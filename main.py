import os
import logging
import subprocess
import datetime
import json
import uuid
import requests
from flask import Flask, request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler

# --- קריאה למשתני סביבה שהוגדרו ב-Railway ---
BOT_TOKEN = os.getenv("TELEGRAM_TOKEN") or os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
GIT_REPO_URL = os.getenv("GIT_REPO_URL")
GIT_BRANCH = os.getenv("GIT_BRANCH", "main")
GIT_USERNAME = os.getenv("GIT_USERNAME", "telegram-bot")
GIT_EMAIL = os.getenv("GIT_EMAIL", "bot@example.com")
PORT = int(os.getenv("PORT", 8080))
GROUP_LINK = os.getenv("GROUP_LINK", "https://t.me/+mIYkHnpCj6g2ZmRk")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
HUGGINGFACE_API_KEY = os.getenv("HUGGINGFACE_API_KEY")

# --- טעינת מנהלים - עם ערך ברירת מחדל אם לא הוגדר ---
ADMIN_USER_IDS_STR = os.getenv("ADMIN_USER_IDS", "224223270")
ADMIN_USER_IDS = []
try:
    ADMIN_USER_IDS = [int(x.strip()) for x in ADMIN_USER_IDS_STR.split(",") if x.strip()]
except ValueError as e:
    logging.error("Error parsing ADMIN_USER_IDS: %s", e)
    ADMIN_USER_IDS = [224223270]  # fallback to default

# --- בדיקה בסיסית ---
if not BOT_TOKEN:
    raise SystemExit("❌ Missing required environment variable: BOT_TOKEN or TELEGRAM_TOKEN.")
if not WEBHOOK_URL:
    raise SystemExit("❌ Missing required environment variable: WEBHOOK_URL.")
if not GIT_REPO_URL:
    raise SystemExit("❌ Missing required environment variable: GIT_REPO_URL.")

logging.info("Admin users: %s", ADMIN_USER_IDS)

# --- לוגים ---
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# --- Flask עבור Railway ---
app = Flask(__name__)

def run(cmd, **kwargs):
    logger.debug("RUN: %s", " ".join(cmd))
    return subprocess.run(cmd, **kwargs)

class AIService:
    def __init__(self):
        self.openai_key = OPENAI_API_KEY
        self.huggingface_key = HUGGINGFACE_API_KEY

    def ask_openai(self, prompt, model="gpt-3.5-turbo"):
        if not self.openai_key:
            return "🤖 **תשובת AI:**\n\nאני כאן כדי לעזור לך עם שאלות על לימודים!\n\n💡 **טיפ:** אתה יכול לשאול אותי על:\n• הסברים בתחומי הלימוד\n• פתרון תרגילים\n• הנחיה בפרויקטים\n• ארגון חומר לימודי\n\n🎓 **אקדמיה להשכלה גבוהה - SLH Academia**"
        
        headers = {
            "Authorization": f"Bearer {self.openai_key}",
            "Content-Type": "application/json"
        }
        
        data = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.7
        }
        
        try:
            response = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers=headers,
                json=data,
                timeout=30
            )
            if response.status_code == 200:
                return response.json()["choices"][0]["message"]["content"]
            else:
                return f"❌ OpenAI API error: {response.status_code}"
        except Exception as e:
            return f"❌ OpenAI request failed: {str(e)}"

    def ask_huggingface(self, prompt, model="microsoft/DialoGPT-large"):
        if not self.huggingface_key:
            return "❌ HuggingFace API key not configured"
        
        headers = {
            "Authorization": f"Bearer {self.huggingface_key}",
            "Content-Type": "application/json"
        }
        
        data = {
            "inputs": prompt,
            "parameters": {
                "max_length": 500,
                "temperature": 0.7,
                "do_sample": True
            }
        }
        
        try:
            response = requests.post(
                f"https://api-inference.huggingface.co/models/{model}",
                headers=headers,
                json=data,
                timeout=30
            )
            if response.status_code == 200:
                result = response.json()
                if isinstance(result, list) and len(result) > 0:
                    return result[0].get("generated_text", prompt)
                return prompt
            else:
                return f"❌ HuggingFace API error: {response.status_code}"
        except Exception as e:
            return f"❌ HuggingFace request failed: {str(e)}"

ai_service = AIService()

class GitHandler:
    def __init__(self, repo_url, repo_path=".git_repo"):
        self.repo_url = repo_url
        self.repo_path = repo_path
        self.branch = GIT_BRANCH
        self.authorized_users = set()
        self._configure_git()
        self._prepare_repo()
        self._load_authorized_users()

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
                # Try to re-clone if pull fails
                import shutil
                shutil.rmtree(self.repo_path, ignore_errors=True)
        
        try:
            run(["git", "clone", "-b", self.branch, self.repo_url, self.repo_path], check=True)
            logger.info("Cloned repository")
        except subprocess.CalledProcessError as e:
            logger.error("Clone failed: %s", e)

    def _load_authorized_users(self):
        authorized_users_file = os.path.join(self.repo_path, "authorized_users.txt")
        self.authorized_users = set()
        
        # Add admin users first
        for admin_id in ADMIN_USER_IDS:
            self.authorized_users.add(admin_id)
        
        # Load from file if exists
        if os.path.exists(authorized_users_file):
            try:
                with open(authorized_users_file, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#"):
                            try:
                                self.authorized_users.add(int(line))
                            except ValueError:
                                logger.warning("Invalid user ID in authorized_users.txt: %s", line)
            except Exception as e:
                logger.error("Error reading authorized_users.txt: %s", e)
        
        logger.info("Loaded %d authorized users: %s", len(self.authorized_users), self.authorized_users)

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
            logger.error("Repo not ready for commit")
            return False
        
        abs_path = os.path.join(self.repo_path, filename)
        try:
            os.makedirs(os.path.dirname(abs_path), exist_ok=True)
            with open(abs_path, "w", encoding="utf-8") as f:
                f.write(content)
            
            run(["git", "-C", self.repo_path, "add", filename], check=True)
            status = run(["git", "-C", self.repo_path, "status", "--porcelain"], capture_output=True, text=True)
            
            if status.stdout.strip() == "":
                logger.info("No changes to commit for %s", filename)
                return True
            
            run(["git", "-C", self.repo_path, "commit", "-m", message], check=True)
            run(["git", "-C", self.repo_path, "push", "origin", self.branch], check=True)
            logger.info("Successfully committed and pushed: %s", filename)
            return True
        except Exception as e:
            logger.error("Git operation failed for %s: %s", filename, e)
            return False

    def add_authorized_user(self, user_id):
        authorized_users_file = os.path.join(self.repo_path, "authorized_users.txt")
        
        # Ensure the file exists with header
        if not os.path.exists(authorized_users_file):
            with open(authorized_users_file, "w", encoding="utf-8") as f:
                f.write("# Authorized users list\n")
                f.write("# Format: one user ID per line\n")
                f.write("# Admins are automatically added from ADMIN_USER_IDS\n\n")
        
        # Check if user already exists
        user_exists = False
        try:
            with open(authorized_users_file, "r", encoding="utf-8") as f:
                lines = f.readlines()
            
            for line in lines:
                if line.strip() == str(user_id):
                    user_exists = True
                    break
        except Exception as e:
            logger.error("Error reading authorized users file: %s", e)
        
        if user_exists:
            logger.info("User %s already in authorized list", user_id)
            self.authorized_users.add(user_id)
            return True  # already exists
        
        # Add the user
        try:
            with open(authorized_users_file, "a", encoding="utf-8") as f:
                f.write(f"{user_id}\n")
            
            # Commit and push the change
            success = self.commit_and_push("authorized_users.txt", 
                                         "".join(lines + [f"{user_id}\n"]), 
                                         f"Add authorized user {user_id}")
            if success:
                self.authorized_users.add(user_id)
                logger.info("Added authorized user: %s", user_id)
                return True
            else:
                logger.error("Failed to commit authorized user addition")
                return False
        except Exception as e:
            logger.error("Failed to add authorized user: %s", e)
            return False

    def remove_authorized_user(self, user_id):
        authorized_users_file = os.path.join(self.repo_path, "authorized_users.txt")
        
        if not os.path.exists(authorized_users_file):
            return True  # nothing to remove
        
        # Read all lines and remove the user
        try:
            with open(authorized_users_file, "r", encoding="utf-8") as f:
                lines = f.readlines()
            
            new_lines = []
            user_removed = False
            for line in lines:
                if line.strip() != str(user_id):
                    new_lines.append(line)
                else:
                    user_removed = True
            
            if not user_removed:
                return True  # user not in file
            
            # Write back without the user
            with open(authorized_users_file, "w", encoding="utf-8") as f:
                f.writelines(new_lines)
            
            # Commit and push the change
            success = self.commit_and_push("authorized_users.txt", 
                                         "".join(new_lines), 
                                         f"Remove authorized user {user_id}")
            if success:
                self.authorized_users.discard(user_id)
                logger.info("Removed authorized user: %s", user_id)
                return True
            else:
                return False
        except Exception as e:
            logger.error("Failed to remove authorized user: %s", e)
            return False

git = GitHandler(GIT_REPO_URL)

class CoinSystem:
    def __init__(self, git_handler):
        self.git = git_handler
        self.coins_file = "coins/coins.json"
        self._ensure_coins_file()

    def _ensure_coins_file(self):
        """Ensure coins file exists with initial structure"""
        coins_path = os.path.join(self.git.repo_path, self.coins_file)
        if not os.path.exists(coins_path):
            os.makedirs(os.path.dirname(coins_path), exist_ok=True)
            initial_data = {
                "coins": {},
                "transactions": [],
                "total_mined": 0
            }
            with open(coins_path, "w", encoding="utf-8") as f:
                json.dump(initial_data, f, indent=2, ensure_ascii=False)
            self.git.commit_and_push(self.coins_file, json.dumps(initial_data, indent=2), "Initialize coins system")

    def _load_coins_data(self):
        coins_path = os.path.join(self.git.repo_path, self.coins_file)
        try:
            with open(coins_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error("Error loading coins data: %s", e)
            return {"coins": {}, "transactions": [], "total_mined": 0}

    def _save_coins_data(self, data):
        coins_path = os.path.join(self.git.repo_path, self.coins_file)
        with open(coins_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return self.git.commit_and_push(self.coins_file, json.dumps(data, indent=2), "Update coins data")

    def mine_coins(self, admin_id, amount, reason):
        """Admin mines new coins"""
        if admin_id not in ADMIN_USER_IDS:
            return False, "רק מנהלים יכולים לכרות מטבעות"
        
        data = self._load_coins_data()
        transaction_id = str(uuid.uuid4())[:8]
        
        transaction = {
            "id": transaction_id,
            "type": "mine",
            "from": "system",
            "to": str(admin_id),
            "amount": amount,
            "reason": reason,
            "timestamp": datetime.datetime.utcnow().isoformat(),
            "admin": str(admin_id)
        }
        
        # Update admin's balance
        if str(admin_id) not in data["coins"]:
            data["coins"][str(admin_id)] = 0
        data["coins"][str(admin_id)] += amount
        data["total_mined"] += amount
        data["transactions"].append(transaction)
        
        if self._save_coins_data(data):
            return True, f"✅ כריתת {amount} מטבעות הצליחה!\nמספר עסקה: {transaction_id}\nסיבה: {reason}"
        else:
            return False, "❌ שגיאה בשמירת כריתת המטבעות"

    def transfer_coins(self, from_user_id, to_user_id, amount, reason):
        """Transfer coins between users"""
        data = self._load_coins_data()
        
        # Check if sender has enough coins
        if str(from_user_id) not in data["coins"] or data["coins"][str(from_user_id)] < amount:
            return False, "❌ אין מספיק מטבעות בארנק"
        
        transaction_id = str(uuid.uuid4())[:8]
        
        transaction = {
            "id": transaction_id,
            "type": "transfer",
            "from": str(from_user_id),
            "to": str(to_user_id),
            "amount": amount,
            "reason": reason,
            "timestamp": datetime.datetime.utcnow().isoformat()
        }
        
        # Update balances
        data["coins"][str(from_user_id)] -= amount
        if str(to_user_id) not in data["coins"]:
            data["coins"][str(to_user_id)] = 0
        data["coins"][str(to_user_id)] += amount
        data["transactions"].append(transaction)
        
        if self._save_coins_data(data):
            return True, f"✅ העברת {amount} מטבעות הצליחה!\nמספר עסקה: {transaction_id}\nסיבה: {reason}"
        else:
            return False, "❌ שגיאה בשמירת העברת המטבעות"

    def get_balance(self, user_id):
        """Get user's coin balance"""
        data = self._load_coins_data()
        return data["coins"].get(str(user_id), 0)

    def get_transaction_history(self, user_id, limit=10):
        """Get transaction history for user"""
        data = self._load_coins_data()
        user_transactions = []
        
        for tx in reversed(data["transactions"]):
            if tx["from"] == str(user_id) or tx["to"] == str(user_id):
                user_transactions.append(tx)
            if len(user_transactions) >= limit:
                break
        
        return user_transactions

    def get_system_stats(self):
        """Get system statistics"""
        data = self._load_coins_data()
        return {
            "total_users": len(data["coins"]),
            "total_mined": data["total_mined"],
            "total_transactions": len(data["transactions"])
        }

coin_system = CoinSystem(git)

# --- בדיקת הרשאה ---
def is_authorized(user_id):
    return user_id in git.authorized_users

def is_admin(user_id):
    return user_id in ADMIN_USER_IDS

# --- פקודות טלגרם ---
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    # Reload authorized users to ensure we have latest data
    git._load_authorized_users()
    
    if is_authorized(user_id):
        balance = coin_system.get_balance(user_id)
        keyboard = [
            [InlineKeyboardButton("🎓 על האקדמיה", callback_data="about_academy")],
            [InlineKeyboardButton("🪙 מצב ארנק", callback_data="check_balance")],
            [InlineKeyboardButton("🤖 שאל את AI", callback_data="ask_ai")],
            [InlineKeyboardButton("📁 תיקיות אישיות", callback_data="personal_folders")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"👋 שלום! אני בוט הלימוד שלך.\n"
            f"💰 מטבעות בארנק: {balance}\n\n"
            "🏫 **ברוך הבא לאקדמיה להשכלה גבוהה!**\n\n"
            "פה תוכל:\n"
            "• ללמוד תחומים חדשים עם AI\n"
            "• לנהל את החומר הלימודי שלך\n"
            "• לקבל תגמולים במטבעות\n"
            "• להתפתח מקצועית\n\n"
            "השתמש בכפתורים למטה לניווט:",
            reply_markup=reply_markup
        )
    else:
        keyboard = [
            [InlineKeyboardButton("🎓 למה להירשם?", callback_data="why_join")],
            [InlineKeyboardButton("💳 רוצה להצטרף - תשלום", callback_data="request_access")],
            [InlineKeyboardButton("📞 יצירת קשר", callback_data="contact_info")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            "🏫 **אקדמיה להשכלה גבוהה - SLH Academia**\n\n"
            "❌ אין לך הרשאה להשתמש בבוט זה.\n\n"
            "💵 עלות גישה: 444 ש\"ח\n\n"
            "🎯 **מה תקבל לאחר הרישום:**\n"
            "• גישה לפורטל למידה מתקדם\n"
            "• ליווי AI אישי ללמידה\n"
            "• תיקיות לימוד אישיות\n"
            "• מערכת תגמולים במטבעות\n"
            "• קהילת לומדים פעילה\n\n"
            "לחץ על 'למה להירשם?' לפרטים נוספים:",
            reply_markup=reply_markup
        )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        return
    
    await update.message.reply_text(
        "📖 **עזרה - אקדמיה להשכלה גבוהה:**\n\n"
        "• שלח טקסט רגיל - יישמר בתיקיה האישית שלך\n"
        "• /gitstatus - מציג את הקומיטים האחרונים\n"
        "• /myfolder - פותח תיקיה אישית חדשה\n"
        "• /balance - מצב מטבעות בארנק\n"
        "• /ask - שאל שאלה את ה-AI\n"
        "• /subjects - ניהול תחומי הלימוד\n"
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
    
    welcome_content = f"""ברוך הבא לתיקיה האישית שלך באקדמיה!

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
• מטלות
• פרויקטים אישיים

שלח טקסט רגיל ואשמור אותו כאן!

🎓 אקדמיה להשכלה גבוהה - SLH Academia
"""
    
    ok = git.commit_and_push(welcome_file, welcome_content, f"Create personal folder for {user.first_name} ({user.id})")
    if ok:
        await update.message.reply_text(
            f"✅ תיקיה אישית נוצרה: {user_folder}/\n\n"
            f"🎓 **אקדמיה להשכלה גבוהה**\n"
            f"כעת תוכל לשלוח טקסט ואשמור אותו בתיקיה שלך.\n\n"
            f"💡 **טיפ:** אתה יכול ליצור תיקיות משנה לפי נושאים:\n"
            f"• {user_folder}/programming/\n"
            f"• {user_folder}/mathematics/\n"
            f"• {user_folder}/projects/\n"
            f"וכו..."
        )
    else:
        await update.message.reply_text("❌ שגיאה ביצירת תיקיה אישית. נסה שוב מאוחר יותר.")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    # Reload authorized users to ensure we have latest data
    git._load_authorized_users()
    
    if not is_authorized(user_id):
        return
    
    user = update.effective_user
    text = update.message.text or ""
    
    if not text.strip():
        await update.message.reply_text("❌ אנא שלח טקסט לשמירה.")
        return
    
    # Check if this is a payment confirmation with photo
    if context.user_data.get('waiting_for_payment_proof'):
        # This will be handled by the photo handler
        return
    
    # Check if waiting for AI question
    if context.user_data.get('waiting_for_ai_question'):
        await update.message.reply_text("🤖 AI מעבד את השאלה שלך...")
        response = ai_service.ask_openai(text)
        await update.message.reply_text(f"🤖 **תשובת AI:**\n\n{response}")
        
        # Save AI conversation
        user_folder = f"students/{user.id}"
        ts = datetime.datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filename = f"{user_folder}/ai_conversation_{ts}.txt"
        
        content = f"""שיחת AI:
שאלה: {text}
תשובה: {response}
תאריך: {datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}
"""
        git.commit_and_push(filename, content, f"AI conversation for {user.first_name}")
        
        context.user_data['waiting_for_ai_question'] = False
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
        await update.message.reply_text(
            f"✅ נשמר בהצלחה!\n"
            f"📁 תיקיה: {user_folder}/\n"
            f"📄 קובץ: note_{ts}.txt\n\n"
            f"🎓 **אקדמיה להשכלה גבוהה**\n"
            f"החומר הלימודי שלך נשמר בצורה מאובטחת."
        )
    else:
        await update.message.reply_text("❌ שגיאה בשמירה. נסה שוב מאוחר יותר.")

# --- Coin System Commands ---
async def balance_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        return
    
    user_id = update.effective_user.id
    balance = coin_system.get_balance(user_id)
    transactions = coin_system.get_transaction_history(user_id, 5)
    
    message = f"💰 **מצב ארנק - אקדמיה להשכלה גבוהה**\n\nמטבעות: {balance}\n\n"
    message += "🔗 **עסקאות אחרונות:**\n"
    
    if transactions:
        for tx in transactions:
            if tx["type"] == "mine":
                message += f"⛏️ +{tx['amount']} - {tx['reason']}\n"
            elif tx["type"] == "transfer":
                if tx["from"] == str(user_id):
                    message += f"📤 -{tx['amount']} - {tx['reason']}\n"
                else:
                    message += f"📥 +{tx['amount']} - {tx['reason']}\n"
    else:
        message += "אין עסקאות עדיין\n"
    
    message += "\n🎓 **המטבעות שלנו:**\n"
    message += "• ניתן להמיר לשיעורים פרטיים\n• ניתן לקבל הנחות על קורסים\n• מעניקים גישה לתוכן בלעדי"
    
    await update.message.reply_text(message)

async def coins_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    
    keyboard = [
        [InlineKeyboardButton("⛏️ כרות מטבעות", callback_data="mine_coins")],
        [InlineKeyboardButton("🎁 העבר מטבעות", callback_data="transfer_coins")],
        [InlineKeyboardButton("📊 סטטיסטיקות", callback_data="coin_stats")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    stats = coin_system.get_system_stats()
    await update.message.reply_text(
        f"🪙 **ניהול מטבעות - אקדמיה**\n\n"
        f"📈 **סטטיסטיקות:**\n"
        f"• משתמשים: {stats['total_users']}\n"
        f"• מטבעות שכורים: {stats['total_mined']}\n"
        f"• עסקאות: {stats['total_transactions']}",
        reply_markup=reply_markup
    )

async def ask_ai_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        return
    
    context.user_data['waiting_for_ai_question'] = True
    await update.message.reply_text(
        "🤖 **AI Assistant - אקדמיה להשכלה גבוהה**\n\n"
        "שלח לי שאלה ואעזור לך עם:\n"
        "• הסברים בתחומי הלימוד\n"
        "• פתרון תרגילים\n"
        "• הנחיה בפרויקטים\n"
        "• תשובות לשאלות כלליות\n\n"
        "💡 **טיפ:** שאל שאלות ספציפיות לתחומי העניין שלך!"
    )

# --- Payment and Access Request System ---
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    data = query.data

    # Reload authorized users to ensure we have latest data
    git._load_authorized_users()

    if data == "why_join":
        # Show benefits of joining
        benefits_text = (
            "🎓 **למה להצטרף לאקדמיה שלנו?**\n\n"
            "✅ **יתרונות בלעדיים:**\n"
            "• פורטל למידה מתקדם עם AI\n"
            "• תיקיות לימוד אישיות\n"
            "• מערכת תגמולים במטבעות\n"
            "• ליווי צמוד של מנחים\n"
            "• קהילת לומדים תומכת\n"
            "• גישה לחומרים בלעדיים\n\n"
            "📚 **תחומי לימוד:**\n"
            "• תכנות ומדעי המחשב\n"
            "• מתמטיקה וסט�יסטיקה\n"
            "• מדעי הנתונים\n"
            "• בינה מלאכותית\n"
            "• וכל תחום שתרצה!\n\n"
            "💼 **יתרונות תעסוקתיים:**\n"
            "• הכנה לראיונות עבודה\n"
            "• בניית תיק פרויקטים\n"
            "• פיתוח מיומנויות מבוקשות\n"
            "• רשת קשרים מקצועית\n\n"
            "💰 **מערכת המטבעות:**\n"
            "• earn coins for achievements\n"
            "• redeem for private lessons\n"
            "• get course discounts\n"
            "• access exclusive content"
        )
        
        keyboard = [
            [InlineKeyboardButton("💳 אני מעוניין - תשלום", callback_data="request_access")],
            [InlineKeyboardButton("📞 יצירת קשר", callback_data="contact_info")],
            [InlineKeyboardButton("🔙 חזרה", callback_data="back_to_start")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(benefits_text, reply_markup=reply_markup)

    elif data == "request_access":
        # User requests access - show payment instructions
        payment_info = (
            "💵 **תשלום עבור גישה לאקדמיה**\n\n"
            "סכום: 444 ש\"ח\n\n"
            "🏦 **פרטים להעברה בנקאית:**\n"
            "• בנק: הפועלים\n"
            "• סניף: כפר גנים (153)\n"
            "• מספר חשבון: 73462\n"
            "• שם המוטב: קאופמן צביקה\n\n"
            "📱 **אופציות תשלום נוספות:**\n"
            "• ארנק טלגרם (Crypto): `UQCr743gEr_nqV_0SBkSp3CtYS_15R3LDLBvLmKeEv7XdGvp`\n"
            "• ביט/PayBox: `+972 54-667-1882`\n\n"
            "📋 **אחרי התשלום:**\n"
            "1. לחץ על 'שלחתי תשלום'\n"
            "2. שלח צילום מסך של ההעברה\n"
            "3. המנהל יאשר את הגישה תוך 24 שעות\n"
            "4. תקבל קישור לקבוצה ופרטי כניסה\n\n"
            "⚠️ **שימו לב:** הגישה תינתן רק לאחר אימות התשלום!\n\n"
            "📧 **לשאלות:** @Osif83\n"
            "📧 **מייל:** osif@slh-academia.com\n"
            "📞 **טלפון:** +972 54-667-1882"
        )
        
        keyboard = [
            [InlineKeyboardButton("💳 שלחתי תשלום - אישור", callback_data="confirm_payment")],
            [InlineKeyboardButton("📞 יצירת קשר", callback_data="contact_info")],
            [InlineKeyboardButton("🔙 חזרה", callback_data="back_to_start")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(payment_info, reply_markup=reply_markup)

    elif data == "contact_info":
        contact_text = (
            "📞 **יצירת קשר - אקדמיה להשכלה גבוהה**\n\n"
            "👤 **מנהל האקדמיה:** Osif Ungar\n"
            "📱 **טלגרם:** @Osif83\n"
            "📧 **אימייל:** osif@slh-academia.com\n"
            "📞 **טלפון:** +972 54-667-1882\n\n"
            "💬 **שאלות לפני רישום?**\n"
            "מוזמן ליצור קשר לכל שאלה!\n\n"
            "🕒 **שעות פעילות:**\n"
            "א'-ה' 09:00-18:00\n"
            "ו' 09:00-13:00"
        )
        
        keyboard = [
            [InlineKeyboardButton("💳 אני מעוניין - תשלום", callback_data="request_access")],
            [InlineKeyboardButton("🔙 חזרה", callback_data="back_to_start")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(contact_text, reply_markup=reply_markup)

    elif data == "confirm_payment":
        # User confirms payment - ask for photo proof
        context.user_data['waiting_for_payment_proof'] = True
        await query.edit_message_text(
            "📸 **שלח צילום מסך של התשלום**\n\n"
            "אנא שלח כעת צילום מסך של ההעברה הבנקאית.\n"
            "התמונה תישלח למנהל לאישור.\n\n"
            "💡 **טיפ:** ודא שהצילום כולל:\n"
            "• שם השולח\n"
            "• סכום ההעברה\n"
            "• תאריך ההעברה\n"
            "• פרטי החשבון"
        )

    elif data == "about_academy":
        academy_info = (
            "🏫 **אקדמיה להשכלה גבוהה - SLH Academia**\n\n"
            "🎯 **המשימה שלנו:**\n"
            "לסנגר השכלה גבוהה איכותית\n"
            "באמצעות טכנולוגיה מתקדמת\n\n"
            "💡 **מה אנחנו מציעים:**\n"
            "• למידה מותאמת אישית עם AI\n"
            "• תוכניות לימוד גמישות\n"
            "• קהילת לומדים תומכת\n"
            "• פיתוח כישורים מעשיים\n\n"
            "🚀 **השיטה שלנו:**\n"
            "1. אבחון תחומי עניין\n"
            "2. בניית תוכנית לימודים\n"
            "3. ליווי צמוד עם AI\n"
            "4. תיעוד והתקדמות\n"
            "5. תגמול והכרה\n\n"
            "🎓 **הצטרף לקהילת הלומדים שלנו!**"
        )
        
        keyboard = [
            [InlineKeyboardButton("🤖 שאל את AI", callback_data="ask_ai")],
            [InlineKeyboardButton("🪙 מצב ארנק", callback_data="check_balance")],
            [InlineKeyboardButton("📁 תיקיות אישיות", callback_data="personal_folders")],
            [InlineKeyboardButton("🔙 חזרה", callback_data="back_to_start")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(academy_info, reply_markup=reply_markup)

    elif data == "ask_ai":
        context.user_data['waiting_for_ai_question'] = True
        await query.edit_message_text(
            "🤖 **AI Assistant - אקדמיה להשכלה גבוהה**\n\n"
            "שלח לי שאלה ואעזור לך עם:\n"
            "• הסברים בתחומי הלימוד\n"
            "• פתרון תרגילים\n"
            "• הנחיה בפרויקטים\n"
            "• תשובות לשאלות כלליות\n\n"
            "💡 **טיפ:** שאל שאלות ספציפיות לתחומי העניין שלך!"
        )

    elif data == "check_balance":
        user_id = query.from_user.id
        balance = coin_system.get_balance(user_id)
        transactions = coin_system.get_transaction_history(user_id, 3)
        
        message = f"💰 **מצב ארנק:**\n\nמטבעות: {balance}\n\n"
        message += "🔗 **עסקאות אחרונות:**\n"
        
        if transactions:
            for tx in transactions:
                if tx["type"] == "mine":
                    message += f"⛏️ +{tx['amount']} - {tx['reason']}\n"
                elif tx["type"] == "transfer":
                    if tx["from"] == str(user_id):
                        message += f"📤 -{tx['amount']} - {tx['reason']}\n"
                    else:
                        message += f"📥 +{tx['amount']} - {tx['reason']}\n"
        else:
            message += "אין עסקאות עדיין\n"
        
        keyboard = [
            [InlineKeyboardButton("🔙 חזרה", callback_data="back_to_start")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(message, reply_markup=reply_markup)

    elif data == "personal_folders":
        user_id = query.from_user.id
        user_folder = f"students/{user_id}"
        
        message = (
            f"📁 **התיקיות האישיות שלך**\n\n"
            f"📂 תיקיה ראשית: `{user_folder}/`\n\n"
            f"💡 **איך להשתמש:**\n"
            f"• שלח טקסט רגיל - יישמר אוטומטית\n"
            f"• השתמש ב-/myfolder ליצירת תיקיה\n"
            f"• צור תיקיות משנה לפי נושאים\n\n"
            f"🎯 **רעיונות לארגון:**\n"
            f"• `{user_folder}/programming/`\n"
            f"• `{user_folder}/mathematics/`\n"
            f"• `{user_folder}/projects/`\n"
            f"• `{user_folder}/notes/`\n\n"
            f"🤖 **טיפ AI:** אתה יכול לבקש מה-AI לעזור\n"
            f"בארגון החומר הלימודי שלך!"
        )
        
        keyboard = [
            [InlineKeyboardButton("📁 צור תיקיה חדשה", callback_data="create_folder")],
            [InlineKeyboardButton("🤖 שאל AI על ארגון", callback_data="ask_ai_organization")],
            [InlineKeyboardButton("🔙 חזרה", callback_data="back_to_start")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(message, reply_markup=reply_markup)

    elif data == "create_folder":
        user_id = query.from_user.id
        user_folder = f"students/{user_id}"
        welcome_file = f"{user_folder}/welcome.txt"
        
        welcome_content = f"""ברוך הבא לתיקיה האישית שלך באקדמיה!

מידע תלמיד:
• שם: {query.from_user.first_name} {query.from_user.last_name or ''}
• שם משתמש: @{query.from_user.username or 'לא צוין'}
• ID: {user_id}
• תאריך יצירה: {datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}

בתיקיה זו תוכל לשמור:
• תרגילים
• שאלות
• פרויקטים
• סיכומים
• מטלות
• פרויקטים אישיים

🎓 אקדמיה להשכלה גבוהה - SLH Academia
"""
        
        ok = git.commit_and_push(welcome_file, welcome_content, f"Create personal folder for {query.from_user.first_name} ({user_id})")
        if ok:
            await query.edit_message_text(
                f"✅ **תיקיה אישית נוצרה!**\n\n"
                f"📁 `{user_folder}/`\n\n"
                f"🎓 כעת תוכל לשלוח טקסט ואשמור אותו בתיקיה שלך.\n"
                f"💡 כל מה שתשלח יישמר אוטומטית."
            )
        else:
            await query.edit_message_text("❌ שגיאה ביצירת תיקיה אישית. נסה שוב מאוחר יותר.")

    elif data == "ask_ai_organization":
        context.user_data['waiting_for_ai_question'] = True
        await query.edit_message_text(
            "🤖 **AI Assistant - ארגון למידה**\n\n"
            "שאל את ה-AI לעזרה בארגון החומר הלימודי:\n"
            "• 'איך לארגן תיקיות ללימוד תכנות?'\n"
            "• 'מה מבנה התיקיות המומלץ למתמטיקה?'\n"
            "• 'איך לנהל פרויקט programming?'\n"
            "• 'טיפים לארגון חומר לימודי'\n\n"
            "שלח את שאלתך now:"
        )

    elif data == "back_to_start":
        # Go back to start
        git._load_authorized_users()  # Reload to ensure latest data
        
        if is_authorized(user_id):
            balance = coin_system.get_balance(user_id)
            keyboard = [
                [InlineKeyboardButton("🎓 על האקדמיה", callback_data="about_academy")],
                [InlineKeyboardButton("🪙 מצב ארנק", callback_data="check_balance")],
                [InlineKeyboardButton("🤖 שאל את AI", callback_data="ask_ai")],
                [InlineKeyboardButton("📁 תיקיות אישיות", callback_data="personal_folders")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                f"👋 שלום! אני בוט הלימוד שלך.\n"
                f"💰 מטבעות בארנק: {balance}\n\n"
                "🏫 **ברוך הבא לאקדמיה להשכלה גבוהה!**\n\n"
                "פה תוכל:\n"
                "• ללמוד תחומים חדשים עם AI\n"
                "• לנהל את החומר הלימודי שלך\n"
                "• לקבל תגמולים במטבעות\n"
                "• להתפתח מקצועית\n\n"
                "השתמש בכפתורים למטה לניווט:",
                reply_markup=reply_markup
            )
        else:
            keyboard = [
                [InlineKeyboardButton("🎓 למה להירשם?", callback_data="why_join")],
                [InlineKeyboardButton("💳 רוצה להצטרף - תשלום", callback_data="request_access")],
                [InlineKeyboardButton("📞 יצירת קשר", callback_data="contact_info")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(
                "🏫 **אקדמיה להשכלה גבוהה - SLH Academia**\n\n"
                "❌ אין לך הרשאה להשתמש בבוט זה.\n\n"
                "💵 עלות גישה: 444 ש\"ח\n\n"
                "🎯 **מה תקבל לאחר הרישום:**\n"
                "• גישה לפורטל למידה מתקדם\n"
                "• ליווי AI אישי ללמידה\n"
                "• תיקיות לימוד אישיות\n"
                "• מערכת תגמולים במטבעות\n"
                "• קהילת לומדים פעילה\n\n"
                "לחץ על 'למה להירשם?' לפרטים נוספים:",
                reply_markup=reply_markup
            )

    elif data.startswith("approve_"):
        # Admin approves a user
        if not is_admin(user_id):
            await query.edit_message_text("❌ רק מנהלים יכולים לאשר משתמשים.")
            return

        target_user_id = int(data.split("_")[1])
        success = git.add_authorized_user(target_user_id)
        if success:
            # Notify the approved user
            try:
                await context.bot.send_message(
                    chat_id=target_user_id,
                    text=f"🎉 **הבקשה שלך אושרה!**\n\n"
                         f"🏫 **ברוך הבא לאקדמיה להשכלה גבוהה!**\n\n"
                         f"👥 **הצטרף לקבוצה:** {GROUP_LINK}\n\n"
                         f"📚 **מה עכשיו?**\n"
                         f"• שלח /start להתחלה\n"
                         f"• שאל את ה-AI שאלות\n"
                         f"• התחל לשמור חומר לימודי\n"
                         f"• צור תיקיות אישיות\n\n"
                         f"🎓 **SLH Academia**"
                )
            except Exception as e:
                logger.error("Failed to notify user %s: %s", target_user_id, e)

            await query.edit_message_text(
                f"✅ **משתמש {target_user_id} אושר בהצלחה!**\n\n"
                f"🏫 נשלח קישור לקבוצה והודעת ברכה."
            )
        else:
            await query.edit_message_text("❌ שגיאה באישור המשתמש. בדוק לוגים.")

    elif data.startswith("reject_"):
        # Admin rejects a user
        if not is_admin(user_id):
            await query.edit_message_text("❌ רק מנהלים יכולים לדחות משתמשים.")
            return

        target_user_id = int(data.split("_")[1])
        # Notify the rejected user
        try:
            await context.bot.send_message(
                chat_id=target_user_id,
                text="❌ **הבקשה שלך לגישה נדחתה.**\n\n"
                     "אם אתה חושב שזו טעות, פנה למנהל @Osif83"
            )
        except Exception as e:
            logger.error("Failed to notify user %s: %s", target_user_id, e)

        await query.edit_message_text(f"❌ משתמש {target_user_id} נדחה.")

    elif data == "mine_coins":
        if not is_admin(user_id):
            return
        
        context.user_data['waiting_for_mine_amount'] = True
        await query.edit_message_text("⛏️ **כריתת מטבעות**\n\nהזן כמות מטבעות לכרייה:")

    elif data == "transfer_coins":
        if not is_admin(user_id):
            return
        
        context.user_data['waiting_for_transfer_details'] = True
        await query.edit_message_text(
            "🎁 **העברת מטבעות**\n\n"
            "הזן בפורמט: `ID_משתמש,כמות,סיבה`\n\n"
            "**דוגמה:**\n"
            "`123456789,10,תגמול על מטלה מצוינת`\n"
            "`987654321,5,השתתפות פעילה בשיעור`"
        )

    elif data == "coin_stats":
        if not is_admin(user_id):
            return
        
        stats = coin_system.get_system_stats()
        await query.edit_message_text(
            f"📊 **סטטיסטיקות מערכת מטבעות:**\n\n"
            f"👥 משתמשים: {stats['total_users']}\n"
            f"⛏️ מטבעות שכורים: {stats['total_mined']}\n"
            f"🔗 עסקאות: {stats['total_transactions']}"
        )

# --- Photo handler for payment proof ---
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('waiting_for_payment_proof'):
        return
    
    user = update.effective_user
    photo = update.message.photo[-1]  # Get the highest resolution photo
    
    # Notify admins about payment proof
    message_text = (
        f"📸 **בקשת גישה עם הוכחת תשלום**\n\n"
        f"👤 **שם:** {user.first_name} {user.last_name or ''}\n"
        f"📱 **משתמש:** @{user.username or 'לא צוין'}\n"
        f"🆔 **ID:** {user.id}\n"
        f"💵 **סכום:** 444 ש\"ח\n"
        f"⏰ **תאריך:** {datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}\n\n"
        f"🏫 **אקדמיה להשכלה גבוהה**"
    )
    
    keyboard = [
        [
            InlineKeyboardButton("✅ אשר גישה", callback_data=f"approve_{user.id}"),
            InlineKeyboardButton("❌ דחה", callback_data=f"reject_{user.id}")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    # Send to all admins with photo
    sent_to_admins = False
    for admin_id in ADMIN_USER_IDS:
        try:
            # Send the photo with caption
            await context.bot.send_photo(
                chat_id=admin_id,
                photo=photo.file_id,
                caption=message_text,
                reply_markup=reply_markup
            )
            sent_to_admins = True
            logger.info("Payment proof sent to admin: %s", admin_id)
        except Exception as e:
            logger.error("Failed to send message to admin %s: %s", admin_id, e)

    if sent_to_admins:
        await update.message.reply_text(
            "📸 **תמונת התשלום נשלחה למנהל לאישור.**\n\n"
            "🏫 **אקדמיה להשכלה גבוהה**\n"
            "תקבל הודעה כאשר תאושר, בדרך כלל תוך 24 שעות.\n\n"
            "📚 **בינתיים, אתה יכול:**\n"
            "• להתכונן ללימודים\n"
            "• לחשוב על תחומי עניין\n"
            "• להכין שאלות למנחה"
        )
    else:
        await update.message.reply_text("❌ שגיאה בשליחת הבקשה. נסה שוב מאוחר יותר.")
    
    context.user_data['waiting_for_payment_proof'] = False

# --- Admin message handlers for coin system ---
async def handle_admin_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    
    user_id = update.effective_user.id
    text = update.message.text
    
    if context.user_data.get('waiting_for_mine_amount'):
        try:
            amount = int(text)
            if amount <= 0:
                await update.message.reply_text("❌ הכמות חייבת להיות חיובית")
                return
            
            context.user_data['mine_amount'] = amount
            context.user_data['waiting_for_mine_amount'] = False
            context.user_data['waiting_for_mine_reason'] = True
            
            await update.message.reply_text("📝 **הזן סיבה לכרייה:**\n\nלדוגמה: 'תגמול על מערכת חדשה'")
            
        except ValueError:
            await update.message.reply_text("❌ הכמות חייבת להיות מספר")
    
    elif context.user_data.get('waiting_for_mine_reason'):
        reason = text
        amount = context.user_data.get('mine_amount')
        
        success, message = coin_system.mine_coins(user_id, amount, reason)
        await update.message.reply_text(message)
        
        # Clean up
        context.user_data.pop('mine_amount', None)
        context.user_data.pop('waiting_for_mine_reason', None)
    
    elif context.user_data.get('waiting_for_transfer_details'):
        try:
            parts = text.split(',', 2)
            if len(parts) < 3:
                await update.message.reply_text("❌ פורמט לא תקין. השתמש ב: ID,כמות,סיבה")
                return
            
            target_user_id = int(parts[0].strip())
            amount = int(parts[1].strip())
            reason = parts[2].strip()
            
            if amount <= 0:
                await update.message.reply_text("❌ הכמות חייבת להיות חיובית")
                return
            
            success, message = coin_system.transfer_coins(user_id, target_user_id, amount, reason)
            await update.message.reply_text(message)
            
            # Clean up
            context.user_data.pop('waiting_for_transfer_details', None)
            
        except ValueError:
            await update.message.reply_text("❌ פורמט לא תקין. השתמש ב: ID,כמות,סיבה")

# --- Flask endpoints ---
@app.route("/", methods=["GET"])
def index():
    return "🚀 Telegram Git Bot - SLH Academia is running!"

@app.route("/health", methods=["GET"])
def health():
    return "✅ Healthy - SLH Academia"

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
    application.add_handler(CommandHandler("balance", balance_cmd))
    application.add_handler(CommandHandler("coins", coins_cmd))
    application.add_handler(CommandHandler("ask", ask_ai_cmd))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_messages))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_handler(CallbackQueryHandler(button_callback))

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
