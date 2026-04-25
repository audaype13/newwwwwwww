from telegram import InlineKeyboardButton, InlineKeyboardMarkup

# الفئات المتاحة - مصدر واحد للحقيقة
CATEGORIES = [
    ("❤️ حب", "حب"),
    ("🕌 أذكار وآيات", "أذكار وآيات"),
    ("💭 اقتباسات عامة", "اقتباسات عامة"),
    ("📜 أبيات شعرية", "ابيات شعرية"),
]

# اختصارات الألوان
P = "primary"   # أزرق
S = "success"   # أخضر
D = "danger"    # أحمر

def get_dev_keyboard():
    keyboard = [
        [InlineKeyboardButton("➕ إضافة قناة نشر", callback_data="add_channel_prompt", style=P)],
        [
            InlineKeyboardButton("🔧 إدارة القنوات", callback_data="manage_channels", style=P),
            InlineKeyboardButton("📂 إدارة الملفات", callback_data="manage_files", style=P),
        ],
        [
            InlineKeyboardButton("👥 إدارة المشرفين", callback_data="manage_admins", style=P),
            InlineKeyboardButton("⚙️ إعدادات البوت", callback_data="bot_settings", style=P),
        ],
        [InlineKeyboardButton("💾 نسخة احتياطية", callback_data="backup_menu", style=P)],
        [
            InlineKeyboardButton("🚀 نشر الآن", callback_data="post_now", style=S),
            InlineKeyboardButton("🔊 إذاعة", callback_data="broadcast_menu", style=P),
        ],
        [
            InlineKeyboardButton("📊 الإحصائيات", callback_data="show_stats", style=P),
            InlineKeyboardButton("تفعيل/إيقاف البوت", callback_data="toggle_bot", style=D),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)

def get_admin_keyboard():
    keyboard = [
        [InlineKeyboardButton("➕ إضافة قناة نشر", callback_data="add_channel_prompt", style=P)],
        [
            InlineKeyboardButton("🔧 إدارة القنوات", callback_data="manage_channels", style=P),
            InlineKeyboardButton("📂 إدارة الملفات", callback_data="manage_files", style=P),
        ],
        [
            InlineKeyboardButton("🚀 نشر الآن", callback_data="post_now", style=S),
            InlineKeyboardButton("🔊 إذاعة", callback_data="broadcast_menu", style=P),
        ],
        [InlineKeyboardButton("📊 الإحصائيات", callback_data="show_stats", style=P)],
    ]
    return InlineKeyboardMarkup(keyboard)

def get_user_keyboard(bot_username: str = None, bot_channel: str = None, show_about: bool = True):
    keyboard = [
        [InlineKeyboardButton("➕ إضافة قناة/مجموعة", callback_data="add_channel_prompt", style=P)],
        [InlineKeyboardButton("🔧 إدارة القنوات", callback_data="manage_channels", style=P)],
        [
            InlineKeyboardButton("📊 الإحصائيات", callback_data="show_stats", style=P),
            InlineKeyboardButton("✍️ اقترح اقتباس", callback_data="suggest_quote", style=S),
        ],
    ]
    # صف الروابط الخارجية
    extra = []
    if show_about:
        extra.append(InlineKeyboardButton("ℹ️ عنا", callback_data="about_us"))
    if bot_username:
        share_url = f"https://t.me/share/url?url=https://t.me/{bot_username}"
        extra.append(InlineKeyboardButton("🔗 شارك البوت", url=share_url))
    if extra:
        keyboard.append(extra)
    if bot_channel:
        ch = bot_channel.lstrip('@')
        keyboard.append([InlineKeyboardButton("📢 قناة البوت", url=f"https://t.me/{ch}", style=P)])
    return InlineKeyboardMarkup(keyboard)

def get_back_keyboard(role):
    keyboard = [[InlineKeyboardButton("🔙 رجوع", callback_data=f"back_{role}")]]
    return InlineKeyboardMarkup(keyboard)

def get_categories_keyboard():
    keyboard = [
        [InlineKeyboardButton(label, callback_data=f"cat_{value}", style=P)]
        for label, value in CATEGORIES
    ]
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="back_home")])
    return InlineKeyboardMarkup(keyboard)

