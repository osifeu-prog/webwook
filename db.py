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
        return None
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.DictCursor)
    return conn

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
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()

def init_schema() -> None:
    if not DATABASE_URL:
        return

    with db_cursor() as (conn, cur):
        if cur is None:
            return

        # טבלאות קיימות
        cur.execute("""
            CREATE TABLE IF NOT EXISTS payments (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                username TEXT,
                pay_method TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                reason TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id BIGINT PRIMARY KEY,
                username TEXT,
                first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                bsc_wallet TEXT,
                total_points INT DEFAULT 0
            );
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS referrals (
                id SERIAL PRIMARY KEY,
                referrer_id BIGINT NOT NULL,
                referred_id BIGINT NOT NULL,
                source TEXT,
                points INT NOT NULL DEFAULT 1,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS rewards (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                reward_type TEXT NOT NULL,
                reason TEXT,
                points INT NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'pending',
                tx_hash TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
        """)

        # 🎯 טבלאות חדשות למערכת מטלות
        cur.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id SERIAL PRIMARY KEY,
                task_number INT NOT NULL UNIQUE,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                reward_points INT NOT NULL DEFAULT 10,
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS user_tasks (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                task_number INT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                submitted_proof TEXT,
                approved_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                UNIQUE(user_id, task_number)
            );
        """)

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

        # מטלות דוגמה - 20 מטלות מוכנות
        for i in range(1, 21):
            cur.execute("""
                INSERT INTO tasks (task_number, title, description, reward_points)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (task_number) DO UPDATE SET
                    title = EXCLUDED.title,
                    description = EXCLUDED.description,
                    reward_points = EXCLUDED.reward_points;
            """, (
                i,
                f"משימה {i} - שלב בקהילה",
                f"זוהי משימה מספר {i} שמטרתה לקדם אותך בקהילה. הגשה וקבלת {i * 5} נקודות!",
                i * 5  # יותר נקודות למשימות מתקדמות
            ))

        logger.info("DB schema updated with tasks system")

# =========================
# פונקציות חדשות למערכת מטלות
# =========================

def get_user_tasks(user_id: int) -> List[Dict[str, Any]]:
    """מחזיר את כל המשימות של משתמש עם סטטוס"""
    with db_cursor() as (conn, cur):
        if cur is None:
            return []
        cur.execute("""
            SELECT t.*, ut.status as user_status, ut.approved_at, ut.submitted_proof
            FROM tasks t
            LEFT JOIN user_tasks ut ON t.task_number = ut.task_number AND ut.user_id = %s
            WHERE t.is_active = TRUE
            ORDER BY t.task_number;
        """, (user_id,))
        rows = cur.fetchall()
        return [dict(row) for row in rows]

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
            logger.error("Failed to start task: %s", e)
            return False

def submit_task(user_id: int, task_number: int, proof_text: str) -> bool:
    """מגיש משימה עם הוכחה"""
    with db_cursor() as (conn, cur):
        if cur is None:
            return False
        try:
            cur.execute("""
                UPDATE user_tasks 
                SET status = 'submitted', submitted_proof = %s
                WHERE user_id = %s AND task_number = %s;
            """, (proof_text, user_id, task_number))
            return True
        except Exception as e:
            logger.error("Failed to submit task: %s", e)
            return False

def approve_task(user_id: int, task_number: int) -> bool:
    """מאשר משימה ומוסיף נקודות"""
    with db_cursor() as (conn, cur):
        if cur is None:
            return False
        try:
            # מאשר את המשימה
            cur.execute("""
                UPDATE user_tasks 
                SET status = 'approved', approved_at = NOW()
                WHERE user_id = %s AND task_number = %s;
            """, (user_id, task_number))
            
            # מוסיף נקודות למשתמש
            cur.execute("""
                UPDATE users 
                SET total_points = total_points + (
                    SELECT reward_points FROM tasks WHERE task_number = %s
                )
                WHERE id = %s;
            """, (task_number, user_id))
            
            return True
        except Exception as e:
            logger.error("Failed to approve task: %s", e)
            return False

def get_user_progress(user_id: int) -> Dict[str, Any]:
    """מחזיר התקדמות משתמש"""
    with db_cursor() as (conn, cur):
        if cur is None:
            return {}
        
        cur.execute("""
            SELECT 
                COUNT(*) as total_tasks,
                COUNT(ut.user_id) as started_tasks,
                SUM(CASE WHEN ut.status = 'approved' THEN 1 ELSE 0 END) as completed_tasks,
                COALESCE(u.total_points, 0) as total_points
            FROM tasks t
            LEFT JOIN user_tasks ut ON t.task_number = ut.task_number AND ut.user_id = %s
            LEFT JOIN users u ON u.id = %s
            WHERE t.is_active = TRUE
            GROUP BY u.total_points;
        """, (user_id, user_id))
        
        row = cur.fetchone()
        return dict(row) if row else {
            'total_tasks': 20,
            'started_tasks': 0,
            'completed_tasks': 0,
            'total_points': 0
        }

# פונקציות קיימות נשארות כפי שהיו...
# [כל הפונקציות הקיימות שלך נשארות כאן]
