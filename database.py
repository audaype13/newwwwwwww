import logging
from config import DATABASE_URL

_db_logger = logging.getLogger(__name__)

from sqlalchemy import create_engine, Column, BigInteger, String, Boolean, DateTime, Text, Integer
try:
    from sqlalchemy.orm import declarative_base
except ImportError:
    from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime

# إعداد MySQL
_db_logger.info(f"Connecting to DB: {DATABASE_URL.split('@')[1] if '@' in DATABASE_URL else 'custom'}")

engine = create_engine(
    DATABASE_URL,
    echo=False,
    pool_size=10,
    max_overflow=20,
    pool_recycle=3600,
    pool_pre_ping=True,
    connect_args={
        'charset': 'utf8mb4',
        'connect_timeout': 10
    }
)

Base = declarative_base()
Session = sessionmaker(bind=engine)

# --- تعريف الجداول ---
# ملاحظة: create_all يتم استدعاؤه من main.py فقط بعد التحقق من الاتصال

class User(Base):
    __tablename__ = 'users'
    id = Column(BigInteger, primary_key=True)
    user_id = Column(BigInteger, unique=True, nullable=False, index=True)
    username = Column(String(100), nullable=True)
    is_admin = Column(Boolean, default=False)

class Channel(Base):
    __tablename__ = 'channels'
    id = Column(BigInteger, primary_key=True)
    channel_id = Column(BigInteger, unique=True, nullable=False, index=True)
    title = Column(String(255), nullable=False)
    added_by = Column(BigInteger, nullable=True, index=True)
    category = Column(String(100), default="اقتباسات عامة")
    msg_format = Column(String(50), default="normal")
    time_type = Column(String(50), default="default")
    time_value = Column(String(50), nullable=True)
    last_post_at = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True, index=True)
    
    # خصائص الملصق التفاعلي
    sticker_file_id = Column(String(255), nullable=True)
    sticker_interval = Column(Integer, default=0)  # ✅ Integer مستورد الآن
    msg_counter = Column(Integer, default=0)      # ✅ Integer مستورد الآن
    sticker_sender_id = Column(BigInteger, nullable=True)

class BotSettings(Base):
    __tablename__ = 'settings'
    id = Column(BigInteger, primary_key=True)
    key = Column(String(100), unique=True, nullable=False)
    value = Column(Text)

class FileContent(Base):
    __tablename__ = 'files_content'
    id = Column(BigInteger, primary_key=True)
    category = Column(String(100), index=True, nullable=False)
    content = Column(Text, nullable=False)

class PendingQuote(Base):
    __tablename__ = 'pending_quotes'
    id = Column(BigInteger, primary_key=True)
    user_id = Column(BigInteger, nullable=False, index=True)
    username = Column(String(100), nullable=True)
    category = Column(String(100), nullable=False)
    content = Column(Text, nullable=False)
    submitted_at = Column(DateTime, default=datetime.now)
    status = Column(String(20), default='pending')  # pending / approved / rejected

# إنشاء الجداول - يتم استدعاؤه من main.py فقط

# --- Context Manager ---
from contextlib import contextmanager

@contextmanager
def get_db_session():
    session = Session()
    try:
        yield session
        session.commit()
    except Exception as e:
        session.rollback()
        raise e
    finally:
        session.close()

# --- Cache للصلاحيات (TTL: 5 دقائق) ---
import time
_admin_cache: dict = {}  # {user_id: (is_admin, timestamp)}
_ADMIN_CACHE_TTL = 300   # ثواني

def is_admin(user_id: int) -> bool:
    now = time.time()
    if user_id in _admin_cache:
        result, ts = _admin_cache[user_id]
        if now - ts < _ADMIN_CACHE_TTL:
            return result
    with get_db_session() as session:
        user = session.query(User).filter_by(user_id=user_id).first()
        result = user.is_admin if user else False
    _admin_cache[user_id] = (result, now)
    return result

def invalidate_admin_cache(user_id: int = None):
    """امسح الـ cache بعد تغيير صلاحية مستخدم"""
    if user_id:
        _admin_cache.pop(user_id, None)
    else:
        _admin_cache.clear()

