# economy.py - כלכלת המשחק המתקדמת
import logging
from decimal import Decimal
from datetime import datetime, timedelta
from typing import Dict, Any, List
from db import db_cursor

logger = logging.getLogger(__name__)

class AcademyEconomy:
    def __init__(self):
        self.base_coin_rate = Decimal('0.1')
        self.learning_multiplier = Decimal('1.5')
        self.teaching_bonus = Decimal('0.3')
        self.leadership_levels = {
            1: {'name': 'מתחיל', 'multiplier': 1.0, 'students_needed': 0},
            2: {'name': 'חונך', 'multiplier': 1.2, 'students_needed': 3},
            3: {'name': 'מדריך', 'multiplier': 1.5, 'students_needed': 10},
            4: {'name': 'מאסטר', 'multiplier': 2.0, 'students_needed': 25},
            5: {'name': 'גורו', 'multiplier': 3.0, 'students_needed': 50}
        }

    def init_user_economy(self, user_id: int) -> bool:
        """מאתחל פרופיל כלכלי למשתמש חדש"""
        with db_cursor() as (conn, cur):
            if cur is None:
                return False
            try:
                cur.execute("""
                    INSERT INTO user_economy (user_id, last_activity_date)
                    VALUES (%s, CURRENT_DATE)
                    ON CONFLICT (user_id) DO NOTHING;
                """, (user_id,))
                return True
            except Exception as e:
                logger.error(f"Failed to init user economy: {e}")
                return False

    def claim_daily_reward(self, user_id: int) -> Dict[str, Any]:
        """תגמול יומי וסטריק"""
        with db_cursor() as (conn, cur):
            if cur is None:
                return {'success': False, 'message': 'Database error'}
            
            try:
                # בודק את הפעילות האחרונה
                cur.execute("""
                    SELECT daily_streak, last_activity_date, academy_coins 
                    FROM user_economy WHERE user_id = %s;
                """, (user_id,))
                
                result = cur.fetchone()
                if not result:
                    self.init_user_economy(user_id)
                    return {'success': False, 'message': 'Profile not initialized'}
                
                streak = result['daily_streak']
                last_date = result['last_activity_date']
                today = datetime.now().date()
                
                # בודק אם כבר קיבל היום
                if last_date == today:
                    return {'success': False, 'message': 'Already claimed today'}
                
                # מחשב סטריק חדש
                if last_date and last_date == today - timedelta(days=1):
                    new_streak = streak + 1
                else:
                    new_streak = 1
                
                # מחשב תגמול
                base_reward = Decimal('10')  # coins בסיסיים
                streak_bonus = Decimal(str(min(new_streak * 2, 50)))  # בונוס סטריק מקסימלי 50
                total_reward = base_reward + streak_bonus
                
                # מעדכן את המשתמש
                cur.execute("""
                    UPDATE user_economy 
                    SET academy_coins = academy_coins + %s,
                        daily_streak = %s,
                        last_activity_date = %s,
                        total_earnings = total_earnings + %s
                    WHERE user_id = %s;
                """, (total_reward, new_streak, today, total_reward, user_id))
                
                # רושם עסקה
                cur.execute("""
                    INSERT INTO economy_transactions 
                    (user_id, transaction_type, amount, description)
                    VALUES (%s, 'daily_reward', %s, 'Daily reward - streak: ' || %s);
                """, (user_id, total_reward, new_streak))
                
                return {
                    'success': True,
                    'reward': total_reward,
                    'new_streak': new_streak,
                    'base_reward': base_reward,
                    'streak_bonus': streak_bonus
                }
                
            except Exception as e:
                logger.error(f"Failed to claim daily reward: {e}")
                return {'success': False, 'message': 'System error'}

    def add_learning_activity(self, user_id: int, activity_type: str, duration_minutes: int = 30) -> Dict[str, Any]:
        """מוסיף נקודות למידה עבור פעילות"""
        with db_cursor() as (conn, cur):
            if cur is None:
                return {'success': False}
            
            try:
                # נקודות למידה בסיסיות
                base_points = duration_minutes // 10  # נקודה כל 10 דקות
                coins_earned = Decimal(str(base_points)) * self.base_coin_rate
                
                # מעדכן משתמש
                cur.execute("""
                    UPDATE user_economy 
                    SET learning_points = learning_points + %s,
                        academy_coins = academy_coins + %s,
                        total_earnings = total_earnings + %s
                    WHERE user_id = %s;
                """, (base_points, coins_earned, coins_earned, user_id))
                
                # רושם עסקה
                cur.execute("""
                    INSERT INTO economy_transactions 
                    (user_id, transaction_type, amount, description)
                    VALUES (%s, 'learning', %s, %s);
                """, (user_id, coins_earned, f'Learning activity: {activity_type}'))
                
                return {
                    'success': True,
                    'points_earned': base_points,
                    'coins_earned': coins_earned,
                    'activity_type': activity_type
                }
                
            except Exception as e:
                logger.error(f"Failed to add learning activity: {e}")
                return {'success': False}

    def add_teaching_reward(self, teacher_id: int, student_id: int, reward_type: str = 'referral') -> Dict[str, Any]:
        """תגמול עבור הוראה והדרכה"""
        with db_cursor() as (conn, cur):
            if cur is None:
                return {'success': False}
            
            try:
                # בודק אם כבר קיבל תגמול עבור תלמיד זה
                cur.execute("""
                    SELECT 1 FROM learning_network 
                    WHERE teacher_id = %s AND student_id = %s;
                """, (teacher_id, student_id))
                
                if cur.fetchone():
                    return {'success': False, 'message': 'Already rewarded for this student'}
                
                # תגמול בסיסי
                teaching_points = 10
                coins_earned = Decimal('5')  # coins עבור תלמיד חדש
                
                # מעדכן מורה
                cur.execute("""
                    UPDATE user_economy 
                    SET teaching_points = teaching_points + %s,
                        academy_coins = academy_coins + %s,
                        total_earnings = total_earnings + %s
                    WHERE user_id = %s;
                """, (teaching_points, coins_earned, coins_earned, teacher_id))
                
                # מוסיף לרשת הלימודית
                cur.execute("""
                    INSERT INTO learning_network 
                    (teacher_id, student_id, coins_earned)
                    VALUES (%s, %s, %s);
                """, (teacher_id, student_id, coins_earned))
                
                # רושם עסקה
                cur.execute("""
                    INSERT INTO economy_transactions 
                    (user_id, transaction_type, amount, description, related_user_id)
                    VALUES (%s, 'teaching', %s, %s, %s);
                """, (teacher_id, coins_earned, f'Teaching reward: {reward_type}', student_id))
                
                # בודק קידום דרגה
                self.check_leadership_promotion(teacher_id)
                
                return {
                    'success': True,
                    'points_earned': teaching_points,
                    'coins_earned': coins_earned,
                    'student_id': student_id
                }
                
            except Exception as e:
                logger.error(f"Failed to add teaching reward: {e}")
                return {'success': False}

    def check_leadership_promotion(self, user_id: int) -> bool:
        """בודק ומקדם דרגת leadership"""
        with db_cursor() as (conn, cur):
            if cur is None:
                return False
            
            try:
                # סופר תלמידים
                cur.execute("""
                    SELECT COUNT(*) as student_count 
                    FROM learning_network 
                    WHERE teacher_id = %s AND status = 'active';
                """, (user_id,))
                
                result = cur.fetchone()
                student_count = result['student_count'] if result else 0
                
                # מוצא את הדרגה הנוכחית
                cur.execute("""
                    SELECT leadership_level FROM user_economy WHERE user_id = %s;
                """, (user_id,))
                
                result = cur.fetchone()
                current_level = result['leadership_level'] if result else 1
                
                # בודק קידום
                new_level = current_level
                for level, data in self.leadership_levels.items():
                    if level > current_level and student_count >= data['students_needed']:
                        new_level = level
                
                if new_level > current_level:
                    cur.execute("""
                        UPDATE user_economy 
                        SET leadership_level = %s 
                        WHERE user_id = %s;
                    """, (new_level, user_id))
                    
                    # תגמול קידום
                    promotion_bonus = Decimal(str(new_level * 10))
                    cur.execute("""
                        UPDATE user_economy 
                        SET academy_coins = academy_coins + %s,
                            total_earnings = total_earnings + %s
                        WHERE user_id = %s;
                    """, (promotion_bonus, promotion_bonus, user_id))
                    
                    # רושם עסקה
                    cur.execute("""
                        INSERT INTO economy_transactions 
                        (user_id, transaction_type, amount, description)
                        VALUES (%s, 'promotion', %s, %s);
                    """, (user_id, promotion_bonus, f'Promotion to level {new_level}'))
                    
                    return True
                
                return False
                
            except Exception as e:
                logger.error(f"Failed to check leadership promotion: {e}")
                return False

    def get_user_economy_stats(self, user_id: int) -> Dict[str, Any]:
        """מחזיר סטטיסטיקות כלכליות של משתמש"""
        with db_cursor() as (conn, cur):
            if cur is None:
                return {}
            
            try:
                # נתוני משתמש
                cur.execute("""
                    SELECT * FROM user_economy WHERE user_id = %s;
                """, (user_id,))
                
                user_data = cur.fetchone()
                if not user_data:
                    self.init_user_economy(user_id)
                    return self.get_user_economy_stats(user_id)
                
                # סופר תלמידים
                cur.execute("""
                    SELECT COUNT(*) as student_count 
                    FROM learning_network 
                    WHERE teacher_id = %s AND status = 'active';
                """, (user_id,))
                
                student_result = cur.fetchone()
                student_count = student_result['student_count'] if student_result else 0
                
                # דרגה נוכחית
                current_level = user_data['leadership_level']
                level_data = self.leadership_levels.get(current_level, {})
                next_level = current_level + 1
                next_level_data = self.leadership_levels.get(next_level, {})
                
                # היסטוריית עסקאות אחרונות
                cur.execute("""
                    SELECT * FROM economy_transactions 
                    WHERE user_id = %s 
                    ORDER BY created_at DESC 
                    LIMIT 5;
                """, (user_id,))
                
                transactions = [dict(row) for row in cur.fetchall()]
                
                return {
                    'academy_coins': user_data['academy_coins'],
                    'learning_points': user_data['learning_points'],
                    'teaching_points': user_data['teaching_points'],
                    'leadership_level': current_level,
                    'level_name': level_data.get('name', 'מתחיל'),
                    'level_multiplier': level_data.get('multiplier', 1.0),
                    'total_earnings': user_data['total_earnings'],
                    'daily_streak': user_data['daily_streak'],
                    'student_count': student_count,
                    'next_level_students_needed': next_level_data.get('students_needed', 0),
                    'recent_transactions': transactions
                }
                
            except Exception as e:
                logger.error(f"Failed to get user economy stats: {e}")
                return {}

    def get_network_stats(self, user_id: int) -> Dict[str, Any]:
        """מחזיר סטטיסטיקות רשת"""
        with db_cursor() as (conn, cur):
            if cur is None:
                return {}
            
            try:
                # רמות הרשת
                cur.execute("""
                    WITH RECURSIVE network_tree AS (
                        SELECT student_id, 1 as level 
                        FROM learning_network 
                        WHERE teacher_id = %s
                        
                        UNION ALL
                        
                        SELECT ln.student_id, nt.level + 1 
                        FROM learning_network ln
                        JOIN network_tree nt ON ln.teacher_id = nt.student_id
                        WHERE nt.level < 3
                    )
                    SELECT level, COUNT(*) as count 
                    FROM network_tree 
                    GROUP BY level 
                    ORDER BY level;
                """, (user_id,))
                
                level_counts = {row['level']: row['count'] for row in cur.fetchall()}
                
                # הכנסות מרשת
                cur.execute("""
                    SELECT SUM(coins_earned) as network_earnings 
                    FROM learning_network 
                    WHERE teacher_id = %s;
                """, (user_id,))
                
                earnings_result = cur.fetchone()
                network_earnings = earnings_result['network_earnings'] if earnings_result else Decimal('0')
                
                return {
                    'level_1_students': level_counts.get(1, 0),
                    'level_2_students': level_counts.get(2, 0),
                    'level_3_students': level_counts.get(3, 0),
                    'total_network_earnings': network_earnings,
                    'network_depth': 3  # עומק הרשת המקסימלי
                }
                
            except Exception as e:
                logger.error(f"Failed to get network stats: {e}")
                return {}

# Instance גלובלי
academy_economy = AcademyEconomy()
