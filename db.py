# db.py - מערכת database מלאה עם כל הטבלאות הנדרשות
import os
import logging
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from decimal import Decimal

# הגדרות לוג
logger = logging.getLogger(__name__)

# חיבור ל-database
def get_db_connection():
    """מחזיר חיבור ל-database"""
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise ValueError("DATABASE_URL environment variable is not set")
    
    try:
        conn = psycopg2.connect(database_url, sslmode='require')
        return conn
    except Exception as e:
        logger.error(f"Failed to connect to database: {e}")
        raise ConnectionError(f"Failed to connect to database: {e}")

# =========================
# אתחול סכמה
# =========================

def init_schema():
    """מאתחל את כל הטבלאות במערכת"""
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        # טבלת משתמשים
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                username VARCHAR(100),
                first_name VARCHAR(100) NOT NULL,
                wallet_address VARCHAR(42),
                referral_code VARCHAR(50),
                total_points INTEGER DEFAULT 0,
                total_tokens DECIMAL(18,8) DEFAULT 0,
                completed_tasks INTEGER DEFAULT 0,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
        """)
        
        # טבלת משימות
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                task_number INTEGER PRIMARY KEY,
                title VARCHAR(200) NOT NULL,
                description TEXT NOT NULL,
                reward_points INTEGER NOT NULL,
                reward_tokens DECIMAL(18,8) NOT NULL,
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
        """)
        
        # טבלת התקדמות משתמשים במשימות
        cur.execute("""
            CREATE TABLE IF NOT EXISTS user_tasks (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                task_number INTEGER NOT NULL,
                status VARCHAR(20) DEFAULT 'pending', -- pending, started, submitted, approved
                submitted_proof TEXT,
                submitted_at TIMESTAMPTZ,
                approved_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                UNIQUE(user_id, task_number)
            );
        """)
        
        # טבלת הפניות
        cur.execute("""
            CREATE TABLE IF NOT EXISTS referrals (
                id SERIAL PRIMARY KEY,
                referrer_id BIGINT NOT NULL,
                referred_id BIGINT NOT NULL,
                bonus_awarded BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                UNIQUE(referrer_id, referred_id)
            );
        """)
        
        # טבלת מנויים ותשלומים
        cur.execute("""
            CREATE TABLE IF NOT EXISTS subscriptions (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                amount DECIMAL(10,2) NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                payment_method TEXT,
                transaction_id TEXT,
                access_granted BOOLEAN DEFAULT FALSE,
                group_access BOOLEAN DEFAULT FALSE,
                expires_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
        """)
        
        # טבלת כלכלת משתמשים
        cur.execute("""
            CREATE TABLE IF NOT EXISTS user_economy (
                user_id BIGINT PRIMARY KEY,
                academy_coins DECIMAL(18,8) DEFAULT 0,
                learning_points INTEGER DEFAULT 0,
                teaching_points INTEGER DEFAULT 0,
                leadership_level INTEGER DEFAULT 1,
                total_earnings DECIMAL(18,8) DEFAULT 0,
                daily_streak INTEGER DEFAULT 0,
                last_activity_date DATE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
        """)
        
        # טבלת רשת לימודית
        cur.execute("""
            CREATE TABLE IF NOT EXISTS learning_network (
                id SERIAL PRIMARY KEY,
                teacher_id BIGINT NOT NULL,
                student_id BIGINT NOT NULL,
                level INTEGER DEFAULT 1,
                coins_earned DECIMAL(18,8) DEFAULT 0,
                status TEXT DEFAULT 'active',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                UNIQUE(teacher_id, student_id)
            );
        """)
        
        # טבלת עסקאות כלכליות
        cur.execute("""
            CREATE TABLE IF NOT EXISTS economy_transactions (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                transaction_type TEXT NOT NULL,
                amount DECIMAL(18,8) NOT NULL,
                description TEXT,
                related_user_id BIGINT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
        """)
        
        # טבלת פעילויות לימודיות
        cur.execute("""
            CREATE TABLE IF NOT EXISTS learning_activities (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                activity_type VARCHAR(100) NOT NULL,
                duration_minutes INTEGER NOT NULL,
                description TEXT,
                points_earned INTEGER DEFAULT 0,
                coins_earned DECIMAL(18,8) DEFAULT 0,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
        """)
        
        # טבלת תיגמול יומי
        cur.execute("""
            CREATE TABLE IF NOT EXISTS daily_rewards (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                reward_date DATE NOT NULL,
                base_reward DECIMAL(18,8) NOT NULL,
                streak_bonus DECIMAL(18,8) DEFAULT 0,
                total_reward DECIMAL(18,8) NOT NULL,
                streak_count INTEGER NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                UNIQUE(user_id, reward_date)
            );
        """)
        
        # טבלת תשלומים
        cur.execute("""
            CREATE TABLE IF NOT EXISTS payments (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                amount DECIMAL(10,2) NOT NULL,
                status VARCHAR(20) DEFAULT 'pending',
                payment_method VARCHAR(50),
                transaction_id VARCHAR(100),
                group_access_granted BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
        """)
        
        # הכנסת משימות דוגמה אם הטבלה ריקה
        cur.execute("SELECT COUNT(*) FROM tasks")
        if cur.fetchone()[0] == 0:
            sample_tasks = [
                (1, "הצטרפות לערוץ הטלגרם", "הצטרף לערוץ הטלגרם הרשמי שלנו והשאר הודעה", 10, 5.0),
                (2, "עקיבה אחרי טוויטר", "עקוב אחרינו בטוויטר וצייץ על הפרויקט", 15, 7.5),
                (3, "הזמנת חבר ראשון", "הזמן חבר אחד להצטרף לבוט", 20, 10.0),
                (4, "שיתוף בפייסבוק", "שתף את הפרויקט בדף הפייסבוק שלך", 12, 6.0),
                (5, "צפייה בסרטון הדרכה", "צפה בסרטון הדרכה וסכם בקצרה", 8, 4.0),
                (6, "השתתפות בדיסקורד", "הצטרף לשרת הדיסקורד והצג את עצמך", 10, 5.0),
                (7, "כתיבת ביקורת", "כתוב ביקורת constructively על הפלטפורמה", 25, 12.5),
                (8, "יצירת תוכן", "צור תוכן מקורי על הפרויקט (פוסט, סרטון, etc.)", 30, 15.0),
                (9, "הזמנת 3 חברים", "הזמן 3 חברים חדשים לפרויקט", 40, 20.0),
                (10, "הפיכת לשגריר", "הפוך לשגריר רשמי של הפרויקט", 50, 25.0)
            ]
            
            for task in sample_tasks:
                cur.execute("""
                    INSERT INTO tasks (task_number, title, description, reward_points, reward_tokens)
                    VALUES (%s, %s, %s, %s, %s)
                """, task)
        
        conn.commit()
        logger.info("✅ Database schema initialized successfully")
        
    except Exception as e:
        conn.rollback()
        logger.error(f"❌ Error initializing database schema: {e}")
        raise
    finally:
        cur.close()
        conn.close()

