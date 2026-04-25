import os
import sys
from dotenv import load_dotenv

# تحميل المتغيرات من .env أولاً
load_dotenv()

# === Telegram Bot ===
TOKEN = os.getenv('TOKEN')
DEVELOPER_ID = int(os.getenv('DEVELOPER_ID', '0'))

# === Pyrogram (اختياري) ===
API_ID = int(os.getenv('API_ID', '0')) if os.getenv('API_ID') else None
API_HASH = os.getenv('API_HASH')

# === Database Configuration ===
DATABASE_URL = os.getenv('DATABASE_URL')

if DATABASE_URL and DATABASE_URL.startswith('mysql://'):
    DATABASE_URL = DATABASE_URL.replace('mysql://', 'mysql+pymysql://', 1)

if not DATABASE_URL:
    DB_USER = os.getenv('DB_USER', 'root')
    DB_PASSWORD = os.getenv('DB_PASSWORD', '')
    DB_HOST = os.getenv('DB_HOST', 'localhost')
    DB_PORT = os.getenv('DB_PORT', '3306')
    DB_NAME = os.getenv('DB_NAME', 'telegram_bot')
    
    if DB_PASSWORD:
        DATABASE_URL = f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

# === Validation ===
def validate_config():
    errors = []
    
    if not TOKEN:
        errors.append("❌ TOKEN غير موجود في .env!")
    if not DEVELOPER_ID:
        errors.append("❌ DEVELOPER_ID غير موجود في .env!")
    if not DATABASE_URL:
        errors.append("❌ قاعدة البيانات غير مكونة في .env!")
    
    if errors:
        print("\n".join(errors), file=sys.stderr)
        sys.exit(1)
    
    db_type = 'Railway' if DATABASE_URL and 'railway' in DATABASE_URL else 'Custom MySQL'
    print(f"✅ Config loaded | DB: {db_type}")
