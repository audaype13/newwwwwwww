import logging
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
import database as db
import config
from keyboards import (
    get_dev_keyboard, get_admin_keyboard, get_user_keyboard,
    get_back_keyboard, get_categories_keyboard, get_format_keyboard,
    get_time_keyboard, get_files_keyboard, get_categories_keyboard_edit,
    get_format_keyboard_edit, get_channel_options_keyboard
)
from utils import post_job, finalize_channel_addition, notify_dev

# اختصارات الألوان
P = "primary"
S = "success"
D = "danger"

logger = logging.getLogger(__name__)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data
    
    if user_id == config.DEVELOPER_ID: 
        role = "dev"
    elif db.is_admin(user_id): 
        role = "admin"
    else: 
        role = "user"

    # اقتراح اقتباس من المستخدم
    if data == "suggest_quote":
        daily_count = db.get_user_daily_quotes_count(user_id)
        if daily_count >= 3:
            await query.edit_message_text(
                "⚠️ <b>وصلت الحد اليومي</b>\nيمكنك إرسال 3 اقتباسات فقط في اليوم.\nحاول مجدداً غداً.",
                parse_mode='HTML', reply_markup=get_back_keyboard(role)
            )
            return
        remaining = 3 - daily_count
        keyboard = [
            [InlineKeyboardButton(label, callback_data=f"suggest_cat_{value}", style=P)]
            for label, value in __import__('keyboards').CATEGORIES
        ]
        keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="back_user")])
        await query.edit_message_text(
            f"✍️ <b>اقتراح اقتباس</b>\n"
            f"متبقي لك اليوم: <b>{remaining}/3</b>\n\n"
            f"اختر فئة الاقتباس:",
            parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    if data.startswith("suggest_cat_"):
        category = data[len("suggest_cat_"):]
        context.user_data['action'] = 'waiting_user_quote'
        context.user_data['suggest_category'] = category
        await query.edit_message_text(
            f"✍️ <b>اقتراح اقتباس</b>\nالفئة: <b>{category}</b>\n\nأرسل الاقتباس الآن:",
            parse_mode='HTML', reply_markup=get_back_keyboard(role)
        )
        return

    # قبول/رفض اقتباس مقترح (للمطور فقط)
    if data.startswith("approve_quote_"):
        if user_id != config.DEVELOPER_ID:
            return
        quote_id = int(data.split("_")[2])
        success = db.approve_pending_quote(quote_id)
        await query.edit_message_text(
            "✅ <b>تم قبول الاقتباس وإضافته لقاعدة البيانات.</b>" if success else "❌ الاقتباس غير موجود أو تمت معالجته مسبقاً.",
            parse_mode='HTML'
        )
        return

    if data.startswith("reject_quote_"):
        if user_id != config.DEVELOPER_ID:
            return
        quote_id = int(data.split("_")[2])
        success = db.reject_pending_quote(quote_id)
        await query.edit_message_text(
            "🚫 <b>تم رفض الاقتباس.</b>" if success else "❌ الاقتباس غير موجود أو تمت معالجته مسبقاً.",
            parse_mode='HTML'
        )
        return

    # تحقق من الاشتراك الإجباري
    if data == "check_sub":
        bot_info = db.get_bot_info()
        force_sub = bot_info.get('force_sub_channel', '').strip()
        if not force_sub:
            await query.answer("✅ لا يوجد اشتراك إجباري", show_alert=False)
            return
        from handlers.start import check_force_sub
        is_sub = await check_force_sub(context.bot, user_id, force_sub)
        if is_sub:
            await query.answer("✅ تم التحقق، أنت مشترك!", show_alert=False)
            bot_info = db.get_bot_info()
            bot_me = await context.bot.get_me()
            welcome = bot_info.get('bot_about', '') or "👋 <b>أهلاً بك في بوت النشر التلقائي</b>\nاختر من القائمة:"
            await query.edit_message_text(
                welcome,
                parse_mode='HTML',
                reply_markup=get_user_keyboard(
                    bot_username=bot_me.username,
                    bot_channel=bot_info.get('bot_channel', ''),
                    show_about=bool(bot_info.get('bot_about'))
                )
            )
        else:
            await query.answer("❌ لم تشترك بعد، اشترك ثم حاول مجدداً", show_alert=True)
        return

    # عنا
    if data == "about_us":
        bot_info = db.get_bot_info()
        about_text = bot_info.get('bot_about', 'لا توجد معلومات متاحة حالياً.')
        await query.answer()
        await context.bot.send_message(chat_id=user_id, text=about_text, parse_mode='HTML')
        return

    # 1. زر تعديل الوقت
    if data == "edit_channel_time":
        await query.edit_message_text("اختر طريقة النشر الجديدة:", reply_markup=get_time_keyboard())
        return

    # 2. إدارة القنوات (تم التعديل ليعمل مع المستخدمين العاديين)
    # إدارة القنوات - مع cache لتجنب استدعاء API لكل قناة
    if data == "manage_channels":
        await query.edit_message_text("⏳ <b>جاري تحميل قنواتك...</b>", parse_mode='HTML')
        with db.get_db_session() as session:
            all_channels = session.query(db.Channel).all()
            accessible_channels = []
            for ch in all_channels:
                try:
                    # للمطور والمشرف: عرض كل القنوات مباشرة بدون فحص API
                    if role in ('dev', 'admin'):
                        accessible_channels.append({
                            'id': ch.id, 'title': ch.title,
                            'category': ch.category, 'is_active': ch.is_active,
                            'time_type': ch.time_type, 'last_post_at': ch.last_post_at
                        })
                    else:
                        user_member = await context.bot.get_chat_member(ch.channel_id, user_id)
                        if user_member.status in ['administrator', 'creator']:
                            accessible_channels.append({
                                'id': ch.id, 'title': ch.title,
                                'category': ch.category, 'is_active': ch.is_active,
                                'time_type': ch.time_type, 'last_post_at': ch.last_post_at
                            })
                except Exception as e:
                    logger.warning(f"Skipping channel {ch.channel_id}: {e}")
                    continue

        if not accessible_channels:
            await query.edit_message_text(
                "📭 <b>لا توجد قنوات</b>\nلا تملك صلاحيات إدارية في أي قناة مضافة.",
                parse_mode='HTML', reply_markup=get_back_keyboard(role)
            )
            return

        # حفظ القنوات في cache
        context.user_data['channels_cache'] = accessible_channels

        keyboard = []
        for ch in accessible_channels:
            status_icon = "🟢" if ch['is_active'] else "🔴"
            time_icon = {"fixed": "⏰", "interval": "⏳", "default": "🔀"}.get(ch['time_type'], "🔀")
            keyboard.append([InlineKeyboardButton(
                f"{status_icon} {ch['title']}  {time_icon}",
                callback_data=f"edit_channel_{ch['id']}", style="primary"
            )])
        keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data=f"back_{role}")])
        total = len(accessible_channels)
        active = sum(1 for c in accessible_channels if c['is_active'])
        await query.edit_message_text(
            f"📋 <b>قنواتك</b>  ({active}/{total} نشطة)\n"
            f"🟢 نشط  🔴 موقوف  ⏰ ساعات  ⏳ فارق  🔀 عشوائي",
            parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    # زر إعدادات القناة (تم السماح للمستخدمين بالدخول طالما مروا من الفلتر)
    if data.startswith("edit_channel_") and data != "edit_channel_time":
        try:
            ch_id = int(data.split("_")[2])
        except ValueError:
            return

        context.user_data['editing_channel_id'] = ch_id

        with db.get_db_session() as session:
            ch = session.query(db.Channel).filter_by(id=ch_id).first()
            if not ch:
                await query.edit_message_text("❌ القناة غير موجودة.", reply_markup=get_back_keyboard(role))
                return
            # نسخ كل البيانات داخل الـ session قبل إغلاقها
            ch_data = {
                'title': ch.title,
                'category': ch.category,
                'is_active': ch.is_active,
                'msg_format': ch.msg_format,
                'time_type': ch.time_type,
                'time_value': ch.time_value,
                'last_post_at': ch.last_post_at,
                'sticker_file_id': ch.sticker_file_id,
                'sticker_interval': ch.sticker_interval,
            }

        time_map = {
            "fixed": f"⏰ ساعات محددة: {ch_data['time_value']}",
            "interval": f"⏳ كل {ch_data['time_value']} دقيقة",
            "default": "🔀 عشوائي/فوري"
        }
        time_text = time_map.get(ch_data['time_type'], "🔀 عشوائي/فوري")
        last_post = ch_data['last_post_at'].strftime("%Y-%m-%d %H:%M") if ch_data['last_post_at'] else "لم ينشر بعد"
        sticker_info = f"✅ كل {ch_data['sticker_interval']} رسالة" if ch_data['sticker_file_id'] else "❌ غير مفعّل"
        fmt_text = "💎 اقتباس" if ch_data['msg_format'] == "blockquote" else "📝 عادي"

        details = (
            f"⚙️ <b>{ch_data['title']}</b>\n"
            f"┌ الحالة: {'🟢 نشط' if ch_data['is_active'] else '🔴 موقوف'}\n"
            f"├ 📂 الفئة: <b>{ch_data['category']}</b>\n"
            f"├ 🎨 الشكل: <b>{fmt_text}</b>\n"
            f"├ ⏱️ التوقيت: <b>{time_text}</b>\n"
            f"├ 🕐 آخر نشر: <b>{last_post}</b>\n"
            f"└ ⭐ الملصق: <b>{sticker_info}</b>"
        )
        await query.edit_message_text(details, parse_mode='HTML', reply_markup=get_channel_options_keyboard(ch_id, ch_data['is_active']))

    # --- إعداد الملصق التفاعلي ---
    if data == "set_sticker_flow":
        ch_id = context.user_data.get('editing_channel_id')
        if not ch_id: 
            return
        context.user_data['action'] = 'waiting_sticker'
        await query.edit_message_text(
            "✏️ أرسل الملصق (Sticker) الذي تريده أن ينشر تلقائياً:", 
            reply_markup=get_back_keyboard(role)
        )

    # حذف القناة
    if data == "confirm_del_channel":
        ch_id = context.user_data.get('editing_channel_id')
        if not ch_id:
            return
        keyboard = [
            [InlineKeyboardButton("❌ لا، تراجع", callback_data=f"edit_channel_{ch_id}")],
            [InlineKeyboardButton("✅ نعم، احذف", callback_data=f"delete_channel_{ch_id}", style="danger")]
        ]
        await query.edit_message_text(
            "⚠️ <b>تأكيد الحذف</b>\nهل أنت متأكد من حذف هذه القناة من النظام؟\n\n<i>لا يمكن التراجع عن هذا الإجراء.</i>",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    if data.startswith("delete_channel_"):
        ch_id = int(data.split("_")[2])
        title = None
        with db.get_db_session() as session:
            ch = session.query(db.Channel).filter_by(id=ch_id).first()
            if ch:
                title = ch.title
                session.delete(ch)
                msg = f"✅ تم حذف القناة <b>{title}</b> بنجاح."
            else:
                msg = "❌ لم يتم العثور على القناة."
        context.user_data['editing_channel_id'] = None
        await query.edit_message_text(msg, parse_mode='HTML', reply_markup=get_back_keyboard(role))
        if title:
            user_tag = f"@{query.from_user.username}" if query.from_user.username else f"ID: {user_id}"
            asyncio.create_task(notify_dev(context, f"🗑️ <b>قناة حُذفت</b>\n📌 الاسم: <b>{title}</b>\n👤 حذفها: {user_tag}"))

    # تغيير الفئة والتنسيق
    if data == "change_cat_select":
        await query.edit_message_text(
            "اختر نوع المحتوى الجديد:", 
            reply_markup=get_categories_keyboard_edit(context)
        )

    if data == "change_fmt_select":
        await query.edit_message_text(
            "اختر شكل الرسالة الجديد:", 
            reply_markup=get_format_keyboard_edit(context)
        )

    if data.startswith("set_edit_cat_"):
        new_cat = data[len("set_edit_cat_"):]
        ch_id = context.user_data.get('editing_channel_id')
        if ch_id:
            # ✅ استخدام Context Manager
            with db.get_db_session() as session:
                try:
                    ch = session.query(db.Channel).filter_by(id=ch_id).first()
                    if ch:
                        ch.category = new_cat
                        msg = f"✅ تم تغيير نوع المحتوى إلى <b>{new_cat}</b>."
                    else:
                        msg = "❌ حدث خطأ."
                except Exception as e:
                    logger.error(f"Error updating category: {e}")
                    msg = "❌ حدث خطأ في قاعدة البيانات."
            
            await query.edit_message_text(msg, parse_mode='HTML', reply_markup=get_back_keyboard(role))

    if data.startswith("set_edit_fmt_"):
        new_fmt = data[len("set_edit_fmt_"):]
        ch_id = context.user_data.get('editing_channel_id')
        if ch_id:
            # ✅ استخدام Context Manager
            with db.get_db_session() as session:
                try:
                    ch = session.query(db.Channel).filter_by(id=ch_id).first()
                    if ch:
                        ch.msg_format = new_fmt
                        msg = f"✅ تم تغيير شكل الرسالة إلى <b>{new_fmt}</b>."
                    else:
                        msg = "❌ حدث خطأ."
                except Exception as e:
                    logger.error(f"Error updating format: {e}")
                    msg = "❌ حدث خطأ في قاعدة البيانات."
            
            await query.edit_message_text(msg, parse_mode='HTML', reply_markup=get_back_keyboard(role))

    # إدارة المشرفين
    if data == "manage_admins":
        if user_id != config.DEVELOPER_ID:
            await query.edit_message_text("⛔️ هذا القسم للمطور فقط.", reply_markup=get_back_keyboard(role))
            return
        keyboard = [
            [InlineKeyboardButton("➕ إضافة مشرف", callback_data="add_admin_step1", style="success")],
            [InlineKeyboardButton("➖ إزالة مشرف", callback_data="del_admin_step1", style="danger")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="back_dev")]
        ]
        await query.edit_message_text(
            "👥 <b>إدارة المشرفين</b>\nاختر العملية:",
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    if data == "add_admin_step1":
        context.user_data['action'] = 'add_admin'
        await query.edit_message_text(
            "➕ <b>إضافة مشرف</b>\nأرسل الآيدي الرقمي أو @يوزرنيم للمستخدم:",
            parse_mode='HTML',
            reply_markup=get_back_keyboard(role)
        )

    if data == "del_admin_step1":
        context.user_data['action'] = 'del_admin'
        await query.edit_message_text(
            "➖ <b>إزالة مشرف</b>\nأرسل الآيدي الرقمي أو @يوزرنيم للمستخدم:",
            parse_mode='HTML',
            reply_markup=get_back_keyboard(role)
        )

    # إدارة الملفات
    if data == "manage_files":
        if not db.is_admin(user_id) and user_id != config.DEVELOPER_ID:
            await query.edit_message_text(
                "⛔️ هذا القسم للمشرفين فقط.", 
                reply_markup=get_back_keyboard(role)
            )
            return
        if user_id == config.DEVELOPER_ID:
            from keyboards import CATEGORIES
            counts = db.get_content_count_by_category()
            counts_dict = {cat: cnt for cat, cnt in counts}
            keyboard = []
            for label, value in CATEGORIES:
                cnt = counts_dict.get(value, 0)
                keyboard.append([InlineKeyboardButton(f"{label} ({cnt} اقتباس)", callback_data=f"dev_file_menu_{value}", style="primary")])
            keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="back_dev")])
            await query.edit_message_text("📂 <b>إدارة ملفات النشر:</b>\nاختر الفئة:", parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            await query.edit_message_text("اختر القسم لرفع ملفات الاقتباسات (txt):", reply_markup=get_files_keyboard())

    if data.startswith("dev_file_menu_"):
        if user_id != config.DEVELOPER_ID:
            return
        category = data[len("dev_file_menu_"):]
        context.user_data['dev_file_category'] = category
        counts_dict = {c: n for c, n in db.get_content_count_by_category()}
        keyboard = [
            [InlineKeyboardButton("📤 رفع ملف جديد (إضافة)", callback_data=f"upload_{category}", style="primary")],
            [InlineKeyboardButton("🔄 استبدال الكل برفع ملف جديد", callback_data=f"replace_file_{category}", style="primary")],
            [InlineKeyboardButton("🗑️ حذف كل محتوى الفئة", callback_data=f"confirm_del_content_{category}", style="danger")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="manage_files")],
        ]
        await query.edit_message_text(
            f"📁 الفئة: <b>{category}</b>\nعدد الاقتباسات: <b>{counts_dict.get(category, 0)}</b>\n\nاختر العملية:",
            parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard)
        )

    if data.startswith("confirm_del_content_"):
        if user_id != config.DEVELOPER_ID:
            return
        category = data[len("confirm_del_content_"):]
        keyboard = [
            [InlineKeyboardButton("❌ لا، ارجع", callback_data=f"dev_file_menu_{category}")],
            [InlineKeyboardButton("✅ نعم، احذف الكل", callback_data=f"do_del_content_{category}", style="danger")],
        ]
        await query.edit_message_text(
            f"⚠️ هل أنت متأكد من حذف <b>كل</b> اقتباسات فئة <b>{category}</b>؟",
            parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard)
        )

    if data.startswith("do_del_content_"):
        if user_id != config.DEVELOPER_ID:
            return
        category = data[len("do_del_content_"):]
        deleted = db.delete_content_by_category(category)
        await query.edit_message_text(
            f"✅ تم حذف <b>{deleted}</b> اقتباس من فئة <b>{category}</b>.",
            parse_mode='HTML', reply_markup=get_back_keyboard(role)
        )

    if data.startswith("replace_file_"):
        if user_id != config.DEVELOPER_ID:
            return
        category = data[len("replace_file_"):]
        db.delete_content_by_category(category)
        context.user_data['upload_category'] = category
        await query.edit_message_text(
            f"🗑️ تم مسح محتوى <b>{category}</b>.\n\nأرسل الآن ملف <code>.txt</code> الجديد:",
            parse_mode='HTML', reply_markup=get_back_keyboard(role)
        )

    if data.startswith("upload_"):
        category = data[len("upload_"):]
        context.user_data['upload_category'] = category
        msg = f"تم اختيار قسم: <b>{category}</b>\n\nالآن قم بإرسال ملف <code>.txt</code> يحتوي على الاقتباسات."
        await query.edit_message_text(msg, parse_mode='HTML', reply_markup=get_back_keyboard(role))

    # ===== إعدادات البوت (للمطور فقط) =====
    if data == "bot_settings":
        if user_id != config.DEVELOPER_ID:
            return
        bot_info = db.get_bot_info()
        settings = db.get_all_settings()
        if settings:
            text = "⚙️ <b>إعدادات البوت الحالية:</b>\n\n"
            text += "\n".join([f"🔹 <code>{k}</code>: <b>{v}</b>" for k, v in settings])
        else:
            text = "⚙️ لا توجد إعدادات محفوظة حالياً."
        keyboard = [
            [InlineKeyboardButton("📢 قناة البوت", callback_data="set_bot_channel", style=P)],
            [InlineKeyboardButton("ℹ️ نص عنا", callback_data="set_bot_about", style=P)],
            [InlineKeyboardButton("👋 رسالة الترحيب", callback_data="set_welcome_msg", style=P)],
            [InlineKeyboardButton("🔒 قناة اشتراك إجباري", callback_data="set_force_sub", style=P)],
            [
                InlineKeyboardButton("✏️ تعديل إعداد", callback_data="edit_setting_prompt", style=P),
                InlineKeyboardButton("➕ إضافة إعداد", callback_data="add_setting_prompt", style=S),
            ],
            [InlineKeyboardButton("🔙 رجوع", callback_data="back_dev")],
        ]
        await query.edit_message_text(text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))

    if data == "edit_setting_prompt":
        if user_id != config.DEVELOPER_ID:
            return
        context.user_data['action'] = 'edit_setting_key'
        await query.edit_message_text("أرسل اسم الإعداد (key) الذي تريد تعديله:", reply_markup=get_back_keyboard(role))

    if data == "add_setting_prompt":
        if user_id != config.DEVELOPER_ID:
            return
        context.user_data['action'] = 'add_setting_key'
        await query.edit_message_text("أرسل اسم الإعداد الجديد (key):", reply_markup=get_back_keyboard(role))

    if data == "set_bot_channel":
        if user_id != config.DEVELOPER_ID:
            return
        current = db.get_setting('bot_channel') or 'غير محدد'
        context.user_data['action'] = 'set_bot_channel'
        await query.edit_message_text(
            f"📢 <b>قناة البوت</b>\nالحالي: <code>{current}</code>\n\nأرسل username القناة (مثال: @mychannel)\nأو أرسل <code>-</code> لإلغائها:",
            parse_mode='HTML', reply_markup=get_back_keyboard(role)
        )

    if data == "set_bot_about":
        if user_id != config.DEVELOPER_ID:
            return
        current = db.get_setting('bot_about') or 'غير محدد'
        context.user_data['action'] = 'set_bot_about'
        await query.edit_message_text(
            f"ℹ️ <b>نص عنا</b>\nالحالي:\n{current}\n\nأرسل النص الجديد (يدعم HTML):",
            parse_mode='HTML', reply_markup=get_back_keyboard(role)
        )

    if data == "set_welcome_msg":
        if user_id != config.DEVELOPER_ID:
            return
        current = db.get_setting('welcome_message') or 'غير محدد'
        context.user_data['action'] = 'set_welcome_msg'
        await query.edit_message_text(
            f"👋 <b>رسالة الترحيب</b>\nالحالي:\n{current}\n\nأرسل النص الجديد (يدعم HTML)\nأو أرسل <code>-</code> للرجوع للافتراضي:",
            parse_mode='HTML', reply_markup=get_back_keyboard(role)
        )

    if data == "set_force_sub":
        if user_id != config.DEVELOPER_ID:
            return
        current = db.get_setting('force_sub_channel') or 'غير مفعّل'
        context.user_data['action'] = 'set_force_sub'
        await query.edit_message_text(
            f"🔒 <b>قناة الاشتراك الإجباري</b>\nالحالي: <code>{current}</code>\n\nأرسل username القناة (مثال: @mychannel)\nأو أرسل <code>-</code> لإلغاء الاشتراك الإجباري:",
            parse_mode='HTML', reply_markup=get_back_keyboard(role)
        )

    # ===== النسخة الاحتياطية (للمطور فقط) =====
    if data == "backup_menu":
        if user_id != config.DEVELOPER_ID:
            return
        keyboard = [
            [InlineKeyboardButton("💾 تصدير نسخة احتياطية", callback_data="backup_export", style="success")],
            [InlineKeyboardButton("📥 استعادة نسخة احتياطية", callback_data="backup_import_prompt", style="primary")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="back_dev")],
        ]
        with db.get_db_session() as session:
            u = session.query(db.User).count()
            c = session.query(db.Channel).count()
            f = session.query(db.FileContent).count()
        await query.edit_message_text(
            f"💾 <b>النسخة الاحتياطية</b>\n\n"
            f"┌ 👥 المستخدمون: <b>{u}</b>\n"
            f"├ 📢 القنوات: <b>{c}</b>\n"
            f"└ 📝 الاقتباسات: <b>{f}</b>\n\n"
            f"<i>التصدير يشمل كل البيانات كملف JSON.</i>",
            parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard)
        )

    if data == "backup_export":
        if user_id != config.DEVELOPER_ID:
            return
        await query.edit_message_text("⏳ <b>جاري تصدير البيانات...</b>", parse_mode='HTML')
        import json, io
        backup_data = db.export_backup()
        json_bytes = json.dumps(backup_data, ensure_ascii=False, indent=2).encode('utf-8')
        file_obj = io.BytesIO(json_bytes)
        file_obj.name = f"backup_{backup_data['exported_at'][:10]}.json"
        await context.bot.send_document(
            chat_id=user_id,
            document=file_obj,
            caption=(
                f"💾 <b>نسخة احتياطية</b>\n"
                f"┌ 👥 المستخدمون: <b>{len(backup_data['users'])}</b>\n"
                f"├ 📢 القنوات: <b>{len(backup_data['channels'])}</b>\n"
                f"├ 📝 الاقتباسات: <b>{len(backup_data['content'])}</b>\n"
                f"└ ⚙️ الإعدادات: <b>{len(backup_data['settings'])}</b>"
            ),
            parse_mode='HTML'
        )
        await query.edit_message_text("✅ <b>تم إرسال النسخة الاحتياطية</b>", parse_mode='HTML', reply_markup=get_back_keyboard(role))

    if data == "backup_import_prompt":
        if user_id != config.DEVELOPER_ID:
            return
        context.user_data['action'] = 'waiting_backup_file'
        await query.edit_message_text(
            "📥 <b>استعادة نسخة احتياطية</b>\n\n"
            "أرسل ملف <code>.json</code> الذي تم تصديره مسبقاً.\n\n"
            "<i>⚠️ البيانات الموجودة لن تُحذف، فقط البيانات الجديدة ستُضاف.</i>",
            parse_mode='HTML', reply_markup=get_back_keyboard(role)
        )

    # إضافة قناة
    if data == "add_channel_prompt":
        context.user_data['step'] = 'waiting_channel'
        await query.edit_message_text(
            "➕ <b>إضافة قناة</b>\n\nأرسل معرف القناة مثل <code>@ChannelName</code>\nأو حوّل (Forward) أي رسالة من القناة هنا:",
            parse_mode='HTML',
            reply_markup=get_back_keyboard(role)
        )

    # اختيارات القسم والتنسيق والوقت
    if data.startswith("cat_"):
        category = data.split("_")[1]
        context.user_data['selected_category'] = category
        msg = f"تم اختيار القسم: <b>{category}</b>.\n\nاختر شكل الرسالة:"
        await query.edit_message_text(msg, parse_mode='HTML', reply_markup=get_format_keyboard())

    if data.startswith("fmt_"):
        fmt = data.split("_")[1]
        context.user_data['selected_format'] = fmt
        await query.edit_message_text("اختر طريقة النشر:", reply_markup=get_time_keyboard())

    if data.startswith("time_"):
        time_type = data.split("_")[1]
        context.user_data['time_type'] = time_type
        
        is_edit_mode = context.user_data.get('editing_channel_id') is not None
        
        if is_edit_mode:
            # ✅ استخدام Context Manager
            with db.get_db_session() as session:
                ch_id = context.user_data.get('editing_channel_id')
                ch = session.query(db.Channel).filter_by(id=ch_id).first()
                
                msg = ""
                if ch:
                    ch.time_type = time_type
                    if time_type == "default":
                        ch.time_value = None
                        msg = "✅ تم تغيير الوقت إلى <b>افتراضي (عشوائي/فوري)</b>."
                        await query.edit_message_text(msg, parse_mode='HTML', reply_markup=get_back_keyboard(role))
                        return
                    else:
                        if time_type == "fixed":
                            context.user_data['action'] = 'set_fixed_time'
                            msg = f"الوقت الحالي: {ch.time_value}\n\nأرسل الساعات الجديدة (مثلاً: 10, 14, 20):"
                        elif time_type == "interval":
                            context.user_data['action'] = 'set_interval'
                            msg = f"الوقت الحالي: {ch.time_value}\n\nأرسل الفارق الزمني الجديد بالدقائق (مثلاً: 60):"
                        
                        context.user_data['mode'] = 'edit' 
                        await query.edit_message_text(msg, reply_markup=get_back_keyboard(role))
                        return
                else:
                    msg = "❌ القناة غير موجودة."
                    await query.edit_message_text(msg)
                    return

        else:
            msg = ""
            if time_type == "fixed":
                context.user_data['action'] = 'set_fixed_time'
                msg = "أرسل الساعات المطلوبة (مثلاً: 10, 14, 20) مفصولة بفاصلة:"
            elif time_type == "interval":
                context.user_data['action'] = 'set_interval'
                msg = "أرسل الفارق الزمني بالدقائق (مثلاً: 60):"
            else:
                await finalize_channel_addition(update, context, query, role)
                return
            
            await query.edit_message_text(msg, reply_markup=get_back_keyboard(role))
        
    # إحصائيات
    if data == "show_stats":
        stats = db.get_stats()
        await query.edit_message_text(stats, parse_mode='HTML', reply_markup=get_back_keyboard(role))

    if data == "back_home":
        context.user_data.clear()
        kb = get_dev_keyboard() if role == "dev" else (get_admin_keyboard() if role == "admin" else None)
        if kb is None:
            bot_info = db.get_bot_info()
            bot_me = await context.bot.get_me()
            kb = get_user_keyboard(
                bot_username=bot_me.username,
                bot_channel=bot_info.get('bot_channel', ''),
                show_about=bool(bot_info.get('bot_about'))
            )
        titles = {"dev": "👨‍💻 <b>لوحة المطور</b>", "admin": "🛡️ <b>لوحة المشرف</b>", "user": "📋 <b>القائمة الرئيسية</b>"}
        await query.edit_message_text(titles[role], parse_mode='HTML', reply_markup=kb)

    if data == "back_dev":
        context.user_data.clear()
        await query.edit_message_text("�‍💻> <b>لوحة المطور</b>", parse_mode='HTML', reply_markup=get_dev_keyboard())

    if data == "back_admin":
        context.user_data.clear()
        await query.edit_message_text("🛡️ <b>لوحة المشرف</b>", parse_mode='HTML', reply_markup=get_admin_keyboard())

    if data == "back_user":
        context.user_data.clear()
        bot_info = db.get_bot_info()
        bot_me = await context.bot.get_me()
        kb = get_user_keyboard(
            bot_username=bot_me.username,
            bot_channel=bot_info.get('bot_channel', ''),
            show_about=bool(bot_info.get('bot_about'))
        )
        await query.edit_message_text("📋 <b>القائمة الرئيسية</b>", parse_mode='HTML', reply_markup=kb)

    # معاينة اقتباس عشوائي من فئة القناة
    if data.startswith("preview_ch_"):
        ch_id = int(data.split("_")[2])
        with db.get_db_session() as session:
            ch = session.query(db.Channel).filter_by(id=ch_id).first()
            if not ch:
                await query.answer("❌ القناة غير موجودة", show_alert=True)
                return
            category = ch.category
            msg_format = ch.msg_format
        text = db.get_next_content(category)
        if not text:
            await query.answer(f"❌ لا يوجد محتوى في فئة {category}", show_alert=True)
            return
        if msg_format == 'blockquote':
            preview = f"<blockquote>{text}</blockquote>"
            parse_mode = 'HTML'
        else:
            preview = text
            parse_mode = None
        await context.bot.send_message(
            chat_id=user_id,
            text=f"👁️ <b>معاينة من فئة {category}:</b>\n\n{preview}" if parse_mode else f"👁️ معاينة من فئة {category}:\n\n{preview}",
            parse_mode='HTML' if parse_mode else None
        )
        await query.answer("✅ تم إرسال المعاينة في خاصك", show_alert=False)
        return

    # نشر فوري لقناة محددة
    if data.startswith("post_ch_"):
        ch_id = int(data.split("_")[2])
        with db.get_db_session() as session:
            ch = session.query(db.Channel).filter_by(id=ch_id).first()
            if not ch:
                await query.answer("❌ القناة غير موجودة", show_alert=True)
                return
            ch_data = {'channel_id': ch.channel_id, 'title': ch.title,
                       'category': ch.category, 'msg_format': ch.msg_format, 'id': ch.id}
        text = db.get_next_content(ch_data['category'])
        if not text:
            await query.answer(f"❌ لا يوجد محتوى في فئة {ch_data['category']}", show_alert=True)
            return
        parse_mode = 'HTML' if ch_data['msg_format'] == 'blockquote' else None
        if ch_data['msg_format'] == 'blockquote':
            text = f"<blockquote>{text}</blockquote>"
        try:
            await context.bot.send_message(chat_id=ch_data['channel_id'], text=text, parse_mode=parse_mode)
            db.update_channel_last_post(ch_data['channel_id'])
            await query.answer(f"✅ تم النشر في {ch_data['title']}", show_alert=False)
        except Exception as e:
            await query.answer(f"❌ فشل النشر: {e}", show_alert=True)
        return

    # إضافة اقتباس يدوي لفئة القناة
    if data.startswith("add_quote_"):
        ch_id = int(data.split("_")[2])
        with db.get_db_session() as session:
            ch = session.query(db.Channel).filter_by(id=ch_id).first()
            if not ch:
                return
            category = ch.category
        context.user_data['action'] = 'waiting_manual_quote'
        context.user_data['manual_quote_category'] = category
        context.user_data['manual_quote_ch_id'] = ch_id
        await query.edit_message_text(
            f"✏️ <b>إضافة اقتباس يدوي</b>\n"
            f"الفئة: <b>{category}</b>\n\n"
            f"أرسل الاقتباس الذي تريد إضافته:",
            parse_mode='HTML', reply_markup=get_back_keyboard(role)
        )
        return

    # تشغيل/إيقاف النشر لقناة محددة
    if data.startswith("toggle_channel_"):
        ch_id = int(data.split("_")[2])
        new_state = db.toggle_channel_posting(ch_id)
        if new_state is None:
            await query.edit_message_text("❌ لم يتم العثور على القناة.", reply_markup=get_back_keyboard(role))
            return
        state_text = "🟢 مفعّل" if new_state else "🔴 موقوف"
        with db.get_db_session() as session:
            ch = session.query(db.Channel).filter_by(id=ch_id).first()
            ch_data = {
                'title': ch.title, 'category': ch.category,
                'msg_format': ch.msg_format, 'time_type': ch.time_type,
                'time_value': ch.time_value, 'last_post_at': ch.last_post_at,
                'sticker_file_id': ch.sticker_file_id, 'sticker_interval': ch.sticker_interval,
            }
        time_map = {"fixed": f"⏰ ساعات محددة: {ch_data['time_value']}", "interval": f"⏳ كل {ch_data['time_value']} دقيقة", "default": "🔀 عشوائي/فوري"}
        time_text = time_map.get(ch_data['time_type'], "🔀 عشوائي/فوري")
        last_post = ch_data['last_post_at'].strftime("%Y-%m-%d %H:%M") if ch_data['last_post_at'] else "لم ينشر بعد"
        sticker_info = f"✅ كل {ch_data['sticker_interval']} رسالة" if ch_data['sticker_file_id'] else "❌ غير مفعّل"
        fmt_text = "💎 اقتباس" if ch_data['msg_format'] == "blockquote" else "📝 عادي"
        details = (
            f"⚙️ <b>{ch_data['title']}</b>\n"
            f"┌ الحالة: {state_text}\n"
            f"├ 📂 الفئة: <b>{ch_data['category']}</b>\n"
            f"├ 🎨 الشكل: <b>{fmt_text}</b>\n"
            f"├ ⏱️ التوقيت: <b>{time_text}</b>\n"
            f"├ 🕐 آخر نشر: <b>{last_post}</b>\n"
            f"└ ⭐ الملصق: <b>{sticker_info}</b>"
        )
        await query.edit_message_text(details, parse_mode='HTML', reply_markup=get_channel_options_keyboard(ch_id, new_state))
        user_tag = f"@{query.from_user.username}" if query.from_user.username else f"ID: {user_id}"
        asyncio.create_task(notify_dev(context, f"⚙️ <b>نشر قناة تغيّر</b>\n📌 القناة: <b>{ch_data['title']}</b>\n👤 بواسطة: {user_tag}\n📊 الحالة: {state_text}"))
        return

    # تفعيل/تعطيل البوت كلياً (للمطور فقط)
    if data == "toggle_bot":
        if user_id != config.DEVELOPER_ID:
            await query.edit_message_text("⛔️ هذا الخيار للمطور فقط.", reply_markup=get_back_keyboard(role))
            return
        with db.get_db_session() as session:
            setting = session.query(db.BotSettings).filter_by(key='posting_status').first()
            status = setting.value if setting else 'off'
            new_status = 'on' if status == 'off' else 'off'
            if setting:
                setting.value = new_status
            else:
                session.add(db.BotSettings(key='posting_status', value=new_status))
        state_text = "🟢 مفعّل" if new_status == 'on' else "🔴 متوقف"
        msg = f"تم تغيير حالة البوت إلى: <b>{state_text}</b>"
        await query.edit_message_text(msg, parse_mode='HTML', reply_markup=get_back_keyboard(role))
        user_tag = f"@{query.from_user.username}" if query.from_user.username else f"ID: {user_id}"
        asyncio.create_task(notify_dev(context, f"🤖 <b>حالة البوت تغيّرت</b>\n👤 بواسطة: {user_tag}\n📊 الحالة: {state_text}"))

    if data == "post_now":
        await query.edit_message_text("⏳ <b>جاري النشر الفوري...</b>", parse_mode='HTML')
        await post_job(context, force_one=True)
        await query.edit_message_text("✅ <b>تم النشر بنجاح</b>", parse_mode='HTML', reply_markup=get_back_keyboard(role))

    if data == "broadcast_menu":
        if not db.is_admin(user_id) and user_id != config.DEVELOPER_ID:
            await query.edit_message_text("⛔️ هذه الميزة للمشرفين فقط.", reply_markup=get_back_keyboard(role))
            return
        context.user_data['action'] = 'waiting_broadcast'
        await query.edit_message_text(
            "📢 <b>إرسال إذاعة</b>\n\nأرسل الرسالة التي تريد إذاعتها لجميع المستخدمين والقنوات:",
            parse_mode='HTML',
            reply_markup=get_back_keyboard(role)
        )