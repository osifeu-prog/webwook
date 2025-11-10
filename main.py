import os
import logging
import subprocess
import datetime
import json
import uuid
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
GROUP_LINK = os.getenv("GROUP_LINK", "https://t.me/your_group_link")

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
            with open(authorized_users_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        try:
                            self.authorized_users.add(int(line))
                        except ValueError:
                            logger.warning("Invalid user ID in authorized_users.txt: %s", line)
        
        logger.info("Loaded %d authorized users", len(self.authorized_users))

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

    def add_authorized_user(self, user_id):
        authorized_users_file = os.path.join(self.repo_path, "authorized_users.txt")
        
        # Ensure the file exists with header
        if not os.path.exists(authorized_users_file):
            with open(authorized_users_file, "w", encoding="utf-8") as f:
                f.write("# Authorized users list\n")
                f.write("# Format: one user ID per line\n")
                f.write("# Admins are automatically added from ADMIN_USER_IDS\n\n")
        
        # Check if user already exists
        with open(authorized_users_file, "r", encoding="utf-8") as f:
            lines = f.readlines()
        
        user_exists = False
        for line in lines:
            if line.strip() == str(user_id):
                user_exists = True
                break
        
        if user_exists:
            return True  # already exists
        
        # Add the user
        with open(authorized_users_file, "a", encoding="utf-8") as f:
            f.write(f"{user_id}\n")
        
        # Commit and push the change
        try:
            run(["git", "-C", self.repo_path, "add", authorized_users_file], check=True)
            run(["git", "-C", self.repo_path, "commit", "-m", f"Add authorized user {user_id}"], check=True)
            run(["git", "-C", self.repo_path, "push", "origin", self.branch], check=True)
            self.authorized_users.add(user_id)
            logger.info("Added authorized user: %s", user_id)
            return True
        except Exception as e:
            logger.error("Failed to add authorized user: %s", e)
            return False

    def remove_authorized_user(self, user_id):
        authorized_users_file = os.path.join(self.repo_path, "authorized_users.txt")
        
        if not os.path.exists(authorized_users_file):
            return True  # nothing to remove
        
        # Read all lines and remove the user
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
        try:
            run(["git", "-C", self.repo_path, "add", authorized_users_file], check=True)
            run(["git", "-C", self.repo_path, "commit", "-m", f"Remove authorized user {user_id}"], check=True)
            run(["git", "-C", self.repo_path, "push", "origin", self.branch], check=True)
            self.authorized_users.discard(user_id)
            logger.info("Removed authorized user: %s", user_id)
            return True
        except Exception as e:
            logger.error("Failed to remove authorized user: %s", e)
            return False

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
        with open(coins_path, "r", encoding="utf-8") as f:
            return json.load(f)

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

git = GitHandler(GIT_REPO_URL)
coin_system = CoinSystem(git)

# --- בדיקת הרשאה ---
def is_authorized(user_id):
    return user_id in git.authorized_users

def is_admin(user_id):
    return user_id in ADMIN_USER_IDS

# --- פקודות טלגרם ---
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if is_authorized(user_id):
        balance = coin_system.get_balance(user_id)
        await update.message.reply_text(
            f"👋 שלום! אני בוט הלימוד שלך.\n"
            f"💰 מטבעות בארנק: {balance}\n\n"
            "פקודות זמינות:\n"
            "/start - הודעה זו\n"
            "/help - עזרה\n"
            "/gitstatus - מצב הריפו\n"
            "/myfolder - פתיחת תיקיה אישית\n"
            "/balance - מצב ארנק\n"
            "/coins - ניהול מטבעות (למנהלים)\n\n"
            "שלח טקסט רגיל ואשמור אותו בתיקיה האישית שלך."
        )
    else:
        keyboard = [
            [InlineKeyboardButton("📨 בקש גישה + תשלום", callback_data="request_access")],
            [InlineKeyboardButton("💳 שלחתי תשלום - אישור", callback_data="confirm_payment")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            "❌ אין לך הרשאה להשתמש בבוט זה.\n\n"
            "💵 עלות גישה: 444 ש\"ח\n\n"
            "אם אתה תלמיד, אתה יכול לבקש גישה לאחר תשלום:\n"
            "1. שלח 444 ש\"ח\n"
            "2. לחץ על 'שלחתי תשלום'\n"
            "3. שלח צילום מסך של התשלום\n"
            "4. המנהל יאשר את הגישה",
            reply_markup=reply_markup
        )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        return
    await update.message.reply_text(
        "📖 עזרה:\n\n"
        "• שלח טקסט רגיל - יישמר בתיקיה האישית שלך\n"
        "• /gitstatus - מציג את הקומיטים האחרונים\n"
        "• /myfolder - פותח תיקיה אישית חדשה\n"
        "• /balance - מצב מטבעות בארנק\n"
        "• /transactions - היסטוריית עסקאות\n"
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
    
    # Check if this is a payment confirmation with photo
    if context.user_data.get('waiting_for_payment_proof'):
        # This will be handled by the photo handler
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

# --- Coin System Commands ---
async def balance_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        return
    
    user_id = update.effective_user.id
    balance = coin_system.get_balance(user_id)
    transactions = coin_system.get_transaction_history(user_id, 5)
    
    message = f"💰 מצב ארנק:\n\nמטבעות: {balance}\n\n"
    message += "🔗 עסקאות אחרונות:\n"
    
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
        f"🪙 ניהול מטבעות - מנהל\n\n"
        f"📈 סטטיסטיקות:\n"
        f"• משתמשים: {stats['total_users']}\n"
        f"• מטבעות שכורים: {stats['total_mined']}\n"
        f"• עסקאות: {stats['total_transactions']}",
        reply_markup=reply_markup
    )

# --- Payment and Access Request System ---
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    data = query.data

    if data == "request_access":
        # User requests access - show payment instructions
        payment_info = (
            "💵 תשלום עבור גישה לבוט:\n\n"
            "סכום: 444 ש\"ח\n\n"
            "אחרי התשלום:\n"
            "1. לחץ על 'שלחתי תשלום'\n"
            "2. שלח צילום מסך של ההעברה\n"
            "3. המנהל יאשר את הגישה\n\n"
            "📧 לשאלות: פנה למנהל"
        )
        
        keyboard = [
            [InlineKeyboardButton("💳 שלחתי תשלום - אישור", callback_data="confirm_payment")],
            [InlineKeyboardButton("🔙 חזרה", callback_data="back_to_start")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(payment_info, reply_markup=reply_markup)

    elif data == "confirm_payment":
        # User confirms payment - ask for photo proof
        context.user_data['waiting_for_payment_proof'] = True
        await query.edit_message_text(
            "📸 שלח צילום מסך של התשלום כרגע.\n\n"
            "התמונה תישלח למנהל לאישור."
        )

    elif data == "back_to_start":
        # Go back to start
        if is_authorized(user_id):
            balance = coin_system.get_balance(user_id)
            await query.edit_message_text(
                f"👋 שלום! אני בוט הלימוד שלך.\n"
                f"💰 מטבעות בארנק: {balance}\n\n"
                "פקודות זמינות:\n"
                "/start - הודעה זו\n"
                "/help - עזרה\n"
                "/gitstatus - מצב הריפו\n"
                "/myfolder - פתיחת תיקיה אישית\n"
                "/balance - מצב ארנק\n"
                "/coins - ניהול מטבעות (למנהלים)\n\n"
                "שלח טקסט רגיל ואשמור אותו בתיקיה האישית שלך."
            )
        else:
            keyboard = [
                [InlineKeyboardButton("📨 בקש גישה + תשלום", callback_data="request_access")],
                [InlineKeyboardButton("💳 שלחתי תשלום - אישור", callback_data="confirm_payment")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(
                "❌ אין לך הרשאה להשתמש בבוט זה.\n\n"
                "💵 עלות גישה: 444 ש\"ח\n\n"
                "אם אתה תלמיד, אתה יכול לבקש גישה לאחר תשלום:\n"
                "1. שלח 444 ש\"ח\n"
                "2. לחץ על 'שלחתי תשלום'\n"
                "3. שלח צילום מסך של התשלום\n"
                "4. המנהל יאשר את הגישה",
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
                    text=f"🎉 הבקשה שלך אושרה! כעת אתה יכול להשתמש בבוט.\n\n"
                         f"👥 הצטרף לקבוצה: {GROUP_LINK}\n\n"
                         f"שלח /start להתחלה."
                )
            except Exception as e:
                logger.error("Failed to notify user %s: %s", target_user_id, e)

            await query.edit_message_text(f"✅ משתמש {target_user_id} אושר בהצלחה! נשלח קישור לקבוצה.")
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
                text="❌ הבקשה שלך לגישה נדחתה. אם אתה חושב שזו טעות, פנה למנהל."
            )
        except Exception as e:
            logger.error("Failed to notify user %s: %s", target_user_id, e)

        await query.edit_message_text(f"❌ משתמש {target_user_id} נדחה.")

    elif data == "mine_coins":
        if not is_admin(user_id):
            return
        
        context.user_data['waiting_for_mine_amount'] = True
        await query.edit_message_text("⛏️ כריתת מטבעות\n\nהזן כמות מטבעות לכרייה:")

    elif data == "transfer_coins":
        if not is_admin(user_id):
            return
        
        context.user_data['waiting_for_transfer_details'] = True
        await query.edit_message_text("🎁 העברת מטבעות\n\nהזן בפורמט: ID_משתמש,כמות,סיבה\n\nדוגמה: 123456789,10,תגמול על מטלה")

    elif data == "coin_stats":
        if not is_admin(user_id):
            return
        
        stats = coin_system.get_system_stats()
        await query.edit_message_text(
            f"📊 סטטיסטיקות מערכת מטבעות:\n\n"
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
        f"📸 בקשת גישה עם הוכחת תשלום:\n\n"
        f"👤 שם: {user.first_name} {user.last_name or ''}\n"
        f"📱 משתמש: @{user.username or 'לא צוין'}\n"
        f"🆔 ID: {user.id}\n"
        f"💵 סכום: 444 ש\"ח\n"
        f"⏰ תאריך: {datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}"
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
        await update.message.reply_text("📸 תמונת התשלום נשלחה למנהל לאישור. תקבל הודעה כאשר תאושר.")
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
            
            await update.message.reply_text("📝 הזן סיבה לכרייה:")
            
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
    application.add_handler(CommandHandler("balance", balance_cmd))
    application.add_handler(CommandHandler("coins", coins_cmd))
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
