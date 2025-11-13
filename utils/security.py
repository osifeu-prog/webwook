# utils/security.py
import re
import secrets
import string

def sanitize_input(text: str, max_length: int = 1000) -> str:
    """מנקה קלט משתמש מפני XSS והזרקות"""
    if not text:
        return ""
    
    # חיתוך לאורך מקסימלי
    text = text[:max_length]
    
    # הסרת תגיות HTML מסוכנות
    text = re.sub(r'<script.*?>.*?</script>', '', text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r'<.*?javascript:.*?>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'<.*?on\w+.*?>', '', text, flags=re.IGNORECASE)
    
    # החלפת תווים מסוכנים
    replacements = {
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#x27;',
        '/': '&#x2F;',
        '\\': '&#x5C;'
    }
    
    for char, replacement in replacements.items():
        text = text.replace(char, replacement)
    
    return text.strip()

def generate_referral_code(length: int = 8) -> str:
    """מייצר קוד הפניה אקראי"""
    alphabet = string.ascii_uppercase + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))

def is_suspicious_activity(user_id: int, action: str, context: dict) -> bool:
    """בודק אם יש פעילות חשודה"""
    # כאן ניתן להוסיף לוגיקה לזיהוי פעילות חשודה
    # כמו יותר מדי בקשות בזמן קצר, פעולות לא הגיוניות, etc.
    
    suspicious_patterns = [
        # יותר מ-10 בקשות לדקה
        ('rate_limit', lambda ctx: ctx.get('requests_per_minute', 0) > 10),
        # שינוי ארנק יותר מפעם אחת ביום
        ('wallet_change_frequency', lambda ctx: ctx.get('wallet_changes_today', 0) > 1),
    ]
    
    for pattern_name, check in suspicious_patterns:
        if check(context):
            return True
    
    return False