def add_channel(ch_id: int, title: str, added_by: int, cat: str, fmt: str, 
                t_type: str = 'default', t_val: str = None) -> bool:
    with get_db_session() as session:
        try:
            existing = session.query(Channel).filter_by(channel_id=ch_id).first()
            if existing:
                return False
            
            new_ch = Channel(
                channel_id=ch_id,
                title=title,
                added_by=added_by,
                category=cat,
                msg_format=fmt,
                time_type=t_type,
                time_value=t_val
            )
            session.add(new_ch)
            return True
        except Exception as e:
            _db_logger.error(f"Error adding channel: {e}")
            return False

def remove_channel_db(ch_id: int) -> bool:
    with get_db_session() as session:
        try:
            ch = session.query(Channel).filter_by(channel_id=ch_id).first()
            if ch:
                session.delete(ch)
                return True
            return False
        except Exception as e:
            _db_logger.error(f"Error removing channel: {e}")
            return False

def add_file_content(category: str, content_list: list) -> int:
    if not content_list:
        return 0
        
    with get_db_session() as session:
        count = 0
        
        if category == 'ابيات شعرية':
            poems = []
            current_poem = []
            
            for line in content_list:
                text = line.strip()
                # فاصل القصيدة: أي سطر يحتوي على شرطات فقط (3 أو أكثر)
                if text and text.replace('-', '') == '' and len(text) >= 3:
                    if current_poem:
                        poems.append("\n".join(current_poem))
                        current_poem = []
                elif text and not text.startswith('الشاعر:'):
                    current_poem.append(text)
            
            # لا ننسى آخر قصيدة
            if current_poem:
                poems.append("\n".join(current_poem))
            
            for poem in poems:
                if poem.strip():
                    session.add(FileContent(category=category, content=poem))
                    count += 1
        else:
            for text in content_list:
                if text.strip():
                    session.add(FileContent(category=category, content=text.strip()))
                    count += 1
        
        return count

def get_next_content(category: str) -> str:
    with get_db_session() as session:
        from sqlalchemy import func
        # func.rand() لـ MySQL، func.random() لـ SQLite/PostgreSQL
        dialect = engine.dialect.name
        rand_func = func.rand() if dialect == 'mysql' else func.random()
        content = session.query(FileContent).filter_by(category=category).order_by(rand_func).first()
        return content.content if content else None

def get_stats() -> str:
    with get_db_session() as session:
        users_count = session.query(User).count()
        channels_count = session.query(Channel).count()
        posts_count = session.query(FileContent).count()
        
        return (
            f"📊 <b>إحصائيات البوت</b>\n"
            f"┌ 👥 المستخدمون: <b>{users_count}</b>\n"
            f"├ 📢 القنوات: <b>{channels_count}</b>\n"
            f"└ 📝 الاقتباسات المخزنة: <b>{posts_count}</b>"
        )

def init_admin(user_id: int, username: str = None):
    with get_db_session() as session:
        existing = session.query(User).filter_by(user_id=user_id).first()
        if not existing:
            admin = User(user_id=user_id, username=username, is_admin=True)
            session.add(admin)
            _db_logger.info(f"Admin initialized: {user_id}")

def get_all_channels():
    with get_db_session() as session:
        channels = session.query(Channel).filter_by(is_active=True).all()
        return [{'id': c.id, 'channel_id': c.channel_id, 'title': c.title} for c in channels]

def update_channel_last_post(channel_id: int):
    with get_db_session() as session:
        ch = session.query(Channel).filter_by(channel_id=channel_id).first()
        if ch:
            ch.last_post_at = datetime.now()

def get_setting(key: str) -> str:
    with get_db_session() as session:
        s = session.query(BotSettings).filter_by(key=key).first()
        return s.value if s else None

def set_setting(key: str, value: str):
    with get_db_session() as session:
        s = session.query(BotSettings).filter_by(key=key).first()
        if s:
            s.value = value
        else:
            session.add(BotSettings(key=key, value=value))

def get_all_settings() -> list:
    with get_db_session() as session:
        return [(s.key, s.value) for s in session.query(BotSettings).all()]

def get_content_count_by_category() -> list:
    with get_db_session() as session:
        from sqlalchemy import func
        return session.query(FileContent.category, func.count(FileContent.id)).group_by(FileContent.category).all()

def delete_content_by_category(category: str) -> int:
    with get_db_session() as session:
        count = session.query(FileContent).filter_by(category=category).count()
        session.query(FileContent).filter_by(category=category).delete()
        return count

