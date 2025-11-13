# db.py - מעודכן עם מערכת מטלות ותגמולים אוטומטית
import os
import logging
from contextlib import contextmanager
from typing import Optional, Any, List, Dict
from datetime import datetime
import psycopg2
import psycopg2.extras

logger = logging.getLogger(__name__)
DATABASE_URL = os.environ.get("DATABASE_URL")

def get_conn():
    if not DATABASE_URL:
        logger.error("DATABASE_URL not set")
        return None
    try:
        conn = psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.DictCursor)
        return conn
    except Exception as e:
        logger.error(f"Database connection failed: {e}")
        return None

@contextmanager
def db_cursor():
    conn = get_conn()
    if conn is None:
        yield None, None
        return
    try:
        cur = conn.cursor()
        yield conn, cur
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.error(f"Database error: {e}")
        raise
    finally:
        cur.close()
        conn.close()

def init_schema() -> None:
    if not DATABASE_URL:
        logger.error("DATABASE_URL not set - skipping schema init")
        return

    with db_cursor() as (conn, cur):
        if cur is None:
            return

        # טבלת משתמשים
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id BIGINT PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                bsc_wallet TEXT,
                total_points INT DEFAULT 0,
                total_tokens DECIMAL(18,8) DEFAULT 0,
                referral_code TEXT,
                referred_by BIGINT
            );
        """)

        # טבלת משימות
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id SERIAL PRIMARY KEY,
                task_number INT NOT NULL UNIQUE,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                reward_points INT NOT NULL DEFAULT 10,
                reward_tokens DECIMAL(18,8) NOT NULL DEFAULT 10,
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
        """)

        # טבלת משימות משתמש
        cur.execute("""
            CREATE TABLE IF NOT EXISTS user_tasks (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                task_number INT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                submitted_proof TEXT,
                submitted_at TIMESTAMPTZ,
                approved_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                UNIQUE(user_id, task_number)
            );
        """)

        # טבלת עסקאות טוקנים
        cur.execute("""
            CREATE TABLE IF NOT EXISTS token_transactions (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                task_number INT,
                token_amount DECIMAL(18,8) NOT NULL,
                tx_hash TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
        """)

        # טבלת הפניות
        cur.execute("""
            CREATE TABLE IF NOT EXISTS referrals (
                id SERIAL PRIMARY KEY,
                referrer_id BIGINT NOT NULL,
                referred_id BIGINT NOT NULL,
                points_earned INT NOT NULL DEFAULT 5,
                tokens_earned DECIMAL(18,8) NOT NULL DEFAULT 5,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                UNIQUE(referred_id)
            );
        """)

        # טבלת תשלומים
        cur.execute("""
            CREATE TABLE IF NOT EXISTS payments (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                username TEXT,
                pay_method TEXT,
                amount DECIMAL(10,2),
                status TEXT NOT NULL DEFAULT 'pending',
                reason TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
        """)

        # מטלות דוגמה - 20 מטלות מוכנות
        sample_tasks = [
            (1, "הצטרפות לערוץ הטלגרם", "הצטרף לערוץ הטלגרם הרשמי שלנו והשאר שם לפחות 7 ימים", 5, 10),
            (2, "שיתוף הפוסט הראשון", "שתף את הפוסט הראשון בערוץ בקבוצה או בערוץ שלך", 10, 20),
            (3, "הזמנת חבר ראשון", "הזמן חבר אחד להצטרף לבוט", 15, 30),
            (4, "יצירת פוסט מקורי", "צור פוסט מקורי על הפרויקט ופרסם אותו", 20, 40),
            (5, "השתתפות בתחרות", "השתתף בתחרות החודשית שלנו", 25, 50),
            (6, "דיווג באג", "דווח על באג או שיפור למערכת", 10, 20),
            (7, "תרגום תוכן", "עזר בתרגום תוכן לשפה נוספת", 15, 30),
            (8, "צירוף 5 חברים", "הזמן 5 חברים חדשים לבוט", 50, 100),
            (9, "סקירת הפרויקט", "כתוב סקירה על הפרויקט בפלטפורמה חיצונית", 20, 40),
            (10, "יצירת תוכן וידאו", "צור סרטון הסבר על הפרויקט", 30, 60),
        ]

        for task_number, title, description, points, tokens in sample_tasks:
            cur.execute("""
                INSERT INTO tasks (task_number, title, description, reward_points, reward_tokens)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (task_number) DO UPDATE SET
                    title = EXCLUDED.title,
                    description = EXCLUDED.description,
                    reward_points = EXCLUDED.reward_points,
                    reward_tokens = EXCLUDED.reward_tokens;
            """, (task_number, title, description, points, tokens))

        logger.info("DB schema initialized successfully")

# =========================
# פונקציות ניהול משתמשים
# =========================