# =========================
# פונקציות משתמשים
# =========================

def store_user(user_id: int, username: str, first_name: str, referral_code: str = None) -> bool:
    """שומר או מעדכן משתמש במערכת"""
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        cur.execute("""
            INSERT INTO users (user_id, username, first_name, referral_code, created_at, updated_at)
            VALUES (%s, %s, %s, %s, NOW(), NOW())
            ON CONFLICT (user_id) 
            DO UPDATE SET 
                username = EXCLUDED.username,
                first_name = EXCLUDED.first_name,
                updated_at = NOW()
            RETURNING user_id
        """, (user_id, username, first_name, referral_code))
        
        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        logger.error(f"Error storing user {user_id}: {e}")
        return False
    finally:
        cur.close()
        conn.close()

def get_user_wallet(user_id: int) -> Optional[str]:
    """מחזיר את כתובת הארנק של המשתמש"""
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        cur.execute("SELECT wallet_address FROM users WHERE user_id = %s", (user_id,))
        result = cur.fetchone()
        return result[0] if result else None
    except Exception as e:
        logger.error(f"Error getting wallet for user {user_id}: {e}")
        return None
    finally:
        cur.close()
        conn.close()

def update_user_wallet(user_id: int, wallet_address: str) -> bool:
    """מעדכן את כתובת הארנק של המשתמש"""
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        cur.execute("""
            UPDATE users 
            SET wallet_address = %s, updated_at = NOW()
            WHERE user_id = %s
        """, (wallet_address, user_id))
        
        conn.commit()
        return cur.rowcount > 0
    except Exception as e:
        conn.rollback()
        logger.error(f"Error updating wallet for user {user_id}: {e}")
        return False
    finally:
        cur.close()
        conn.close()

