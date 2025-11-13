# economy.py - כלכלת המשחק המתקדמת (מתוקן)
import os
import logging
from decimal import Decimal
from datetime import datetime, timedelta
from typing import Dict, Any, List
from db import (
    init_user_economy, 
    update_user_economy, 
    add_economy_transaction,
    get_user_economy_stats as db_get_user_economy_stats,
    get_network_stats as db_get_network_stats,
    add_learning_activity as db_add_learning_activity,
    claim_daily_reward as db_claim_daily_reward,
    add_teaching_reward as db_add_teaching_reward
)

logger = logging.getLogger(__name__)

class AcademyEconomy:
    def __init__(self):
        self.base_coin_rate = Decimal('0.1')
        self.learning_multiplier = Decimal('1.5')
        self.teaching_bonus = Decimal('0.3')
        self.leadership_levels = {
            1: {'name': 'מתחיל 🌱', 'multiplier': 1.0, 'students_needed': 0},
            2: {'name': 'לומד 📚', 'multiplier': 1.1, 'students_needed': 2},
            3: {'name': 'מתרגל 💪', 'multiplier': 1.2, 'students_needed': 5},
            4: {'name': 'מתקדם ⭐', 'multiplier': 1.4, 'students_needed': 10},
            5: {'name': 'מומחה 🔥', 'multiplier': 1.7, 'students_needed': 20},
            6: {'name': 'מאסטר 🏆', 'multiplier': 2.0, 'students_needed': 35},
            7: {'name': 'גורו 🌟', 'multiplier': 2.5, 'students_needed': 50},
            8: {'name': 'לגנדרי ✨', 'multiplier': 3.0, 'students_needed': 100}
        }

    def init_user_economy(self, user_id: int) -> bool:
        """מאתחל פרופיל כלכלי למשתמש חדש"""
        return init_user_economy(user_id)

    def claim_daily_reward(self, user_id: int) -> Dict[str, Any]:
        """תגמול יומי וסטריק"""
        return db_claim_daily_reward(user_id)

    def add_learning_activity(self, user_id: int, activity_type: str, duration_minutes: int = 30) -> Dict[str, Any]:
        """מוסיף נקודות למידה עבור פעילות"""
        return db_add_learning_activity(user_id, activity_type, duration_minutes)

    def add_teaching_reward(self, teacher_id: int, student_id: int, reward_type: str = 'referral') -> Dict[str, Any]:
        """תגמול עבור הוראה והדרכה"""
        return db_add_teaching_reward(teacher_id, student_id, reward_type)

    def check_leadership_promotion(self, user_id: int) -> bool:
        """בודק ומקדם דרגת leadership"""
        try:
            stats = self.get_user_economy_stats(user_id)
            if not stats:
                return False
            
            student_count = stats.get('student_count', 0)
            current_level = stats.get('leadership_level', 1)
            
            # בודק קידום
            new_level = current_level
            for level, data in self.leadership_levels.items():
                if level > current_level and student_count >= data['students_needed']:
                    new_level = level
            
            if new_level > current_level:
                # מעדכן דרגה
                updates = {
                    'leadership_level': new_level,
                    'academy_coins': stats.get('academy_coins', 0) + (new_level * 5)
                }
                
                success = update_user_economy(user_id, updates)
                
                if success:
                    # מוסיף עסקה לכבוד הקידום
                    promotion_bonus = new_level * 5
                    add_economy_transaction(
                        user_id, 
                        'leadership_promotion', 
                        float(promotion_bonus),
                        f'Promoted to {self.leadership_levels[new_level]["name"]}'
                    )
                
                return success
            
            return False
            
        except Exception as e:
            logger.error(f"Failed to check leadership promotion: {e}")
            return False

    def get_user_economy_stats(self, user_id: int) -> Dict[str, Any]:
        """מחזיר סטטיסטיקות כלכליות של משתמש"""
        return db_get_user_economy_stats(user_id)

    def get_network_stats(self, user_id: int) -> Dict[str, Any]:
        """מחזיר סטטיסטיקות רשת"""
        return db_get_network_stats(user_id)

    def convert_coins_to_tokens(self, user_id: int, coins_amount: float) -> Dict[str, Any]:
        """ממיר Academy Coins ל-tokens אמיתיים"""
        try:
            stats = self.get_user_economy_stats(user_id)
            if not stats:
                return {'success': False, 'message': 'User not found'}
            
            current_coins = stats.get('academy_coins', 0)
            
            if coins_amount > current_coins:
                return {'success': False, 'message': 'Not enough coins'}
            
            # שער המרה (לדוגמה: 10 coins = 1 token)
            conversion_rate = 10.0
            tokens_amount = coins_amount / conversion_rate
            
            # מעדכן את מאזן ה-coins
            updates = {
                'academy_coins': current_coins - coins_amount
            }
            
            success = update_user_economy(user_id, updates)
            
            if success:
                # רושם את ההמרה
                add_economy_transaction(
                    user_id,
                    'coin_conversion',
                    -coins_amount,
                    f'Converted {coins_amount} coins to {tokens_amount} tokens'
                )
                
                return {
                    'success': True,
                    'coins_converted': coins_amount,
                    'tokens_received': tokens_amount,
                    'new_balance': current_coins - coins_amount
                }
            else:
                return {'success': False, 'message': 'Conversion failed'}
            
        except Exception as e:
            logger.error(f"Failed to convert coins: {e}")
            return {'success': False, 'message': 'System error'}

    def get_leaderboard(self, limit: int = 10) -> List[Dict[str, Any]]:
        """מחזיר טבלת מובילים לפי Academy Coins"""
        try:
            import psycopg2
            from psycopg2.extras import RealDictCursor
            
            conn = psycopg2.connect(os.environ.get("DATABASE_URL"), sslmode='require')
            cur = conn.cursor(cursor_factory=RealDictCursor)
            
            cur.execute("""
                SELECT 
                    u.user_id,
                    u.first_name,
                    u.username,
                    ue.academy_coins,
                    ue.leadership_level,
                    ue.learning_points,
                    ue.teaching_points
                FROM user_economy ue
                JOIN users u ON ue.user_id = u.user_id
                ORDER BY ue.academy_coins DESC
                LIMIT %s
            """, (limit,))
            
            leaderboard = []
            for i, row in enumerate(cur.fetchall(), 1):
                leaderboard.append({
                    'rank': i,
                    'user_id': row['user_id'],
                    'name': row['first_name'] or f"User {row['user_id']}",
                    'username': row['username'],
                    'academy_coins': float(row['academy_coins']),
                    'leadership_level': row['leadership_level'],
                    'learning_points': row['learning_points'],
                    'teaching_points': row['teaching_points']
                })
            
            cur.close()
            conn.close()
            
            return leaderboard
            
        except Exception as e:
            logger.error(f"Failed to get leaderboard: {e}")
            return []

# Instance גלובלי
academy_economy = AcademyEconomy()
