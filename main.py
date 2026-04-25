import logging
import asyncio
from sqlalchemy import text
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ChatMemberHandler
)
try:
    import pyrogram
    pyrogram_available = True
except ImportError:
    pyrogram_available = False

import config
import database as db
import utils
from handlers import start, buttons, messages, events, channel_monitor

# إعداد التسجيل
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

async def error_handler(update, context):
    logger.error(f"Exception: {context.error}", exc_info=context.error)
    try:
        await context.bot.send_message(
            chat_id=config.DEVELOPER_ID,
            text=f"⚠️ <b>خطأ غير متوقع</b>\n<code>{str(context.error)[:300]}</code>",
            parse_mode='HTML'
        )
    except Exception:
        pass

# إعداد Pyrogram Client (اختياري)
try:
    app_client = pyrogram.Client(
        "bot_account",
        api_id=config.API_ID,
        api_hash=config.API_HASH,
        bot_token=config.TOKEN
    )
    pyrogram_available = True
except AttributeError:
    app_client = None
    pyrogram_available = False
    print("تنبية api id و api hash غير موجودين ")

def main():
    # ✅ تعديل 1: إضافة try-except لإنشاء الجداول مع معالجة أخطاء MySQL
    try:
        db.Base.metadata.create_all(db.engine)
        logger.info("Database tables created/verified successfully")
    except Exception as e:
        logger.error(f"Failed to create database tables: {e}")
        raise
    
    # ✅ تعديل 2: اختبار الاتصال بقاعدة البيانات قبل تشغيل البوت
    try:
        with db.get_db_session() as session:
            session.execute(text("SELECT 1"))
        logger.info("Database connection test successful")
    except Exception as e:
        logger.error(f"Database connection failed: {e}")
        raise

    # ✅ استخدم Application (يعمل مع الإصدار 21.x)
    application = Application.builder().token(config.TOKEN).build()

    # --- تسجيل المعالجات ---

    # 1. معالج الأوامر (مثل /start)
    application.add_handler(CommandHandler("start", start.start))

    # 2. معالج الأزرار (CallbackQuery)
    application.add_handler(CallbackQueryHandler(buttons.button_handler))
    
    # 3. معالج الرسائل في الخاص
    application.add_handler(MessageHandler(
        filters.ChatType.PRIVATE & (filters.TEXT | filters.Document.ALL | filters.Sticker.ALL), 
        messages.message_handler
    ))

    # 4. معالج كلمة "تفعيل" في المجموعات
    application.add_handler(MessageHandler(
        filters.Regex("^تفعيل$") & filters.ChatType.GROUPS, 
        messages.message_handler
    ))
    
    # 5. معالج مراقبة القنوات للملصق التفاعلي
    application.add_handler(MessageHandler(
        filters.ChatType.CHANNEL & (filters.TEXT | filters.PHOTO), 
        channel_monitor.channel_monitor
    ))

    # 6. أحداث العضوية (المغادرة)
    application.add_handler(
        ChatMemberHandler(events.chat_member_handler, ChatMemberHandler.CHAT_MEMBER)
    )

    # 7. معالج الأخطاء العام
    application.add_error_handler(error_handler)

    # ✅ تعديل 3: إضافة معالج لإغلاق الجلسات عند إيقاف البوت
    async def shutdown(application):
        logger.info("Shutting down... Closing database connections")
        db.Session.remove()
    
    application.post_shutdown = shutdown

    # تشغيل النشر التلقائي
    job_queue = application.job_queue
    job_queue.run_repeating(utils.post_job, interval=60, first=10)

    print("Bot is running...")
    application.run_polling(allowed_updates=["message", "callback_query", "chat_member", "my_chat_member", "channel_post"])

if __name__ == '__main__':
    main()