# =========================
# פונקציות משימות
# =========================

def get_user_tasks(user_id: int) -> List[Dict[str, Any]]:
    """מחזיר את כל המשימות עם הסטטוס של המשתמש"""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    try:
        cur.execute("""
            SELECT 
                t.task_number,
                t.title,
                t.description,
                t.reward_points,
                t.reward_tokens,
                COALESCE(ut.status, 'pending') as user_status,
                ut.submitted_proof,
                ut.submitted_at,
                ut.approved_at
            FROM tasks t
            LEFT JOIN user_tasks ut ON t.task_number = ut.task_number AND ut.user_id = %s
            WHERE t.is_active = TRUE
            ORDER BY t.task_number
        """, (user_id,))
        
        return cur.fetchall()
    except Exception as e:
        logger.error(f"Error getting tasks for user {user_id}: {e}")
        return []
    finally:
        cur.close()
        conn.close()

def start_task(user_id: int, task_number: int) -> bool:
    """מתחיל משימה עבור משתמש"""
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        cur.execute("""
            INSERT INTO user_tasks (user_id, task_number, status, created_at, updated_at)
            VALUES (%s, %s, 'started', NOW(), NOW())
            ON CONFLICT (user_id, task_number) 
            DO UPDATE SET 
                status = 'started',
                updated_at = NOW()
            RETURNING id
        """, (user_id, task_number))
        
        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        logger.error(f"Error starting task {task_number} for user {user_id}: {e}")
        return False
    finally:
        cur.close()
        conn.close()

def submit_task(user_id: int, task_number: int, proof: str) -> bool:
    """מגיש משימה עם הוכחה"""
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        cur.execute("""
            UPDATE user_tasks 
            SET status = 'submitted', 
                submitted_proof = %s,
                submitted_at = NOW(),
                updated_at = NOW()
            WHERE user_id = %s AND task_number = %s
            RETURNING id
        """, (proof, user_id, task_number))
        
        conn.commit()
        return cur.rowcount > 0
    except Exception as e:
        conn.rollback()
        logger.error(f"Error submitting task {task_number} for user {user_id}: {e}")
        return False
    finally:
        cur.close()
        conn.close()

def approve_task(user_id: int, task_number: int) -> bool:
    """מאשר משימה ומעדכן את התגמולים"""
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        # תחילה, מאמתים שהמשימה הוגשה
        cur.execute("""
            SELECT status FROM user_tasks 
            WHERE user_id = %s AND task_number = %s
        """, (user_id, task_number))
        
        result = cur.fetchone()
        if not result or result[0] != 'submitted':
            return False
        
        # מקבלים את פרטי המשימה
        cur.execute("""
            SELECT reward_points, reward_tokens 
            FROM tasks 
            WHERE task_number = %s
        """, (task_number,))
        
        task_reward = cur.fetchone()
        if not task_reward:
            return False
        
        reward_points, reward_tokens = task_reward
        
        # מעדכנים את סטטוס המשימה
        cur.execute("""
            UPDATE user_tasks 
            SET status = 'approved', 
                approved_at = NOW(),
                updated_at = NOW()
            WHERE user_id = %s AND task_number = %s
        """, (user_id, task_number))
        
        # מעדכנים את הסטטיסטיקות של המשתמש
        cur.execute("""
            UPDATE users 
            SET total_points = total_points + %s,
                total_tokens = total_tokens + %s,
                completed_tasks = completed_tasks + 1,
                updated_at = NOW()
            WHERE user_id = %s
        """, (reward_points, reward_tokens, user_id))
        
        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        logger.error(f"Error approving task {task_number} for user {user_id}: {e}")
        return False
    finally:
        cur.close()
        conn.close()

# =========================
# פונקציות סטטיסטיקות והפניות
# =========================