def store_user(user_id: int, username: str = None, first_name: str = None, referral_code: str = None) -> bool:
    """שומר או מעדכן משתמש במערכת"""
    with db_cursor() as (conn, cur):
        if cur is None:
            return False
        try:
            cur.execute("""
                INSERT INTO users (id, username, first_name, referral_code)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    username = EXCLUDED.username,
                    first_name = EXCLUDED.first_name,
                    referral_code = EXCLUDED.referral_code
                WHERE users.referral_code IS NULL;
            """, (user_id, username, first_name, referral_code))
            return True
        except Exception as e:
            logger.error(f"Failed to store user: {e}")
            return False

def get_user_wallet(user_id: int) -> str:
    """מחזיר את כתובת הארנק של המשתמש"""
    with db_cursor() as (conn, cur):
        if cur is None:
            return ""
        try:
            cur.execute("SELECT bsc_wallet FROM users WHERE id = %s", (user_id,))
            result = cur.fetchone()
            return result['bsc_wallet'] if result and result['bsc_wallet'] else ""
        except Exception as e:
            logger.error(f"Failed to get user wallet: {e}")
            return ""

def update_user_wallet(user_id: int, wallet_address: str) -> bool:
    """מעדכן את כתובת הארנק של המשתמש"""
    with db_cursor() as (conn, cur):
        if cur is None:
            return False
        try:
            cur.execute("UPDATE users SET bsc_wallet = %s WHERE id = %s", (wallet_address, user_id))
            return True
        except Exception as e:
            logger.error(f"Failed to update user wallet: {e}")
            return False

# =========================
# פונקציות מערכת משימות
# =========================

def get_user_tasks(user_id: int) -> List[Dict[str, Any]]:
    """מחזיר את כל המשימות של משתמש עם סטטוס"""
    with db_cursor() as (conn, cur):
        if cur is None:
            return []
        try:
            cur.execute("""
                SELECT t.*, ut.status as user_status, ut.approved_at, ut.submitted_proof
                FROM tasks t
                LEFT JOIN user_tasks ut ON t.task_number = ut.task_number AND ut.user_id = %s
                WHERE t.is_active = TRUE
                ORDER BY t.task_number;
            """, (user_id,))
            rows = cur.fetchall()
            return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Failed to get user tasks: {e}")
            return []

def start_task(user_id: int, task_number: int) -> bool:
    """מתחיל משימה עבור משתמש"""
    with db_cursor() as (conn, cur):
        if cur is None:
            return False
        try:
            cur.execute("""
                INSERT INTO user_tasks (user_id, task_number, status)
                VALUES (%s, %s, 'started')
                ON CONFLICT (user_id, task_number) DO UPDATE SET
                    status = EXCLUDED.status,
                    created_at = NOW();
            """, (user_id, task_number))
            return True
        except Exception as e:
            logger.error(f"Failed to start task: {e}")
            return False

def submit_task(user_id: int, task_number: int, proof_text: str) -> bool:
    """מגיש משימה עם הוכחה"""
    with db_cursor() as (conn, cur):
        if cur is None:
            return False
        try:
            cur.execute("""
                UPDATE user_tasks 
                SET status = 'submitted', submitted_proof = %s, submitted_at = NOW()
                WHERE user_id = %s AND task_number = %s;
            """, (proof_text, user_id, task_number))
            return True
        except Exception as e:
            logger.error(f"Failed to submit task: {e}")
            return False

def approve_task(user_id: int, task_number: int) -> bool:
    """מאשר משימה ומוסיף נקודות"""
    with db_cursor() as (conn, cur):
        if cur is None:
            return False
        try:
            # מאתר את פרטי המשימה
            cur.execute("SELECT reward_points, reward_tokens FROM tasks WHERE task_number = %s", (task_number,))
            task = cur.fetchone()
            if not task:
                return False

            points = task['reward_points']
            tokens = task['reward_tokens']

            # מאשר את המשימה
            cur.execute("""
                UPDATE user_tasks 
                SET status = 'approved', approved_at = NOW()
                WHERE user_id = %s AND task_number = %s AND status = 'submitted';
            """, (user_id, task_number))

            if cur.rowcount == 0:
                return False

            # מוסיף נקודות וטוקנים למשתמש
            cur.execute("""
                UPDATE users 
                SET total_points = total_points + %s,
                    total_tokens = total_tokens + %s
                WHERE id = %s;
            """, (points, tokens, user_id))

            # רושם את העסקה
            cur.execute("""
                INSERT INTO token_transactions (user_id, task_number, token_amount, status)
                VALUES (%s, %s, %s, 'completed');
            """, (user_id, task_number, tokens))

            return True
        except Exception as e:
            logger.error(f"Failed to approve task: {e}")
            return False

