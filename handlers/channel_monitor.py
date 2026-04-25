import logging
from telegram import Update
from telegram.ext import ContextTypes
import database as db

try:
    import pyrogram
    pyrogram_available = True
except ImportError:
    pyrogram_available = False

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
                    sent = False
                    sender_id = channel.sticker_sender_id

                    # إرسال عبر Pyrogram كمستخدم لو sender_id محدد
                    if sender_id and pyrogram_available:
                        try:
                            from main import app_client
                            if app_client:
                                async with app_client:
                                    await app_client.send_sticker(
                                        chat_id=chat_id,
                                        sticker=channel.sticker_file_id
                                    )
                                sent = True
                                logger.info(f"Sticker sent via Pyrogram to {channel.title}")
                        except Exception as e:
                            logger.warning(f"Pyrogram sticker failed, falling back to bot: {e}")

                    # fallback: إرسال عبر البوت
                    if not sent:
                        await context.bot.send_sticker(
                            chat_id=chat_id,
                            sticker=channel.sticker_file_id
                        )
                        logger.info(f"Sticker sent to {channel.title}")

                    channel.msg_counter = 0
                except Exception as e:
                    logger.error(f"Failed to send sticker in {channel.title}: {e}")

        except Exception as e:
            logger.error(f"Error in channel monitor: {e}")
