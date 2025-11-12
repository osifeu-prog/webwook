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

from db import (
    init_schema, log_payment, update_payment_status, store_user, add_referral,
    get_top_referrers, get_monthly_payments, get_approval_stats, create_reward,
    get_user_tasks, start_task, submit_task, approve_task, get_user_progress
)
from token_distributor import token_distributor

# [כל ההגדרות ההתחלתיות נשארות כפי שהיו...]
# BOT_TOKEN, WEBHOOK_URL, ADMIN_IDS, etc.

# =========================
# Handlers חדשים למערכת מטלות
# =========================

async def tasks_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """פקודת /tasks - מציגה את כל המשימות"""
    user = update.effective_user
    if not user:
        return

    tasks = get_user_tasks(user.id)
    progress = get_user_progress(user.id)
    
    text = (
        f"🎯 *לוח משימות - התקדמות אישית*\n\n"
        f"✅ הושלמו: {progress['completed_tasks']}/{progress['total_tasks']}\n"
        f"📊 נקודות: {progress['total_points']}\n"
        f"💰 טוקנים צפויים: {progress['completed_tasks'] * 10}\n\n"
        f"*רשימת המשימות:*\n"
    )
    
    keyboard = []
    for task in tasks:
        status_icon = "🟢" if task['user_status'] == 'approved' else "🟡" if task['user_status'] == 'submitted' else "⚪"
        text += f"{status_icon} *משימה {task['task_number']}:* {task['title']}\n"
        text += f"   נקודות: {task['reward_points']} | "
        
        if not task['user_status']:
            text += "❌ לא התחלת\n"
            keyboard.append([InlineKeyboardButton(
                f"🚀 התחל משימה {task['task_number']}", 
                callback_data=f"start_task:{task['task_number']}"
            )])
        elif task['user_status'] == 'started':
            text += "📝 בתהליך\n"
            keyboard.append([InlineKeyboardButton(
                f"📤 הגש משימה {task['task_number']}", 
                callback_data=f"submit_task:{task['task_number']}"
            )])
        elif task['user_status'] == 'submitted':
            text += "⏳ ממתין לאישור\n"
        elif task['user_status'] == 'approved':
            text += f"✅ אושר ב{task['approved_at'].strftime('%d/%m')}\n"
    
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
        await query.edit_message_text(
            f"🎉 *התחלת משימה {task_number}!* \n\n"
            f"כדי להשלים את המשימה, לחץ על 'הגש משימה' כשסיימת.\n"
            f"לאחר האישור תקבל {task_number * 5} נקודות וטוקנים!",
            parse_mode="Markdown"
        )
    else:
        await query.answer("שגיאה בהתחלת המשימה", show_alert=True)

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
    
    if submit_task(user.id, task_number, proof_text):
        # שולח למנהלים לאישור
        admin_text = (
            f"📝 *הגשה חדשה למשימה {task_number}*\n\n"
            f"משתמש: {user.first_name} (@{user.username})\n"
            f"ID: {user.id}\n"
            f"הוכחה: {proof_text}\n\n"
            f"לאישור:\n"
            f"/approve_task {user.id} {task_number}"
        )
        
        try:
            await context.bot.send_message(
                chat_id=PAYMENTS_LOG_CHAT_ID,
                text=admin_text,
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"Failed to notify admins: {e}")
        
        await message.reply_text(
            f"✅ *המשימה {task_number} הוגשה!*\n\n"
            f"ההוכחה נשלחה למנהלים לאישור.\n"
            f"תקבל הודעה כשהמשימה תאושר ותקבל את הנקודות והטוקנים.",
            parse_mode="Markdown"
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
        # שולח טוקנים אוטומטית
        token_amount = token_distributor.calculate_task_reward(task_number)
        tx_hash = token_distributor.send_tokens(
            get_user_wallet(user_id),  # נניח שיש לנו פונקציה שמחזירה ארנק
            token_amount
        )
        
        await update.message.reply_text(
            f"✅ משימה {task_number} אושרה למשתמש {user_id}!\n"
            f"נשלחו {token_amount} טוקנים\n"
            f"TX: {tx_hash}"
        )
        
        # הודעה למשתמש
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=f"🎉 *משימה {task_number} אושרה!*\n\n"
                     f"קיבלת {task_number * 5} נקודות ו-{token_amount} טוקנים!\n"
                     f"תעודת Txn: `{tx_hash}`",
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"Failed to notify user: {e}")
    else:
        await update.message.reply_text("❌ שגיאה באישור המשימה")

# [הרשמת handlers חדשים - להוסיף ל-main.py הקיים]
ptb_app.add_handler(CommandHandler("tasks", tasks_command))
ptb_app.add_handler(CallbackQueryHandler(start_task_callback, pattern="^start_task:"))
ptb_app.add_handler(CallbackQueryHandler(submit_task_callback, pattern="^submit_task:"))
ptb_app.add_handler(MessageHandler(filters.TEXT & filters.ChatType.PRIVATE, handle_task_proof))
ptb_app.add_handler(CommandHandler("approve_task", approve_task_command))

# [כל שאר הקוד נשאר כפי שהיה...]
