# استفاده از تصویر سبک Python 3.11
FROM python:3.11-slim

# تنظیم مسیر کاری داخل کانتینر
WORKDIR /Mafia

# کپی فایل requirements برای نصب پکیج‌ها
COPY requirements.txt .

# نصب پکیج‌ها روی Python اصلی و رفع وابستگی‌های احتمالی
RUN apt-get update && apt-get install -y gcc libffi-dev \
    && pip install --upgrade pip \
    && pip install -r requirements.txt \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# کپی کل پروژه
COPY . .

# بررسی نصب aiogram (اختیاری، برای debug)
RUN pip show aiogram

# اجرای ربات
CMD ["python", "main.py"]

