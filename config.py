from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
import database as db
import config
from keyboards import get_dev_keyboard, get_admin_keyboard, get_user_keyboard
from utils import send_notification_to_admins

async def check_force_sub(bot, user_id: int, channel: str) -> bool:
    """يتحقق إذا المستخدم مشترك في قناة الاشتراك الإجباري"""
    try:
        member = await bot.get_chat_member(f"@{channel.lstrip('@')}", user_id)
        return member.status not in ['left', 'kicked']
    except Exception:
        return True  # لو فشل التحقق، نسمح بالمرور

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    username = update.effective_user.username
    first_name = update.effective_user.first_name or ""

    # جلب إعدادات البوت
    bot_info = db.get_bot_info()
    force_sub = bot_info.get('force_sub_channel', '').strip()
    bot_channel = bot_info.get('bot_channel', '').strip()
    bot_about = bot_info.get('bot_about', '').strip()
    welcome_msg = bot_info.get('welcome_message', '').strip()

    # الاشتراك الإجباري - لا يطبق على المطور والمشرفين
    if force_sub and user_id != config.DEVELOPER_ID and not db.is_admin(user_id):
        is_subscribed = await check_force_sub(context.bot, user_id, force_sub)
        if not is_subscribed:
            ch = force_sub.lstrip('@')
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ اشترك الآن", url=f"https://t.me/{ch}", style="success")],
                [InlineKeyboardButton("🔄 تحقق من الاشتراك", callback_data="check_sub")]
            ])
            await update.message.reply_text(
                f"⚠️ <b>يجب الاشتراك في قناتنا أولاً</b>\n\n"
                f"اشترك في القناة ثم اضغط <b>تحقق من الاشتراك</b>:",
                parse_mode='HTML', reply_markup=keyboard
            )
            return

    # تسجيل المستخدم
    with db.get_db_session() as session:
        user = session.query(db.User).filter_by(user_id=user_id).first()
        is_new_user = False
        total_users = session.query(db.User).count()

        if not user:
            session.add(db.User(user_id=user_id, username=username))
            is_new_user = True
            total_users += 1
        else:
            if username != user.username:
                user.username = username

    # إشعار المستخدم الجديد
    if is_new_user:
        user_tag = f"@{username}" if username else "بدون يوزر"
        notif_msg = (
            f"👤 <b>مستخدم جديد انضم</b>\n"
            f"┌ الاسم: <b>{first_name}</b>\n"
            f"├ المعرف: {user_tag}\n"
            f"├ الآيدي: <code>{user_id}</code>\n"
            f"└ إجمالي المستخدمين: <b>{total_users}</b>"
        )
        notif_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("👤 فتح الملف الشخصي", url=f"tg://user?id={user_id}")]
        ])
        # جلب IDs قبل إغلاق الـ session
        with db.get_db_session() as session:
            admin_ids = [a.user_id for a in session.query(db.User).filter_by(is_admin=True).all()]
        for admin_id in admin_ids:
            try:
                await context.bot.send_message(chat_id=admin_id, text=notif_msg, parse_mode='HTML', reply_markup=notif_kb)
            except Exception:
                pass
        try:
            await context.bot.send_message(chat_id=config.DEVELOPER_ID, text=notif_msg, parse_mode='HTML', reply_markup=notif_kb)
        except Exception:
            pass

    # جلب username البوت للمشاركة
    bot_me = await context.bot.get_me()
    bot_username = bot_me.username

    if user_id == config.DEVELOPER_ID:
        await update.message.reply_text(
            "👨‍💻 <b>مرحباً بك يا مطور</b>\nلوحة التحكم الكاملة:",
            reply_markup=get_dev_keyboard(), parse_mode='HTML'
        )
    elif db.is_admin(user_id):
        await update.message.reply_text(
            "🛡️ <b>مرحباً بك يا مشرف</b>\nلوحة الإدارة:",
            reply_markup=get_admin_keyboard(), parse_mode='HTML'
        )
    else:
        welcome = welcome_msg if welcome_msg else "👋 <b>أهلاً بك في بوت النشر التلقائي</b>\nاختر من القائمة:"
        await update.message.reply_text(
            welcome,
            reply_markup=get_user_keyboard(
                bot_username=bot_username,
                bot_channel=bot_channel,
                show_about=bool(bot_about)
            ),
            parse_mode='HTML'
        )