def get_bot_info() -> dict:
    """جلب إعدادات البوت الأساسية دفعة واحدة"""
    with get_db_session() as session:
        keys = ['bot_channel', 'bot_about', 'force_sub_channel', 'welcome_message']
        result = {}
        for s in session.query(BotSettings).filter(BotSettings.key.in_(keys)).all():
            result[s.key] = s.value
        return result

def get_user_daily_quotes_count(user_id: int) -> int:
    with get_db_session() as session:
        today = datetime.now().date()
        return session.query(PendingQuote).filter(
            PendingQuote.user_id == user_id,
            PendingQuote.submitted_at >= datetime(today.year, today.month, today.day)
        ).count()

def add_pending_quote(user_id: int, username: str, category: str, content: str) -> int:
    with get_db_session() as session:
        q = PendingQuote(user_id=user_id, username=username, category=category, content=content)
        session.add(q)
        session.flush()
        return q.id

def approve_pending_quote(quote_id: int) -> bool:
    with get_db_session() as session:
        q = session.query(PendingQuote).filter_by(id=quote_id).first()
        if not q or q.status != 'pending':
            return False
        q.status = 'approved'
        session.add(FileContent(category=q.category, content=q.content))
        return True

def reject_pending_quote(quote_id: int) -> bool:
    with get_db_session() as session:
        q = session.query(PendingQuote).filter_by(id=quote_id).first()
        if not q or q.status != 'pending':
            return False
        q.status = 'rejected'
        return True

def toggle_channel_posting(channel_db_id: int) -> bool:
    """تبديل حالة النشر لقناة معينة، يرجع الحالة الجديدة"""
    with get_db_session() as session:
        ch = session.query(Channel).filter_by(id=channel_db_id).first()
        if ch:
            ch.is_active = not ch.is_active
            return ch.is_active
        return None

def export_backup() -> dict:
    """تصدير كل البيانات كـ dict"""
    with get_db_session() as session:
        users = [{'user_id': u.user_id, 'username': u.username, 'is_admin': u.is_admin}
                 for u in session.query(User).all()]
        channels = [{'channel_id': c.channel_id, 'title': c.title, 'added_by': c.added_by,
                     'category': c.category, 'msg_format': c.msg_format, 'time_type': c.time_type,
                     'time_value': c.time_value, 'is_active': c.is_active,
                     'sticker_file_id': c.sticker_file_id, 'sticker_interval': c.sticker_interval,
                     'sticker_sender_id': c.sticker_sender_id}
                    for c in session.query(Channel).all()]
        content = [{'category': f.category, 'content': f.content}
                   for f in session.query(FileContent).all()]
        settings = [{'key': s.key, 'value': s.value}
                    for s in session.query(BotSettings).all()]
        return {
            'version': 1,
            'exported_at': datetime.now().isoformat(),
            'users': users,
            'channels': channels,
            'content': content,
            'settings': settings
        }

def import_backup(data: dict) -> dict:
    """استيراد نسخة احتياطية، يرجع إحصائيات ما تم استيراده"""
    stats = {'users': 0, 'channels': 0, 'content': 0, 'settings': 0, 'skipped': 0}
    with get_db_session() as session:
        for u in data.get('users', []):
            if not session.query(User).filter_by(user_id=u['user_id']).first():
                session.add(User(user_id=u['user_id'], username=u.get('username'), is_admin=u.get('is_admin', False)))
                stats['users'] += 1
            else:
                stats['skipped'] += 1

        for c in data.get('channels', []):
            if not session.query(Channel).filter_by(channel_id=c['channel_id']).first():
                session.add(Channel(
                    channel_id=c['channel_id'], title=c['title'], added_by=c.get('added_by'),
                    category=c.get('category', 'اقتباسات عامة'), msg_format=c.get('msg_format', 'normal'),
                    time_type=c.get('time_type', 'default'), time_value=c.get('time_value'),
                    is_active=c.get('is_active', True), sticker_file_id=c.get('sticker_file_id'),
                    sticker_interval=c.get('sticker_interval', 0), sticker_sender_id=c.get('sticker_sender_id')
                ))
                stats['channels'] += 1
            else:
                stats['skipped'] += 1

        for f in data.get('content', []):
            session.add(FileContent(category=f['category'], content=f['content']))
            stats['content'] += 1

        for s in data.get('settings', []):
            existing = session.query(BotSettings).filter_by(key=s['key']).first()
            if existing:
                existing.value = s['value']
            else:
                session.add(BotSettings(key=s['key'], value=s['value']))
            stats['settings'] += 1

    return stats
