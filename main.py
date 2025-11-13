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
    get_user_progress, init_schema, create_payment, approve_payment, has_paid_access,
    init_user_economy, get_user_economy_stats, add_learning_activity, claim_daily_reward,
    add_teaching_reward, get_network_stats
)
from token_distributor import token_distributor
from config import BotConfig, TaskConfig, EconomyConfig
from utils.validators import validate_wallet_address, validate_task_submission
from utils.formatters import format_tokens, format_progress

# הגדרות לוג
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# הסתרת טוקן בלוגים
class SensitiveFilter(logging.Filter):
    def filter(self, record):
        token = BotConfig.BOT_TOKEN
        if token and token in record.getMessage():
            return False
        return True

for handler in logging.root.handlers:
    handler.addFilter(SensitiveFilter())

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
        init_user_economy(user.id)
    
    return success

async def send_to_notifications_group(context: ContextTypes.DEFAULT_TYPE, message: str) -> None:
    """שולח הודעה לקבוצת ההודעות"""
    try:
        if hasattr(BotConfig, 'NOTIFICATIONS_GROUP_ID') and BotConfig.NOTIFICATIONS_GROUP_ID:
            await context.bot.send_message(
                chat_id=BotConfig.NOTIFICATIONS_GROUP_ID,
                text=message
            )
    except Exception as e:
        logger.info(f"לא ניתן לשלוח להודעות קבוצה: {e}")

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
                    add_teaching_reward(referred_by, user.id, 'referral')
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
    init_user_economy(user.id)

    text = (
        f"🎓 ברוך הבא לאקדמיה הדיגיטלית! 🚀\n\n"
        
        f"👋 שלום {user.first_name}!\n\n"
        
        f"💎 זו לא עוד פלטפורמה - זו הנכס הדיגיטלי שלך!\n\n"
        
        f"🎯 מה תקבל כאן:\n"
        f"• ידע מעשי שניתן למנף מיידית 💼\n"
        f"• יכולת לבנות רשת לימודית משלך 🕸️\n"
        f"• כלכלת משחק שמרוויחה עבורך 🎮\n"
        f"• Academy Coins - המטבע שלך 🪙\n\n"
        
        f"📈 איך מרוויחים:\n"
        f"1. לומדים וצוברים נקודות 📚\n"
        f"2. מלמדים ומרחיבים את הרשת 👥\n"
        f"3. מתקדמים בדרגות Leadership 🏆\n"
        f"4. ממירים ל-tokens אמיתיים 💰\n\n"
        
        f"🚀 גישה מלאה לאקדמיה:\n"
        f"• עלות: {BotConfig.ACADEMY_PRICE} ש\"ח\n"
        f"• קבוצת לימוד פרטית: {BotConfig.ACADEMY_GROUP_LINK}\n"
        f"• תמיכה אישית\n"
        f"• {EconomyConfig.ACADEMY_SIGNUP_BONUS} Academy Coins מתנה!\n\n"
        
        f"💼 זכור: האקדמיה היא הנכס הדיגיטלי שלך!\n"
        f"אתה בונה כאן עסק משלים שיכול להניב הכנסות פסיביות דרך כלכלת המשחק."
    )

    keyboard = [
        [InlineKeyboardButton(f"🎓 הצטרפות לאקדמיה ({BotConfig.ACADEMY_PRICE}₪)", callback_data="join_academy")],
        [InlineKeyboardButton("🎮 כלכלת המשחק", callback_data="economy")],
        [InlineKeyboardButton("🎯 משימות", callback_data="tasks")],
        [InlineKeyboardButton("💰 ארנק", callback_data="wallet")],
        [InlineKeyboardButton("📊 סטטיסטיקות", callback_data="stats")]
    ]
    
    if user.id in BotConfig.ADMIN_IDS:
        keyboard.append([InlineKeyboardButton("👑 ניהול", callback_data="admin")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        text,
        reply_markup=reply_markup
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """פקודת /help מעודכנת"""
    await update.message.reply_text(
        "📖 מדריך שימוש - אקדמיה דיגיטלית\n\n"
        "🎯 /tasks - הצג את כל המשימות הזמינות\n"
        "💰 /wallet - צפה בארנק ובטוקנים שלך\n"
        "🏦 /economy - כלכלת המשחק ו-Academy Coins\n"
        "📊 /stats - סטטיסטיקות אישיות\n"
        "👥 /referrals - הזמן חברים וקבל בונוסים\n"
        "🔗 /set_wallet <address> - הגדר ארנק BSC\n"
        "💳 /payment - הרשמה לאקדמיה המלאה\n"
        "🆘 /help - הצג הודעה זו\n\n"
        "לשאלות נוספות פנה למנהלים."
    )

# =========================
# Handlers הפניות
# =========================

async def referrals_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """פקודת /referrals - הזמנת חברים"""
    user = update.effective_user
    if not user:
        return

    stats = get_user_stats(user.id)
    bot_username = (await context.bot.get_me()).username
    
    text = (
        f"👥 הזמן חברים - קבל בונוסים!\n\n"
        f"📧 קישור הזמנה אישי:\n"
        f"https://t.me/{bot_username}?start=ref_{user.id}\n\n"
        f"🎁 מה תקבל:\n"
        f"• {EconomyConfig.REFERRAL_BONUS['points']} נקודות לכל חבר שהצטרף\n"
        f"• {EconomyConfig.REFERRAL_BONUS['tokens']} טוקנים לכל חבר שהצטרף\n"
        f"• {EconomyConfig.REFERRAL_BONUS['coins']} Academy Coins לכל חבר שהצטרף\n\n"
        f"📈 סטטיסטיקות ההפניות שלך:\n"
        f"• {stats['referral_count']} חברים הוזמנו\n"
        f"• {stats['referral_count'] * EconomyConfig.REFERRAL_BONUS['points']} נקודות בונוס\n"
        f"• {stats['referral_count'] * EconomyConfig.REFERRAL_BONUS['tokens']} טוקנים בונוס\n\n"
        f"💎 הזמן עוד חברים ותרוויח יותר!"
    )
    
    keyboard = [
        [InlineKeyboardButton("🎯 חזרה לתפריט", callback_data="back_main")]
    ]
    
    await update.message.reply_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# =========================
# Handlers מנהל
# =========================

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """פקודת /admin - פאנל ניהול"""
    user = update.effective_user
    if user.id not in BotConfig.ADMIN_IDS:
        await update.message.reply_text("❌ אין הרשאה")
        return
    
    pending_approvals = get_pending_approvals()
    top_referrers = get_top_referrers(5)
    
    text = (
        f"👑 פאנל ניהול - אקדמיה דיגיטלית\n\n"
        f"📊 סטטיסטיקות מערכת:\n"
        f"• ⏳ {len(pending_approvals)} משימות ממתינות לאישור\n"
        f"• 👤 {len(top_referrers)} מובילים בהפניות\n\n"
        
        f"📋 פקודות מנהל זמינות:\n"
        f"• /pending_tasks - הצג משימות ממתינות\n"
        f"• /approve_task <user_id> <task_number> - אשר משימה\n"
        f"• /group_info - מידע על הקבוצה\n"
        f"• /broadcast <message> - שליחת הודעה לכל המשתמשים\n\n"
        
        f"🔧 ניהול מערכת:\n"
        f"• /stats - סטטיסטיקות מערכת\n"
        f"• /backup - גיבוי נתונים\n"
    )
    
    keyboard = [
        [InlineKeyboardButton("⏳ משימות ממתינות", callback_data="admin_pending")],
        [InlineKeyboardButton("🏆 טופ מזמינים", callback_data="admin_top_ref")],
        [InlineKeyboardButton("👥 מידע קבוצה", callback_data="admin_group_info")],
        [InlineKeyboardButton("🔙 חזרה", callback_data="back_main")]
    ]
    
    await update.message.reply_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def pending_tasks_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """פקודת /pending_tasks - הצגת משימות ממתינות"""
    user = update.effective_user
    if user.id not in BotConfig.ADMIN_IDS:
        await update.message.reply_text("❌ אין הרשאה")
        return
    
    pending_tasks = get_pending_approvals()
    
    if not pending_tasks:
        await update.message.reply_text("✅ אין משימות ממתינות לאישור")
        return
    
    text = "⏳ משימות ממתינות לאישור:\n\n"
    
    for i, task in enumerate(pending_tasks[:10], 1):  # מוגבל ל-10 משימות
        text += (
            f"{i}. משימה {task['task_number']} - {task['title']}\n"
            f"👤 {task['first_name']} (@{task['username'] or 'ללא'})\n"
            f"🆔 {task['user_id']}\n"
            f"📝 {task['submitted_proof'][:100]}{'...' if len(task['submitted_proof']) > 100 else ''}\n"
            f"⏰ {task['submitted_at'].strftime('%d/%m/%Y %H:%M')}\n"
            f"/approve_task {task['user_id']} {task['task_number']}\n\n"
        )
    
    if len(pending_tasks) > 10:
        text += f"... ועוד {len(pending_tasks) - 10} משימות"
    
    await update.message.reply_text(text)

async def approve_task_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """פקודת /approve_task - אישור משימה"""
    user = update.effective_user
    if user.id not in BotConfig.ADMIN_IDS:
        await update.message.reply_text("❌ אין הרשאה")
        return
    
    if len(context.args) != 2:
        await update.message.reply_text("שימוש: /approve_task <user_id> <task_number>")
        return
    
    try:
        user_id = int(context.args[0])
        task_number = int(context.args[1])
        
        if approve_task(user_id, task_number):
            # שליחת הודעה למשתמש
            try:
                tasks = get_user_tasks(user_id)
                task = next((t for t in tasks if t['task_number'] == task_number), None)
                task_title = task['title'] if task else f"משימה {task_number}"
                
                await context.bot.send_message(
                    chat_id=user_id,
                    text=f"🎉 המשימה '{task_title}' אושרה!\n\n"
                         f"✅ קיבלת את התגמולים עבור המשימה.\n"
                         f"💎 המשיך ללמוד ולהרוויח!"
                )
                
                # הודעה לקבוצת ההודעות
                user_info = f"{task['first_name']} (@{task['username'] or 'ללא'})" if task else f"משתמש {user_id}"
                await send_to_notifications_group(
                    context,
                    f"✅ משימה אושרה: {user_info} - {task_title}"
                )
            except Exception as e:
                logger.info(f"לא ניתן לשלוח הודעה למשתמש: {e}")
            
            await update.message.reply_text(f"✅ משימה {task_number} אושרה למשתמש {user_id}")
        else:
            await update.message.reply_text("❌ לא ניתן לאשר את המשימה")
    except ValueError:
        await update.message.reply_text("❌ פרמטרים לא תקינים")

async def group_info_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """פקודת /group_info - מידע על הקבוצה"""
    user = update.effective_user
    if user.id not in BotConfig.ADMIN_IDS:
        await update.message.reply_text("❌ אין הרשאה")
        return
    
    text = (
        f"👥 מידע קבוצת האקדמיה\n\n"
        f"🔗 קישור קבוצה:\n"
        f"{BotConfig.ACADEMY_GROUP_LINK}\n\n"
        f"📊 סטטיסטיקות:\n"
        f"• קישור קבוצה: פעיל ✅\n"
        f"• קבוצה פרטית: כן ✅\n"
        f"• גישה: למשתתפים בלבד 🔒\n\n"
        f"💡 הנחיות:\n"
        f"1. הקבוצה מיועדת למשתתפים ששילמו {BotConfig.ACADEMY_PRICE} ש\"ח\n"
        f"2. יש לאשר משתתפים ידנית\n"
        f"3. שמור על הקבוצה פעילה ואיכותית\n"
    )
    
    keyboard = [
        [InlineKeyboardButton("🔗 פתח קבוצה", url=BotConfig.ACADEMY_GROUP_LINK)],
        [InlineKeyboardButton("👑 חזרה לניהול", callback_data="admin")]
    ]
    
    await update.message.reply_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# =========================
# Handlers תשלומים והצטרפות
# =========================

async def payment_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """פקודת /payment - הרשמה לאקדמיה"""
    user = update.effective_user
    
    # בדיקה אם כבר יש גישה
    if has_paid_access(user.id):
        await update.message.reply_text(
            f"✅ כבר יש לך גישה מלאה לאקדמיה!\n\n"
            f"🔗 קבוצת האקדמיה: {BotConfig.ACADEMY_GROUP_LINK}\n\n"
            f"💎 המשך ללמוד ולהרוויח!"
        )
        return
    
    bank = BotConfig.BANK_DETAILS
    
    text = (
        f"🎓 הצטרפות לאקדמיה - השקעה בעצמך!\n\n"
        
        f"💼 מה מקבלים?\n"
        f"• גישה מלאה לבוט האקדמיה 🎯\n"
        f"• הצטרפות לקבוצה הפרטית: {BotConfig.ACADEMY_GROUP_LINK} 👥\n"
        f"• נכס דיגיטלי לכל החיים 📚\n"
        f"• יכולת לצרף משתתפים ולבנות רשת 🕸️\n"
        f"• מערכת מעקב והתקדמות מתקדמת 📊\n"
        f"• {EconomyConfig.ACADEMY_SIGNUP_BONUS} Academy Coins עם ההצטרפות 💎\n\n"
        
        f"💰 השקעה: {BotConfig.ACADEMY_PRICE} ש\"ח\n\n"
        
        f"🏦 איך משלמים?\n"
        f"1. העברה {BotConfig.ACADEMY_PRICE} ש\"ח לחשבון הבא:\n"
        f"   בנק: {bank['bank']}\n"
        f"   סניף: {bank['branch']}\n"
        f"   חשבון: {bank['account']}\n\n"
        
        f"2. שלח אישור תשלום עם השם שלך\n"
        f"3. נאשר בתוך 24 שעות\n\n"
        
        f"🚀 זכור: האקדמיה היא הנכס הדיגיטלי שלך!\n"
        f"אתה בונה כאן עסק משלים שיכול להניב הכנסות פסיביות דרך כלכלת המשחק."
    )
    
    keyboard = [
        [InlineKeyboardButton("💳 אישור תשלום", callback_data="confirm_payment")],
        [InlineKeyboardButton("🔗 קבוצת האקדמיה", url=BotConfig.ACADEMY_GROUP_LINK)],
        [InlineKeyboardButton("🏠 חזרה", callback_data="back_main")]
    ]
    
    await update.message.reply_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def confirm_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """אישור תשלום"""
    query = update.callback_query
    await query.answer()
    
    user = query.from_user
    
    # יצירת רשומת תשלום
    if create_payment(user.id, BotConfig.ACADEMY_PRICE, "bank_transfer"):
        context.user_data['pending_payment_confirmation'] = True
        
        bank = BotConfig.BANK_DETAILS
        
        await query.edit_message_text(
            f"💳 אישור תשלום\n\n"
            f"1. בצע העברה של {BotConfig.ACADEMY_PRICE} ש\"ח לחשבון:\n"
            f"   בנק: {bank['bank']}\n"
            f"   סניף: {bank['branch']}\n"
            f"   חשבון: {bank['account']}\n\n"
            f"2. שלח צילום מסך של ההעברה\n"
            f"3. פרטים נוספים:\n"
            f"   • שם מלא\n"
            f"   • מספר טלפון\n"
            f"   • אימייל (אופציונלי)\n\n"
            f"נאשר את ההצטרפות בתוך 24 שעות!\n\n"
            f"🔗 לאחר האישור תקבל גישה ל: {BotConfig.ACADEMY_GROUP_LINK}"
        )
    else:
        await query.answer("❌ שגיאה ביצירת בקשת תשלום", show_alert=True)

# =========================
# Handlers כלכלת משחק
# =========================

async def economy_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """פקודת /economy - מציג את המצב הכלכלי"""
    user = update.effective_user
    if not user or not await ensure_user(update):
        return

    stats = get_user_economy_stats(user.id)
    network_stats = get_network_stats(user.id)
    
    text = (
        f"🏦 כלכלת האקדמיה - {user.first_name}\n\n"
        f"💰 מאזן:\n"
        f"🪙 Academy Coins: {stats.get('academy_coins', 0):.2f}\n"
        f"📚 נקודות למידה: {stats.get('learning_points', 0)}\n"
        f"👨‍🏫 נקודות הוראה: {stats.get('teaching_points', 0)}\n"
        f"💎 סך הרווחים: {stats.get('total_earnings', 0):.2f} coins\n\n"
        
        f"🎯 דרגת Leadership:\n"
        f"🏆 {stats.get('level_name', 'מתחיל')} (רמה {stats.get('leadership_level', 1)})\n"
        f"📈 מכפיל: x{stats.get('level_multiplier', 1.0)}\n"
        f"👥 תלמידים: {stats.get('student_count', 0)}\n"
        f"🎓 נדרשים לדרגה הבאה: {stats.get('next_level_students_needed', 0)} תלמידים\n\n"
    )
    
    # הוספת נתוני רשת אם קיימים
    if network_stats.get('level_1_students', 0) > 0 or network_stats.get('level_2_students', 0) > 0 or network_stats.get('level_3_students', 0) > 0:
        text += (
            f"📊 סטטיסטיקות רשת:\n"
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
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def daily_reward_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """תיגמול יומי"""
    query = update.callback_query
    await query.answer()
    
    user = query.from_user
    result = claim_daily_reward(user.id)
    
    if result['success']:
        await query.edit_message_text(
            f"🎁 תיגמול יומי\n\n"
            f"💰 קיבלת {result['reward']:.2f} Academy Coins!\n"
            f"📊 בסיס: {result['base_reward']:.2f}\n"
            f"🔥 בונוס סטריק: {result['streak_bonus']:.2f}\n"
            f"📈 סטריק נוכחי: {result['new_streak']} ימים\n\n"
            f"💎 חזור מחר לעוד תיגמול!"
        )
        
        # שליחה להודעות קבוצה
        await send_to_notifications_group(
            context,
            f"🎉 {user.first_name} (@{user.username or 'ללא'}) קיבל תיגמול יומי של {result['reward']:.2f} coins! (סטריק: {result['new_streak']})"
        )
    else:
        await query.answer(result.get('message', '❌ שגיאה בתיגמול היומי'), show_alert=True)

async def learning_activity_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """פעילות לימודית"""
    query = update.callback_query
    await query.answer()
    
    text = (
        "📖 פעילות לימודית\n\n"
        "בחר סוג פעילות:\n\n"
        "🎯 כל פעילות מזכה בנקודות ו-Academy Coins\n"
        "💡 ככל שהפעילות ארוכה יותר, כך הרווח גדול יותר"
    )
    
    keyboard = [
        [InlineKeyboardButton("📚 קריאת מאמר (10 דק')", callback_data="activity_reading_10")],
        [InlineKeyboardButton("🎥 צפייה בסרטון (15 דק')", callback_data="activity_video_15")],
        [InlineKeyboardButton("💻 תרגול מעשי (20 דק')", callback_data="activity_practice_20")],
        [InlineKeyboardButton("📝 כתיבת תוכן (25 דק')", callback_data="activity_writing_25")],
        [InlineKeyboardButton("🔙 חזרה", callback_data="economy")]
    ]
    
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def handle_learning_activity(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """מטפל בבחירת פעילות לימודית"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    user = query.from_user
    
    # מיפוי פעילויות
    activities = {
        'activity_reading_10': {'type': 'קריאת מאמר', 'duration': 10},
        'activity_video_15': {'type': 'צפייה בסרטון', 'duration': 15},
        'activity_practice_20': {'type': 'תרגול מעשי', 'duration': 20},
        'activity_writing_25': {'type': 'כתיבת תוכן', 'duration': 25}
    }
    
    activity = activities.get(data)
    if activity:
        context.user_data['pending_activity'] = activity
        await query.edit_message_text(
            f"📖 {activity['type']} - {activity['duration']} דקות\n\n"
            f"📝 שלח תיאור קצר של מה למדת:\n"
            f"(2-3 משפטים מספיקים)"
        )

async def handle_activity_description(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """מטפל בתיאור הפעילות"""
    user = update.effective_user
    description = update.message.text
    
    if 'pending_activity' not in context.user_data:
        return
    
    activity = context.user_data['pending_activity']
    
    result = add_learning_activity(
        user.id, 
        activity['type'], 
        activity['duration'], 
        description
    )
    
    if result['success']:
        await update.message.reply_text(
            f"🎉 פעילות נרשמה בהצלחה!\n\n"
            f"📊 נקודות: +{result['points_earned']}\n"
            f"🪙 Academy Coins: +{result['coins_earned']:.2f}\n"
            f"📚 סוג: {result['activity_type']}\n\n"
            f"💎 המשך ללמוד ולהרוויח!"
        )
        
        # שליחה להודעות קבוצה
        await send_to_notifications_group(
            context,
            f"📚 {user.first_name} (@{user.username or 'ללא'}) השלים פעילות: {activity['type']} - {result['points_earned']} נקודות, {result['coins_earned']:.2f} coins"
        )
        
        del context.user_data['pending_activity']
    else:
        await update.message.reply_text("❌ שגיאה ברישום הפעילות")

async def my_network_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """הרשת שלי"""
    query = update.callback_query
    await query.answer()
    
    user = query.from_user
    network_stats = get_network_stats(user.id)
    economy_stats = get_user_economy_stats(user.id)
    
    text = (
        f"👥 הרשת הלימודית שלי\n\n"
        f"📊 סטטיסטיקות רשת:\n"
        f"🔗 Level 1: {network_stats.get('level_1_students', 0)} תלמידים\n"
        f"🔗 Level 2: {network_stats.get('level_2_students', 0)} תלמידים\n"
        f"🔗 Level 3: {network_stats.get('level_3_students', 0)} תלמידים\n"
        f"💵 רווחי רשת: {network_stats.get('total_network_earnings', 0):.2f} coins\n\n"
        
        f"🎯 דרגת Leadership:\n"
        f"🏆 {economy_stats.get('level_name', 'מתחיל')}\n"
        f"👥 תלמידים: {economy_stats.get('student_count', 0)}\n"
        f"🎓 נדרשים לדרגה הבאה: {economy_stats.get('next_level_students_needed', 0)} תלמידים\n\n"
        
        f"💡 טיפ: הזמן יותר חברים כדי להגדיל את הרשת ולהרוויח יותר!"
    )
    
    keyboard = [
        [InlineKeyboardButton("👥 הזמן חברים", callback_data="referrals")],
        [InlineKeyboardButton("🔙 חזרה לכלכלה", callback_data="economy")]
    ]
    
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

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
        f"💰 ארנק אישי\n\n"
        f"👤 בעלים: {user.first_name}\n"
        f"🆔 ID: {user.id}\n"
    )
    
    if wallet_address:
        text += f"📍 ארנק: {wallet_address}\n\n"
    else:
        text += f"📍 ארנק: לא הוגדר ❌\n\n"
    
    text += (
        f"מאזן:\n"
        f"🪙 טוקנים: {stats['total_tokens']}\n"
        f"📊 נקודות: {stats['total_points']}\n"
        f"🎯 משימות שהושלמו: {stats['completed_tasks']}/{stats['total_tasks']}\n"
        f"👥 חברים שהוזמנו: {stats['referral_count']}\n\n"
    )
    
    if not wallet_address:
        text += "ℹ️ כדי לקבל טוקנים, הגדר את כתובת ה-BSC Wallet שלך עם הפקודה:\n/set_wallet <your_bsc_address>"
    
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
            "דוגמה: `/set_wallet 0x742E4C4F4B6B577B8B9B0C1D2E3F4A5B6C7D8E9F`"
        )
        return
    
    wallet_address = context.args[0]
    
    # וולידציה
    if not validate_wallet_address(wallet_address):
        await update.message.reply_text(
            "❌ כתובת ארנק לא תקינה. ודא שזו כתובת BSC חוקית (0x... באורך 42 תווים)"
        )
        return
    
    if update_user_wallet(user.id, wallet_address):
        await update.message.reply_text(
            f"✅ ארנק עודכן בהצלחה!\n\n"
            f"📍 {wallet_address}\n\n"
            f"כעת תוכל לקבל טוקנים למשימות שלך!"
        )
    else:
        await update.message.reply_text("❌ שגיאה בעדכון הארנק. נסה שוב.")

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """פקודת /stats - סטטיסטיקות אישיות"""
    user = update.effective_user
    if not user:
        return

    stats = get_user_stats(user.id)
    economy_stats = get_user_economy_stats(user.id)
    
    text = (
        f"📊 סטטיסטיקות אישיות\n\n"
        f"👤 {user.first_name}\n"
        f"🏆 דרגה: {stats['rank']}\n\n"
        f"הישגים:\n"
        f"🎯 משימות: {stats['completed_tasks']}/{stats['total_tasks']} ({stats['completed_tasks']/stats['total_tasks']*100:.1f}%)\n"
        f"📊 נקודות: {stats['total_points']}\n"
        f"🪙 טוקנים: {stats['total_tokens']}\n"
        f"👥 הפניות: {stats['referral_count']}\n\n"
    )
    
    # סטטיסטיקות כלכלה
    if economy_stats:
        text += f"כלכלת משחק:\n"
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
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# =========================
# Handlers משימות
# =========================

async def tasks_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """פקודת /tasks - מציגה את כל המשימות"""
    user = update.effective_user
    if not user or not await ensure_user(update):
        return

    tasks = get_user_tasks(user.id)
    progress = get_user_stats(user.id)
    
    text = (
        f"🎯 לוח משימות - התקדמות אישית\n\n"
        f"✅ הושלמו: {progress['completed_tasks']}/{progress['total_tasks']}\n"
        f"📊 נקודות: {progress['total_points']}\n"
        f"💰 טוקנים: {progress['total_tokens']}\n"
        f"🏆 דרגה: {progress['rank']}\n\n"
        f"רשימת המשימות:\n"
    )
    
    keyboard = []
    for task in tasks:
        status_icon = "🟢" if task['user_status'] == 'approved' else "🟡" if task['user_status'] == 'submitted' else "🔵" if task['user_status'] == 'started' else "⚪"
        text += f"{status_icon} משימה {task['task_number']}: {task['title']}\n"
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
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def start_task_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """מתחיל משימה"""
    query = update.callback_query
    await query.answer()
    
    user = query.from_user
    task_number = int(query.data.split(':')[1])
    
    if start_task(user.id, task_number):
        tasks = get_user_tasks(user.id)
        task = next((t for t in tasks if t['task_number'] == task_number), None)
        
        if task:
            await query.edit_message_text(
                f"🎯 התחלת משימה {task_number}\n\n"
                f"📝 {task['title']}\n\n"
                f"📋 תיאור:\n{task['description']}\n\n"
                f"🎁 פרס:\n"
                f"• {task['reward_points']} נקודות\n"
                f"• {task['reward_tokens']} טוקנים\n\n"
                f"📤 כשתסיים, לחץ על 'הגש משימה'"
            )
        else:
            await query.answer("❌ לא נמצאה משימה", show_alert=True)
    else:
        await query.answer("❌ שגיאה בהתחלת המשימה", show_alert=True)

async def submit_task_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """מגיש משימה"""
    query = update.callback_query
    await query.answer()
    
    user = query.from_user
    task_number = int(query.data.split(':')[1])
    
    context.user_data['pending_task_submission'] = task_number
    await query.edit_message_text(
        f"📤 הגשת משימה {task_number}\n\n"
        f"📝 שלח את ההוכחה להשלמת המשימה:\n"
        f"(קישור, צילום מסך, או טקסט)\n\n"
        f"💡 דוגמאות:\n"
        f"• קישור לפוסט\n"
        f"• צילום מסך של ההצטרפות\n"
        f"• תיאור מפורט של מה עשית"
    )

async def handle_task_proof(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """מטפל בהוכחת משימה"""
    user = update.effective_user
    proof = update.message.text
    
    if 'pending_task_submission' not in context.user_data:
        return
    
    task_number = context.user_data['pending_task_submission']
    
    if submit_task(user.id, task_number, proof):
        # שליחה להודעות קבוצה
        tasks = get_user_tasks(user.id)
        task = next((t for t in tasks if t['task_number'] == task_number), None)
        task_title = task['title'] if task else f"משימה {task_number}"
        
        await send_to_notifications_group(
            context,
            f"📤 {user.first_name} (@{user.username or 'ללא'}) הגיש משימה: {task_title}\n\n📝 הוכחה: {proof[:100]}..."
        )
        
        await update.message.reply_text(
            f"✅ המשימה {task_number} הוגשה בהצלחה!\n\n"
            f"📤 ההוכחה נשלחה לאישור המנהלים.\n"
            f"⏳ תקבל הודעה כאשר המשימה תאושר.\n\n"
            f"💎 בינתיים, אתה יכול להמשיך למשימות אחרות!"
        )
        del context.user_data['pending_task_submission']
    else:
        await update.message.reply_text("❌ שגיאה בהגשת המשימה")

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
    elif data == "admin_pending":
        await pending_tasks_command(update, context)
    elif data == "admin_top_ref":
        await admin_top_referrers_callback(update, context)
    elif data == "admin_group_info":
        await group_info_command(update, context)
    elif data == "my_network":
        await my_network_callback(update, context)
    else:
        await query.answer("❌ פעולה לא זמינה", show_alert=True)

# =========================
# פונקציות Callback נוספות
# =========================

async def tasks_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """כפתור משימות"""
    query = update.callback_query
    user = query.from_user
    
    tasks = get_user_tasks(user.id)
    progress = get_user_stats(user.id)
    
    text = (
        f"🎯 לוח משימות - התקדמות אישית\n\n"
        f"✅ הושלמו: {progress['completed_tasks']}/{progress['total_tasks']}\n"
        f"📊 נקודות: {progress['total_points']}\n\n"
        f"בחר משימה:"
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
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def wallet_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """כפתור ארנק"""
    query = update.callback_query
    user = query.from_user
    
    stats = get_user_stats(user.id)
    wallet_address = get_user_wallet(user.id)
    
    text = (
        f"💰 ארנק אישי\n\n"
        f"🪙 טוקנים: {stats['total_tokens']}\n"
        f"📊 נקודות: {stats['total_points']}\n"
        f"🎯 משימות: {stats['completed_tasks']}/{stats['total_tasks']}\n\n"
    )
    
    if wallet_address:
        text += f"📍 {wallet_address[:20]}...\n"
    else:
        text += "📍 לא הוגדר ❌\n"
    
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
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def set_wallet_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """כפתור הגדרת ארנק"""
    query = update.callback_query
    await query.answer()
    
    await query.edit_message_text(
        "🔗 הגדרת ארנק BSC\n\n"
        "שלח את כתובת ה-BSC Wallet שלך בפורמט:\n"
        "/set_wallet 0x742E4C4F4B6B577B8B9B0C1D2E3F4A5B6C7D8E9F\n\n"
        "אחרי שתגדיר את הארנק, תוכל לקבל טוקנים למשימות שלך!"
    )

async def economy_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """כפתור כלכלה"""
    query = update.callback_query
    user = query.from_user
    
    stats = get_user_economy_stats(user.id)
    network_stats = get_network_stats(user.id)
    
    text = (
        f"🏦 כלכלת האקדמיה\n\n"
        f"🪙 Academy Coins: {stats.get('academy_coins', 0):.2f}\n"
        f"📚 למידה: {stats.get('learning_points', 0)} נקודות\n"
        f"👨‍🏫 הוראה: {stats.get('teaching_points', 0)} נקודות\n"
        f"🏆 {stats.get('level_name', 'מתחיל')} (רמה {stats.get('leadership_level', 1)})\n\n"
    )
    
    if network_stats.get('level_1_students', 0) > 0:
        text += f"🔗 רשת: {network_stats.get('level_1_students', 0)} תלמידים\n"
        text += f"💎 רווחי רשת: {network_stats.get('total_network_earnings', 0):.2f} coins\n"
    
    keyboard = [
        [InlineKeyboardButton("🎁 תיגמול יומי", callback_data="daily_reward")],
        [InlineKeyboardButton("📖 פעילות לימודית", callback_data="learning_activity")],
        [InlineKeyboardButton("👥 הרשת שלי", callback_data="my_network")],
        [InlineKeyboardButton("🔙 חזרה", callback_data="back_main")]
    ]
    
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def stats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """כפתור סטטיסטיקות"""
    query = update.callback_query
    user = query.from_user
    
    stats = get_user_stats(user.id)
    economy_stats = get_user_economy_stats(user.id)
    
    text = (
        f"📊 סטטיסטיקות אישיות\n\n"
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
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def referrals_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """כפתור הפניות"""
    query = update.callback_query
    user = query.from_user
    
    stats = get_user_stats(user.id)
    bot_username = (await context.bot.get_me()).username
    
    text = (
        f"👥 הזמן חברים\n\n"
        f"📧 קישור הזמנה:\n"
        f"https://t.me/{bot_username}?start=ref_{user.id}\n\n"
        f"🎁 {EconomyConfig.REFERRAL_BONUS['points']} נקודות + {EconomyConfig.REFERRAL_BONUS['tokens']} טוקנים לחבר\n"
        f"📈 {stats['referral_count']} חברים הוזמנו\n"
        f"💎 {stats['referral_count'] * EconomyConfig.REFERRAL_BONUS['points']} נקודות בונוס"
    )
    
    keyboard = [
        [InlineKeyboardButton("🎯 משימות", callback_data="tasks")],
        [InlineKeyboardButton("🏠 חזרה", callback_data="back_main")]
    ]
    
    await query.edit_message_text(
        text,
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
    
    if user.id not in BotConfig.ADMIN_IDS:
        await query.answer("❌ אין הרשאה", show_alert=True)
        return
    
    pending_approvals = get_pending_approvals()
    
    text = (
        f"👑 פאנל ניהול\n\n"
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
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def admin_top_referrers_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """כפתור טופ מזמינים"""
    query = update.callback_query
    user = query.from_user
    
    if user.id not in BotConfig.ADMIN_IDS:
        await query.answer("❌ אין הרשאה", show_alert=True)
        return
    
    top_referrers = get_top_referrers(10)
    
    text = "🏆 טופ 10 מזמינים:\n\n"
    
    for i, referrer in enumerate(top_referrers, 1):
        text += f"{i}. {referrer['first_name']} (@{referrer['username'] or 'ללא'})\n"
        text += f"   🎯 {referrer['referral_count']} הפניות\n\n"
    
    if not top_referrers:
        text += "אין עדיין הפניות במערכת"
    
    keyboard = [
        [InlineKeyboardButton("👑 חזרה לניהול", callback_data="admin")]
    ]
    
    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def start_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """כפתור חזרה לתפריט ראשי"""
    query = update.callback_query
    user = query.from_user
    
    keyboard = [
        [InlineKeyboardButton(f"🎓 הצטרפות לאקדמיה ({BotConfig.ACADEMY_PRICE}₪)", callback_data="join_academy")],
        [InlineKeyboardButton("🎮 כלכלת המשחק", callback_data="economy")],
        [InlineKeyboardButton("🎯 משימות", callback_data="tasks")],
        [InlineKeyboardButton("💰 ארנק", callback_data="wallet")],
        [InlineKeyboardButton("📊 סטטיסטיקות", callback_data="stats")]
    ]
    
    if user.id in BotConfig.ADMIN_IDS:
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
    ptb_app.add_handler(CommandHandler("group_info", group_info_command))
    
    # handlers למערכת משימות
    ptb_app.add_handler(CallbackQueryHandler(start_task_callback, pattern="^start_task:"))
    ptb_app.add_handler(CallbackQueryHandler(submit_task_callback, pattern="^submit_task:"))
    ptb_app.add_handler(MessageHandler(filters.TEXT & filters.ChatType.PRIVATE, handle_task_proof))
    
    # handlers לכלכלת משחק
    ptb_app.add_handler(CallbackQueryHandler(daily_reward_callback, pattern="^daily_reward$"))
    ptb_app.add_handler(CallbackQueryHandler(learning_activity_callback, pattern="^learning_activity$"))
    ptb_app.add_handler(CallbackQueryHandler(my_network_callback, pattern="^my_network$"))
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
        # אתחול סכמת DB ראשון
        logger.info("🔄 Initializing database schema...")
        init_schema()
        logger.info("✅ Database schema initialized successfully!")
        
        await ptb_app.initialize()
        await ptb_app.bot.set_webhook(url=f"{BotConfig.WEBHOOK_URL}/webhook")
        register_handlers()
        logger.info("🤖 Bot started successfully!")
        logger.info(f"🌐 Webhook URL: {BotConfig.WEBHOOK_URL}/webhook")
        logger.info(f"👑 Admin IDs: {BotConfig.ADMIN_IDS}")
        
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
        "admin_ids": list(BotConfig.ADMIN_IDS)
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=BotConfig.PORT)
