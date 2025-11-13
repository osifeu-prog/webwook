# db.py - מערכת database מלאה עם כל הטבלאות הנדרשות - מתוקן
import os
import logging
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from decimal import Decimal
from urllib.parse import urlparse
import re

# הגדרות לוג
logger = logging.getLogger(__name__)

# חיבור ל-database
def get_db_connection():
    """מחזיר חיבור ל-database"""
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise ValueError("DATABASE_URL environment variable is not set")
    
    try:
        # אם ה-URL מכיל את המילה "port" או "host", ננסה לתקן
        if "port" in database_url and "host" in database_url:
            # ננסה לחלץ את המידע מה-URL הקיים
            if "postgresql://user:pass@host:port/dbname" in database_url:
                # זה כנראה ה-URL הדיפולטי - ננסה להשתמש ב-DATABASE_URL האמיתי
                # או ליצור אחד מתאים
                railway_db_url = os.environ.get("DATABASE_PUBLIC_URL")
                if railway_db_url:
                    database_url = railway_db_url
                    logger.info(f"Using DATABASE_PUBLIC_URL: {database_url}")
                else:
                    # ננסה לבנות URL מהמשתנים הבודדים אם קיימים
                    db_host = os.environ.get("PGHOST", "localhost")
                    db_port = os.environ.get("PGPORT", "5432")
                    db_name = os.environ.get("PGDATABASE", "railway")
                    db_user = os.environ.get("PGUSER", "postgres")
                    db_pass = os.environ.get("PGPASSWORD", "")
                    
                    database_url = f"postgresql://{db_user}:{db_pass}@{db_host}:{db_port}/{db_name}"
                    logger.info(f"Built database URL from environment variables")
        
        logger.info(f"Connecting to database with URL: {database_url[:50]}...")  # לוג חלקי מטעמי אבטחה
        
        return psycopg2.connect(database_url, sslmode='require')
    except Exception as e:
        logger.error(f"Failed to connect to database: {e}")
        logger.error(f"Database URL (partial): {str(database_url)[:50]}...")
        raise ConnectionError(f"Failed to connect to database: {e}")

# =========================
# אתחול סכמה
# =========================

def init_schema():
    """מאתחל את כל הטבלאות במערכת"""
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        logger.info("Starting database schema initialization...")
        
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
        logger.info("✅ Created/verified users table")
        
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
        logger.info("✅ Created/verified tasks table")
        
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
        logger.info("✅ Created/verified user_tasks table")
        
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
        logger.info("✅ Created/verified referrals table")
        
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
        logger.info("✅ Created/verified subscriptions table")
        
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
        logger.info("✅ Created/verified user_economy table")
        
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
        logger.info("✅ Created/verified learning_network table")
        
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
        logger.info("✅ Created/verified economy_transactions table")
        
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
        logger.info("✅ Created/verified learning_activities table")
        
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
        logger.info("✅ Created/verified daily_rewards table")
        
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
        logger.info("✅ Created/verified payments table")
        
        # הכנסת משימות דוגמה אם הטבלה ריקה
        cur.execute("SELECT COUNT(*) FROM tasks")
        count_result = cur.fetchone()
        task_count = count_result[0] if count_result else 0
        
        if task_count == 0:
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
            
            logger.info(f"✅ Inserted {len(sample_tasks)} sample tasks")
        
        conn.commit()
        logger.info("🎉 Database schema initialized successfully!")
        
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"❌ Error initializing database schema: {e}")
        raise
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

# =========================
# פונקציות משתמשים
# =========================

def store_user(user_id: int, username: str, first_name: str, referral_code: str = None) -> bool:
    """שומר או מעדכן משתמש במערכת"""
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
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
        logger.info(f"✅ User {user_id} stored/updated successfully")
        return True
    except Exception as e:
        if conn:
            conn.rollback()
        logger.error(f"❌ Error storing user {user_id}: {e}")
        return False
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

# ... (כל שאר הפונקציות נשארות כמו שהיו) ...

def get_user_wallet(user_id: int) -> Optional[str]:
    """מחזיר את כתובת הארנק של המשתמש"""
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        cur.execute("SELECT wallet_address FROM users WHERE user_id = %s", (user_id,))
        result = cur.fetchone()
        return result[0] if result else None
    except Exception as e:
        logger.error(f"Error getting wallet for user {user_id}: {e}")
        return None
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

# ... (כל שאר הפונקציות נשארות ללא שינוי) ...
