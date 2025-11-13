# main.py - מעודכן עם כלכלת משחק מלאה ומערכת תשלומים
import os
import logging
from datetime import datetime
from typing import Dict, Any, List
from decimal import Decimal

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters

from db import (
    store_user, get_user_wallet, update_user_wallet,
    get_user_tasks, start_task, submit_task, approve_task, 
    get_user_stats, add_referral, get_top_referrers, get_pending_approvals,
    get_user_progress, init_schema
)
from token_distributor import token_distributor
from config import BotConfig, TaskConfig
from utils.validators import validate_wallet_address, validate_task_submission
from utils.formatters import format_tokens, format_progress
from economy import academy_economy

# הגדרות לוג
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# משתני סביבה - משימוש BotConfig
ADMIN_IDS = BotConfig.ADMIN_IDS
PORT = BotConfig.PORT
WEBHOOK_URL = BotConfig.WEBHOOK_URL

# אתחול הבוט
ptb_app = Application.builder().token(BotConfig.BOT_TOKEN).build()

# =========================
# Utilities
# =========================

async def ensure_user(update: Update) -> bool:
    """מוודא שהמשתמש רשום במערכת"""
    user = update.effective_user
    if not user:
        return False
    
    success = store_user(
        user_id=user.id,
        username=user.username,
        first_name=user.first_name
    )
    
    # מאתחל כלכלה למשתמש חדש
    if success:
        academy_economy.init_user_economy(user.id)
    
    return success

def has_premium_access(user_id: int) -> bool:
    """בודק אם למשתמש יש גישת פרימיום"""
    # TODO: implement premium access check from database
    # For now, return True for testing
    return True

# =========================
# Handlers בסיסיים
# =========================

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """פקודת /start עם הפניות וכלכלת משחק"""
    user = update.effective_user
    if not user:
        return

    # בדיקת קוד הפניה
    referral_code = None
    if context.args and context.args[0].startswith('ref_'):
        try:
            referral_code = context.args[0].split('ref_')[1]
            referred_by = int(referral_code)
            if referred_by != user.id:  # מונע הפניה עצמית
                if add_referral(referred_by, user.id):
                    # תגמול כלכלי עבור ההפניה
                    academy_economy.add_teaching_reward(referred_by, user.id, 'referral')
                    await update.message.reply_text(
                        "🎉 הצטרפת דרך הזמנה של חבר! קיבלת 5 נקודות בונוס!"
                    )
        except (ValueError, IndexError):
            pass

    # רישום המשתמש
    store_user(
        user_id=user.id,
        username=user.username,
        first_name=user.first_name,
        referral_code=referral_code
    )
    
    # אתחול כלכלה
    academy_economy.init_user_economy(user.id)

    text = (
        f"🎓 *ברוך הבא לאקדמיה הדיגיטלית!* 🚀\n\n"
        
        f"👋 שלום {user.first_name}!\n\n"
        
        f"💎 *זו לא עוד פלטפורמה - זו הנכס הדיגיטלי שלך!*\n\n"
        
        f"🎯 *מה תקבל כאן:*\n"
        f"• ידע מעשי שניתן למנף מיידית 💼\n"
        f"• יכולת לבנות רשת לימודית משלך 🕸️\n"
        f"• כלכלת משחק שמרוויחה עבורך 🎮\n"
        f"• Academy Coins - המטבע שלך 🪙\n\n"
        
        f"📈 *איך מרוויחים?*\n"
        f"1. לומדים וצוברים נקודות 📚\n"
        f"2. מלמדים ומרחיבים את הרשת 👥\n"
        f"3. מתקדמים בדרגות Leadership 🏆\n"
        f"4. ממירים ל-tokens אמיתיים 💰\n\n"
        
        f"🚀 *האקדמיה שייכת לך* - אתה בונה נכס דיגיטלי שיכול להניב הכנסות!\n\n"
        f"מוכן להתחיל במסע? 🌟"
    )

    keyboard = [
        [InlineKeyboardButton("🎓 הצטרפות לאקדמיה (444₪)", callback_data="join_academy")],
        [InlineKeyboardButton("🎮 כלכלת המשחק", callback_data="economy")],
        [InlineKeyboardButton("🎯 משימות", callback_data="tasks")],
        [InlineKeyboardButton("💰 ארנק", callback_data="wallet")],
        [InlineKeyboardButton("📊 סטטיסטיקות", callback_data="stats")]
    ]
    
    if user.id in ADMIN_IDS:
        keyboard.append([InlineKeyboardButton("👑 ניהול", callback_data="admin")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        text,
        parse_mode="Markdown",
        reply_markup=reply_markup
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """פקודת /help מעודכנת"""
    await update.message.reply_text(
        "📖 *מדריך שימוש - אקדמיה דיגיטלית*\n\n"
        "🎯 */tasks* - הצג את כל המשימות הזמינות\n"
        "💰 */wallet* - צפה בארנק ובטוקנים שלך\n"
        "🏦 */economy* - כלכלת המשחק ו-Academy Coins\n"
        "📊 */stats* - סטטיסטיקות אישיות\n"
        "👥 */referrals* - הזמן חברים וקבל בונוסים\n"
        "🔗 */set_wallet <address>* - הגדר ארנק BSC\n"
        "💳 */payment* - הרשמה לאקדמיה המלאה\n"
        "🆘 */help* - הצג הודעה זו\n\n"
        "לשאלות נוספות פנה למנהלים.",
        parse_mode="Markdown"
    )

# =========================
# Handlers כלכלת משחק
# =========================

async def economy_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """פקודת /economy - מציג את המצב הכלכלי"""
    user = update.effective_user
    if not user or not await ensure_user(update):
        return

    stats = academy_economy.get_user_economy_stats(user.id)
    network_stats = academy_economy.get_network_stats(user.id)
    
    text = (
        f"🏦 *כלכלת האקדמיה - {user.first_name}*\n\n"
        f"💰 *מאזן:*\n"
        f"🪙 Academy Coins: {stats.get('academy_coins', 0):.2f}\n"
        f"📚 נקודות למידה: {stats.get('learning_points', 0)}\n"
        f"👨‍🏫 נקודות הוראה: {stats.get('teaching_points', 0)}\n"
        f"💎 סך הרווחים: {stats.get('total_earnings', 0):.2f} coins\n\n"
        
        f"🎯 *דרגת Leadership:*\n"
        f"🏆 {stats.get('level_name', 'מתחיל')} (רמה {stats.get('leadership_level', 1)})\n"
        f"📈 מכפיל: x{stats.get('level_multiplier', 1.0)}\n"
        f"👥 תלמידים: {stats.get('student_count', 0)}\n"
        f"🎓 נדרשים לדרגה הבאה: {stats.get('next_level_students_needed', 0)} תלמידים\n\n"
        
        f"📊 *סטטיסטיקות רשת:*\n"
        f"🔗 Level 1: {network_stats.get('level_1_students', 0)} תלמידים\n"
        f"🔗 Level 2: {network_stats.get('level_2_students', 0)} תלמידים\n"
        f"🔗 Level 3: {network_stats.get('level_3_students', 0)} תלמידים\n"
        f"💵 רווחי רשת: {network_stats.get('total_network_earnings', 0):.2f} coins\n"
    )
    
    keyboard = [
        [InlineKeyboardButton("🎁 תיגמול יומי", callback_data="daily_reward")],
        [InlineKeyboardButton("📖 פעילות לימודית", callback_data="learning_activity")],
        [InlineKeyboardButton("👥 הרשת שלי", callback_data="my_network")],
        [InlineKeyboardButton("💰 המרת coins", callback_data="convert_coins")],
        [InlineKeyboardButton("🏠 חזרה", callback_data="back_main")]
    ]
    
    await update.message.reply_text(
        text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def daily_reward_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """תיגמול יומי"""
    query = update.callback_query
    await query.answer()
    
    user = query.from_user
    result = academy_economy.claim_daily_reward(user.id)
    
    if result['success']:
        text = (
            f"🎉 *תיגמול יומי התקבל!*\n\n"
            f"💰 coins: +{result['reward']:.2f}\n"
            f"📈 בסיס: {result['base_reward']:.2f}\n"
            f"🔥 בונוס סטריק: +{result['streak_bonus']:.2f}\n"
            f"📅 סטריק נוכחי: {result['new_streak']} ימים\n\n"
            f"המשך ללמוד ולצבור! 🚀"
        )
    else:
        text = f"❌ {result['message']}"
    
    await query.edit_message_text(
        text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🏦 חזרה לכלכלה", callback_data="economy")
        ]])
    )

