import logging
import asyncio
import random
from datetime import datetime
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
import database as db
import config
from keyboards import get_back_keyboard

logger = logging.getLogger(__name__)

async def is_bot_admin_in_channel(bot, user_id, channel_id):
    try:
        chat_member = await bot.get_chat_member(channel_id, bot.id)
        return chat_member.status in ['administrator', 'creator']
    except Exception as e:
        logger.error(f"Error checking admin status: {e}")
        return False

async def send_notification_to_admins(context: ContextTypes.DEFAULT_TYPE, message: str):
    """إرسال إشعار للمشرفين والمطور"""
    with db.get_db_session() as session:
        admin_ids = [a.user_id for a in session.query(db.User).filter_by(is_admin=True).all()]
    for admin_id in admin_ids:
        try:
            await context.bot.send_message(chat_id=admin_id, text=message, parse_mode='HTML')
        except Exception as e:
            logger.warning(f"Failed to notify admin {admin_id}: {e}")
    try:
        await context.bot.send_message(chat_id=config.DEVELOPER_ID, text=message, parse_mode='HTML')
    except Exception as e:
        logger.warning(f"Failed to notify dev: {e}")

async def notify_dev(context: ContextTypes.DEFAULT_TYPE, message: str, keyboard=None):
    """إشعار المطور فقط"""
    try:
        await context.bot.send_message(
            chat_id=config.DEVELOPER_ID, text=message,
            parse_mode='HTML', reply_markup=keyboard
        )
    except Exception as e:
        logger.warning(f"Failed to notify dev: {e}")

async def _send_channel_notification(context, msg, keyboard=None):
    """إرسال إشعار القناة للمطور مع زر اختياري"""
    try:
        await context.bot.send_message(
            chat_id=config.DEVELOPER_ID, text=msg,
            parse_mode='HTML', reply_markup=keyboard
        )
    except Exception as e:
        logger.warning(f"Failed to send channel notification: {e}")

async def post_job(context: ContextTypes.DEFAULT_TYPE, force_one=False):
    """مهمة النشر التلقائي مع إدارة صحيحة للجلسات"""
    
    # ✅ استخدام Context Manager للجلسة الرئيسية
    with db.get_db_session() as session:
        setting = session.query(db.BotSettings).filter_by(key='posting_status').first()
        
        print(f"--- Job Check --- Status: {setting.value if setting else 'None'}, Force: {force_one}")

        if not force_one and (not setting or setting.value == 'off'):
            return

        # ✅ جلب البيانات كـ list of dicts بدلاً من ORM objects
        channels_data = []
        channels = session.query(db.Channel).filter_by(is_active=True).all()
        
        for ch in channels:
            channels_data.append({
                'id': ch.id,
                'channel_id': ch.channel_id,
                'title': ch.title,
                'category': ch.category,
                'msg_format': ch.msg_format,
                'time_type': ch.time_type,
                'time_value': ch.time_value,
                'last_post_at': ch.last_post_at,
                'sticker_file_id': ch.sticker_file_id,
                'sticker_interval': ch.sticker_interval,
                'msg_counter': ch.msg_counter
            })
        
        print(f"Found {len(channels_data)} active channels.")

    if not channels_data:
        return

    now = datetime.now()
    
    for channel_data in channels_data:
        try:
            should_post = False
            reason = ""
            
            if force_one:
                should_post = True
                reason = "Force Post"
            elif channel_data['time_type'] == 'default':
                if random.random() < 0.05:
                    should_post = True
                    reason = "Random Post (5%)"
            
            elif channel_data['time_type'] == 'fixed':
                if channel_data['time_value']:
                    allowed_hours = [int(h.strip()) for h in channel_data['time_value'].split(',')]
                    current_hour = now.hour
                    if current_hour in allowed_hours:
                        if channel_data['last_post_at']:
                            last_hour = channel_data['last_post_at'].hour
                            if last_hour != current_hour:
                                should_post = True
                                reason = f"Fixed Time {current_hour}"
                        else:
                            should_post = True

            elif channel_data['time_type'] == 'interval':
                if channel_data['time_value'] and channel_data['last_post_at']:
                    interval_minutes = int(channel_data['time_value'])
                    diff = now - channel_data['last_post_at']
                    if diff.total_seconds() >= (interval_minutes * 60):
                        should_post = True
                        reason = "Interval Passed"
                elif not channel_data['last_post_at']:
                    should_post = True

            if should_post:
                # ✅ جلب المحتوى في جلسة منفصلة
                text = db.get_next_content(channel_data['category'])
                if not text:
                    continue

                parse_mode = 'HTML' if channel_data['msg_format'] == 'blockquote' else None
                if channel_data['msg_format'] == 'blockquote':
                    text = f"<blockquote>{text}</blockquote>"

                # إرسال الاقتباس
                sent_message = await context.bot.send_message(
                    chat_id=channel_data['channel_id'],
                    text=text,
                    parse_mode=parse_mode
                )
                
                # ✅ منطق الملصق التفاعلي مع Context Manager
                if channel_data['sticker_interval'] and channel_data['sticker_file_id']:
                    with db.get_db_session() as sticker_session:
                        db_channel = sticker_session.query(db.Channel).filter_by(id=channel_data['id']).first()
                        
                        if db_channel:
                            db_channel.msg_counter += 1
                            
                            if db_channel.msg_counter >= channel_data['sticker_interval']:
                                try:
                                    # إرسال الملصق بشكل مستقل
                                    await context.bot.send_sticker(
                                        chat_id=channel_data['channel_id'],
                                        sticker=channel_data['sticker_file_id']
                                    )
                                    
                                    db_channel.msg_counter = 0
                                    logger.info(f"Sticker sent via post_job to {db_channel.title}")
                                except Exception as e:
                                    logger.error(f"Error sending sticker: {e}")
                
                # ✅ تحديث وقت النشر الأخير
                with db.get_db_session() as update_session:
                    db_channel = update_session.query(db.Channel).filter_by(id=channel_data['id']).first()
                    if db_channel:
                        db_channel.last_post_at = now
                
                if force_one:
                    return
                await asyncio.sleep(1) 

        except Exception as e:
            logger.error(f"ERROR in {channel_data.get('title', 'Unknown')}: {e}")
            print(f"ERROR in {channel_data.get('title', 'Unknown')}: {e}")
            asyncio.create_task(notify_dev(
                context,
                f"⚠️ <b>خطأ في النشر التلقائي</b>\n📢 القناة: <b>{channel_data.get('title', 'Unknown')}</b>\n❌ الخطأ: <code>{e}</code>"
            ))

