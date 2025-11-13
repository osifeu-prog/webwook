# main.py - מעודכן עם אינטגרציה מלאה ל-database
import os
import logging
from collections import deque
from contextlib import asynccontextmanager
from datetime import datetime
from http import HTTPStatus
from typing import Deque, Set, Literal, Optional, Dict, Any, List

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
from telegram.error import TelegramError

from db import (
    init_schema, store_user, get_user_wallet, update_user_wallet,
    get_user_tasks, start_task, submit_task, approve_task, 
    get_user_stats, add_referral, get_top_referrers, get_pending_approvals
)
from token_distributor import token_distributor

# הגדרות לוג
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# משתני סביבה
BOT_TOKEN = os.environ.get("BOT_TOKEN")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "https://webwook-production.up.railway.app")
ADMIN_IDS = [int(x.strip()) for x in os.environ.get("ADMIN_USER_IDS", "224223270").split(",")]
PORT = int(os.environ.get("PORT", 8080))

# אתחול הבוט
ptb_app = Application.builder().token(BOT_TOKEN).build()

# =========================
# Utilities
# =========================

async def ensure_user(update: Update) -> bool:
    """מוודא שהמשתמש רשום במערכת"""
    user = update.effective_user
    if not user:
        return False
    
    return store_user(
        user_id=user.id,
        username=user.username,
        first_name=user.first_name
    )