def get_user_stats(user_id: int) -> Dict[str, Any]:
    """מחזיר סטטיסטיקות משתמש"""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    try:
        # סטטיסטיקות בסיסיות
        cur.execute("""
            SELECT 
                total_points,
                total_tokens,
                completed_tasks,
                created_at
            FROM users 
            WHERE user_id = %s
        """, (user_id,))
        
        user_data = cur.fetchone()
        if not user_data:
            return {}
        
        # מספר הפניות
        cur.execute("""
            SELECT COUNT(*) as referral_count 
            FROM referrals 
            WHERE referrer_id = %s
        """, (user_id,))
        
        referral_count = cur.fetchone()['referral_count']
        
        # מספר משימות כולל
        cur.execute("SELECT COUNT(*) as total_tasks FROM tasks WHERE is_active = TRUE")
        total_tasks = cur.fetchone()['total_tasks']
        
        # חישוב דרגה
        completed_tasks = user_data['completed_tasks']
        if completed_tasks >= 8:
            rank = "מאסטר 🏆"
        elif completed_tasks >= 5:
            rank = "מתקדם ⭐"
        elif completed_tasks >= 3:
            rank = "בינוני 🔥"
        elif completed_tasks >= 1:
            rank = "מתחיל 🌱"
        else:
            rank = "חדש 👶"
        
        return {
            'total_points': user_data['total_points'],
            'total_tokens': float(user_data['total_tokens']),
            'completed_tasks': user_data['completed_tasks'],
            'total_tasks': total_tasks,
            'referral_count': referral_count,
            'rank': rank,
            'member_since': user_data['created_at'].strftime('%d/%m/%Y')
        }
    except Exception as e:
        logger.error(f"Error getting stats for user {user_id}: {e}")
        return {}
    finally:
        cur.close()
        conn.close()

def add_referral(referrer_id: int, referred_id: int) -> bool:
    """מוסיף הפניה חדשה ומעדכן בונוסים"""
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        # מוסיף את ההפניה
        cur.execute("""
            INSERT INTO referrals (referrer_id, referred_id, created_at)
            VALUES (%s, %s, NOW())
            ON CONFLICT (referrer_id, referred_id) DO NOTHING
            RETURNING id
        """, (referrer_id, referred_id))
        
        if cur.rowcount == 0:
            return False  # ההפניה כבר קיימת
        
        # מוסיף בונוס למזמין
        cur.execute("""
            UPDATE users 
            SET total_points = total_points + 5,
                total_tokens = total_tokens + 5,
                updated_at = NOW()
            WHERE user_id = %s
        """, (referrer_id,))
        
        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        logger.error(f"Error adding referral from {referrer_id} to {referred_id}: {e}")
        return False
    finally:
        cur.close()
        conn.close()

def get_top_referrers(limit: int = 10) -> List[Dict[str, Any]]:
    """מחזיר את הטופ מזמינים"""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    try:
        cur.execute("""
            SELECT 
                u.user_id,
                u.first_name,
                u.username,
                COUNT(r.id) as referral_count
            FROM users u
            JOIN referrals r ON u.user_id = r.referrer_id
            GROUP BY u.user_id, u.first_name, u.username
            ORDER BY referral_count DESC
            LIMIT %s
        """, (limit,))
        
        return cur.fetchall()
    except Exception as e:
        logger.error(f"Error getting top referrers: {e}")
        return []
    finally:
        cur.close()
        conn.close()

def get_pending_approvals() -> List[Dict[str, Any]]:
    """מחזיר את כל המשימות הממתינות לאישור"""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    try:
        cur.execute("""
            SELECT 
                ut.user_id,
                ut.task_number,
                ut.submitted_proof,
                ut.submitted_at,
                u.first_name,
                u.username,
                t.title
            FROM user_tasks ut
            JOIN users u ON ut.user_id = u.user_id
            JOIN tasks t ON ut.task_number = t.task_number
            WHERE ut.status = 'submitted'
            ORDER BY ut.submitted_at ASC
        """)
        
        return cur.fetchall()
    except Exception as e:
        logger.error(f"Error getting pending approvals: {e}")
        return []
    finally:
        cur.close()
        conn.close()

