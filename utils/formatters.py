# utils/formatters.py
from decimal import Decimal
from typing import Dict, Any

def format_tokens(amount: Decimal, decimals: int = 8) -> str:
    """מעצב כמות טוקנים לתצוגה"""
    if amount == 0:
        return "0"
    
    # עיגול למספר המקומות הרצוי
    formatted = f"{amount:.{decimals}f}"
    
    # הסרת אפסים מיותרים אחרי הנקודה
    if '.' in formatted:
        formatted = formatted.rstrip('0').rstrip('.')
    
    return formatted

def format_progress(completed: int, total: int) -> Dict[str, Any]:
    """מעצב נתוני התקדמות"""
    if total == 0:
        return {
            'percentage': 0,
            'progress_bar': '⬜⬜⬜⬜⬜⬜⬜⬜⬜⬜',
            'completed': 0,
            'total': 0
        }
    
    percentage = (completed / total) * 100
    filled_squares = int((completed / total) * 10)
    
    progress_bar = '🟩' * filled_squares + '⬜' * (10 - filled_squares)
    
    return {
        'percentage': round(percentage, 1),
        'progress_bar': progress_bar,
        'completed': completed,
        'total': total
    }

def format_large_number(number: int) -> str:
    """מעצב מספרים גדולים לקריאה (K, M)"""
    if number >= 1_000_000:
        return f"{number/1_000_000:.1f}M"
    elif number >= 1_000:
        return f"{number/1_000:.1f}K"
    else:
        return str(number)

def format_duration(seconds: int) -> str:
    """מעצב זמן לקריאה"""
    if seconds < 60:
        return f"{seconds} שניות"
    elif seconds < 3600:
        minutes = seconds // 60
        return f"{minutes} דקות"
    elif seconds < 86400:
        hours = seconds // 3600
        return f"{hours} שעות"
    else:
        days = seconds // 86400
        return f"{days} ימים"