def get_user_progress(user_id: int) -> Dict[str, Any]:
    """מחזיר התקדמות משתמש"""
    with db_cursor() as (conn, cur):
        if cur is None:
            return {
                'total_tasks': 10,
                'started_tasks': 0,
                'completed_tasks': 0,
                'total_points': 0,
                'total_tokens': 0
            }
        
        try:
            cur.execute("""
                SELECT 
                    COUNT(*) as total_tasks,
                    COUNT(ut.user_id) as started_tasks,
                    SUM(CASE WHEN ut.status = 'approved' THEN 1 ELSE 0 END) as completed_tasks
                FROM tasks t
                LEFT JOIN user_tasks ut ON t.task_number = ut.task_number AND ut.user_id = %s
                WHERE t.is_active = TRUE;
            """, (user_id,))
            
            task_stats = cur.fetchone()
            
            cur.execute("""
                SELECT total_points, total_tokens 
                FROM users 
                WHERE id = %s;
            """, (user_id,))
            
            user_stats = cur.fetchone()
            
            return {
                'total_tasks': task_stats['total_tasks'] if task_stats else 10,
                'started_tasks': task_stats['started_tasks'] if task_stats else 0,
                'completed_tasks': task_stats['completed_tasks'] if task_stats else 0,
                'total_points': user_stats['total_points'] if user_stats else 0,
                'total_tokens': user_stats['total_tokens'] if user_stats else 0
            }
        except Exception as e:
            logger.error(f"Failed to get user progress: {e}")
            return {
                'total_tasks': 10,
                'started_tasks': 0,
                'completed_tasks': 0,
                'total_points': 0,
                'total_tokens': 0
            }

def get_user_stats(user_id: int) -> Dict[str, Any]:
    """מחזיר סטטיסטיקות מלאות של משתמש"""
    progress = get_user_progress(user_id)
    
    with db_cursor() as (conn, cur):
        if cur is None:
            return progress
            
        try:
            cur.execute("""
                SELECT COUNT(*) as referral_count
                FROM referrals 
                WHERE referrer_id = %s;
            """, (user_id,))
            
            ref_result = cur.fetchone()
            referral_count = ref_result['referral_count'] if ref_result else 0
            
            progress['referral_count'] = referral_count
            
            # חישוב דרגה
            total_points = progress['total_points']
            if total_points >= 100:
                progress['rank'] = "מאסטר 🏆"
            elif total_points >= 50:
                progress['rank'] = "מתקדם ⭐"
            elif total_points >= 20:
                progress['rank'] = "מנוסה 🔥"
            elif total_points >= 10:
                progress['rank'] = "מתחיל 🚀"
            else:
                progress['rank'] = "חדש 👶"
                
            return progress
            
        except Exception as e:
            logger.error(f"Failed to get user stats: {e}")
            progress['referral_count'] = 0
            progress['rank'] = "חדש 👶"
            return progress

# =========================
# פונקציות הפניות
# =========================

def add_referral(referrer_id: int, referred_id: int) -> bool:
    """מוסיף הפניה חדשה"""
    with db_cursor() as (conn, cur):
        if cur is None:
            return False
        try:
            # בודק שהמשתמש המוזמן לא הוזמן כבר
            cur.execute("SELECT 1 FROM referrals WHERE referred_id = %s", (referred_id,))
            if cur.fetchone():
                return False
                
            # מוסיף את ההפניה
            cur.execute("""
                INSERT INTO referrals (referrer_id, referred_id, points_earned, tokens_earned)
                VALUES (%s, %s, 5, 5);
            """, (referrer_id, referred_id))
            
            # מוסיף נקודות למזמין
            cur.execute("""
                UPDATE users 
                SET total_points = total_points + 5,
                    total_tokens = total_tokens + 5
                WHERE id = %s;
            """, (referrer_id,))
            
            return True
        except Exception as e:
            logger.error(f"Failed to add referral: {e}")
            return False

def get_top_referrers(limit: int = 10) -> List[Dict[str, Any]]:
    """מחזיר את המובילים בהפניות"""
    with db_cursor() as (conn, cur):
        if cur is None:
            return []
        try:
            cur.execute("""
                SELECT 
                    u.id,
                    u.username,
                    u.first_name,
                    COUNT(r.id) as referral_count,
                    SUM(r.points_earned) as total_points
                FROM users u
                JOIN referrals r ON u.id = r.referrer_id
                GROUP BY u.id, u.username, u.first_name
                ORDER BY referral_count DESC
                LIMIT %s;
            """, (limit,))
            rows = cur.fetchall()
            return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Failed to get top referrers: {e}")
            return []

# =========================
# פונקציות מנהל
# =========================

def get_pending_approvals() -> List[Dict[str, Any]]:
    """מחזיר משימות הממתינות לאישור"""
    with db_cursor() as (conn, cur):
        if cur is None:
            return []
        try:
            cur.execute("""
                SELECT 
                    ut.user_id,
                    u.username,
                    u.first_name,
                    ut.task_number,
                    t.title,
                    ut.submitted_proof,
                    ut.submitted_at
                FROM user_tasks ut
                JOIN users u ON ut.user_id = u.id
                JOIN tasks t ON ut.task_number = t.task_number
                WHERE ut.status = 'submitted'
                ORDER BY ut.submitted_at;
            """)
            rows = cur.fetchall()
            return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Failed to get pending approvals: {e}")
            return []

# אתחול הסכמה בעת ייבוא
init_schema()