def get_user_progress(user_id: int) -> Dict[str, Any]:
    """מחזיר התקדמות משתמש (לא בשימוש כרגע אבל נשמר לתאימות)"""
    return get_user_stats(user_id)

# =========================
# פונקציות כלכלה
# =========================

def init_user_economy(user_id: int) -> bool:
    """מאתחל רשומה כלכלית למשתמש"""
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        cur.execute("""
            INSERT INTO user_economy (user_id, created_at, updated_at)
            VALUES (%s, NOW(), NOW())
            ON CONFLICT (user_id) DO NOTHING
            RETURNING user_id
        """, (user_id,))
        
        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        logger.error(f"Error initializing economy for user {user_id}: {e}")
        return False
    finally:
        cur.close()
        conn.close()

def get_user_economy_stats(user_id: int) -> Dict[str, Any]:
    """מחזיר סטטיסטיקות כלכלה למשתמש"""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    try:
        cur.execute("""
            SELECT 
                academy_coins,
                learning_points,
                teaching_points,
                leadership_level,
                total_earnings,
                daily_streak,
                last_activity_date
            FROM user_economy 
            WHERE user_id = %s
        """, (user_id,))
        
        economy_data = cur.fetchone()
        if not economy_data:
            init_user_economy(user_id)
            return get_user_economy_stats(user_id)
        
        # חישוב שם דרגה
        level = economy_data['leadership_level']
        level_names = {
            1: "מתחיל 🌱",
            2: "לומד 📚", 
            3: "מתרגל 💪",
            4: "מתקדם ⭐",
            5: "מומחה 🔥",
            6: "מאסטר 🏆",
            7: "גורו 🌟",
            8: "לגנדרי ✨"
        }
        
        level_name = level_names.get(level, "מתחיל 🌱")
        level_multiplier = 1.0 + (level - 1) * 0.1
        
        # מספר תלמידים
        cur.execute("""
            SELECT COUNT(*) as student_count 
            FROM learning_network 
            WHERE teacher_id = %s AND status = 'active'
        """, (user_id,))
        
        student_count = cur.fetchone()['student_count']
        next_level_students_needed = level * 2
        
        return {
            'academy_coins': float(economy_data['academy_coins']),
            'learning_points': economy_data['learning_points'],
            'teaching_points': economy_data['teaching_points'],
            'leadership_level': level,
            'level_name': level_name,
            'level_multiplier': level_multiplier,
            'total_earnings': float(economy_data['total_earnings']),
            'daily_streak': economy_data['daily_streak'],
            'student_count': student_count,
            'next_level_students_needed': next_level_students_needed
        }
    except Exception as e:
        logger.error(f"Error getting economy stats for user {user_id}: {e}")
        return {}
    finally:
        cur.close()
        conn.close()

def update_user_economy(user_id: int, updates: Dict[str, Any]) -> bool:
    """מעדכן את הנתונים הכלכליים של משתמש"""
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        set_clause = ", ".join([f"{key} = %s" for key in updates.keys()])
        values = list(updates.values())
        values.append(user_id)
        
        query = f"""
            UPDATE user_economy 
            SET {set_clause}, updated_at = NOW()
            WHERE user_id = %s
        """
        
        cur.execute(query, values)
        conn.commit()
        return cur.rowcount > 0
    except Exception as e:
        conn.rollback()
        logger.error(f"Error updating economy for user {user_id}: {e}")
        return False
    finally:
        cur.close()
        conn.close()

def add_economy_transaction(user_id: int, transaction_type: str, amount: float, description: str = None, related_user_id: int = None) -> bool:
    """מוסיף עסקה כלכלית חדשה"""
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        cur.execute("""
            INSERT INTO economy_transactions 
            (user_id, transaction_type, amount, description, related_user_id, created_at)
            VALUES (%s, %s, %s, %s, %s, NOW())
        """, (user_id, transaction_type, amount, description, related_user_id))
        
        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        logger.error(f"Error adding economy transaction for user {user_id}: {e}")
        return False
    finally:
        cur.close()
        conn.close()