async def learning_activity_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """רישום פעילות לימודית"""
    query = update.callback_query
    await query.answer()
    
    text = (
        f"📚 *רישום פעילות לימודית*\n\n"
        f"🎯 בחר סוג פעילות:\n\n"
        f"• קריאת חומר (30 דקות) 📖\n"
        f"• צפייה בשיעור (30 דקות) 🎥\n"
        f"• תרגול מעשי (30 דקות) 💻\n"
        f"• השתתפות בדיון (20 דקות) 💬\n"
        f"• הגשת מטלה (45 דקות) 📝\n\n"
        f"לאחר הבחירה, תתבקש לשלוח תיאור קצר של הפעילות."
    )
    
    keyboard = [
        [InlineKeyboardButton("📖 קריאת חומר", callback_data="activity_reading")],
        [InlineKeyboardButton("🎥 צפייה בשיעור", callback_data="activity_watching")],
        [InlineKeyboardButton("💻 תרגול מעשי", callback_data="activity_practice")],
        [InlineKeyboardButton("💬 השתתפות בדיון", callback_data="activity_discussion")],
        [InlineKeyboardButton("📝 הגשת מטלה", callback_data="activity_assignment")],
        [InlineKeyboardButton("🔙 חזרה", callback_data="economy")]
    ]
    
    await query.edit_message_text(
        text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def handle_learning_activity(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """מטפל בבחירת פעילות לימודית"""
    query = update.callback_query
    await query.answer()
    
    user = query.from_user
    activity_type = query.data
    
    # מיפוי פעילויות לזמנים
    activity_durations = {
        'activity_reading': 30,
        'activity_watching': 30,
        'activity_practice': 30,
        'activity_discussion': 20,
        'activity_assignment': 45
    }
    
    activity_names = {
        'activity_reading': 'קריאת חומר',
        'activity_watching': 'צפייה בשיעור',
        'activity_practice': 'תרגול מעשי',
        'activity_discussion': 'השתתפות בדיון',
        'activity_assignment': 'הגשת מטלה'
    }
    
    duration = activity_durations.get(activity_type, 30)
    activity_name = activity_names.get(activity_type, 'פעילות לימודית')
    
    # שמירת סוג הפעילות בהקשר
    context.user_data['pending_learning_activity'] = {
        'type': activity_type,
        'name': activity_name,
        'duration': duration
    }
    
    await query.edit_message_text(
        f"📝 *רישום {activity_name}*\n\n"
        f"⏰ משך מוערך: {duration} דקות\n\n"
        f"✍️ שלח תיאור קצר של מה עשית:\n"
        f"• איזה חומר קראת?\n"
        f"• איזה שיעור צפית?\n"
        f"• מה תרגלת?\n"
        f"• על מה דנת?\n"
        f"• איזו מטלה הגשת?\n\n"
        f"ההודעה הבאה שלך תירשם כפעילות הלימודית.",
        parse_mode="Markdown"
    )

async def handle_activity_description(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """מטפל בתיאור הפעילות הלימודית"""
    user = update.effective_user
    message = update.message
    
    if 'pending_learning_activity' not in context.user_data:
        return
    
    activity_data = context.user_data['pending_learning_activity']
    description = message.text
    
    # רישום הפעילות במערכת הכלכלה
    result = academy_economy.add_learning_activity(
        user.id, 
        activity_data['name'], 
        activity_data['duration']
    )
    
    if result['success']:
        await message.reply_text(
            f"✅ *פעילות לימודית נרשמה!*\n\n"
            f"📚 {activity_data['name']}\n"
            f"⏰ {activity_data['duration']} דקות\n"
            f"📊 נקודות: +{result['points_earned']}\n"
            f"🪙 coins: +{result['coins_earned']:.2f}\n\n"
            f"המשך לצבור ידע וערך! 💎",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🏦 חזרה לכלכלה", callback_data="economy")
            ]])
        )
    else:
        await message.reply_text(
            "❌ שגיאה ברישום הפעילות. נסה שוב.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🏦 חזרה לכלכלה", callback_data="economy")
            ]])
        )
    
    del context.user_data['pending_learning_activity']