async def finalize_channel_addition(update, context, query, role):
    """إنهاء إضافة القناة"""
    pending = context.user_data.get('pending_channel')
    if not pending: 
        return
    
    cat = context.user_data.get('selected_category')
    fmt = context.user_data.get('selected_format', 'normal')
    time_conf = context.user_data.get('time_settings', {'type': 'default'})
    time_type = time_conf.get('type', 'default')
    time_value = time_conf.get('value')

    # ✅ استخدام الدالة المعدلة في database.py
    success = db.add_channel(
        ch_id=pending['id'], 
        title=pending['title'], 
        added_by=update.effective_user.id, 
        cat=cat, 
        fmt=fmt, 
        t_type=time_type, 
        t_val=time_value
    )
    
    if not success:
        error_msg = "❌ حدث خطأ أثناء إضافة القناة. قد تكون القناة مضافة مسبقاً."
        if query:
            await query.edit_message_text(error_msg, parse_mode='HTML')
        else:
            await update.message.reply_text(error_msg, parse_mode='HTML')
        return
    
    # مسح البيانات المؤقتة
    context.user_data['pending_channel'] = None
    context.user_data['selected_category'] = None
    context.user_data['time_settings'] = None
    
    time_text = ""
    if time_type == 'fixed':
        time_text = f"⏰ الساعات: {time_value}"
    elif time_type == 'interval':
        time_text = f"⏳ كل: {time_value} دقيقة"
    else:
        time_text = "🚀 فوري/عشوائي"
        
    msg = (
        f"✅ <b>تمت إضافة القناة بنجاح</b>\n"
        f"┌ 📌 الاسم: <b>{pending['title']}</b>\n"
        f"├ 📂 الفئة: <b>{cat}</b>\n"
        f"├ 🎨 الشكل: <b>{'اقتباس' if fmt == 'blockquote' else 'عادي'}</b>\n"
        f"└ ⏱️ التوقيت: <b>{time_text}</b>"
    )

    # إشعار المطور مع زر للقناة
    user = update.effective_user
    user_tag = f"@{user.username}" if user.username else f"ID: {user.id}"
    
    # جلب إحصائيات القناة
    with db.get_db_session() as session:
        total_channels = session.query(db.Channel).count()
    
    notif_msg = (
        f"📢 <b>قناة جديدة أُضيفت</b>\n"
        f"┌ 📌 الاسم: <b>{pending['title']}</b>\n"
        f"├ 🆔 الآيدي: <code>{pending['id']}</code>\n"
        f"├ 👤 أضافها: {user_tag}\n"
        f"├ 📂 الفئة: <b>{cat}</b>\n"
        f"├ 🎨 الشكل: <b>{'اقتباس' if fmt == 'blockquote' else 'عادي'}</b>\n"
        f"├ ⏱️ التوقيت: <b>{time_text}</b>\n"
        f"└ 📊 إجمالي القنوات: <b>{total_channels}</b>"
    )
    
    # زر فتح القناة - يعمل فقط إذا كان username موجود
    channel_username = pending.get('username')
    notif_keyboard = None
    if channel_username:
        notif_keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📢 فتح القناة", url=f"https://t.me/{channel_username.lstrip('@')}")]
        ])
    
    asyncio.create_task(_send_channel_notification(context, notif_msg, notif_keyboard))

    if query:
        await query.edit_message_text(msg, parse_mode='HTML', reply_markup=get_back_keyboard(role))
    else:
        await update.message.reply_text(msg, parse_mode='HTML', reply_markup=get_back_keyboard(role))