def get_network_stats(user_id: int) -> Dict[str, Any]:
    """מחזיר סטטיסטיקות רשת למשתמש"""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    try:
        # תלמידים לפי רמות
        cur.execute("""
            SELECT 
                level,
                COUNT(*) as student_count,
                SUM(coins_earned) as level_earnings
            FROM learning_network 
            WHERE teacher_id = %s AND status = 'active'
            GROUP BY level
            ORDER BY level
        """, (user_id,))
        
        level_stats = cur.fetchall()
        
        level_1_students = 0
        level_2_students = 0  
        level_3_students = 0
        total_network_earnings = 0
        
        for stat in level_stats:
            if stat['level'] == 1:
                level_1_students = stat['student_count']
            elif stat['level'] == 2:
                level_2_students = stat['student_count']
            elif stat['level'] == 3:
                level_3_students = stat['student_count']
            
            total_network_earnings += float(stat['level_earnings'] or 0)
        
        return {
            'level_1_students': level_1_students,
            'level_2_students': level_2_students,
            'level_3_students': level_3_students,
            'total_network_earnings': total_network_earnings
        }
    except Exception as e:
        logger.error(f"Error getting network stats for user {user_id}: {e}")
        return {}
    finally:
        cur.close()
        conn.close()

# =========================
# פונקציות לפעילויות לימודיות
# =========================