# =========================
# Handlers תשלומים והצטרפות
# =========================

async def payment_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """פקודת /payment - הרשמה לאקדמיה"""
    user = update.effective_user
    
    text = (
        f"🎓 *הצטרפות לאקדמיה - השקעה בעצמך!*\n\n"
        
        f"💼 *מה מקבלים?*\n"
        f"• גישה מלאה לבוט האקדמיה 🎯\n"
        f"• הצטרפות לקבוצה הפרטית: https://t.me/+WaA_aHzbwlU4MjNk 👥\n"
        f"• נכס דיגיטלי לכל החיים 📚\n"
        f"• יכולת לצרף משתתפים ולבנות רשת 🕸️\n"
        f"• מערכת מעקב והתקדמות מתקדמת 📊\n"
        f"• 100 Academy Coins עם ההצטרפות 💎\n\n"
        
        f"💰 *השקעה:* 444 ש\"ח\n\n"
        
        f"🏦 *איך משלמים?*\n"
        f"1. העברה 444 ש\"ח לחשבון הבא:\n"
        f"   בנק: ______\n"
        f"   סניף: ______\n"
        f"   חשבון: ______\n\n"
        
        f"2. שלח אישור תשלום עם השם שלך\n"
        f"3. נאשר בתוך 24 שעות\n\n"
        
        f"🚀 *זכור:* האקדמיה היא *הנכס הדיגיטלי שלך*!\n"
        f"אתה בונה כאן עסק משלים שיכול להניב הכנסות פסיביות דרך כלכלת המשחק."
    )
    
    keyboard = [
        [InlineKeyboardButton("💳 אישור תשלום", callback_data="confirm_payment")],
        [InlineKeyboardButton("❓ שאלות נפוצות", callback_data="payment_faq")],
        [InlineKeyboardButton("🏠 חזרה", callback_data="back_main")]
    ]
    
    await update.message.reply_text(
        text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def confirm_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """אישור תשלום"""
    query = update.callback_query
    await query.answer()
    
    context.user_data['pending_payment_confirmation'] = True
    
    await query.edit_message_text(
        f"💳 *אישור תשלום*\n\n"
        f"1. בצע העברה של 444 ש\"ח\n"
        f"2. שלח צילום מסך של ההעברה\n"
        f"3. פרטים נוספים:\n"
        f"   • שם מלא\n"
        f"   • מספר טלפון\n"
        f"   • אימייל (אופציונלי)\n\n"
        f"נאשר את ההצטרפות בתוך 24 שעות!\n\n"
        f"📞 לשאלות: @your_contact",
        parse_mode="Markdown"
    )

# =========================
# Handlers מערכת משימות
# =========================

async def tasks_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """פקודת /tasks - מציגה את כל המשימות"""
    user = update.effective_user
    if not user or not await ensure_user(update):
        return

    tasks = get_user_tasks(user.id)
    progress = get_user_stats(user.id)
    
    text = (
        f"🎯 *לוח משימות - התקדמות אישית*\n\n"
        f"✅ הושלמו: {progress['completed_tasks']}/{progress['total_tasks']}\n"
        f"📊 נקודות: {progress['total_points']}\n"
        f"💰 טוקנים: {progress['total_tokens']}\n"
        f"🏆 דרגה: {progress['rank']}\n\n"
        f"*רשימת המשימות:*\n"
    )
    
    keyboard = []
    for task in tasks:
        status_icon = "🟢" if task['user_status'] == 'approved' else "🟡" if task['user_status'] == 'submitted' else "🔵" if task['user_status'] == 'started' else "⚪"
        text += f"{status_icon} *משימה {task['task_number']}:* {task['title']}\n"
        text += f"   נקודות: {task['reward_points']} | טוקנים: {task['reward_tokens']}\n"
        
        if not task['user_status'] or task['user_status'] == 'pending':
            text += "   ❌ לא התחלת\n"
            keyboard.append([InlineKeyboardButton(
                f"🚀 התחל משימה {task['task_number']}", 
                callback_data=f"start_task:{task['task_number']}"
            )])
        elif task['user_status'] == 'started':
            text += "   📝 בתהליך\n"
            keyboard.append([InlineKeyboardButton(
                f"📤 הגש משימה {task['task_number']}", 
                callback_data=f"submit_task:{task['task_number']}"
            )])
        elif task['user_status'] == 'submitted':
            text += "   ⏳ ממתין לאישור\n"
        elif task['user_status'] == 'approved':
            text += f"   ✅ אושר ב{task['approved_at'].strftime('%d/%m')}\n"
        text += "\n"
    
    keyboard.append([InlineKeyboardButton("💰 ארנק", callback_data="wallet")])
    keyboard.append([InlineKeyboardButton("🏠 חזרה לתפריט ראשי", callback_data="back_main")])
    
    await update.message.reply_text(
        text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def start_task_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """מתחיל משימה"""
    query = update.callback_query
    await query.answer()
    
    user = query.from_user
    task_number = int(query.data.split(":")[1])
    
    if start_task(user.id, task_number):
        task_info = next((t for t in get_user_tasks(user.id) if t['task_number'] == task_number), None)
        
        if task_info:
            await query.edit_message_text(
                f"🎉 *התחלת משימה {task_number}!*\n\n"
                f"*{task_info['title']}*\n\n"
                f"{task_info['description']}\n\n"
                f"🎁 *תגמול:* {task_info['reward_points']} נקודות + {task_info['reward_tokens']} טוקנים\n\n"
                f"כדי להשלים את המשימה, לחץ על 'הגש משימה' כשסיימת.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton(f"📤 הגש משימה {task_number}", callback_data=f"submit_task:{task_number}"),
                    InlineKeyboardButton("📋 חזרה לרשימה", callback_data="tasks")
                ]])
            )
    else:
        await query.answer("❌ שגיאה בהתחלת המשימה", show_alert=True)

