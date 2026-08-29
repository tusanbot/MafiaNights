import logging
from aiogram import types, Bot, Dispatcher
from aiogram.utils.exceptions import ChatAdminRequired
from aiogram.types import Message # برای Type Hinting

# متغیر سراسری برای نگه‌داشتن نمونه NicknameManager از main.py
NICKNAMES_MANAGER = None 

def set_global_nick_manager(manager):
    """
    برای تنظیم نمونه NicknameManager که در main.py ساخته شده، استفاده می‌شود.
    """
    global NICKNAMES_MANAGER
    NICKNAMES_MANAGER = manager
    logging.info("✅ نمونه NicknameManager به صورت سراسری در patch تنظیم شد.")


async def is_group_admin(chat_id: int, user_id: int, bot: Bot) -> bool:
    """بررسی می‌کند آیا کاربر مدیر گروه است یا خالق آن."""
    # اگر در چت خصوصی است، همه مجاز هستند (یا باید چک گروه اصلی اعمال شود)
    if chat_id > 0:
        return True # فرض می‌کنیم اگر در پیوی باشد، مجاز است (می‌توانید اینجا را تغییر دهید)
    
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        # اگر status یکی از 'creator' یا 'administrator' باشد
        if member.status in ["creator", "administrator"]:
            return True
        return False
    except ChatAdminRequired:
        logging.error(f"❌ ربات در گروه {chat_id} دسترسی ادمینی لازم را ندارد.")
        return False
    except Exception:
        return False


# ==========================================
# توابع هندلرهای ربات برای مدیریت مستعار
# ==========================================

def register_nickname_handlers(dp: Dispatcher, bot: Bot):
    """
    این تابع باید از main.py فراخوانی شود:
    register_nickname_handlers(dp, bot)
    """
    global NICKNAMES_MANAGER
    if not NICKNAMES_MANAGER:
        logging.error("❌ نمونه NICKNAMES_MANAGER تنظیم نشده است. هندلرها غیرفعال می‌شوند.")
        return
        
    nick = NICKNAMES_MANAGER # نام کوتاه‌تر برای استفاده در هندلرها

    # -------------------------
    # ست‌کردن نام مستعار (فقط ادمین)
    # -------------------------
    @dp.message_handler(lambda m: m.chat.type in ["group", "supergroup"] and m.reply_to_message and m.text and m.text.startswith("تنظیم مستعار "))
    async def set_nick_command(message: types.Message):
        # بررسی دسترسی ادمین
        if not await is_group_admin(message.chat.id, message.from_user.id, bot):
            await message.reply("⛔ فقط مدیران گروه می‌توانند نام مستعار تعیین کنند.", reply_to_message_id=message.message_id)
            return

        target = message.reply_to_message.from_user
        nickname = message.text.replace("تنظیم مستعار ", "", 1).strip()
        
        if not nickname:
            await message.reply("لطفا نام مستعار را بعد از دستور وارد کنید.", reply_to_message_id=message.message_id)
            return
            
        # استفاده از متد set جدید
        nick.set(target.id, nickname)
        await message.reply(f"✅ نام مستعار برای {target.full_name} تنظیم شد: **{nickname}**", parse_mode="Markdown")

    # -------------------------
    # حذف نام مستعار (فقط ادمین)
    # -------------------------
    @dp.message_handler(lambda m: m.chat.type in ["group", "supergroup"] and m.reply_to_message and m.text.strip() == "حذف مستعار")
    async def delete_nick_command(message: types.Message):
        # بررسی دسترسی ادمین
        if not await is_group_admin(message.chat.id, message.from_user.id, bot):
            await message.reply("⛔ فقط مدیران گروه می‌توانند نام مستعار حذف کنند.", reply_to_message_id=message.message_id)
            return

        target = message.reply_to_message.from_user
        
        if nick.delete(target.id): # فراخوانی متد delete
            await message.reply(f"🗑️ نام مستعار کاربر {target.full_name} با موفقیت حذف شد.")
        else:
            await message.reply("ℹ️ این کاربر قبلاً نام مستعاری ثبت نکرده بود.")
            
    # -------------------------
    # دریافت نام مستعار (برای تست)
    # -------------------------
    @dp.message_handler(lambda m: m.reply_to_message and m.text.strip() == "نام مستعار")
    async def get_nick_command(message: types.Message):
        target = message.reply_to_message.from_user
        nickname = nick.get(target.id) # استفاده از متد get جدید

        if nickname:
            await message.reply(f"📛 نام مستعار این کاربر: **{nickname}**", parse_mode="Markdown")
        else:
            await message.reply("ℹ️ این کاربر نام مستعار ندارد.")

    # -------------------------
    # لیست مستعارها (فقط ادمین)
    # -------------------------
    @dp.message_handler(lambda m: m.chat.type in ["group", "supergroup"] and m.text.strip() == "لیست مستعار")
    async def list_nick_command(message: types.Message):
        # بررسی دسترسی ادمین
        if not await is_group_admin(message.chat.id, message.from_user.id, bot):
            await message.reply("⛔ فقط مدیران گروه می‌توانند لیست مستعار را مشاهده کنند.")
            return

        data = nick.all()
        if not data:
            await message.reply("📛 هیچ نام مستعاری ثبت نشده.")
            return

        text = "📛 <b>لیست نام‌های مستعار:</b>\n\n"
        # استفاده از متد all جدید
        for uid, name in sorted(data.items(), key=lambda x: str(x[1] or '').lower()):
            text += f" - {name}  <code>{uid}</code>\n"

        await message.reply(text, parse_mode="HTML")


# ==========================================
# تابع کمکی برای کل پروژه (مثلاً main.py)
# ==========================================
def display_name(user_id: int, fallback: str):
    """در کل پروژه فقط از این استفاده می‌کنیم"""
    global NICKNAMES_MANAGER
    if NICKNAMES_MANAGER:
        # استفاده از متد get_nick یا get جدید
        return NICKNAMES_MANAGER.get(user_id) or fallback
    return fallback
