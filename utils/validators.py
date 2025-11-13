# utils/validators.py
import re
from web3 import Web3

def validate_wallet_address(address: str) -> bool:
    """בודק אם כתובת ארנק תקינה"""
    if not address or not isinstance(address, str):
        return False
    
    # בדיקת פורמט בסיסי
    if not address.startswith('0x') or len(address) != 42:
        return False
    
    # בדיקת checksum
    try:
        checksum_address = Web3.to_checksum_address(address)
        return checksum_address == address or checksum_address.lower() == address.lower()
    except:
        return False

def validate_task_submission(proof_text: str, min_length: int = 10) -> bool:
    """בודק אם הגשת משימה תקינה"""
    if not proof_text or not isinstance(proof_text, str):
        return False
    
    # הסרת רווחים מיותרים
    clean_text = proof_text.strip()
    
    # בדיקת אורך מינימלי
    if len(clean_text) < min_length:
        return False
    
    # בדיקת תווים לא חוקיים (בסיסית)
    if re.search(r'[<>{}]', clean_text):
        return False
    
    return True

def validate_username(username: str) -> bool:
    """בודק אם שם משתמש תקין"""
    if not username:
        return True  # שם משתמש אופציונלי
    
    if len(username) < 3 or len(username) > 32:
        return False
    
    # בדיקת תווים תקינים
    if not re.match(r'^[a-zA-Z0-9_]+$', username):
        return False
    
    return True