async def submit_task_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """מבקש מהמשתמש להגיש הוכחה"""
    query = update.callback_query
    await query.answer()
    
    task_number = int(query.data.split(":")[1])
    context.user_data['pending_task_submission'] = task_number
    
    task_info = next((t for t in get_user_tasks(query.from_user.id) if t['task_number'] == task_number), None)
    
    if task_info:
        await query.edit_message_text(
            f"📤 *הגשת משימה {task_number}: {task_info['title']}*\n\n"
            f"שלח הודעה עם ההוכחה שהשלמת את המשימה.\n"
            f"זה יכול להיות:\n"
            f"• לינק לפוסט/צ'אט\n• צילום מסך\n• טקסט הסבר\n\n"
            f"*הוכחה נדרשת:* {task_info['description']}\n\n"
            f"ההודעה הבאה שלך תירשם כהוכחה למשימה זו.",
            parse_mode="Markdown"
        )

async def handle_task_proof(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """מטפל בהוכחת משימה שהמשתמש שולח"""
    user = update.effective_user
    message = update.message
    
    if 'pending_task_submission' not in context.user_data:
        return
    
    task_number = context.user_data['pending_task_submission']
    proof_text = message.text or "הוכחה במדיה"
    
    # ולידציה של הקלט
    if not validate_task_submission(proof_text):
        await message.reply_text(
            "❌ ההוכחה קצרה מדי או מכילה תווים לא תקינים. נסה שוב עם הוכחה מפורטת יותר."
        )
        return
    
    if submit_task(user.id, task_number, proof_text):
        # שולח למנהלים לאישור
        admin_text = (
            f"📝 *הגשה חדשה למשימה {task_number}*\n\n"
            f"👤 משתמש: {user.first_name} (@{user.username})\n"
            f"🆔 ID: {user.id}\n"
            f"🎯 משימה: {task_number}\n"
            f"📎 הוכחה: {proof_text[:500]}{'...' if len(proof_text) > 500 else ''}\n\n"
            f"לאישור:\n"
            f"`/approve_task {user.id} {task_number}`"
        )
        
        for admin_id in ADMIN_IDS:
            try:
                await context.bot.send_message(
                    chat_id=admin_id,
                    text=admin_text,
                    parse_mode="Markdown"
                )
            except Exception as e:
                logger.error(f"Failed to notify admin {admin_id}: {e}")
        
        await message.reply_text(
            f"✅ *המשימה {task_number} הוגשה!*\n\n"
            f"ההוכחה נשלחה למנהלים לאישור.\n"
            f"תקבל הודעה כשהמשימה תאושר ותקבל את הנקודות והטוקנים.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("📋 חזרה למשימות", callback_data="tasks")
            ]])
        )
        
        del context.user_data['pending_task_submission']
    else:
        await message.reply_text("❌ שגיאה בהגשת המשימה. נסה שוב.")

