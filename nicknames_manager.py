import os
import logging
from sqlalchemy import create_engine, Column, BigInteger, String
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base

logging.basicConfig(level=logging.INFO) 

# ------------------------------------------------
# ۱. کلاس جایگزین (Dummy) - در صورت شکست دیتابیس
# ------------------------------------------------
class DummyNicknameManager:
    """کلاس جایگزین در صورت شکست اتصال به دیتابیس"""
    def __init__(self):
        logging.critical("❌ استفاده از حالت Dummy: نام مستعار ذخیره نخواهد شد.")
        
    def set(self, user_id, nickname):
        pass
        
    def set_nick(self, user_id, nickname): # اضافه شده برای سازگاری
        pass

    def get(self, user_id):
        return None
        
    def get_nick(self, user_id): # اضافه شده برای سازگاری
        return None

    def delete(self, user_id): # اضافه شده
        logging.warning("⚠️ دیتابیس فعال نیست. حذف نام مستعار انجام نشد.")
        return False
        
    def all(self):
        return {}

# ------------------------------------------------
# ۲. کلاس اصلی (واقعی) - برای کار با دیتابیس
# ------------------------------------------------
# تعریف کلاس واقعی (NicknameManager) قبل از استفاده
class NicknameManager:
    def __init__(self):
        global db_initialization_success
        self.db_ready = False

        if db_initialization_success:
            try:
                Base.metadata.create_all(bind=engine)
                self.db_ready = True
                logging.info("✅ اتصال به PostgreSQL و ایجاد جدول Nicknames موفقیت‌آمیز بود.")
            except Exception as e:
                logging.critical(f"❌ خطای حیاتی در اتصال دیتابیس (Create Tables): {e}")
                logging.critical("ربات بدون قابلیت ذخیره نام مستعار اجرا خواهد شد.")
        else:
            logging.warning("⚠️ دیتابیس فعال نیست. ذخیره نام مستعار غیرفعال است.")


    def _get_session(self):
        """تلاش برای ایجاد یک سشن دیتابیس"""
        if not self.db_ready:
            return None
        try:
            return SessionLocal()
        except Exception as e:
            logging.error(f"❌ خطای ایجاد سشن دیتابیس: {e}")
            return None

    def set(self, user_id, nickname):
        return self.set_nick(user_id, nickname)

    def set_nick(self, user_id, nickname): # متد اصلی ذخیره
        if not self.db_ready: return
        session = self._get_session()
        if not session: return

        try:
            record = session.query(Nickname).filter(Nickname.user_id == user_id).first()
            
            if record:
                record.nickname = nickname
            else:
                new_record = Nickname(user_id=user_id, nickname=nickname)
                session.add(new_record)
                
            session.commit()
            logging.info(f"✅ نام مستعار کاربر {user_id} ذخیره/به‌روزرسانی شد.")
            
        except Exception as e:
            session.rollback()
            logging.error(f"❌ خطای ذخیره‌سازی نام مستعار: {e}")
        finally:
            session.close()

    def get(self, user_id):
        return self.get_nick(user_id)

    def get_nick(self, user_id): # متد اصلی دریافت
        if not self.db_ready: return None
        session = self._get_session()
        if not session: return None
        
        try:
            record = session.query(Nickname).filter(Nickname.user_id == user_id).first()
            return record.nickname if record else None
        except Exception:
            return None
        finally:
            session.close()

    def delete(self, user_id): # متد جدید حذف
        if not self.db_ready: return False
        session = self._get_session()
        if not session: return False

        try:
            # حذف رکورد بر اساس user_id
            deleted_rows = session.query(Nickname).filter(Nickname.user_id == user_id).delete()
            session.commit()
            
            if deleted_rows > 0:
                logging.info(f"✅ نام مستعار کاربر {user_id} حذف شد.")
                return True
            return False

        except Exception as e:
            session.rollback()
            logging.error(f"❌ خطای حذف نام مستعار: {e}")
            return False
        finally:
            session.close()
            
    def all(self):
        if not self.db_ready: return {}
        session = self._get_session()
        if not session: return {}
        
        try:
            records = session.query(Nickname).all()
            return {r.user_id: r.nickname for r in records}
        except Exception:
            return {}
        finally:
            session.close()

# ------------------------------------------------
# ۳. تنظیمات دیتابیس (پس از تعریف کلاس‌ها)
# ------------------------------------------------
DATABASE_URL = os.getenv("DATABASE_URL")
db_initialization_success = False

class DummyBase:
    metadata = None
class DummyEngine:
    pass
class DummySessionLocal:
    def __init__(self, *args, **kwargs):
        pass
    def __call__(self, *args, **kwargs):
        return None

Base = DummyBase
engine = DummyEngine()
SessionLocal = DummySessionLocal()

if DATABASE_URL: 
    try:
        if DATABASE_URL.startswith("postgres://"):
            DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql+psycopg2://", 1)

        engine = create_engine(DATABASE_URL)
        Base = declarative_base()
        SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        db_initialization_success = True
    except Exception as e:
        logging.critical(f"❌ خطای حیاتی در پیکربندی دیتابیس (Environment/URL): {e}")
else:
    logging.error("❌ متغیر محیطی DATABASE_URL تنظیم نشده است!")


# ------------------------------------------------
# ۴. مدل دیتابیس
# ------------------------------------------------
class Nickname(Base):
    __tablename__ = "nicknames"
    user_id = Column(BigInteger, primary_key=True, index=True)
    nickname = Column(String, index=True)


# ------------------------------------------------
# ۵. تعیین کلاس نهایی برای ایمپورت
# ------------------------------------------------
if db_initialization_success:
    FinalNicknameManager = NicknameManager
else:
    FinalNicknameManager = DummyNicknameManager