# =========================
# Handlers בסיסיים
# =========================

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """פקודת /start עם הפניות"""
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

    keyboard = [
        [InlineKeyboardButton("🎯 משימות", callback_data="tasks")],
        [InlineKeyboardButton("💰 ארנק", callback_data="wallet")],
        [InlineKeyboardButton("📊 סטטיסטיקות", callback_data="stats")],
        [InlineKeyboardButton("👥 הזמן חברים", callback_data="referrals")]
    ]
    
    if user.id in ADMIN_IDS:
        keyboard.append([InlineKeyboardButton("👑 ניהול", callback_data="admin")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"👋 שלום {user.first_name}!\n\n"
        f"ברוך הבא לבוט התגמולים שלנו! 🎉\n\n"
        f"כאן תוכל:\n"
        f"• 🎯 לבצע משימות ולקבל תגמולים\n"
        f"• 💰 לצבור טוקנים ומטבעות\n"
        f"• 👥 להזמין חברים ולקבל בונוסים\n\n"
        f"לחץ על '🎯 משימות' כדי להתחיל!",
        reply_markup=reply_markup
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """פקודת /help"""
    await update.message.reply_text(
        "📖 *מדריך שימוש*\n\n"
        "🎯 */tasks* - הצג את כל המשימות הזמינות\n"
        "💰 */wallet* - צפה בארנק ובטוקנים שלך\n"
        "📊 */stats* - סטטיסטיקות אישיות\n"
        "👥 */referrals* - הזמן חברים וקבל בונוסים\n"
        "🆘 */help* - הצג הודעה זו\n\n"
        "לשאלות נוספות פנה למנהלים.",
        parse_mode="Markdown"
    )

# =========================
# Handlers למערכת משימות
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
        
        # הודעה למשתמש
        try:
            task_info = next((t for t in get_user_tasks(user_id) if t['task_number'] == task_number), None)
            if task_info:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=f"🎉 *משימה {task_number} אושרה!*\n\n"
                         f"קיבלת {task_info['reward_points']} נקודות ו-{task_info['reward_tokens']} טוקנים!\n"
                         f"📈 continue לצבור עוד טוקנים!",
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
    
    # וולידציה בסיסית של כתובת
    if not wallet_address.startswith('0x') or len(wallet_address) != 42:
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
    
    # חישוב התקדמות
    if stats['completed_tasks'] > 0:
        avg_points_per_task = stats['total_points'] / stats['completed_tasks']
        text += f"📈 ממוצע נקודות למשימה: {avg_points_per_task:.1f}\n"
    
    if stats['referral_count'] > 0:
        referral_bonus = stats['referral_count'] * 5
        text += f"🎁 בונוס הפניות: +{referral_bonus} נקודות\n"
    
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
# Handlers הפניות
# =========================

async def referrals_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """פקודת /referrals - מערכת הפניות"""
    user = update.effective_user
    if not user:
        return

    stats = get_user_stats(user.id)
    bot_username = (await context.bot.get_me()).username
    
    text = (
        f"👥 *הזמן חברים וקבל בונוסים!*\n\n"
        f"📧 *קישור ההזמנה שלך:*\n"
        f"`https://t.me/{bot_username}?start=ref_{user.id}`\n\n"
        f"🎁 *תגמולים:*\n"
        f"• 5 נקודות + 5 טוקנים עבור כל חבר שהצטרף\n"
        f"• 2 נקודות נוספות עבור כל משימה שהחבר ישלים\n\n"
        f"📊 *סטטיסטיקות הפניות:*\n"
        f"👥 חברים שהוזמנו: {stats['referral_count']}\n"
        f"💎 נקודות מהפניות: {stats['referral_count'] * 5}\n"
    )
    
    # טופ 10 מזמינים
    top_referrers = get_top_referrers(10)
    if top_referrers:
        text += f"\n🏆 *טופ 10 מזמינים:*\n"
        for i, referrer in enumerate(top_referrers[:5], 1):
            name = referrer['first_name'] or referrer['username'] or f"User {referrer['id']}"
            text += f"{i}. {name}: {referrer['referral_count']} הפניות\n"
    
    keyboard = [
        [InlineKeyboardButton("📋 הדגם איך להזמין", callback_data="referral_guide")],
        [InlineKeyboardButton("🏠 חזרה", callback_data="back_main")]
    ]
    
    await update.message.reply_text(
        text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# =========================
# Handlers מנהל
# =========================

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """פקודת /admin - פאנל ניהול"""
    user = update.effective_user
    if user.id not in ADMIN_IDS:
        await update.message.reply_text("❌ אין הרשאה")
        return
    
    pending_approvals = get_pending_approvals()
    top_referrers = get_top_referrers(5)
    
    text = (
        f"👑 *פאנל ניהול*\n\n"
        f"📊 *סטטיסטיקות:*\n"
        f"⏳ משימות ממתינות: {len(pending_approvals)}\n"
        f"🏆 טופ מזמין: {top_referrers[0]['first_name'] if top_referrers else 'אין'}\n\n"
    )
    
    if token_distributor.is_connected():
        balance = token_distributor.get_token_balance()
        text += f"💰 יתרת טוקנים: {balance}\n"
    else:
        text += f"⚠️ TokenDistributor לא פעיל\n"
    
    text += f"\n*פקודות ניהול:*\n"
    text += f"• /approve_task <user_id> <task> - אישור משימה\n"
    text += f"• /pending_tasks - הצג משימות ממתינות\n"
    text += f"• /top_referrers - טופ מזמינים\n"
    
    keyboard = [
        [InlineKeyboardButton("⏳ משימות ממתינות", callback_data="admin_pending")],
        [InlineKeyboardButton("🏆 טופ מזמינים", callback_data="admin_top_ref")],
        [InlineKeyboardButton("💰 סטטוס טוקנים", callback_data="admin_token_status")],
        [InlineKeyboardButton("🏠 חזרה", callback_data="back_main")]
    ]
    
    await update.message.reply_text(
        text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def pending_tasks_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """פקודת /pending_tasks - הצג משימות ממתינות"""
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("❌ אין הרשאה")
        return
    
    pending_approvals = get_pending_approvals()
    
    if not pending_approvals:
        await update.message.reply_text("✅ אין משימות ממתינות לאישור")
        return
    
    text = "⏳ *משימות ממתינות לאישור:*\n\n"
    
    for i, approval in enumerate(pending_approvals, 1):
        text += (
            f"{i}. 👤 {approval['first_name']} (@{approval['username']})\n"
            f"   🆔 {approval['user_id']} | 🎯 משימה {approval['task_number']}\n"
            f"   📝 {approval['title']}\n"
            f"   📎 הוכחה: {approval['submitted_proof'][:100]}...\n"
            f"   ⏰ הוגש: {approval['submitted_at'].strftime('%d/%m %H:%M')}\n"
            f"   ✅ אישור: `/approve_task {approval['user_id']} {approval['task_number']}`\n\n"
        )
    
    await update.message.reply_text(text, parse_mode="Markdown")

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
    elif data == "referrals":
        await referrals_callback(update, context)
    elif data == "admin":
        await admin_callback(update, context)
    elif data == "back_main":
        await start_callback(update, context)
    elif data.startswith("start_task:"):
        await start_task_callback(update, context)
    elif data.startswith("submit_task:"):
        await submit_task_callback(update, context)

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

async def stats_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """כפתור סטטיסטיקות"""
    query = update.callback_query
    user = query.from_user
    
    stats = get_user_stats(user.id)
    
    text = (
        f"📊 *סטטיסטיקות אישיות*\n\n"
        f"🏆 {stats['rank']}\n\n"
        f"🎯 {stats['completed_tasks']}/{stats['total_tasks']} משימות\n"
        f"📊 {stats['total_points']} נקודות\n"
        f"🪙 {stats['total_tokens']} טוקנים\n"
        f"👥 {stats['referral_count']} הפניות\n\n"
        f"המשך בקצב הזה! 💪"
    )
    
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
        [InlineKeyboardButton("🎯 משימות", callback_data="tasks")],
        [InlineKeyboardButton("💰 ארנק", callback_data="wallet")],
        [InlineKeyboardButton("📊 סטטיסטיקות", callback_data="stats")],
        [InlineKeyboardButton("👥 הזמן חברים", callback_data="referrals")]
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
    
    # handlers מנהל
    ptb_app.add_handler(CommandHandler("admin", admin_command))
    ptb_app.add_handler(CommandHandler("pending_tasks", pending_tasks_command))
    ptb_app.add_handler(CommandHandler("approve_task", approve_task_command))
    
    # handlers למערכת משימות
    ptb_app.add_handler(CallbackQueryHandler(start_task_callback, pattern="^start_task:"))
    ptb_app.add_handler(CallbackQueryHandler(submit_task_callback, pattern="^submit_task:"))
    ptb_app.add_handler(MessageHandler(filters.TEXT & filters.ChatType.PRIVATE, handle_task_proof))
    
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
        "version": "2.0"
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
        "admin_ids": ADMIN_IDS
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