async def approve_task_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """פקודת מנהל לאישור משימה"""
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("❌ אין הרשאה")
        return
    
    if len(context.args) != 2:
        await update.message.reply_text("שימוש: /approve_task <user_id> <task_number>")
        return
    
    try:
        user_id = int(context.args[0])
        task_number = int(context.args[1])
    except ValueError:
        await update.message.reply_text("מספרים לא תקינים")
        return
    
    if approve_task(user_id, task_number):
        # שולח טוקנים אוטומטית אם מערכת TokenDistributor פעילה
        wallet_address = get_user_wallet(user_id)
        if wallet_address and token_distributor.is_connected():
            task_info = next((t for t in get_user_tasks(user_id) if t['task_number'] == task_number), None)
            if task_info:
                token_amount = task_info['reward_tokens']
                tx_hash = token_distributor.send_tokens(wallet_address, token_amount)
                
                if tx_hash:
                    await update.message.reply_text(
                        f"✅ משימה {task_number} אושרה למשתמש {user_id}!\n"
                        f"🎁 נשלחו {task_info['reward_points']} נקודות ו-{token_amount} טוקנים\n"
                        f"📜 TX: `{tx_hash}`",
                        parse_mode="Markdown"
                    )
                else:
                    await update.message.reply_text(
                        f"✅ משימה {task_number} אושרה למשתמש {user_id}!\n"
                        f"🎁 נוספו {task_info['reward_points']} נקודות\n"
                        f"⚠️ לא נשלחו טוקנים - בעיה בחיבור ל-blockchain"
                    )
        else:
            await update.message.reply_text(
                f"✅ משימה {task_number} אושרה למשתמש {user_id}!\n"
                f"🎁 נקודות נוספו אך טוקנים לא נשלחו (ארנק לא מוגדר או blockchain לא פעיל)"
            )
        
        # הודעה למשתמש
        try:
            task_info = next((t for t in get_user_tasks(user_id) if t['task_number'] == task_number), None)
            if task_info:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=f"🎉 *משימה {task_number} אושרה!*\n\n"
                         f"קיבלת {task_info['reward_points']} נקודות ו-{task_info['reward_tokens']} טוקנים!\n"
                         f"📈 המשך לצבור עוד טוקנים!",
                    parse_mode="Markdown"
                )
        except Exception as e:
            logger.error(f"Failed to notify user: {e}")
    else:
        await update.message.reply_text("❌ שגיאה באישור המשימה. ייתכן שהמשימה לא הוגשה או כבר אושרה.")

# =========================
# Handlers ארנק וסטטיסטיקות
# =========================

