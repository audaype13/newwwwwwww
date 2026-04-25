import asyncio
import logging
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes
import database as db
import config
from utils import send_notification_to_admins, notify_dev

logger = logging.getLogger(__name__)

async def chat_member_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    result = update.chat_member
    if not result:
        return

    old_status = result.old_chat_member.status
    new_status = result.new_chat_member.status

    # البوت أُزيل فعلاً - فقط عند الحذف أو المغادرة
    bot_removed = (
        old_status in ['administrator', 'member', 'restricted'] and
        new_status in ['left', 'kicked'] and
        result.new_chat_member.user.id == context.bot.id
    )

    if not bot_removed:
        return

    chat_id = update.effective_chat.id
    chat_title = update.effective_chat.title
    chat_username = update.effective_chat.username

    success = db.remove_channel_db(chat_id)

    msg = (
        f"⚠️ <b>البوت أُزيل من قناة</b>\n"
        f"┌ 📌 الاسم: <b>{chat_title}</b>\n"
        f"└ 🗄️ قاعدة البيانات: {'✅ حُذفت' if success else '❌ لم تُحذف'}"
    )
    keyboard = None
    if chat_username:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📢 فتح القناة", url=f"https://t.me/{chat_username}")]
        ])

    try:
        await context.bot.send_message(
            chat_id=config.DEVELOPER_ID, text=msg,
            parse_mode='HTML', reply_markup=keyboard
        )
    except Exception as e:
        logger.warning(f"Failed to notify dev: {e}")

    if success:
        logger.info(f"Channel {chat_title} ({chat_id}) removed from database")
    else:
        logger.warning(f"Failed to remove channel {chat_id} from database")
