# config.py
import os
import logging
from typing import List, Set

# Logging Configuration
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('bot.log', encoding='utf-8')
    ]
)

# Bot Configuration
class BotConfig:
    BOT_TOKEN = os.environ.get("BOT_TOKEN")
    WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "https://webwook-production.up.railway.app")
    ADMIN_IDS: Set[int] = set(
        int(x.strip()) for x in os.environ.get("ADMIN_USER_IDS", "224223270").split(",") 
        if x.strip()
    )
    PORT = int(os.environ.get("PORT", 8080))
    
    # Features
    ENABLE_TASKS = True
    ENABLE_TOKEN_DISTRIBUTION = True
    ENABLE_REFERRALS = True
    ENABLE_PAYMENTS = False  # ניתן להפעיל בהמשך
    
    # Limits
    MAX_TASK_PROOF_LENGTH = 2000
    MAX_USERNAME_LENGTH = 32
    DAILY_TASK_LIMIT = 10
    REFERRAL_BONUS_POINTS = 5
    REFERRAL_BONUS_TOKENS = 5

# Database Configuration
class DatabaseConfig:
    DATABASE_URL = os.environ.get("DATABASE_URL")
    MAX_CONNECTIONS = 20
    STATEMENT_TIMEOUT = 30000  # 30 seconds in milliseconds

# Blockchain Configuration
class BlockchainConfig:
    BSC_RPC_URL = os.environ.get("BSC_RPC_URL", "https://bsc-dataseed.binance.org/")
    TOKEN_CONTRACT = os.environ.get("TOKEN_CONTRACT", "0xACb0A09414CEA1C879c67bB7A877E4e19480f022")
    DISTRIBUTOR_PRIVATE_KEY = os.environ.get("DISTRIBUTOR_PRIVATE_KEY")
    
    # Gas Settings
    GAS_LIMIT = 100000
    GAS_PRICE_MULTIPLIER = 1.1
    MAX_GAS_PRICE = 50  # gwei
    
    # Token Settings
    TOKEN_DECIMALS = 18
    MIN_TOKEN_TRANSFER = 0.001

# Task Configuration
class TaskConfig:
    TASKS = [
        {
            'number': 1,
            'title': 'הצטרפות לערוץ הטלגרם',
            'description': 'הצטרף לערוץ הטלגרם הרשמי שלנו והשאר שם לפחות 7 ימים',
            'points': 5,
            'tokens': 10,
            'category': 'social'
        },
        {
            'number': 2,
            'title': 'שיתוף הפוסט הראשון',
            'description': 'שתף את הפוסט הראשון בערוץ בקבוצה או בערוץ שלך',
            'points': 10,
            'tokens': 20,
            'category': 'social'
        },
        {
            'number': 3,
            'title': 'הזמנת חבר ראשון',
            'description': 'הזמן חבר אחד להצטרף לבוט',
            'points': 15,
            'tokens': 30,
            'category': 'referral'
        },
        {
            'number': 4,
            'title': 'יצירת פוסט מקורי',
            'description': 'צור פוסט מקורי על הפרויקט ופרסם אותו',
            'points': 20,
            'tokens': 40,
            'category': 'content'
        },
        {
            'number': 5,
            'title': 'השתתפות בתחרות',
            'description': 'השתתף בתחרות החודשית שלנו',
            'points': 25,
            'tokens': 50,
            'category': 'engagement'
        }
    ]
    
    @classmethod
    def get_task_by_number(cls, task_number: int) -> dict:
        """מחזיר משימה לפי מספר"""
        for task in cls.TASKS:
            if task['number'] == task_number:
                return task
        return None

# Validation
def validate_config():
    """בודק שהקונפיגורציה תקינה"""
    errors = []
    
    if not BotConfig.BOT_TOKEN:
        errors.append("BOT_TOKEN is required")
    
    if not DatabaseConfig.DATABASE_URL:
        errors.append("DATABASE_URL is required")
    
    if BotConfig.ENABLE_TOKEN_DISTRIBUTION and not BlockchainConfig.DISTRIBUTOR_PRIVATE_KEY:
        errors.append("DISTRIBUTOR_PRIVATE_KEY is required for token distribution")
    
    if errors:
        raise ValueError(f"Configuration errors: {', '.join(errors)}")

# Validate on import
try:
    validate_config()
except ValueError as e:
    logging.error(f"Configuration error: {e}")