async def wallet_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """פקודת /wallet - מציג את מצב הארנק"""
    user = update.effective_user
    if not user:
        return

    stats = get_user_stats(user.id)
    wallet_address = get_user_wallet(user.id)
    
    text = (
        f"💰 *ארנק אישי*\n\n"
        f"👤 בעלים: {user.first_name}\n"
        f"🆔 ID: {user.id}\n"
    )
    
    if wallet_address:
        text += f"📍 ארנק: `{wallet_address}`\n\n"
    else:
        text += f"📍 ארנק: *לא הוגדר* ❌\n\n"
    
    text += (
        f"*מאזן:*\n"
        f"🪙 טוקנים: {stats['total_tokens']}\n"
        f"📊 נקודות: {stats['total_points']}\n"
        f"🎯 משימות שהושלמו: {stats['completed_tasks']}/{stats['total_tasks']}\n"
        f"👥 חברים שהוזמנו: {stats['referral_count']}\n\n"
    )
    
    if not wallet_address:
        text += "ℹ️ כדי לקבל טוקנים, הגדר את כתובת ה-BSC Wallet שלך עם הפקודה:\n`/set_wallet <your_bsc_address>`"
    
    keyboard = []
    if not wallet_address:
        keyboard.append([InlineKeyboardButton("🔗 הגדר ארנק", callback_data="set_wallet")])
    
    keyboard.extend([
        [InlineKeyboardButton("🎯 משימות", callback_data="tasks")],
        [InlineKeyboardButton("📊 סטטיסטיקות", callback_data="stats")],
        [InlineKeyboardButton("🏠 חזרה", callback_data="back_main")]
    ])
    
    await update.message.reply_text(
        text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def set_wallet_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """פקודת /set_wallet - הגדרת ארנק BSC"""
    user = update.effective_user
    if not user:
        return
    
    if not context.args:
        await update.message.reply_text(
            "שימוש: `/set_wallet <your_bsc_address>`\n\n"
            "דוגמה: `/set_wallet 0x742E4C4F4B6B577B8B9B0C1D2E3F4A5B6C7D8E9F`",
            parse_mode="Markdown"
        )
        return
    
    wallet_address = context.args[0]
    
    # וולידציה עם הפונקציה החדשה
    if not validate_wallet_address(wallet_address):
        await update.message.reply_text(
            "❌ כתובת ארנק לא תקינה. ודא שזו כתובת BSC חוקית (0x... באורך 42 תווים)"
        )
        return
    
    if update_user_wallet(user.id, wallet_address):
        await update.message.reply_text(
            f"✅ *ארנק עודכן בהצלחה!*\n\n"
            f"📍 `{wallet_address}`\n\n"
            f"כעת תוכל לקבל טוקנים למשימות שלך!",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text("❌ שגיאה בעדכון הארנק. נסה שוב.")

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """פקודת /stats - סטטיסטיקות אישיות"""
    user = update.effective_user
    if not user:
        return

    stats = get_user_stats(user.id)
    economy_stats = academy_economy.get_user_economy_stats(user.id)
    
    text = (
        f"📊 *סטטיסטיקות אישיות*\n\n"
        f"👤 {user.first_name}\n"
        f"🏆 דרגה: {stats['rank']}\n\n"
        f"*הישגים:*\n"
        f"🎯 משימות: {stats['completed_tasks']}/{stats['total_tasks']} ({stats['completed_tasks']/stats['total_tasks']*100:.1f}%)\n"
        f"📊 נקודות: {stats['total_points']}\n"
        f"🪙 טוקנים: {stats['total_tokens']}\n"
        f"👥 הפניות: {stats['referral_count']}\n\n"
    )
    
    # סטטיסטיקות כלכלה
    if economy_stats:
        text += f"*כלכלת משחק:*\n"
        text += f"🏦 Academy Coins: {economy_stats.get('academy_coins', 0):.2f}\n"
        text += f"📚 למידה: {economy_stats.get('learning_points', 0)} נקודות\n"
        text += f"👨‍🏫 הוראה: {economy_stats.get('teaching_points', 0)} נקודות\n"
        text += f"💎 סך רווחים: {economy_stats.get('total_earnings', 0):.2f} coins\n"
    
    keyboard = [
        [InlineKeyboardButton("🎯 משימות", callback_data="tasks")],
        [InlineKeyboardButton("💰 ארנק", callback_data="wallet")],
        [InlineKeyboardButton("🏠 חזרה", callback_data="back_main")]
    ]
    
    await update.message.reply_text(
        text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# =========================
# Callback Handlers
# =========================

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """מטפל בכל הלחיצות על כפתורים"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    
    if data == "tasks":
        await tasks_callback(update, context)
    elif data == "wallet":
        await wallet_callback(update, context)
    elif data == "stats":
        await stats_callback(update, context)
    elif data == "economy":
        await economy_callback(update, context)
    elif data == "referrals":
        await referrals_callback(update, context)
    elif data == "admin":
        await admin_callback(update, context)
    elif data == "back_main":
        await start_callback(update, context)
    elif data == "set_wallet":
        await set_wallet_callback_handler(update, context)
    elif data == "join_academy":
        await payment_command_callback(update, context)
    elif data.startswith("start_task:"):
        await start_task_callback(update, context)
    elif data.startswith("submit_task:"):
        await submit_task_callback(update, context)
    elif data == "daily_reward":
        await daily_reward_callback(update, context)
    elif data == "learning_activity":
        await learning_activity_callback(update, context)
    elif data.startswith("activity_"):
        await handle_learning_activity(update, context)
    elif data == "confirm_payment":
        await confirm_payment_callback(update, context)

async def tasks_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """כפתור משימות"""
    query = update.callback_query
    user = query.from_user
    
    tasks = get_user_tasks(user.id)
    progress = get_user_stats(user.id)
    
    text = (
        f"🎯 *לוח משימות - התקדמות אישית*\n\n"
        f"✅ הושלמו: {progress['completed_tasks']}/{progress['total_tasks']}\n"
        f"📊 נקודות: {progress['total_points']}\n\n"
        f"*בחר משימה:*"
    )
    
    keyboard = []
    for task in tasks[:5]:  # רק 5 הראשונות לתצוגה קומפקטית
        status_icon = "🟢" if task['user_status'] == 'approved' else "🟡" if task['user_status'] == 'submitted' else "🔵" if task['user_status'] == 'started' else "⚪"
        button_text = f"{status_icon} משימה {task['task_number']}"
        
        if not task['user_status'] or task['user_status'] == 'pending':
            keyboard.append([InlineKeyboardButton(
                button_text, 
                callback_data=f"start_task:{task['task_number']}"
            )])
        elif task['user_status'] == 'started':
            keyboard.append([InlineKeyboardButton(
                button_text + " 📤", 
                callback_data=f"submit_task:{task['task_number']}"
            )])
        else:
            keyboard.append([InlineKeyboardButton(
                button_text + " ✅", 
                callback_data=f"start_task:{task['task_number']}"
            )])
    
    keyboard.extend([
        [InlineKeyboardButton("💰 ארנק", callback_data="wallet")],
        [InlineKeyboardButton("🏠 חזרה", callback_data="back_main")]
    ])
    
    await query.edit_message_text(
        text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def wallet_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """כפתור ארנק"""
    query = update.callback_query
    user = query.from_user
    
    stats = get_user_stats(user.id)
    wallet_address = get_user_wallet(user.id)
    
    text = (
        f"💰 *ארנק אישי*\n\n"
        f"🪙 טוקנים: {stats['total_tokens']}\n"
        f"📊 נקודות: {stats['total_points']}\n"
        f"🎯 משימות: {stats['completed_tasks']}/{stats['total_tasks']}\n\n"
    )
    
    if wallet_address:
        text += f"📍 `{wallet_address[:20]}...`\n"
    else:
        text += "📍 *לא הוגדר* ❌\n"
    
    keyboard = []
    if not wallet_address:
        keyboard.append([InlineKeyboardButton("🔗 הגדר ארנק", callback_data="set_wallet")])
    
    keyboard.extend([
        [InlineKeyboardButton("🎯 משימות", callback_data="tasks")],
        [InlineKeyboardButton("📊 סטטיסטיקות", callback_data="stats")],
        [InlineKeyboardButton("🏠 חזרה", callback_data="back_main")]
    ])
    
    await query.edit_message_text(
        text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def set_wallet_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """כפתור הגדרת ארנק"""
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        "🔗 *הגדרת ארנק BSC*\n\n"
        "שלח את כתובת ה-BSC Wallet שלך בפורמט:\n"
        "`/set_wallet 0x742E4C4F4B6B577B8B9B0C1D2E3F4A5B6C7D8E9F`\n\n"
        "אחרי שתגדיר את הארנק, תוכל לקבל טוקנים למשימות שלך!",
        parse_mode="Markdown"
    )

async def economy_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """כפתור כלכלה"""
    query = update.callback_query
    user = query.from_user
    
    stats = academy_economy.get_user_economy_stats(user.id)
    network_stats = academy_economy.get_network_stats(user.id)
    
    text = (
        f"🏦 *כלכלת האקדמיה*\n\n"
        f"🪙 Academy Coins: {stats.get('academy_coins', 0):.2f}\n"
        f"📚 למידה: {stats.get('learning_points', 0)} נקודות\n"
        f"👨‍🏫 הוראה: {stats.get('teaching_points', 0)} נקודות\n"
        f"🏆 {stats.get('level_name', 'מתחיל')} (רמה {stats.get('leadership_level', 1)})\n\n"
        f"🔗 רשת: {network_stats.get('level_1_students', 0)} תלמידים\n"
        f"💎 רווחי רשת: {network_stats.get('total_network_earnings', 0):.2f} coins\n"
    )
    
    keyboard = [
        [InlineKeyboardButton("🎁 תיגמול יומי", callback_data="daily_reward")],
        [InlineKeyboardButton("📖 פעילות לימודית", callback_data="learning_activity")],
        [InlineKeyboardButton("👥 הרשת שלי", callback_data="my_network")],
        [InlineKeyboardButton("🔙 חזרה", callback_data="back_main")]
    ]
    
    await query.edit_message_text(
        text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def stats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """כפתור סטטיסטיקות"""
    query = update.callback_query
    user = query.from_user
    
    stats = get_user_stats(user.id)
    economy_stats = academy_economy.get_user_economy_stats(user.id)
    
    text = (
        f"📊 *סטטיסטיקות אישיות*\n\n"
        f"🏆 {stats['rank']}\n\n"
        f"🎯 {stats['completed_tasks']}/{stats['total_tasks']} משימות\n"
        f"📊 {stats['total_points']} נקודות\n"
        f"🪙 {stats['total_tokens']} טוקנים\n"
        f"👥 {stats['referral_count']} הפניות\n"
    )
    
    if economy_stats:
        text += f"\n🏦 {economy_stats.get('academy_coins', 0):.2f} Academy Coins\n"
        text += f"📈 Level {economy_stats.get('leadership_level', 1)} {economy_stats.get('level_name', 'מתחיל')}\n"
    
    text += f"\nהמשך בקצב הזה! 💪"
    
    keyboard = [
        [InlineKeyboardButton("🎯 משימות", callback_data="tasks")],
        [InlineKeyboardButton("💰 ארנק", callback_data="wallet")],
        [InlineKeyboardButton("🏠 חזרה", callback_data="back_main")]
    ]
    
    await query.edit_message_text(
        text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def referrals_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """כפתור הפניות"""
    query = update.callback_query
    user = query.from_user
    
    stats = get_user_stats(user.id)
    bot_username = (await context.bot.get_me()).username
    
    text = (
        f"👥 *הזמן חברים*\n\n"
        f"📧 *קישור הזמנה:*\n"
        f"`https://t.me/{bot_username}?start=ref_{user.id}`\n\n"
        f"🎁 5 נקודות + 5 טוקנים לחבר\n"
        f"📈 {stats['referral_count']} חברים הוזמנו\n"
        f"💎 {stats['referral_count'] * 5} נקודות בונוס"
    )
    
    keyboard = [
        [InlineKeyboardButton("🎯 משימות", callback_data="tasks")],
        [InlineKeyboardButton("🏠 חזרה", callback_data="back_main")]
    ]
    
    await query.edit_message_text(
        text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def payment_command_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """כפתור הצטרפות לאקדמיה"""
    query = update.callback_query
    await query.answer()
    
    await payment_command(update, context)

async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """כפתור ניהול"""
    query = update.callback_query
    user = query.from_user
    
    if user.id not in ADMIN_IDS:
        await query.answer("❌ אין הרשאה", show_alert=True)
        return
    
    pending_approvals = get_pending_approvals()
    
    text = (
        f"👑 *פאנל ניהול*\n\n"
        f"⏳ {len(pending_approvals)} משימות ממתינות\n"
        f"👤 {user.first_name}\n\n"
        f"בחר פעולה:"
    )
    
    keyboard = [
        [InlineKeyboardButton("⏳ משימות ממתינות", callback_data="admin_pending")],
        [InlineKeyboardButton("🏆 טופ מזמינים", callback_data="admin_top_ref")],
        [InlineKeyboardButton("🔙 חזרה", callback_data="back_main")]
    ]
    
    await query.edit_message_text(
        text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def start_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """כפתור חזרה לתפריט ראשי"""
    query = update.callback_query
    user = query.from_user
    
    keyboard = [
        [InlineKeyboardButton("🎓 הצטרפות לאקדמיה (444₪)", callback_data="join_academy")],
        [InlineKeyboardButton("🎮 כלכלת המשחק", callback_data="economy")],
        [InlineKeyboardButton("🎯 משימות", callback_data="tasks")],
        [InlineKeyboardButton("💰 ארנק", callback_data="wallet")],
        [InlineKeyboardButton("📊 סטטיסטיקות", callback_data="stats")]
    ]
    
    if user.id in ADMIN_IDS:
        keyboard.append([InlineKeyboardButton("👑 ניהול", callback_data="admin")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        f"👋 שלום {user.first_name}!\n\n"
        f"מה תרצה לעשות?",
        reply_markup=reply_markup
    )

# =========================
# הרשמת Handlers
# =========================

def register_handlers():
    """מרשם את כל ה-handlers"""
    # handlers בסיסיים
    ptb_app.add_handler(CommandHandler("start", start_command))
    ptb_app.add_handler(CommandHandler("help", help_command))
    ptb_app.add_handler(CommandHandler("tasks", tasks_command))
    ptb_app.add_handler(CommandHandler("wallet", wallet_command))
    ptb_app.add_handler(CommandHandler("stats", stats_command))
    ptb_app.add_handler(CommandHandler("referrals", referrals_command))
    ptb_app.add_handler(CommandHandler("set_wallet", set_wallet_command))
    ptb_app.add_handler(CommandHandler("economy", economy_command))
    ptb_app.add_handler(CommandHandler("payment", payment_command))
    
    # handlers מנהל
    ptb_app.add_handler(CommandHandler("admin", admin_command))
    ptb_app.add_handler(CommandHandler("pending_tasks", pending_tasks_command))
    ptb_app.add_handler(CommandHandler("approve_task", approve_task_command))
    
    # handlers למערכת משימות
    ptb_app.add_handler(CallbackQueryHandler(start_task_callback, pattern="^start_task:"))
    ptb_app.add_handler(CallbackQueryHandler(submit_task_callback, pattern="^submit_task:"))
    ptb_app.add_handler(MessageHandler(filters.TEXT & filters.ChatType.PRIVATE, handle_task_proof))
    
    # handlers לכלכלת משחק
    ptb_app.add_handler(CallbackQueryHandler(daily_reward_callback, pattern="^daily_reward$"))
    ptb_app.add_handler(CallbackQueryHandler(learning_activity_callback, pattern="^learning_activity$"))
    ptb_app.add_handler(CallbackQueryHandler(handle_learning_activity, pattern="^activity_"))
    ptb_app.add_handler(MessageHandler(filters.TEXT & filters.ChatType.PRIVATE, handle_activity_description))
    
    # handlers כלליים
    ptb_app.add_handler(CallbackQueryHandler(handle_callback))

# =========================
# FastAPI & Webhook
# =========================

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

app = FastAPI()

@app.on_event("startup")
async def startup_event():
    """אתחול הבוט בעת הפעלת האפליקציה"""
    try:
        await ptb_app.initialize()
        await ptb_app.bot.set_webhook(url=f"{WEBHOOK_URL}/webhook")
        register_handlers()
        logger.info("🤖 Bot started successfully!")
        logger.info(f"🌐 Webhook URL: {WEBHOOK_URL}/webhook")
        logger.info(f"👑 Admin IDs: {ADMIN_IDS}")
        
        # אתחול סכמת DB
        init_schema()
        
    except Exception as e:
        logger.error(f"❌ Failed to start bot: {e}")

@app.on_event("shutdown")
async def shutdown_event():
    """ניקוי משאבים בעת כיבוי"""
    try:
        await ptb_app.shutdown()
        logger.info("🤖 Bot shutdown successfully")
    except Exception as e:
        logger.error(f"❌ Error during shutdown: {e}")

@app.post("/webhook")
async def webhook(request: Request):
    """Endpoint ל-webhook של Telegram"""
    try:
        data = await request.json()
        update = Update.de_json(data, ptb_app.bot)
        await ptb_app.process_update(update)
        return JSONResponse(content={"status": "ok"})
    except Exception as e:
        logger.error(f"❌ Webhook error: {e}")
        return JSONResponse(content={"status": "error"}, status_code=500)

@app.get("/")
async def root():
    """Health check endpoint"""
    return {
        "status": "online", 
        "service": "webwook-bot",
        "timestamp": datetime.now().isoformat(),
        "version": "3.0",
        "features": ["tasks", "economy", "payments", "token_distribution"]
    }

@app.get("/health")
async def health():
    """Health check endpoint"""
    db_status = "connected" if os.environ.get("DATABASE_URL") else "disconnected"
    blockchain_status = "connected" if token_distributor.is_connected() else "disconnected"
    
    return {
        "status": "healthy",
        "database": db_status,
        "blockchain": blockchain_status,
        "economy": "active",
        "timestamp": datetime.now().isoformat()
    }

@app.get("/debug")
async def debug():
    """Debug endpoint"""
    pending_approvals = get_pending_approvals()
    top_referrers = get_top_referrers(3)
    
    return {
        "pending_approvals": len(pending_approvals),
        "top_referrers": [{"name": r["first_name"], "count": r["referral_count"]} for r in top_referrers],
        "blockchain_connected": token_distributor.is_connected(),
        "admin_ids": list(ADMIN_IDS)
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
