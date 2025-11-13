# main.py - מעודכן עם מערכת מטלות ותגמולים
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
# Handlers בסיסיים
# =========================

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """פקודת /start"""
    user = update.effective_user
    keyboard = [
        [InlineKeyboardButton("🎯 משימות", callback_data="tasks")],
        [InlineKeyboardButton("💰 ארנק", callback_data="wallet")],
        [InlineKeyboardButton("📊 סטטיסטיקות", callback_data="stats")],
        [InlineKeyboardButton("👥 הזמן חברים", callback_data="referrals")]
    ]
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
        "👥 */referrals* - הזמן חברים וקבל בונוסים\n\n"
        "לשאלות נוספות פנה למנהלים.",
        parse_mode="Markdown"
    )

# =========================
# Handlers למערכת מטלות
# =========================

async def tasks_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """פקודת /tasks - מציגה את כל המשימות"""
    user = update.effective_user
    if not user:
        return

    # TODO: החלף עם פונקציות DB אמיתיות
    progress = {
        'completed_tasks': 0,
        'total_tasks': 20,
        'total_points': 0
    }
    
    text = (
        f"🎯 *לוח משימות - התקדמות אישית*\n\n"
        f"✅ הושלמו: {progress['completed_tasks']}/{progress['total_tasks']}\n"
        f"📊 נקודות: {progress['total_points']}\n"
        f"💰 טוקנים צפויים: {progress['completed_tasks'] * 10}\n\n"
        f"*רשימת המשימות:*\n\n"
        f"🟢 *משימה 1:* הצטרפות לערוץ הטלגרם\n"
        f"   נקודות: 5 | ⚪ לא התחלת\n\n"
        f"🟢 *משימה 2:* שיתוף הפוסט הראשון\n"
        f"   נקודות: 10 | ⚪ לא התחלת\n\n"
        f"🟢 *משימה 3:* הזמנת חבר ראשון\n"
        f"   נקודות: 15 | ⚪ לא התחלת\n"
    )
    
    keyboard = [
        [InlineKeyboardButton("🚀 התחל משימה 1", callback_data="start_task:1")],
        [InlineKeyboardButton("🚀 התחל משימה 2", callback_data="start_task:2")],
        [InlineKeyboardButton("🚀 התחל משימה 3", callback_data="start_task:3")],
        [InlineKeyboardButton("🏠 חזרה לתפריט ראשי", callback_data="back_main")]
    ]
    
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
    
    # TODO: החלף עם פונקציית DB אמיתית
    # if start_task(user.id, task_number):
    
    await query.edit_message_text(
        f"🎉 *התחלת משימה {task_number}!* \n\n"
        f"כדי להשלים את המשימה, לחץ על 'הגש משימה' כשסיימת.\n"
        f"לאחר האישור תקבל {task_number * 5} נקודות וטוקנים!",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton(f"📤 הגש משימה {task_number}", callback_data=f"submit_task:{task_number}"),
            InlineKeyboardButton("🏠 חזרה לתפריט ראשי", callback_data="back_main")
        ]])
    )

