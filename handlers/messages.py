import asyncio
import logging
from telegram import Update
from telegram.ext import ContextTypes, filters
import database as db
import config
from keyboards import get_back_keyboard, get_categories_keyboard
from utils import is_bot_admin_in_channel, finalize_channel_addition, notify_dev

logger = logging.getLogger(__name__)

async def broadcast_task(context, text):
    """مهمة الإذاعة مع معالجة FloodWait"""
    success_users = 0
    success_channels = 0
    failed = 0

    with db.get_db_session() as session:
        users = [u.user_id for u in session.query(db.User).all()]
        channels = [c.channel_id for c in session.query(db.Channel).all()]

    for uid in users:
        try:
            await context.bot.send_message(chat_id=uid, text=text, parse_mode='HTML')
            success_users += 1
        except Exception as e:
            err = str(e)
            if 'Flood' in err or 'flood' in err:
                # استخرج وقت الانتظار من رسالة الخطأ
                import re
                wait = int(re.search(r'(\d+)', err).group(1)) if re.search(r'(\d+)', err) else 30
                logger.warning(f"FloodWait {wait}s during broadcast")
                await asyncio.sleep(wait)
                try:
                    await context.bot.send_message(chat_id=uid, text=text, parse_mode='HTML')
                    success_users += 1
                except Exception:
                    failed += 1
            else:
                failed += 1
        await asyncio.sleep(0.05)

    for cid in channels:
        try:
            await context.bot.send_message(chat_id=cid, text=text, parse_mode='HTML')
            success_channels += 1
        except Exception as e:
            err = str(e)
            if 'Flood' in err or 'flood' in err:
                import re
                wait = int(re.search(r'(\d+)', err).group(1)) if re.search(r'(\d+)', err) else 30
                await asyncio.sleep(wait)
                try:
                    await context.bot.send_message(chat_id=cid, text=text, parse_mode='HTML')
                    success_channels += 1
                except Exception:
                    failed += 1
            else:
                failed += 1
        await asyncio.sleep(0.05)

    logger.info(f"Broadcast done. Users: {success_users}, Channels: {success_channels}, Failed: {failed}")
    try:
        await context.bot.send_message(
            chat_id=config.DEVELOPER_ID,
            text=(
                f"✅ <b>انتهت الإذاعة</b>\n"
                f"┌ 👥 المستخدمون: <b>{success_users}</b>\n"
                f"├ 📢 القنوات: <b>{success_channels}</b>\n"
                f"└ ❌ فشل: <b>{failed}</b>"
            ),
            parse_mode='HTML'
        )
    except Exception:
        pass

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user:
        return

    # --- تعريف المتغيرات الأساسية في البداية ---
    user_id = update.effective_user.id
    text = update.message.text if update.message else None
    document = update.message.document if update.message else None
    
    if user_id == config.DEVELOPER_ID: 
        role = "dev"
    elif db.is_admin(user_id): 
        role = "admin"
    else: 
        role = "user"
    
    forward_from = None
    if update.message:
        # الإصدار الجديد: forward_origin
        if hasattr(update.message, 'forward_origin') and update.message.forward_origin:
            origin = update.message.forward_origin
            if hasattr(origin, 'chat'):
                forward_from = origin.chat
        # الإصدار القديم: forward_from_chat
        elif hasattr(update.message, 'forward_from_chat') and update.message.forward_from_chat:
            forward_from = update.message.forward_from_chat

    # --- منطق إعداد الملصق التفاعلي ---
    if context.user_data.get('action') == 'waiting_sticker':
        if not update.message or not update.message.sticker:
            await update.message.reply_text("❌ يرجى إرسال ملصق صحيح فقط.")
            return
        
        context.user_data['temp_sticker_id'] = update.message.sticker.file_id
        context.user_data['action'] = 'waiting_sticker_interval'
        await update.message.reply_text(
            "✅ تم حفظ الملصق.\n\nالآن أرسل الرقم: (بعد كل كم رسالة يتم النشر؟)\nمثلاً: 10", 
            reply_markup=get_back_keyboard(role)
        )
        return

    if context.user_data.get('action') == 'waiting_sticker_interval':
        if not text:
            await update.message.reply_text("❌ يرجى إرسال نص.", reply_markup=get_back_keyboard(role))
            return
            
        try:
            interval = int(text.strip())
            if interval < 1: 
                raise ValueError
        except ValueError:
            await update.message.reply_text(
                "❌ يرجى إرسال رقم صحيح أكبر من صفر.", 
                reply_markup=get_back_keyboard(role)
            )
            return
        
        context.user_data['temp_sticker_interval'] = interval
        context.user_data['action'] = 'waiting_sticker_sender'
        await update.message.reply_text(
            "✅ تم حفظ العدد.\n\nالآن أرسل آيدي الشخص الذي سيرسل الملصق (لأن ينشر كأنه شخص وليس بوت).\nأو اكتب 0 ليرسله البوت نفسه.", 
            reply_markup=get_back_keyboard(role)
        )
        return

    if context.user_data.get('action') == 'waiting_sticker_sender':
        if not text:
            await update.message.reply_text("❌ يرجى إرسال نص.", reply_markup=get_back_keyboard(role))
            return
            
        sender_id = None
        try:
            val = int(text.strip())
            if val != 0:
                sender_id = val
        except:
            sender_id = None 

        ch_id = context.user_data.get('editing_channel_id')
        if not ch_id:
            context.user_data['action'] = None
            return

        # ✅ استخدام Context Manager
        with db.get_db_session() as session:
            try:
                ch = session.query(db.Channel).filter_by(id=ch_id).first()
                if ch:
                    ch.sticker_file_id = context.user_data.get('temp_sticker_id')
                    ch.sticker_interval = context.user_data.get('temp_sticker_interval')
                    ch.sticker_sender_id = sender_id
                    ch.msg_counter = 0
                    
                    sender_txt = "البوت" if not sender_id else f"الشخص: {sender_id}"
                    msg = f"✅ تم تفعيل الملصق التفاعلي بنجاح!\n\n⭐ الملصق: تم التعيين\n🔢 العدد: كل {ch.sticker_interval} رسالة\n👤 المرسل: {sender_txt}"
                else:
                    msg = "❌ حدث خطأ."
            except Exception as e:
                logger.error(f"Error saving sticker settings: {e}")
                msg = "❌ حدث خطأ أثناء الحفظ."
        
        context.user_data.pop('temp_sticker_id', None)
        context.user_data.pop('temp_sticker_interval', None)
        context.user_data['action'] = None
        
        await update.message.reply_text(msg, parse_mode='HTML', reply_markup=get_back_keyboard(role))
        return

    # --- إضافة/حذف مشرف ---
    if context.user_data.get('action') == 'add_admin':
        if not text:
            await update.message.reply_text("❌ يرجى إرسال نص.", reply_markup=get_back_keyboard(role))
            return
            
        target = text.strip().replace("@", "")
        
        # ✅ استخدام Context Manager
        with db.get_db_session() as session:
            try:
                try:
                    target_id = int(target)
                except ValueError:
                    target_id = None
                user = session.query(db.User).filter(
                    (db.User.username == target) | (db.User.user_id == target_id)
                ).first()
                if user:
                    user.is_admin = True
                    uname = f"@{user.username}" if user.username else f"ID:{user.user_id}"
                    msg = f"✅ تم رفع {uname} مشرفاً بنجاح."
                    db.invalidate_admin_cache(user.user_id)
                else:
                    msg = "❌ المستخدم غير موجود في قاعدة بيانات البوت."
            except Exception as e:
                logger.error(f"Error adding admin: {e}")
                msg = "❌ حدث خطأ."
        
        context.user_data['action'] = None
        await update.message.reply_text(msg, parse_mode='HTML', reply_markup=get_back_keyboard(role))
        if "✅" in msg:
            asyncio.create_task(notify_dev(context, f"👤 <b>مشرف جديد أُضيف</b>\n🆔 المعرف: <code>{target}</code>"))
        return

    if context.user_data.get('action') == 'del_admin':
        if not text:
            await update.message.reply_text("❌ يرجى إرسال نص.", reply_markup=get_back_keyboard(role))
            return
            
        target = text.strip().replace("@", "")
        
        # ✅ استخدام Context Manager
        with db.get_db_session() as session:
            try:
                try:
                    target_id = int(target)
                except ValueError:
                    target_id = None
                user = session.query(db.User).filter(
                    (db.User.username == target) | (db.User.user_id == target_id)
                ).first()
                if user and user.user_id != config.DEVELOPER_ID:
                    user.is_admin = False
                    uname = f"@{user.username}" if user.username else f"ID:{user.user_id}"
                    msg = f"✅ تم إزالة صلاحية المشرف من {uname}."
                    db.invalidate_admin_cache(user.user_id)
                else:
                    msg = "❌ حدث خطأ أو تحاول حذف المطور."
            except Exception as e:
                logger.error(f"Error removing admin: {e}")
                msg = "❌ حدث خطأ."
        
        context.user_data['action'] = None
        await update.message.reply_text(msg, parse_mode='HTML', reply_markup=get_back_keyboard(role))
        if "✅" in msg:
            asyncio.create_task(notify_dev(context, f"👤 <b>مشرف أُزيل</b>\n🆔 المعرف: <code>{target}</code>"))
        return

    # رفع الملفات
    if document and context.user_data.get('upload_category'):
        category = context.user_data['upload_category']
        if document.mime_type == "text/plain":
            file = await document.get_file()
            content_bytes = bytes(await file.download_as_bytearray())
            # دعم encodings متعددة
            content_text = None
            for enc in ('utf-8', 'utf-8-sig', 'windows-1256', 'cp1256', 'latin-1'):
                try:
                    content_text = content_bytes.decode(enc).splitlines()
                    break
                except (UnicodeDecodeError, LookupError):
                    continue
            if content_text is None:
                await update.message.reply_text("❌ تعذر قراءة الملف، تأكد أنه محفوظ بترميز UTF-8.", reply_markup=get_back_keyboard(role))
                return
            content_list = [line for line in content_text if line.strip()]
            count = db.add_file_content(category, content_list)
            msg = f"✅ تمت إضافة <b>{count}</b> اقتباس لقسم <b>{category}</b> بنجاح."
            context.user_data['upload_category'] = None
            user_tag = f"@{update.effective_user.username}" if update.effective_user.username else f"ID: {user_id}"
            asyncio.create_task(notify_dev(
                context,
                f"📂 <b>ملف محتوى رُفع</b>\n"
                f"👤 بواسطة: {user_tag}\n"
                f"📁 الفئة: <b>{category}</b>\n"
                f"📝 عدد الاقتباسات المضافة: <b>{count}</b>"
            ))
        else:
            msg = "❌ يرجى رفع ملف بصيغة .txt فقط."
        await update.message.reply_text(msg, parse_mode='HTML', reply_markup=get_back_keyboard(role))
        return

    # إضافة قناة
    if context.user_data.get('step') == 'waiting_channel':
        channel_id = None
        title = ""
        
        if forward_from:
            channel_id = forward_from.id
            title = forward_from.title
            username = forward_from.username
        elif text and (text.startswith("@") or text.startswith("-100")):
            try:
                chat = await context.bot.get_chat(text)
                channel_id = chat.id
                title = chat.title
                username = chat.username
            except:
                msg = "❌ تعذر الوصول للقناة. تأكد من المعرف وأن البوت مشرف."
                await update.message.reply_text(msg, reply_markup=get_back_keyboard(role))
                return
        else:
            return

        is_bot_admin = await is_bot_admin_in_channel(context.bot, channel_id)
        
        if not is_bot_admin:
            msg = (
                f"⛔️ <b>البوت ليس مشرفاً</b>\n"
                f"القناة: <b>{title}</b>\n\n"
                f"يرجى تعيين البوت مشرفاً في القناة ثم المحاولة مجدداً."
            )
            await update.message.reply_text(msg, parse_mode='HTML', reply_markup=get_back_keyboard(role))
            return

        context.user_data['pending_channel'] = {'id': channel_id, 'title': title, 'username': username}
        context.user_data['step'] = None
        msg = f"✅ <b>تم التحقق من القناة</b>\n📌 <b>{title}</b>\n\nاختر فئة المحتوى:"
        await update.message.reply_text(msg, parse_mode='HTML', reply_markup=get_categories_keyboard())
        return

    # --- إعدادات الوقت ---
    if context.user_data.get('action') == 'set_fixed_time':
        if not text:
            await update.message.reply_text("❌ يرجى إرسال نص.", reply_markup=get_back_keyboard(role))
            return
            
        time_input = text.strip()
        
        if context.user_data.get('mode') == 'edit':
            ch_id = context.user_data.get('editing_channel_id')
            
            # ✅ استخدام Context Manager
            with db.get_db_session() as session:
                try:
                    ch = session.query(db.Channel).filter_by(id=ch_id).first()
                    if ch:
                        ch.time_type = 'fixed'
                        ch.time_value = time_input
                        msg = f"✅ تم تحديث وقت القناة <b>{ch.title}</b>\n🕒 الساعات: {time_input}"
                    else:
                        msg = "❌ خطأ في العثور على القناة."
                except Exception as e:
                    logger.error(f"Error updating fixed time: {e}")
                    msg = "❌ حدث خطأ أثناء التحديث."
            
            context.user_data['action'] = None
            context.user_data['mode'] = None
            await update.message.reply_text(msg, parse_mode='HTML', reply_markup=get_back_keyboard(role))
        else:
            try:
                context.user_data['time_settings'] = {'type': 'fixed', 'value': time_input}
                await finalize_channel_addition(update, context, None, role)
            except Exception as e:
                logger.error(f"Error adding fixed time: {e}")
                await update.message.reply_text("❌ حدث خطأ أثناء حفظ الإعدادات.", reply_markup=get_back_keyboard(role))
        return

    if context.user_data.get('action') == 'set_interval':
        if not text:
            await update.message.reply_text("❌ يرجى إرسال نص.", reply_markup=get_back_keyboard(role))
            return
            
        try:
            val = int(text.strip())
        except ValueError:
            await update.message.reply_text("❌ يرجى إرسال رقم صحيح للدقائق.", reply_markup=get_back_keyboard(role))
            return
            
        if context.user_data.get('mode') == 'edit':
            ch_id = context.user_data.get('editing_channel_id')
            
            # ✅ استخدام Context Manager
            with db.get_db_session() as session:
                try:
                    ch = session.query(db.Channel).filter_by(id=ch_id).first()
                    if ch:
                        ch.time_type = 'interval'
                        ch.time_value = str(val)
                        msg = f"✅ تم تحديث وقت القناة <b>{ch.title}</b>\n⏳ كل: {val} دقيقة"
                    else:
                        msg = "❌ خطأ في العثور على القناة."
                except Exception as e:
                    logger.error(f"Error updating interval: {e}")
                    msg = "❌ حدث خطأ أثناء التحديث."
            
            context.user_data['action'] = None
            context.user_data['mode'] = None
            await update.message.reply_text(msg, parse_mode='HTML', reply_markup=get_back_keyboard(role))
        else:
            try:
                context.user_data['time_settings'] = {'type': 'interval', 'value': str(val)}
                await finalize_channel_addition(update, context, None, role)
            except Exception as e:
                logger.error(f"Error adding interval: {e}")
                await update.message.reply_text("❌ حدث خطأ أثناء حفظ الإعدادات.", reply_markup=get_back_keyboard(role))
        return

    # إعدادات البوت المخصصة
    if context.user_data.get('action') == 'set_welcome_msg':
        if not text:
            await update.message.reply_text("❌ يرجى إرسال نص.", reply_markup=get_back_keyboard(role))
            return
        val = '' if text.strip() == '-' else text.strip()
        db.set_setting('welcome_message', val)
        context.user_data['action'] = None
        await update.message.reply_text("✅ تم تحديث رسالة الترحيب.", reply_markup=get_back_keyboard(role))
        return

    if context.user_data.get('action') == 'set_bot_channel':
        if not text:
            await update.message.reply_text("❌ يرجى إرسال نص.", reply_markup=get_back_keyboard(role))
            return
        val = '' if text.strip() == '-' else text.strip().lstrip('@')
        db.set_setting('bot_channel', val)
        context.user_data['action'] = None
        await update.message.reply_text(
            f"✅ تم {'إلغاء' if not val else 'تعيين'} قناة البوت{f': <b>@{val}</b>' if val else ''}.",
            parse_mode='HTML', reply_markup=get_back_keyboard(role)
        )
        return

    if context.user_data.get('action') == 'set_bot_about':
        if not text:
            await update.message.reply_text("❌ يرجى إرسال نص.", reply_markup=get_back_keyboard(role))
            return
        val = '' if text.strip() == '-' else text.strip()
        db.set_setting('bot_about', val)
        context.user_data['action'] = None
        await update.message.reply_text("✅ تم تحديث نص عنا.", reply_markup=get_back_keyboard(role))
        return

    if context.user_data.get('action') == 'set_force_sub':
        if not text:
            await update.message.reply_text("❌ يرجى إرسال نص.", reply_markup=get_back_keyboard(role))
            return
        val = '' if text.strip() == '-' else text.strip().lstrip('@')
        db.set_setting('force_sub_channel', val)
        context.user_data['action'] = None
        await update.message.reply_text(
            f"✅ {'تم إلغاء الاشتراك الإجباري.' if not val else f'تم تعيين قناة الاشتراك الإجباري: <b>@{val}</b>'}",
            parse_mode='HTML', reply_markup=get_back_keyboard(role)
        )
        return

    # اقتراح اقتباس من المستخدم
    if context.user_data.get('action') == 'waiting_user_quote':
        if not text:
            await update.message.reply_text("❌ يرجى إرسال نص.", reply_markup=get_back_keyboard(role))
            return
        category = context.user_data.pop('suggest_category', 'اقتباسات عامة')
        context.user_data['action'] = None

        # تحقق من الحد اليومي مرة أخرى
        daily_count = db.get_user_daily_quotes_count(user_id)
        if daily_count >= 3:
            await update.message.reply_text("⚠️ وصلت الحد اليومي (3 اقتباسات).", reply_markup=get_back_keyboard(role))
            return

        quote_id = db.add_pending_quote(
            user_id=user_id,
            username=update.effective_user.username or '',
            category=category,
            content=text.strip()
        )

        await update.message.reply_text(
            "✅ <b>تم إرسال اقتباسك للمراجعة</b>\nسيتم إضافته بعد موافقة المشرف.",
            parse_mode='HTML', reply_markup=get_back_keyboard(role)
        )

        # إرسال للمطور مع أزرار القبول والرفض
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        user_tag = f"@{update.effective_user.username}" if update.effective_user.username else f"ID: {user_id}"
        notif_msg = (
            f"✍️ <b>اقتباس جديد للمراجعة</b>\n"
            f"┌ 👤 المستخدم: {user_tag}\n"
            f"├ 📂 الفئة: <b>{category}</b>\n"
            f"└ 📝 الاقتباس:\n\n<blockquote>{text.strip()}</blockquote>"
        )
        kb = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ قبول", callback_data=f"approve_quote_{quote_id}"),
                InlineKeyboardButton("🚫 رفض", callback_data=f"reject_quote_{quote_id}"),
            ]
        ])
        asyncio.create_task(notify_dev(context, notif_msg, keyboard=kb))
        return

    # إضافة اقتباس يدوي
    if context.user_data.get('action') == 'waiting_manual_quote':
        if not text:
            await update.message.reply_text("❌ يرجى إرسال نص.", reply_markup=get_back_keyboard(role))
            return
        category = context.user_data.get('manual_quote_category')
        ch_id = context.user_data.get('manual_quote_ch_id')
        db.add_file_content(category, [text.strip()])
        context.user_data['action'] = None
        context.user_data.pop('manual_quote_category', None)
        context.user_data.pop('manual_quote_ch_id', None)
        await update.message.reply_text(
            f"✅ <b>تمت إضافة الاقتباس</b>\n📂 الفئة: <b>{category}</b>",
            parse_mode='HTML', reply_markup=get_back_keyboard(role)
        )
        return

    # استعادة نسخة احتياطية
    if context.user_data.get('action') == 'waiting_backup_file':
        if user_id != config.DEVELOPER_ID:
            return
        # قبول JSON بأي mime type أو ملف اسمه ينتهي بـ .json
        is_json = (
            document and (
                document.mime_type in ('application/json', 'text/plain', 'application/octet-stream') or
                (document.file_name and document.file_name.endswith('.json'))
            )
        )
        if not document or not is_json:
            await update.message.reply_text("❌ يرجى إرسال ملف JSON فقط.", reply_markup=get_back_keyboard(role))
            return
        import json
        file = await document.get_file()
        content_bytes = bytes(await file.download_as_bytearray())
        try:
            backup_data = json.loads(content_bytes.decode('utf-8'))
        except Exception:
            await update.message.reply_text("❌ الملف تالف أو غير صالح.", reply_markup=get_back_keyboard(role))
            context.user_data['action'] = None
            return
        if backup_data.get('version') != 1:
            await update.message.reply_text("❌ إصدار النسخة غير مدعوم.", reply_markup=get_back_keyboard(role))
            context.user_data['action'] = None
            return
        await update.message.reply_text("⏳ <b>جاري استعادة البيانات...</b>", parse_mode='HTML')
        stats = db.import_backup(backup_data)
        await update.message.reply_text(
            f"✅ <b>تمت الاستعادة بنجاح</b>\n\n"
            f"┌ 👥 مستخدمون جدد: <b>{stats['users']}</b>\n"
            f"├ 📢 قنوات جديدة: <b>{stats['channels']}</b>\n"
            f"├ 📝 اقتباسات: <b>{stats['content']}</b>\n"
            f"├ ⚙️ إعدادات: <b>{stats['settings']}</b>\n"
            f"└ ⏭️ تم تخطيه (موجود): <b>{stats['skipped']}</b>",
            parse_mode='HTML', reply_markup=get_back_keyboard(role)
        )
        context.user_data['action'] = None
        return

    # إذاعة
    if context.user_data.get('action') == 'waiting_broadcast':
        if not update.message:
            return
            
        msg_to_send = update.message.text or update.message.caption
        if not msg_to_send: 
            return
        
        await update.message.reply_text("⏳ <b>جاري إرسال الإذاعة...</b>\nسيتم إعلامك عند الانتهاء.", parse_mode='HTML')
        asyncio.create_task(broadcast_task(context, msg_to_send))
        context.user_data['action'] = None
        return

    # تعديل إعداد - إدخال الـ key
    if context.user_data.get('action') == 'edit_setting_key':
        if not text:
            await update.message.reply_text("❌ يرجى إرسال نص.", reply_markup=get_back_keyboard(role))
            return
        existing = db.get_setting(text.strip())
        if existing is None:
            await update.message.reply_text(f"❌ الإعداد <code>{text.strip()}</code> غير موجود.", parse_mode='HTML', reply_markup=get_back_keyboard(role))
            context.user_data['action'] = None
            return
        context.user_data['setting_key'] = text.strip()
        context.user_data['action'] = 'edit_setting_value'
        await update.message.reply_text(
            f"القيمة الحالية لـ <code>{text.strip()}</code>: <b>{existing}</b>\n\nأرسل القيمة الجديدة:",
            parse_mode='HTML', reply_markup=get_back_keyboard(role)
        )
        return

    # تعديل إعداد - إدخال القيمة الجديدة
    if context.user_data.get('action') == 'edit_setting_value':
        if not text:
            await update.message.reply_text("❌ يرجى إرسال نص.", reply_markup=get_back_keyboard(role))
            return
        key = context.user_data.pop('setting_key', None)
        if key:
            db.set_setting(key, text.strip())
            await update.message.reply_text(f"✅ تم تحديث <code>{key}</code> إلى <b>{text.strip()}</b>.", parse_mode='HTML', reply_markup=get_back_keyboard(role))
        context.user_data['action'] = None
        return

    # إضافة إعداد جديد - إدخال الـ key
    if context.user_data.get('action') == 'add_setting_key':
        if not text:
            await update.message.reply_text("❌ يرجى إرسال نص.", reply_markup=get_back_keyboard(role))
            return
        context.user_data['setting_key'] = text.strip()
        context.user_data['action'] = 'add_setting_value'
        await update.message.reply_text(f"أرسل القيمة للإعداد <code>{text.strip()}</code>:", parse_mode='HTML', reply_markup=get_back_keyboard(role))
        return

    # إضافة إعداد جديد - إدخال القيمة
    if context.user_data.get('action') == 'add_setting_value':
        if not text:
            await update.message.reply_text("❌ يرجى إرسال نص.", reply_markup=get_back_keyboard(role))
            return
        key = context.user_data.pop('setting_key', None)
        if key:
            db.set_setting(key, text.strip())
            await update.message.reply_text(f"✅ تمت إضافة الإعداد <code>{key}</code> = <b>{text.strip()}</b>.", parse_mode='HTML', reply_markup=get_back_keyboard(role))
        context.user_data['action'] = None
        return

    # تفعيل المجموعات
    if text == "تفعيل":
        chat_id = update.effective_chat.id
        chat_type = update.effective_chat.type
        
        if chat_type in ['group', 'supergroup']:
            is_bot_admin = await is_bot_admin_in_channel(context.bot, chat_id)
            if not is_bot_admin:
                await update.message.reply_text("يجب أن أكون مشرفاً في المجموعة للتفعيل.")
                return
            
            # ✅ استخدام الدالة المعدلة
            success = db.add_channel(
                ch_id=chat_id, 
                title=update.effective_chat.title, 
                added_by=user_id, 
                cat="اقتباسات عامة", 
                fmt="normal"
            )
            
            if success:
                await update.message.reply_text("✅ تم تفعيل البوت في المجموعة بنجاح!")
                asyncio.create_task(notify_dev(
                    context,
                    f"👥 <b>مجموعة جديدة فُعّلت</b>\n"
                    f"📌 الاسم: <b>{update.effective_chat.title}</b>\n"
                    f"🆔 الآيدي: <code>{chat_id}</code>\n"
                    f"👤 فعّلها: @{update.effective_user.username or user_id}"
                ))
            else:
                await update.message.reply_text("❌ المجموعة مضافة مسبقاً أو حدث خطأ.")