import logging
from telegram import Update
from telegram.ext import ContextTypes
import database as db

logger = logging.getLogger(__name__)

async def channel_monitor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """مراقبة رسائل القناة لعداد الملصق التفاعلي - يحسب الرسائل الخارجية فقط"""
    if not update.channel_post:
        return

    msg = update.channel_post
    chat_id = update.effective_chat.id

    # تجاهل الرسائل المرسلة من البوت نفسه لتجنب race condition مع post_job
    if msg.via_bot and msg.via_bot.id == context.bot.id:
        return
    if msg.sender_chat and msg.sender_chat.id == chat_id:
        # رسالة من القناة نفسها (أي من البوت عبر post_job) - تجاهل
        return

    if not (msg.text or msg.photo):
        return

    with db.get_db_session() as session:
        try:
            channel = session.query(db.Channel).filter_by(channel_id=chat_id).first()

            if not (channel and channel.sticker_file_id and channel.sticker_interval):
                return

            channel.msg_counter += 1

            if channel.msg_counter >= channel.sticker_interval:
                try:
                    await context.bot.send_sticker(
                        chat_id=chat_id,
                        sticker=channel.sticker_file_id
                    )
                    channel.msg_counter = 0
                    logger.info(f"Sticker sent to {channel.title}")
                except Exception as e:
                    logger.error(f"Failed to send sticker in {channel.title}: {e}")

        except Exception as e:
            logger.error(f"Error in channel monitor: {e}")