async def submit_task_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """מבקש מהמשתמש להגיש הוכחה"""
    query = update.callback_query
    await query.answer()
    
    task_number = int(query.data.split(":")[1])
    context.user_data['pending_task_submission'] = task_number
    
    await query.edit_message_text(
        f"📤 *הגשת משימה {task_number}*\n\n"
        f"שלח הודעה עם ההוכחה שהשלמת את המשימה.\n"
        f"זה יכול להיות:\n"
        f"• לינק לפוסט\n• צילום מסך\n• טקסט הסבר\n\n"
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
    
    # TODO: החלף עם פונקציית DB אמיתית
    # if submit_task(user.id, task_number, proof_text):
    
    await message.reply_text(
        f"✅ *המשימה {task_number} הוגשה!*\n\n"
        f"ההוכחה נשלחה למנהלים לאישור.\n"
        f"תקבל הודעה כשהמשימה תאושר ותקבל את הנקודות והטוקנים.",
        parse_mode="Markdown"
    )
    
    del context.user_data['pending_task_submission']

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
    
    # TODO: החלף עם פונקציית DB אמיתית
    # if approve_task(user_id, task_number):
    
    await update.message.reply_text(
        f"✅ משימה {task_number} אושרה למשתמש {user_id}!\n"
        f"נשלחו {task_number * 10} טוקנים\n"
        f"TX: simulated_transaction_hash"
    )

# =========================
# Handlers נוספים
# =========================

async def wallet_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """פקודת /wallet - מציג את מצב הארנק"""
    user = update.effective_user
    
    # TODO: החלף עם נתונים אמיתיים מה-DB
    wallet_data = {
        'tokens': 0,
        'points': 0,
        'pending_tokens': 50
    }
    
    await update.message.reply_text(
        f"💰 *ארנק אישי*\n\n"
        f"👤 בעלים: {user.first_name}\n"
        f"🆔 ID: {user.id}\n\n"
        f"*מאזן:*\n"
        f"🪙 טוקנים: {wallet_data['tokens']}\n"
        f"📊 נקודות: {wallet_data['points']}\n"
        f"⏳ טוקנים ממתינים: {wallet_data['pending_tokens']}\n\n"
        f"לצבור עוד טוקנים, בצע משימות!",
        parse_mode="Markdown"
    )

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """פקודת /stats - סטטיסטיקות אישיות"""
    user = update.effective_user
    
    # TODO: החלף עם נתונים אמיתיים מה-DB
    stats_data = {
        'completed_tasks': 0,
        'total_tasks': 20,
        'referrals': 0,
        'rank': "מתחיל"
    }
    
    await update.message.reply_text(
        f"📊 *סטטיסטיקות אישיות*\n\n"
        f"👤 {user.first_name}\n\n"
        f"🎯 משימות שהושלמו: {stats_data['completed_tasks']}/{stats_data['total_tasks']}\n"
        f"👥 חברים שהוזמנו: {stats_data['referrals']}\n"
        f"🏆 דרגה: {stats_data['rank']}\n\n"
        f"המשך בקצב הזה! 💪",
        parse_mode="Markdown"
    )

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
    elif data == "back_main":
        await start_callback(update, context)

async def tasks_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """כפתור משימות"""
    query = update.callback_query
    user = query.from_user
    
    progress = {
        'completed_tasks': 0,
        'total_tasks': 20,
        'total_points': 0
    }
    
    text = (
        f"🎯 *לוח משימות - התקדמות אישית*\n\n"
        f"✅ הושלמו: {progress['completed_tasks']}/{progress['total_tasks']}\n"
        f"📊 נקודות: {progress['total_points']}\n\n"
        f"*בחר משימה:*"
    )
    
    keyboard = [
        [InlineKeyboardButton("🚀 משימה 1 - הצטרפות", callback_data="start_task:1")],
        [InlineKeyboardButton("🚀 משימה 2 - שיתוף", callback_data="start_task:2")],
        [InlineKeyboardButton("🚀 משימה 3 - הזמנה", callback_data="start_task:3")],
        [InlineKeyboardButton("🏠 חזרה", callback_data="back_main")]
    ]
    
    await query.edit_message_text(
        text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def wallet_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """כפתור ארנק"""
    query = update.callback_query
    user = query.from_user
    
    wallet_data = {
        'tokens': 0,
        'points': 0,
        'pending_tokens': 50
    }
    
    text = (
        f"💰 *ארנק אישי*\n\n"
        f"🪙 טוקנים: {wallet_data['tokens']}\n"
        f"📊 נקודות: {wallet_data['points']}\n"
        f"⏳ טוקנים ממתינים: {wallet_data['pending_tokens']}\n\n"
        f"לצבור עוד טוקנים, בצע משימות!"
    )
    
    keyboard = [
        [InlineKeyboardButton("🎯 למשימות", callback_data="tasks")],
        [InlineKeyboardButton("🏠 חזרה", callback_data="back_main")]
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
    
    stats_data = {
        'completed_tasks': 0,
        'total_tasks': 20,
        'referrals': 0,
        'rank': "מתחיל"
    }
    
    text = (
        f"📊 *סטטיסטיקות אישיות*\n\n"
        f"🎯 משימות שהושלמו: {stats_data['completed_tasks']}/{stats_data['total_tasks']}\n"
        f"👥 חברים שהוזמנו: {stats_data['referrals']}\n"
        f"🏆 דרגה: {stats_data['rank']}\n\n"
        f"המשך בקצב הזה! 💪"
    )
    
    keyboard = [
        [InlineKeyboardButton("🎯 למשימות", callback_data="tasks")],
        [InlineKeyboardButton("🏠 חזרה", callback_data="back_main")]
    ]
    
    await query.edit_message_text(
        text,
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def referrals_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """כפתור הזמנות"""
    query = update.callback_query
    
    text = (
        f"👥 *הזמן חברים וקבל בונוסים!*\n\n"
        f"📧 שלח את הקישור הזה לחברים:\n"
        f"`https://t.me/{(await query.bot.get_me()).username}?start=ref_{query.from_user.id}`\n\n"
        f"🎁 תקבל 10 טוקנים עבור כל חבר שהצטרף!\n"
        f"📈 ועוד 5 טוקנים עבור כל משימה שהחבר ישלים!"
    )
    
    keyboard = [
        [InlineKeyboardButton("🏠 חזרה", callback_data="back_main")]
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
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        f"👋 שלום {user.first_name}!\n\n"
        f"ברוך הבא לבוט התגמולים שלנו! 🎉\n\n"
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
    
    # handlers למערכת משימות
    ptb_app.add_handler(CallbackQueryHandler(start_task_callback, pattern="^start_task:"))
    ptb_app.add_handler(CallbackQueryHandler(submit_task_callback, pattern="^submit_task:"))
    ptb_app.add_handler(MessageHandler(filters.TEXT & filters.ChatType.PRIVATE, handle_task_proof))
    ptb_app.add_handler(CommandHandler("approve_task", approve_task_command))
    
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
    await ptb_app.initialize()
    await ptb_app.bot.set_webhook(url=f"{WEBHOOK_URL}/webhook")
    register_handlers()
    logger.info("Bot started successfully!")

@app.on_event("shutdown")
async def shutdown_event():
    """ניקוי משאבים בעת כיבוי"""
    await ptb_app.shutdown()

@app.post("/webhook")
async def webhook(request: Request):
    """Endpoint ל-webhook של Telegram"""
    try:
        data = await request.json()
        update = Update.de_json(data, ptb_app.bot)
        await ptb_app.process_update(update)
        return JSONResponse(content={"status": "ok"})
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return JSONResponse(content={"status": "error"}, status_code=500)

@app.get("/")
async def root():
    """Health check endpoint"""
    return {"status": "online", "service": "webwook-bot"}

@app.get("/health")
async def health():
    """Health check endpoint"""
    return {"status": "healthy"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
