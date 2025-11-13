# config.py - Configuration for WebWook Bot
import os
from typing import Set

class BotConfig:
    """Configuration for Telegram Bot"""
    BOT_TOKEN = os.environ.get("BOT_TOKEN", "8351227223:AAHZyMmXdkKECnxTMvlEDYj5mFM9aOfnceI")
    ADMIN_IDS = {int(x) for x in os.environ.get("ADMIN_USER_IDS", "224223270").split(",")}
    PORT = int(os.environ.get("PORT", 8080))
    WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "https://webwook-production.up.railway.app")
    
    # קבוצות וקהילות
    ACADEMY_GROUP_LINK = "https://t.me/+WaA_aHzbwlU4MjNk"
    NOTIFICATIONS_GROUP_LINK = "https://t.me/+GFJjgH6orbdkZGE8"
    NOTIFICATIONS_GROUP_ID = -1001234567890  # צריך להחליף עם ID אמיתי
    
    # תשלומים
    ACADEMY_PRICE = 444
    BANK_DETAILS = {
        "bank": "בנק הפועלים",
        "branch": "הסניף המרכזי", 
        "account": "1234567"
    }

class TaskConfig:
    """Configuration for tasks system"""
    DEFAULT_TASKS = [
        {
            "number": 1,
            "title": "הצטרפות לערוץ הטלגרם",
            "description": "הצטרף לערוץ הטלגרם הרשמי שלנו והשאר הודעה",
            "points": 10,
            "tokens": 5.0
        },
        {
            "number": 2,
            "title": "עקיבה אחרי טוויטר", 
            "description": "עקוב אחרינו בטוויטר וצייץ על הפרויקט",
            "points": 15,
            "tokens": 7.5
        },
        {
            "number": 3,
            "title": "הזמנת חבר ראשון",
            "description": "הזמן חבר אחד להצטרף לבוט",
            "points": 20,
            "tokens": 10.0
        },
        {
            "number": 4,
            "title": "שיתוף בפייסבוק",
            "description": "שתף את הפרויקט בדף הפייסבוק שלך", 
            "points": 12,
            "tokens": 6.0
        },
        {
            "number": 5,
            "title": "צפייה בסרטון הדרכה",
            "description": "צפה בסרטון הדרכה וסכם בקצרה",
            "points": 8,
            "tokens": 4.0
        },
        {
            "number": 6, 
            "title": "השתתפות בדיסקורד",
            "description": "הצטרף לשרת הדיסקורד והצג את עצמך",
            "points": 10,
            "tokens": 5.0
        },
        {
            "number": 7,
            "title": "כתיבת ביקורת",
            "description": "כתוב ביקורת constructively על הפלטפורמה",
            "points": 25, 
            "tokens": 12.5
        },
        {
            "number": 8,
            "title": "יצירת תוכן",
            "description": "צור תוכן מקורי על הפרויקט (פוסט, סרטון, etc.)",
            "points": 30,
            "tokens": 15.0
        },
        {
            "number": 9,
            "title": "הזמנת 3 חברים", 
            "description": "הזמן 3 חברים חדשים לפרויקט",
            "points": 40,
            "tokens": 20.0
        },
        {
            "number": 10,
            "title": "הפיכת לשגריר",
            "description": "הפוך לשגריר רשמי של הפרויקט", 
            "points": 50,
            "tokens": 25.0
        }
    ]
    
    AUTO_APPROVE_TASKS = {1, 2, 3}  # משימות שאינן דורשות אישור מנהל

class EconomyConfig:
    """Configuration for economy system"""
    DAILY_REWARD_BASE = 1.0
    DAILY_REWARD_STREAK_BONUS = 0.1
    MAX_STREAK_BONUS = 2.0
    
    LEARNING_POINTS_PER_MINUTE = 0.2
    LEARNING_COINS_PER_MINUTE = 0.1
    
    REFERRAL_BONUS = {
        "points": 5,
        "tokens": 5, 
        "coins": 2
    }
    
    ACADEMY_SIGNUP_BONUS = 100  # Academy Coins
    
    # דרגות Leadership
    LEADERSHIP_LEVELS = {
        1: {"name": "מתחיל 🌱", "students_needed": 0, "multiplier": 1.0},
        2: {"name": "לומד 📚", "students_needed": 2, "multiplier": 1.1},
        3: {"name": "מתרגל 💪", "students_needed": 4, "multiplier": 1.2},
        4: {"name": "מתקדם ⭐", "students_needed": 8, "multiplier": 1.3},
        5: {"name": "מומחה 🔥", "students_needed": 16, "multiplier": 1.4},
        6: {"name": "מאסטר 🏆", "students_needed": 32, "multiplier": 1.5},
        7: {"name": "גורו 🌟", "students_needed": 64, "multiplier": 1.6},
        8: {"name": "לגנדרי ✨", "students_needed": 128, "multiplier": 1.7}
    }
