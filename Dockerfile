FROM python:3.12-slim

WORKDIR /app

# تثبيت أدوات البناء اللازمة لـ pyrogram/TgCrypto
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# تثبيت المتطلبات
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# نسخ الكود
COPY . .

CMD ["python", "main.py"]