def add_learning_activity(user_id: int, activity_type: str, duration: int, description: str = None) -> Dict[str, Any]:
    """מוסיף פעילות לימודית חדשה"""
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        # חישוב נקודות ומטבעות
        base_points = min(duration // 5, 10)  # מקסימום 10 נקודות
        base_coins = duration * 0.1  # 0.1 coin per minute
        
        # עדכון הכלכלה של המשתמש
        cur.execute("""
            UPDATE user_economy 
            SET learning_points = learning_points + %s,
                academy_coins = academy_coins + %s,
                total_earnings = total_earnings + %s,
                updated_at = NOW()
            WHERE user_id = %s
        """, (base_points, base_coins, base_coins, user_id))
        
        # הוספת הפעילות
        cur.execute("""
            INSERT INTO learning_activities 
            (user_id, activity_type, duration_minutes, description, points_earned, coins_earned, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, NOW())
        """, (user_id, activity_type, duration, description, base_points, base_coins))
        
        # הוספת עסקה כלכלית
        add_economy_transaction(
            user_id, 
            'learning_activity', 
            base_coins, 
            f'{activity_type} - {duration} minutes',
            None
        )
        
        conn.commit()
        
        return {
            'success': True,
            'points_earned': base_points,
            'coins_earned': base_coins,
            'activity_type': activity_type
        }
    except Exception as e:
        conn.rollback()
        logger.error(f"Error adding learning activity for user {user_id}: {e}")
        return {'success': False, 'error': str(e)}
    finally:
        cur.close()
        conn.close()

def claim_daily_reward(user_id: int) -> Dict[str, Any]:
    """מעבד תיגמול יומי"""
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    try:
        today = datetime.now().date()
        
        # בודק אם כבר קיבל היום
        cur.execute("""
            SELECT * FROM daily_rewards 
            WHERE user_id = %s AND reward_date = %s
        """, (user_id, today))
        
        if cur.fetchone():
            return {'success': False, 'message': 'כבר קיבלת את התיגמול היומי היום!'}
        
        # בודק את הסטריק הנוכחי
        cur.execute("""
            SELECT streak_count, reward_date 
            FROM daily_rewards 
            WHERE user_id = %s 
            ORDER BY reward_date DESC 
            LIMIT 1
        """, (user_id,))
        
        last_reward = cur.fetchone()
        
        if last_reward and last_reward['reward_date'] == today - timedelta(days=1):
            current_streak = last_reward['streak_count'] + 1
        else:
            current_streak = 1
        
        # חישוב התגמול
        base_reward = 1.0
        streak_bonus = min(current_streak * 0.1, 2.0)  # מקסימום בונוס 2.0
        total_reward = base_reward + streak_bonus
        
        # שמירת התיגמול
        cur.execute("""
            INSERT INTO daily_rewards 
            (user_id, reward_date, base_reward, streak_bonus, total_reward, streak_count, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, NOW())
        """, (user_id, today, base_reward, streak_bonus, total_reward, current_streak))
        
        # עדכון הכלכלה של המשתמש
        cur.execute("""
            UPDATE user_economy 
            SET academy_coins = academy_coins + %s,
                total_earnings = total_earnings + %s,
                daily_streak = %s,
                last_activity_date = %s,
                updated_at = NOW()
            WHERE user_id = %s
        """, (total_reward, total_reward, current_streak, today, user_id))
        
        # הוספת עסקה כלכלית
        add_economy_transaction(
            user_id, 
            'daily_reward', 
            total_reward, 
            f'Daily reward - streak {current_streak}',
            None
        )
        
        conn.commit()
        
        return {
            'success': True,
            'reward': total_reward,
            'base_reward': base_reward,
            'streak_bonus': streak_bonus,
            'new_streak': current_streak
        }
    except Exception as e:
        conn.rollback()
        logger.error(f"Error claiming daily reward for user {user_id}: {e}")
        return {'success': False, 'error': str(e)}
    finally:
        cur.close()
        conn.close()

def add_teaching_reward(teacher_id: int, student_id: int, reward_type: str) -> bool:
    """מוסיף תגמול הוראה למורה"""
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        reward_amount = 2.0 if reward_type == 'referral' else 1.0
        
        # עדכון הכלכלה של המורה
        cur.execute("""
            UPDATE user_economy 
            SET teaching_points = teaching_points + 1,
                academy_coins = academy_coins + %s,
                total_earnings = total_earnings + %s,
                updated_at = NOW()
            WHERE user_id = %s
        """, (reward_amount, reward_amount, teacher_id))
        
        # הוספת לרשת הלימודית או עדכון
        cur.execute("""
            INSERT INTO learning_network (teacher_id, student_id, level, coins_earned, status, created_at)
            VALUES (%s, %s, 1, %s, 'active', NOW())
            ON CONFLICT (teacher_id, student_id) 
            DO UPDATE SET 
                coins_earned = learning_network.coins_earned + EXCLUDED.coins_earned,
                updated_at = NOW()
        """, (teacher_id, student_id, reward_amount))
        
        # הוספת עסקה כלכלית
        add_economy_transaction(
            teacher_id, 
            'teaching_reward', 
            reward_amount, 
            f'{reward_type} - student {student_id}',
            student_id
        )
        
        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        logger.error(f"Error adding teaching reward for teacher {teacher_id}: {e}")
        return False
    finally:
        cur.close()
        conn.close()

# =========================
# פונקציות תשלומים
# =========================

def create_payment(user_id: int, amount: float, payment_method: str = "bank_transfer") -> bool:
    """יוצר רשומת תשלום חדשה"""
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        cur.execute("""
            INSERT INTO payments (user_id, amount, payment_method, created_at, updated_at)
            VALUES (%s, %s, %s, NOW(), NOW())
            RETURNING id
        """, (user_id, amount, payment_method))
        
        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        logger.error(f"Error creating payment for user {user_id}: {e}")
        return False
    finally:
        cur.close()
        conn.close()

def approve_payment(user_id: int) -> bool:
    """מאשר תשלום ומעניק גישה לקבוצה"""
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        cur.execute("""
            UPDATE payments 
            SET status = 'approved', 
                group_access_granted = TRUE,
                updated_at = NOW()
            WHERE user_id = %s AND status = 'pending'
        """, (user_id,))
        
        # מוסיף Academy Coins בונוס
        cur.execute("""
            UPDATE user_economy 
            SET academy_coins = academy_coins + 100,
                total_earnings = total_earnings + 100,
                updated_at = NOW()
            WHERE user_id = %s
        """, (user_id,))
        
        conn.commit()
        return cur.rowcount > 0
    except Exception as e:
        conn.rollback()
        logger.error(f"Error approving payment for user {user_id}: {e}")
        return False
    finally:
        cur.close()
        conn.close()

def has_paid_access(user_id: int) -> bool:
    """בודק אם למשתמש יש גישת תשלום מאושרת"""
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        cur.execute("""
            SELECT COUNT(*) 
            FROM payments 
            WHERE user_id = %s AND status = 'approved' AND group_access_granted = TRUE
        """, (user_id,))
        
        result = cur.fetchone()
        return result[0] > 0 if result else False
    except Exception as e:
        logger.error(f"Error checking paid access for user {user_id}: {e}")
        return False
    finally:
        cur.close()
        conn.close()