def get_format_keyboard():
    keyboard = [
        [InlineKeyboardButton("📝 رسالة عادية", callback_data="fmt_normal", style=P)],
        [InlineKeyboardButton("💎 رسالة بشكل اقتباس", callback_data="fmt_blockquote", style=P)],
        [InlineKeyboardButton("🔙 رجوع", callback_data="back_home")],
    ]
    return InlineKeyboardMarkup(keyboard)

def get_time_keyboard():
    keyboard = [
        [InlineKeyboardButton("⏰ ساعات محددة", callback_data="time_fixed", style=P)],
        [InlineKeyboardButton("⏳ فارق زمني (دقائق)", callback_data="time_interval", style=P)],
        [InlineKeyboardButton("🚫 افتراضي (عشوائي/فوري)", callback_data="time_default", style=P)],
        [InlineKeyboardButton("🔙 رجوع", callback_data="back_home")],
    ]
    return InlineKeyboardMarkup(keyboard)

def get_files_keyboard():
    keyboard = [
        [InlineKeyboardButton(label, callback_data=f"upload_{value}", style=P)]
        for label, value in CATEGORIES
    ]
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="back_admin")])
    return InlineKeyboardMarkup(keyboard)

def get_categories_keyboard_edit(context):
    ch_id = context.user_data.get('editing_channel_id')
    keyboard = [
        [InlineKeyboardButton(label, callback_data=f"set_edit_cat_{value}", style=P)]
        for label, value in CATEGORIES
    ]
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data=f"edit_channel_{ch_id}")])
    return InlineKeyboardMarkup(keyboard)

def get_format_keyboard_edit(context):
    ch_id = context.user_data.get('editing_channel_id')
    keyboard = [
        [InlineKeyboardButton("📝 رسالة عادية", callback_data="set_edit_fmt_normal", style=P)],
        [InlineKeyboardButton("💎 رسالة بشكل اقتباس", callback_data="set_edit_fmt_blockquote", style=P)],
        [InlineKeyboardButton("🔙 رجوع", callback_data=f"edit_channel_{ch_id}")],
    ]
    return InlineKeyboardMarkup(keyboard)

def get_channel_options_keyboard(ch_id: int, is_active: bool):
    toggle_text = "⏸️ إيقاف النشر" if is_active else "▶️ تشغيل النشر"
    toggle_style = D if is_active else S
    keyboard = [
        [InlineKeyboardButton("🔄 تغيير نوع المحتوى", callback_data="change_cat_select", style=P)],
        [InlineKeyboardButton("🎨 تغيير شكل الرسالة", callback_data="change_fmt_select", style=P)],
        [InlineKeyboardButton("⏰ تغيير الوقت", callback_data="edit_channel_time", style=P)],
        [InlineKeyboardButton("⭐ تعيين ملصق تفاعلي", callback_data="set_sticker_flow", style=P)],
        [
            InlineKeyboardButton("👁️ معاينة اقتباس", callback_data=f"preview_ch_{ch_id}", style=P),
            InlineKeyboardButton("🚀 نشر الآن", callback_data=f"post_ch_{ch_id}", style=S),
        ],
        [InlineKeyboardButton("✏️ إضافة اقتباس يدوي", callback_data=f"add_quote_{ch_id}", style=P)],
        [InlineKeyboardButton(toggle_text, callback_data=f"toggle_channel_{ch_id}", style=toggle_style)],
        [InlineKeyboardButton("🗑️ حذف القناة", callback_data="confirm_del_channel", style=D)],
        [InlineKeyboardButton("🔙 رجوع", callback_data="manage_channels")],
    ]
    return InlineKeyboardMarkup(keyboard)
