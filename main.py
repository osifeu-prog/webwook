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
from typing import Dict, List, Optional, Any, Tuple
import time
from functools import wraps
from prometheus_client import Counter, Histogram, Gauge, generate_latest
from flask import Response

# ===== CONFIGURATION =====
class Config:
    """ניהול תצורת המערכת"""
    def __init__(self):
        self.BOT_TOKEN = os.getenv("TELEGRAM_TOKEN") or os.getenv("BOT_TOKEN")
        self.WEBHOOK_URL = os.getenv("WEBHOOK_URL")
        self.GIT_REPO_URL = os.getenv("GIT_REPO_URL")
        self.GIT_BRANCH = os.getenv("GIT_BRANCH", "main")
        self.GIT_USERNAME = os.getenv("GIT_USERNAME", "telegram-bot")
        self.GIT_EMAIL = os.getenv("GIT_EMAIL", "bot@example.com")
        self.PORT = int(os.getenv("PORT", 8080))
        self.GROUP_LINK = os.getenv("GROUP_LINK", "https://t.me/+mIYkHnpCj6g2ZmRk")
        self.OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
        self.HUGGINGFACE_API_KEY = os.getenv("HUGGINGFACE_API_KEY")
        self.SECRET_TOKEN = os.getenv("SECRET_TOKEN")
        
        # Admin configuration
        admin_ids_str = os.getenv("ADMIN_USER_IDS", "224223270")
        self.ADMIN_USER_IDS = self._parse_admin_ids(admin_ids_str)
        
        self._validate_required_config()
    
    def _parse_admin_ids(self, admin_ids_str: str) -> List[int]:
        """פרסור IDsof מנהלים"""
        try:
            return [int(x.strip()) for x in admin_ids_str.split(",") if x.strip()]
        except ValueError as e:
            logging.error("Error parsing ADMIN_USER_IDS: %s", e)
            return [224223270]  # fallback
    
    def _validate_required_config(self):
        """ולידציה של תצורה נדרשת"""
        if not self.BOT_TOKEN:
            raise SystemExit("❌ Missing required environment variable: BOT_TOKEN or TELEGRAM_TOKEN.")
        if not self.WEBHOOK_URL:
            raise SystemExit("❌ Missing required environment variable: WEBHOOK_URL.")
        if not self.GIT_REPO_URL:
            raise SystemExit("❌ Missing required environment variable: GIT_REPO_URL.")

# ===== LOGGING SETUP =====
class SecureFormatter(logging.Formatter):
    """פורמטר לוגים מאובטח שמסתיר מידע רגיש"""
    def format(self, record):
        message = super().format(record)
        # הסתרת טוקנים ומידע רגיש בלוגים
        sensitive_keys = ['BOT_TOKEN', 'OPENAI_API_KEY', 'HUGGINGFACE_API_KEY', 'SECRET_TOKEN']
        for key in sensitive_keys:
            value = os.getenv(key)
            if value:
                message = message.replace(value, f"{key}_REDACTED")
        return message

# הגדרת לוגינג
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

# החלת הפורמטר המוגן
for handler in logging.root.handlers:
    handler.setFormatter(SecureFormatter("%(asctime)s - %(levelname)s - %(message)s"))

logger = logging.getLogger(__name__)

# ===== PROMETHEUS METRICS =====
REQUEST_COUNT = Counter('http_requests_total', 'Total HTTP Requests', ['method', 'endpoint', 'status'])
REQUEST_LATENCY = Histogram('http_request_duration_seconds', 'HTTP request latency', ['endpoint'])
ACTIVE_USERS = Gauge('active_users', 'Number of active users')
COIN_BALANCE = Gauge('coin_balance', 'User coin balance', ['user_id'])
GIT_SYNC_STATUS = Gauge('git_sync_status', 'Git repository sync status')
AI_REQUESTS = Counter('ai_requests_total', 'Total AI requests', ['model', 'status'])

# ===== UTILITIES =====
class CommandRunner:
    """מנהל הרצת פקודות מערכת"""
    
    @staticmethod
    def run(cmd: List[str], **kwargs) -> subprocess.CompletedProcess:
        """הרצת פקודה עם לוגינג"""
        logger.debug("RUN: %s", " ".join(cmd))
        return subprocess.run(cmd, **kwargs)

class DateTimeUtils:
    """כלי עזר לניהול תאריכים וזמנים"""
    
    @staticmethod
    def get_timestamp() -> str:
        """מחזיר טיימסטאמפ לפורמט YYYYMMDD_HHMMSS"""
        return datetime.datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    
    @staticmethod
    def get_iso_timestamp() -> str:
        """מחזיר תאריך בפורמט ISO"""
        return datetime.datetime.utcnow().isoformat()
    
    @staticmethod
    def get_formatted_datetime() -> str:
        """מחזיר תאריך בפורמט קריא"""
        return datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')

class ValidationUtils:
    """כלי עזר לוולידציה"""
    
    @staticmethod
    def is_valid_user_id(user_id: Any) -> bool:
        """וולידציה של ID משתמש"""
        try:
            return isinstance(user_id, int) and user_id > 0
        except (ValueError, TypeError):
            return False
    
    @staticmethod
    def is_valid_amount(amount: Any) -> bool:
        """וולידציה של כמות מטבעות"""
        try:
            return isinstance(amount, (int, float)) and amount > 0
        except (ValueError, TypeError):
            return False

# ===== AI SERVICES =====
class AIService:
    """שירות AI מאוחד עם תמיכה במודלים שונים"""
    
    def __init__(self, config: Config):
        self.config = config
        self.models = {
            'gpt-3.5-turbo': 'openai',
            'gpt-4': 'openai',
            'microsoft/DialoGPT-large': 'huggingface',
            'facebook/blenderbot-400M-distill': 'huggingface'
        }
    
    def ask_ai(self, prompt: str, model: str = "gpt-3.5-turbo") -> str:
        """שליחת שאלה ל-AI עם בחירת מודל"""
        model_type = self.models.get(model, 'openai')
        
        if model_type == 'openai':
            return self._ask_openai(prompt, model)
        else:
            return self._ask_huggingface(prompt, model)
    
    def _ask_openai(self, prompt: str, model: str = "gpt-3.5-turbo") -> str:
        """שימוש ב-OpenAI API"""
        if not self.config.OPENAI_API_KEY:
            return self._get_default_response()
        
        headers = {
            "Authorization": f"Bearer {self.config.OPENAI_API_KEY}",
            "Content-Type": "application/json"
        }
        
        data = {
            "model": model,
            "messages": [
                {"role": "system", "content": "אתה עוזר AI לאקדמיה להשכלה גבוהה. ענה בעברית."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.7,
            "max_tokens": 1000
        }
        
        try:
            response = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers=headers,
                json=data,
                timeout=30
            )
            
            AI_REQUESTS.labels(model=model, status=response.status_code).inc()
            
            if response.status_code == 200:
                return response.json()["choices"][0]["message"]["content"]
            else:
                logger.error("OpenAI API error: %s", response.status_code)
                return f"❌ שגיאה ב-OpenAI API: {response.status_code}"
                
        except requests.exceptions.Timeout:
            AI_REQUESTS.labels(model=model, status='timeout').inc()
            return "❌ פסק זמן בבקשה ל-OpenAI. נסה שוב מאוחר יותר."
        except Exception as e:
            AI_REQUESTS.labels(model=model, status='error').inc()
            logger.error("OpenAI request failed: %s", str(e))
            return f"❌ בקשת OpenAI נכשלה: {str(e)}"
    
    def _ask_huggingface(self, prompt: str, model: str = "microsoft/DialoGPT-large") -> str:
        """שימוש ב-HuggingFace API"""
        if not self.config.HUGGINGFACE_API_KEY:
            return "❌ HuggingFace API key not configured"
        
        headers = {
            "Authorization": f"Bearer {self.config.HUGGINGFACE_API_KEY}",
            "Content-Type": "application/json"
        }
        
        data = {
            "inputs": prompt,
            "parameters": {
                "max_length": 500,
                "temperature": 0.7,
                "do_sample": True,
                "return_full_text": False
            }
        }
        
        try:
            response = requests.post(
                f"https://api-inference.huggingface.co/models/{model}",
                headers=headers,
                json=data,
                timeout=30
            )
            
            AI_REQUESTS.labels(model=model, status=response.status_code).inc()
            
            if response.status_code == 200:
                result = response.json()
                if isinstance(result, list) and len(result) > 0:
                    return result[0].get("generated_text", prompt)
                return prompt
            else:
                logger.error("HuggingFace API error: %s", response.status_code)
                return f"❌ שגיאה ב-HuggingFace API: {response.status_code}"
                
        except requests.exceptions.Timeout:
            AI_REQUESTS.labels(model=model, status='timeout').inc()
            return "❌ פסק זמן בבקשה ל-HuggingFace. נסה שוב מאוחר יותר."
        except Exception as e:
            AI_REQUESTS.labels(model=model, status='error').inc()
            logger.error("HuggingFace request failed: %s", str(e))
            return f"❌ בקשת HuggingFace נכשלה: {str(e)}"
    
    def _get_default_response(self) -> str:
        """תגובת ברירת מחדל כאשר אין API key"""
        return (
            "🤖 **תשובת AI:**\n\n"
            "אני כאן כדי לעזור לך עם שאלות על לימודים!\n\n"
            "💡 **טיפ:** אתה יכול לשאול אותי על:\n"
            "• הסברים בתחומי הלימוד\n• פתרון תרגילים\n"
            "• הנחיה בפרויקטים\n• ארגון חומר לימודי\n\n"
            "🎓 **אקדמיה להשכלה גבוהה - SLH Academia**"
        )

# ===== GIT MANAGEMENT =====
class GitHandler:
    """מנהל Git מתקדם עם caching ואופטימיזציות"""
    
    def __init__(self, config: Config, repo_path: str = ".git_repo"):
        self.config = config
        self.repo_url = config.GIT_REPO_URL
        self.repo_path = repo_path
        self.branch = config.GIT_BRANCH
        self.authorized_users = set()
        self.last_sync = None
        self._configure_git()
        self._prepare_repo()
        self._load_authorized_users()
    
    def _configure_git(self):
        """הגדרות Git גלובליות"""
        try:
            CommandRunner.run(["git", "config", "--global", "user.name", self.config.GIT_USERNAME], check=True)
            CommandRunner.run(["git", "config", "--global", "user.email", self.config.GIT_EMAIL], check=True)
            logger.info("Git configured: %s <%s>", self.config.GIT_USERNAME, self.config.GIT_EMAIL)
        except subprocess.CalledProcessError as e:
            logger.warning("Git config failed: %s", e)
    
    def _prepare_repo(self):
        """הכנת הריפוזיטורי - clone או pull"""
        if os.path.isdir(os.path.join(self.repo_path, ".git")):
            self._sync_repo()
        else:
            self._clone_repo()
    
    def _sync_repo(self):
        """סנכרון הריפוזיטורי עם origin"""
        try:
            CommandRunner.run(["git", "-C", self.repo_path, "pull", "origin", self.branch], check=True)
            self.last_sync = DateTimeUtils.get_iso_timestamp()
            logger.info("Repository synced successfully")
            GIT_SYNC_STATUS.set(1)
        except subprocess.CalledProcessError as e:
            logger.warning("Pull failed: %s, attempting re-clone", e)
            self._force_reclone()
    
    def _clone_repo(self):
        """Clone של הריפוזיטורי"""
        try:
            CommandRunner.run(["git", "clone", "-b", self.branch, self.repo_url, self.repo_path], check=True)
            self.last_sync = DateTimeUtils.get_iso_timestamp()
            logger.info("Repository cloned successfully")
            GIT_SYNC_STATUS.set(1)
        except subprocess.CalledProcessError as e:
            logger.error("Clone failed: %s", e)
            GIT_SYNC_STATUS.set(0)
            raise
    
    def _force_reclone(self):
        """כופה clone מחדש של הריפוזיטורי"""
        import shutil
        try:
            shutil.rmtree(self.repo_path, ignore_errors=True)
            self._clone_repo()
        except Exception as e:
            logger.error("Force re-clone failed: %s", e)
            GIT_SYNC_STATUS.set(0)
            raise
    
    def _load_authorized_users(self):
        """טעינת משתמשים מורשים מהקובץ"""
        authorized_users_file = os.path.join(self.repo_path, "authorized_users.txt")
        self.authorized_users = set()
        
        # הוספת מנהלים
        for admin_id in self.config.ADMIN_USER_IDS:
            self.authorized_users.add(admin_id)
        
        # טעינה מהקובץ
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
        
        logger.info("Loaded %d authorized users", len(self.authorized_users))
        ACTIVE_USERS.set(len(self.authorized_users))
    
    def repo_ready(self) -> bool:
        """בודק אם הריפוזיטורי מוכן"""
        return os.path.isdir(os.path.join(self.repo_path, ".git"))
    
    def get_repo_status(self) -> Dict[str, Any]:
        """מחזיר סטטוס מלא של הריפוזיטורי"""
        if not self.repo_ready():
            return {"status": "not_ready", "last_sync": self.last_sync}
        
        try:
            # בדיקת שינויים שלא commit
            status_result = CommandRunner.run(
                ["git", "-C", self.repo_path, "status", "--porcelain"], 
                capture_output=True, text=True
            )
            has_changes = bool(status_result.stdout.strip())
            
            # commit אחרון
            last_commit_result = CommandRunner.run(
                ["git", "-C", self.repo_path, "log", "-1", "--pretty=format:%h - %s - %ad", "--date=short"],
                capture_output=True, text=True
            )
            last_commit = last_commit_result.stdout.strip() if last_commit_result.returncode == 0 else "Unknown"
            
            return {
                "status": "ready",
                "last_sync": self.last_sync,
                "has_changes": has_changes,
                "last_commit": last_commit,
                "branch": self.branch
            }
        except Exception as e:
            logger.error("Error getting repo status: %s", e)
            return {"status": "error", "error": str(e)}
    
    def commit_and_push(self, filename: str, content: str, message: str) -> bool:
        """commit ו-push עם טיפול בשגיאות מתקדם"""
        if not self.repo_ready():
            logger.error("Repo not ready for commit")
            return False
        
        abs_path = os.path.join(self.repo_path, filename)
        
        try:
            # יצירת תיקיות אם צריך
            os.makedirs(os.path.dirname(abs_path), exist_ok=True)
            
            # כתיבה לקובץ
            with open(abs_path, "w", encoding="utf-8") as f:
                f.write(content)
            
            # git add
            CommandRunner.run(["git", "-C", self.repo_path, "add", filename], check=True)
            
            # בדיקה אם יש שינויים
            status = CommandRunner.run(
                ["git", "-C", self.repo_path, "status", "--porcelain"], 
                capture_output=True, text=True
            )
            
            if not status.stdout.strip():
                logger.info("No changes to commit for %s", filename)
                return True
            
            # commit ו-push
            CommandRunner.run(["git", "-C", self.repo_path, "commit", "-m", message], check=True)
            CommandRunner.run(["git", "-C", self.repo_path, "push", "origin", self.branch], check=True)
            
            self.last_sync = DateTimeUtils.get_iso_timestamp()
            logger.info("Successfully committed and pushed: %s", filename)
            return True
            
        except subprocess.CalledProcessError as e:
            logger.error("Git operation failed for %s: %s", filename, e)
            return False
        except Exception as e:
            logger.error("Unexpected error in commit_and_push: %s", e)
            return False
    
    def add_authorized_user(self, user_id: int) -> bool:
        """הוספת משתמש מורשה"""
        authorized_users_file = os.path.join(self.repo_path, "authorized_users.txt")
        
        # יצירת קובץ אם לא קיים
        if not os.path.exists(authorized_users_file):
            with open(authorized_users_file, "w", encoding="utf-8") as f:
                f.write("# Authorized users list\n# Format: one user ID per line\n# Admins are automatically added\n\n")
        
        # בדיקה אם המשתמש כבר קיים
        try:
            with open(authorized_users_file, "r", encoding="utf-8") as f:
                lines = f.readlines()
            
            user_exists = any(line.strip() == str(user_id) for line in lines)
            
            if user_exists:
                logger.info("User %s already in authorized list", user_id)
                self.authorized_users.add(user_id)
                ACTIVE_USERS.set(len(self.authorized_users))
                return True
            
            # הוספת המשתמש
            with open(authorized_users_file, "a", encoding="utf-8") as f:
                f.write(f"{user_id}\n")
            
            # commit השינוי
            success = self.commit_and_push(
                "authorized_users.txt", 
                "".join(lines + [f"{user_id}\n"]), 
                f"Add authorized user {user_id}"
            )
            
            if success:
                self.authorized_users.add(user_id)
                ACTIVE_USERS.set(len(self.authorized_users))
                logger.info("Added authorized user: %s", user_id)
                return True
            else:
                logger.error("Failed to commit authorized user addition")
                return False
                
        except Exception as e:
            logger.error("Failed to add authorized user: %s", e)
            return False
    
    def remove_authorized_user(self, user_id: int) -> bool:
        """הסרת משתמש מורשה"""
        authorized_users_file = os.path.join(self.repo_path, "authorized_users.txt")
        
        if not os.path.exists(authorized_users_file):
            return True
        
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
                return True
            
            # כתיבה מחדש ללא המשתמש
            with open(authorized_users_file, "w", encoding="utf-8") as f:
                f.writelines(new_lines)
            
            # commit השינוי
            success = self.commit_and_push(
                "authorized_users.txt", 
                "".join(new_lines), 
                f"Remove authorized user {user_id}"
            )
            
            if success:
                self.authorized_users.discard(user_id)
                ACTIVE_USERS.set(len(self.authorized_users))
                logger.info("Removed authorized user: %s", user_id)
                return True
            else:
                return False
                
        except Exception as e:
            logger.error("Failed to remove authorized user: %s", e)
            return False

# ===== COIN SYSTEM =====
class CoinSystem:
    """מערכת מטבעות מתקדמת עם ניהול עסקאות"""
    
    def __init__(self, git_handler: GitHandler):
        self.git = git_handler
        self.coins_file = "coins/coins.json"
        self._ensure_coins_file()
    
    def _ensure_coins_file(self):
        """וידוא שקובץ המטבעות קיים"""
        coins_path = os.path.join(self.git.repo_path, self.coins_file)
        if not os.path.exists(coins_path):
            os.makedirs(os.path.dirname(coins_path), exist_ok=True)
            initial_data = {
                "coins": {},
                "transactions": [],
                "total_mined": 0,
                "system_created": DateTimeUtils.get_iso_timestamp()
            }
            with open(coins_path, "w", encoding="utf-8") as f:
                json.dump(initial_data, f, indent=2, ensure_ascii=False)
            self.git.commit_and_push(
                self.coins_file, 
                json.dumps(initial_data, indent=2), 
                "Initialize coins system"
            )
    
    def _load_coins_data(self) -> Dict[str, Any]:
        """טעינת נתוני מטבעות"""
        coins_path = os.path.join(self.git.repo_path, self.coins_file)
        try:
            with open(coins_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error("Error loading coins data: %s", e)
            return {"coins": {}, "transactions": [], "total_mined": 0}
    
    def _save_coins_data(self, data: Dict[str, Any]) -> bool:
        """שמירת נתוני מטבעות"""
        coins_path = os.path.join(self.git.repo_path, self.coins_file)
        try:
            with open(coins_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            return self.git.commit_and_push(
                self.coins_file, 
                json.dumps(data, indent=2), 
                "Update coins data"
            )
        except Exception as e:
            logger.error("Error saving coins data: %s", e)
            return False
    
    def mine_coins(self, admin_id: int, amount: int, reason: str) -> Tuple[bool, str]:
        """כריית מטבעות חדשים - מנהלים בלבד"""
        if admin_id not in self.git.config.ADMIN_USER_IDS:
            return False, "רק מנהלים יכולים לכרות מטבעות"
        
        if amount <= 0:
            return False, "הכמות חייבת להיות חיובית"
        
        data = self._load_coins_data()
        transaction_id = str(uuid.uuid4())[:8]
        
        transaction = {
            "id": transaction_id,
            "type": "mine",
            "from": "system",
            "to": str(admin_id),
            "amount": amount,
            "reason": reason,
            "timestamp": DateTimeUtils.get_iso_timestamp(),
            "admin": str(admin_id)
        }
        
        # עדכון יתרת המנהל
        if str(admin_id) not in data["coins"]:
            data["coins"][str(admin_id)] = 0
        data["coins"][str(admin_id)] += amount
        data["total_mined"] += amount
        data["transactions"].append(transaction)
        
        if self._save_coins_data(data):
            COIN_BALANCE.labels(user_id=str(admin_id)).set(data["coins"][str(admin_id)])
            return True, f"✅ כריתת {amount} מטבעות הצליחה!\nמספר עסקה: {transaction_id}\nסיבה: {reason}"
        else:
            return False, "❌ שגיאה בשמירת כריתת המטבעות"
    
    def transfer_coins(self, from_user_id: int, to_user_id: int, amount: int, reason: str) -> Tuple[bool, str]:
        """העברת מטבעות בין משתמשים"""
        if amount <= 0:
            return False, "הכמות חייבת להיות חיובית"
        
        if from_user_id == to_user_id:
            return False, "❌ לא ניתן להעביר מטבעות לעצמך"
        
        data = self._load_coins_data()
        
        # בדיקה אם לשולח יש מספיק מטבעות
        if (str(from_user_id) not in data["coins"] or 
            data["coins"][str(from_user_id)] < amount):
            return False, "❌ אין מספיק מטבעות בארנק"
        
        transaction_id = str(uuid.uuid4())[:8]
        
        transaction = {
            "id": transaction_id,
            "type": "transfer",
            "from": str(from_user_id),
            "to": str(to_user_id),
            "amount": amount,
            "reason": reason,
            "timestamp": DateTimeUtils.get_iso_timestamp()
        }
        
        # עדכון יתרות
        data["coins"][str(from_user_id)] -= amount
        if str(to_user_id) not in data["coins"]:
            data["coins"][str(to_user_id)] = 0
        data["coins"][str(to_user_id)] += amount
        data["transactions"].append(transaction)
        
        if self._save_coins_data(data):
            COIN_BALANCE.labels(user_id=str(from_user_id)).set(data["coins"][str(from_user_id)])
            COIN_BALANCE.labels(user_id=str(to_user_id)).set(data["coins"][str(to_user_id)])
            return True, f"✅ העברת {amount} מטבעות הצליחה!\nמספר עסקה: {transaction_id}\nסיבה: {reason}"
        else:
            return False, "❌ שגיאה בשמירת העברת המטבעות"
    
    def get_balance(self, user_id: int) -> int:
        """קבלת יתרת מטבעות"""
        data = self._load_coins_data()
        balance = data["coins"].get(str(user_id), 0)
        COIN_BALANCE.labels(user_id=str(user_id)).set(balance)
        return balance
    
    def get_transaction_history(self, user_id: int, limit: int = 10) -> List[Dict]:
        """היסטוריית עסקאות למשתמש"""
        data = self._load_coins_data()
        user_transactions = []
        
        for tx in reversed(data["transactions"]):
            if tx["from"] == str(user_id) or tx["to"] == str(user_id):
                user_transactions.append(tx)
            if len(user_transactions) >= limit:
                break
        
        return user_transactions
    
    def get_system_stats(self) -> Dict[str, Any]:
        """סטטיסטיקות מערכת"""
        data = self._load_coins_data()
        
        # חישוב סכום מטבעות כולל
        total_coins = sum(data["coins"].values())
        
        return {
            "total_users": len(data["coins"]),
            "total_mined": data["total_mined"],
            "total_coins": total_coins,
            "total_transactions": len(data["transactions"]),
            "system_created": data.get("system_created", "Unknown")
        }
    
    def get_user_rankings(self, limit: int = 10) -> List[Tuple[int, int]]:
        """דירוג משתמשים לפי כמות מטבעות"""
        data = self._load_coins_data()
        
        # יצירת רשימת (user_id, balance) ממוינת
        rankings = []
        for user_id_str, balance in data["coins"].items():
            if balance > 0:  # רק משתמשים עם מטבעות
                rankings.append((int(user_id_str), balance))
        
        # מיון לפי כמות מטבעות (יורד)
        rankings.sort(key=lambda x: x[1], reverse=True)
        
        return rankings[:limit]

# ===== FLASK APP & MONITORING =====
app = Flask(__name__)

# Initialize components
config = Config()

# Log startup with secure info
logger.info("Bot starting with secure logging. Admin users: %s", config.ADMIN_USER_IDS)

# Initialize services
ai_service = AIService(config)
git_handler = GitHandler(config)
coin_system = CoinSystem(git_handler)

# ===== MONITORING DECORATORS =====
def monitor_requests(func):
    """Decorator for monitoring HTTP requests"""
    @wraps(func)
    def wrapper(*args, **kwargs):
        start_time = time.time()
        
        try:
            response = func(*args, **kwargs)
            status_code = getattr(response, 'status_code', 200)
            REQUEST_COUNT.labels(method='GET', endpoint=func.__name__, status=status_code).inc()
            return response
        except Exception as e:
            REQUEST_COUNT.labels(method='GET', endpoint=func.__name__, status=500).inc()
            raise e
        finally:
            latency = time.time() - start_time
            REQUEST_LATENCY.labels(endpoint=func.__name__).observe(latency)
    
    return wrapper

# ===== FLASK ROUTES =====
@app.route("/", methods=["GET"])
@monitor_requests
def index():
    return "🚀 Telegram Git Bot - SLH Academia is running!"

@app.route("/health", methods=["GET"])
@monitor_requests
def health():
    return "✅ Healthy - SLH Academia"

@app.route("/metrics", methods=["GET"])
def metrics():
    """Endpoint for Prometheus metrics"""
    return Response(generate_latest(), mimetype='text/plain')

@app.route("/health/detailed", methods=["GET"])
@monitor_requests
def detailed_health():
    """בדיקת בריאות מפורטת"""
    health_status = {
        'status': 'healthy',
        'timestamp': time.time(),
        'checks': {}
    }
    
    # Check Git repository
    try:
        repo_ready = git_handler.repo_ready()
        health_status['checks']['git_repo'] = {
            'status': 'healthy' if repo_ready else 'unhealthy',
            'details': git_handler.get_repo_status()
        }
    except Exception as e:
        health_status['checks']['git_repo'] = {
            'status': 'unhealthy',
            'error': str(e)
        }
    
    # Check coin system
    try:
        coin_stats = coin_system.get_system_stats()
        health_status['checks']['coin_system'] = {
            'status': 'healthy',
            'details': coin_stats
        }
    except Exception as e:
        health_status['checks']['coin_system'] = {
            'status': 'unhealthy',
            'error': str(e)
        }
    
    # Update overall status
    unhealthy_checks = [
        check for check in health_status['checks'].values() 
        if check['status'] == 'unhealthy'
    ]
    
    if unhealthy_checks:
        health_status['status'] = 'unhealthy'
    
    return health_status

@app.route("/webhook/" + (config.BOT_TOKEN or ""), methods=["POST"])
def webhook():
    if config.BOT_TOKEN:
        application = Application.builder().token(config.BOT_TOKEN).build()
        update = Update.de_json(request.get_json(), application.bot)
        application.process_update(update)
    return "OK"

# ===== TELEGRAM BOT HANDLERS =====
def is_authorized(user_id: int) -> bool:
    """בדיקת הרשאות משתמש"""
    return user_id in git_handler.authorized_users

def is_admin(user_id: int) -> bool:
    """בדיקה אם משתמש הוא מנהל"""
    return user_id in config.ADMIN_USER_IDS

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """פקודת /start"""
    user_id = update.effective_user.id
    
    # רענון רשימת משתמשים מורשים
    git_handler._load_authorized_users()
    
    if is_authorized(user_id):
        balance = coin_system.get_balance(user_id)
        keyboard = [
            [InlineKeyboardButton("🎓 על האקדמיה", callback_data="about_academy")],
            [InlineKeyboardButton("🪙 מצב ארנק", callback_data="check_balance")],
            [InlineKeyboardButton("🤖 שאל את AI", callback_data="ask_ai")],
            [InlineKeyboardButton("📁 תיקיות אישיות", callback_data="personal_folders")],
            [InlineKeyboardButton("📊 סטטוס מערכת", callback_data="system_status")]
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
    """פקודת /help"""
    if not is_authorized(update.effective_user.id):
        return
    
    help_text = (
        "📖 **עזרה - אקדמיה להשכלה גבוהה:**\n\n"
        "**פקודות בסיסיות:**\n"
        "• /start - התחלת שיחה\n"
        "• /help - הצגת עזרה\n"
        "• /gitstatus - מצב Git\n"
        "• /myfolder - יצירת תיקיה אישית\n"
        "• /balance - מצב מטבעות\n"
        "• /ask - שאילת שאלת AI\n\n"
        "**למנהלים:**\n"
        "• /coins - ניהול מטבעות\n"
        "• /stats - סטטיסטיקות מערכת\n\n"
        "**שימוש כללי:**\n"
        "• שלח טקסט רגיל - יישמר בתיקיה האישית\n"
        "• לחץ על כפתורים לתפריטים שונים\n"
        "• כל השינויים נשמרים אוטומטית ב-Git"
    )
    
    await update.message.reply_text(help_text)

async def git_status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """פקודת /gitstatus"""
    if not is_authorized(update.effective_user.id):
        return
    
    repo_status = git_handler.get_repo_status()
    
    if repo_status["status"] == "not_ready":
        await update.message.reply_text("❌ הריפוזיטורי לא מוכן")
        return
    
    status_text = "📊 **סטטוס Git:**\n\n"
    status_text += f"🔄 **סנכרון אחרון:** {repo_status.get('last_sync', 'לא ידוע')}\n"
    status_text += f"🌿 **Branch:** {repo_status.get('branch', 'לא ידוע')}\n"
    status_text += f"📝 **שינויים שלא commit:** {'כן' if repo_status.get('has_changes') else 'לא'}\n"
    status_text += f"🔗 **Commit אחרון:** {repo_status.get('last_commit', 'לא ידוע')}\n\n"
    
    # קומיטים אחרונים
    try:
        result = CommandRunner.run(
            ["git", "-C", git_handler.repo_path, "log", "--oneline", "-5"],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            status_text += "📜 **קומיטים אחרונים:**\n" + result.stdout
    except Exception as e:
        logger.error("Error getting git log: %s", e)
    
    await update.message.reply_text(status_text)

async def system_stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """פקודת /stats - סטטיסטיקות מערכת"""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ רק מנהלים יכולים לראות סטטיסטיקות מערכת")
        return
    
    # סטטיסטיקות Git
    repo_status = git_handler.get_repo_status()
    
    # סטטיסטיקות מטבעות
    coin_stats = coin_system.get_system_stats()
    
    # סטטיסטיקות משתמשים
    total_authorized = len(git_handler.authorized_users)
    admins_count = len(config.ADMIN_USER_IDS)
    regular_users = total_authorized - admins_count
    
    stats_text = "📈 **סטטיסטיקות מערכת - אקדמיה:**\n\n"
    
    stats_text += "👥 **משתמשים:**\n"
    stats_text += f"• משתמשים מורשים: {total_authorized}\n"
    stats_text += f"• מנהלים: {admins_count}\n"
    stats_text += f"• משתמשים רגילים: {regular_users}\n\n"
    
    stats_text += "🪙 **מערכת מטבעות:**\n"
    stats_text += f"• משתמשים עם מטבעות: {coin_stats['total_users']}\n"
    stats_text += f"• מטבעות שכורים: {coin_stats['total_mined']}\n"
    stats_text += f"• מטבעות במערכת: {coin_stats['total_coins']}\n"
    stats_text += f"• עסקאות: {coin_stats['total_transactions']}\n\n"
    
    stats_text += "📊 **Git:**\n"
    stats_text += f"• סטטוס: {repo_status.get('status', 'Unknown')}\n"
    stats_text += f"• סנכרון אחרון: {repo_status.get('last_sync', 'Unknown')}\n"
    stats_text += f"• Branch: {repo_status.get('branch', 'Unknown')}\n"
    
    await update.message.reply_text(stats_text)

async def myfolder_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """פקודת /myfolder"""
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
• תאריך יצירה: {DateTimeUtils.get_formatted_datetime()}

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
    
    ok = git_handler.commit_and_push(welcome_file, welcome_content, f"Create personal folder for {user.first_name} ({user.id})")
    if ok:
        await update.message.reply_text(
            f"✅ **תיקיה אישית נוצרה בהצלחה!**\n\n"
            f"📁 `{user_folder}/`\n\n"
            f"🎓 **אקדמיה להשכלה גבוהה**\n"
            f"כעת תוכל לשלוח טקסט ואשמור אותו בתיקיה שלך.\n\n"
            f"💡 **טיפ:** אתה יכול ליצור תיקיות משנה לפי נושאים:\n"
            f"• `{user_folder}/programming/`\n"
            f"• `{user_folder}/mathematics/`\n"
            f"• `{user_folder}/projects/`\n"
            f"וכו..."
        )
    else:
        await update.message.reply_text(
            "❌ **שגיאה ביצירת תיקיה אישית.**\n\n"
            "🏫 **אקדמיה להשכלה גבוהה**\n"
            "המערכת תנסה שוב באופן אוטומטי.\n"
            "אתה יכול לנסות שוב בעוד כמה דקות."
        )

async def balance_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """פקודת /balance"""
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

async def ask_ai_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """פקודת /ask"""
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

async def coins_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """פקודת /coins - ניהול מטבעות למנהלים"""
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

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """טיפול בהודעות טקסט"""
    user_id = update.effective_user.id
    
    # רענון רשימת משתמשים מורשים
    git_handler._load_authorized_users()
    
    if not is_authorized(user_id):
        return
    
    user = update.effective_user
    text = update.message.text or ""
    
    if not text.strip():
        await update.message.reply_text("❌ אנא שלח טקסט לשמירה.")
        return
    
    # Check if waiting for AI question
    if context.user_data.get('waiting_for_ai_question'):
        await update.message.reply_text("🤖 AI מעבד את השאלה שלך...")
        response = ai_service.ask_ai(text)
        await update.message.reply_text(f"🤖 **תשובת AI:**\n\n{response}")
        
        # Save AI conversation
        user_folder = f"students/{user.id}"
        ts = DateTimeUtils.get_timestamp()
        filename = f"{user_folder}/ai_conversation_{ts}.txt"
        
        content = f"""שיחת AI:
שאלה: {text}
תשובה: {response}
תאריך: {DateTimeUtils.get_formatted_datetime()}
"""
        git_handler.commit_and_push(filename, content, f"AI conversation for {user.first_name}")
        
        context.user_data['waiting_for_ai_question'] = False
        return
    
    # Check if this is admin command for coins
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
            return
            
        except ValueError:
            await update.message.reply_text("❌ הכמות חייבת להיות מספר")
            return
    
    elif context.user_data.get('waiting_for_mine_reason'):
        reason = text
        amount = context.user_data.get('mine_amount')
        
        success, message = coin_system.mine_coins(user_id, amount, reason)
        await update.message.reply_text(message)
        
        # Clean up
        context.user_data.pop('mine_amount', None)
        context.user_data.pop('waiting_for_mine_reason', None)
        return
    
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
            return
            
        except ValueError:
            await update.message.reply_text("❌ פורמט לא תקין. השתמש ב: ID,כמות,סיבה")
            return
    
    # Check if waiting for payment proof
    if context.user_data.get('waiting_for_payment_proof'):
        # This will be handled by the photo handler
        return
    
    # Regular text message - save to personal folder
    user_folder = f"students/{user.id}"
    ts = DateTimeUtils.get_timestamp()
    filename = f"{user_folder}/note_{ts}.txt"
    
    content = f"""מידע תלמיד:
• שם: {user.first_name} {user.last_name or ''}
• שם משתמש: @{user.username or 'לא צוין'}
• ID: {user.id}
• תאריך: {DateTimeUtils.get_formatted_datetime()}

תוכן:
{text}
"""
    
    commit_message = f"Note from {user.first_name} ({user.id}) at {ts}"
    ok = git_handler.commit_and_push(filename, content, commit_message)
    
    if ok:
        await update.message.reply_text(
            f"✅ **נשמר בהצלחה!**\n"
            f"📁 תיקיה: `{user_folder}/`\n"
            f"📄 קובץ: `note_{ts}.txt`\n\n"
            f"🎓 **אקדמיה להשכלה גבוהה**\n"
            f"החומר הלימודי שלך נשמר בצורה מאובטחת."
        )
    else:
        await update.message.reply_text(
            "❌ **שגיאה בשמירה.**\n\n"
            "🏫 **אקדמיה להשכלה גבוהה**\n"
            "המערכת תנסה לשמור שוב מאוחר יותר.\n"
            "אתה יכול להמשיך להשתמש בשאר התכונות."
        )

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """טיפול בתמונות (הוכחת תשלום)"""
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
        f"⏰ **תאריך:** {DateTimeUtils.get_formatted_datetime()}\n\n"
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
    for admin_id in config.ADMIN_USER_IDS:
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

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """טיפול בלחיצות על כפתורים"""
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    data = query.data

    # רענון רשימת משתמשים מורשים
    git_handler._load_authorized_users()

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
            "• מתמטיקה וסטטיסטיקה\n"
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
            "📧 **לשאלות:** @Osif83"
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
            "• סכום ההעברה (444 ש\"ח)\n"
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
• תאריך יצירה: {DateTimeUtils.get_formatted_datetime()}

בתיקיה זו תוכל לשמור:
• תרגילים
• שאלות
• פרויקטים
• סיכומים
• מטלות
• פרויקטים אישיים

🎓 אקדמיה להשכלה גבוהה - SLH Academia
"""
        
        ok = git_handler.commit_and_push(welcome_file, welcome_content, f"Create personal folder for {query.from_user.first_name} ({user_id})")
        if ok:
            await query.edit_message_text(
                f"✅ **תיקיה אישית נוצרה!**\n\n"
                f"📁 `{user_folder}/`\n\n"
                f"🎓 כעת תוכל לשלוח טקסט ואשמור אותו בתיקיה שלך.\n"
                f"💡 כל מה שתשלח יישמר אוטומטית."
            )
        else:
            await query.edit_message_text(
                "❌ **שגיאה ביצירת תיקיה אישית.**\n\n"
                "🏫 **אקדמיה להשכלה גבוהה**\n"
                "המערכת תנסה שוב באופן אוטומטי.\n"
                "אתה יכול לנסות שוב בעוד כמה דקות."
            )

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

    elif data == "system_status":
        repo_status = git_handler.get_repo_status()
        coin_stats = coin_system.get_system_stats()
        
        status_text = "📊 **סטטוס מערכת - אקדמיה:**\n\n"
        
        status_text += "🔄 **Git Repository:**\n"
        status_text += f"• סטטוס: {repo_status.get('status', 'Unknown')}\n"
        status_text += f"• סנכרון אחרון: {repo_status.get('last_sync', 'Unknown')}\n"
        status_text += f"• Branch: {repo_status.get('branch', 'Unknown')}\n\n"
        
        status_text += "🪙 **מערכת מטבעות:**\n"
        status_text += f"• משתמשים פעילים: {coin_stats['total_users']}\n"
        status_text += f"• מטבעות במערכת: {coin_stats['total_coins']}\n"
        status_text += f"• עסקאות: {coin_stats['total_transactions']}\n\n"
        
        status_text += "👥 **משתמשים:**\n"
        status_text += f"• משתמשים מורשים: {len(git_handler.authorized_users)}\n"
        status_text += f"• מנהלים: {len(config.ADMIN_USER_IDS)}\n\n"
        
        status_text += f"🕒 **זמן מערכת:** {DateTimeUtils.get_formatted_datetime()}"
        
        keyboard = [
            [InlineKeyboardButton("🔙 חזרה", callback_data="back_to_start")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(status_text, reply_markup=reply_markup)

    elif data == "back_to_start":
        # Go back to start
        git_handler._load_authorized_users()  # Reload to ensure latest data
        
        if is_authorized(user_id):
            balance = coin_system.get_balance(user_id)
            keyboard = [
                [InlineKeyboardButton("🎓 על האקדמיה", callback_data="about_academy")],
                [InlineKeyboardButton("🪙 מצב ארנק", callback_data="check_balance")],
                [InlineKeyboardButton("🤖 שאל את AI", callback_data="ask_ai")],
                [InlineKeyboardButton("📁 תיקיות אישיות", callback_data="personal_folders")],
                [InlineKeyboardButton("📊 סטטוס מערכת", callback_data="system_status")]
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
        success = git_handler.add_authorized_user(target_user_id)
        if success:
            # Reload authorized users to ensure the new user is recognized
            git_handler._load_authorized_users()
            
            # Notify the approved user
            try:
                await context.bot.send_message(
                    chat_id=target_user_id,
                    text=f"🎉 **הבקשה שלך אושרה!**\n\n"
                         f"🏫 **ברוך הבא לאקדמיה להשכלה גבוהה!**\n\n"
                         f"👥 **הצטרף לקבוצה:** {config.GROUP_LINK}\n\n"
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
        rankings = coin_system.get_user_rankings(5)
        
        stats_text = f"📊 **סטטיסטיקות מערכת מטבעות:**\n\n"
        stats_text += f"👥 משתמשים: {stats['total_users']}\n"
        stats_text += f"⛏️ מטבעות שכורים: {stats['total_mined']}\n"
        stats_text += f"💰 מטבעות במערכת: {stats['total_coins']}\n"
        stats_text += f"🔗 עסקאות: {stats['total_transactions']}\n\n"
        
        if rankings:
            stats_text += "🏆 **דירוג משתמשים:**\n"
            for i, (user_id, balance) in enumerate(rankings, 1):
                stats_text += f"{i}. User {user_id}: {balance} coins\n"
        
        await query.edit_message_text(stats_text)

# ===== BOT SETUP =====
def setup_bot_handlers(application):
    """הגדרת handlers לבוט"""
    # Command handlers
    application.add_handler(CommandHandler("start", start_cmd))
    application.add_handler(CommandHandler("help", help_cmd))
    application.add_handler(CommandHandler("gitstatus", git_status_cmd))
    application.add_handler(CommandHandler("stats", system_stats_cmd))
    application.add_handler(CommandHandler("myfolder", myfolder_cmd))
    application.add_handler(CommandHandler("balance", balance_cmd))
    application.add_handler(CommandHandler("ask", ask_ai_cmd))
    application.add_handler(CommandHandler("coins", coins_cmd))
    
    # Message handlers
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    
    # Callback query handler
    application.add_handler(CallbackQueryHandler(button_callback))

def main():
    """הפעלת הבוט הראשי"""
    application = Application.builder().token(config.BOT_TOKEN).build()
    
    # Setup handlers
    setup_bot_handlers(application)
    
    # Configure webhook
    webhook_path = f"/webhook/{config.BOT_TOKEN}"
    webhook_url = f"{config.WEBHOOK_URL.rstrip('/')}{webhook_path}"
    
    logger.info("Setting webhook to: %s", "***" + webhook_url[-20:])  # Secure logging
    
    try:
        application.run_webhook(
            listen="0.0.0.0",
            port=config.PORT,
            url_path=webhook_path,
            webhook_url=webhook_url,
            secret_token=config.SECRET_TOKEN
        )
        logger.info("Bot started successfully with webhook")
    except Exception as e:
        logger.error("Failed to start bot: %s", e)
        raise

if __name__ == "__main__":
    main()
