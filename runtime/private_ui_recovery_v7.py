"""Final canonical fixes for private profile, scenario navigation, and /start."""
from __future__ import annotations

import logging

from aiogram.dispatcher.handler import CancelHandler
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.exceptions import MessageNotModified


def _private(callback):
    message = getattr(callback, "message", None)
    return bool(message and getattr(message.chat, "type", None) == "private")


def _fn(item):
    return getattr(item, "handler", None) or getattr(item, "callback", None)


def _promote(handlers, predicate):
    if handlers is None:
        return 0
    matches = [h for h in list(handlers) if predicate(h)]
    if not matches:
        return 0
    handlers[:] = matches + [h for h in list(handlers) if h not in matches]
    return len(matches)


async def install(app):
    dp = app.dp
    handlers = getattr(getattr(dp, "callback_query_handlers", None), "handlers", None)
    if handlers is None or getattr(app, "_private_ui_recovery_v7", False):
        return False

    try:
        from runtime import final_private_ui

        def canonical_start_keyboard():
            kb = InlineKeyboardMarkup(row_width=1)
            kb.add(InlineKeyboardButton("🛠 مدیریت بازی", callback_data="manage_game"))
            kb.add(InlineKeyboardButton("⚙️ مدیریت سناریو", callback_data="final:scenarios"))
            kb.add(InlineKeyboardButton("⚙️ امکانات اضافه", callback_data="addons_menu"))
            kb.add(InlineKeyboardButton("👤 پروفایل", callback_data="up:profile"))
            kb.add(InlineKeyboardButton("📚 راهنما", callback_data="final:help"))
            return kb

        final_private_ui.start_keyboard = canonical_start_keyboard
    except Exception:
        logging.exception("private v7: failed to patch canonical start keyboard")

    async def canonical_start(message, state):
        """Last-resort /start owner for every FSM state and both chat types."""
        try:
            await state.finish()
        except Exception:
            logging.exception("private v7 /start: failed to clear FSM state")

        if getattr(message.chat, "type", None) == "private":
            from runtime.final_private_ui import start_keyboard
            await message.answer("🎭 <b>Mafia Nights</b>\n\nیک گزینه را انتخاب کنید:", reply_markup=start_keyboard(), parse_mode="HTML")
        elif getattr(message.chat, "type", None) in {"group", "supergroup"}:
            try:
                from main1 import main_menu_keyboard
                await message.reply("🏠 منوی اصلی گروه:", reply_markup=main_menu_keyboard())
            except Exception:
                logging.exception("private v7 /start: group menu failed")
                await message.reply("🏠 منوی اصلی گروه در دسترس نیست.")
        else:
            raise CancelHandler()
        logging.info("PRIVATE UI V7 /START handled chat_type=%s user_id=%s", message.chat.type, message.from_user.id)
        raise CancelHandler()

    async def home(callback):
        if not _private(callback):
            raise CancelHandler()
        try:
            from runtime.final_private_ui import start_keyboard
            await callback.message.edit_text("🎭 <b>Mafia Nights</b>\n\nیک گزینه را انتخاب کنید:", reply_markup=start_keyboard(), parse_mode="HTML")
        except MessageNotModified:
            pass
        await callback.answer()
        raise CancelHandler()

    async def profile(callback):
        if not _private(callback):
            raise CancelHandler()
        enhancement = getattr(app, "profile_enhancements", None)
        if enhancement is None:
            await callback.answer("❌ پروفایل در دسترس نیست.", show_alert=True)
            raise CancelHandler()
        try:
            await enhancement.profile(callback)
        except Exception:
            logging.exception("private v7 profile failed")
            await callback.answer("❌ نمایش پروفایل انجام نشد.", show_alert=True)
        raise CancelHandler()

    async def profile_settings(callback):
        if not _private(callback):
            raise CancelHandler()
        enhancement = getattr(app, "profile_enhancements", None)
        if enhancement is None:
            await callback.answer("❌ تنظیمات پروفایل در دسترس نیست.", show_alert=True)
            raise CancelHandler()
        try:
            await enhancement.settings(callback)
        except Exception:
            logging.exception("private v7 profile settings failed")
            await callback.answer("❌ تنظیمات پروفایل در دسترس نیست.", show_alert=True)
        raise CancelHandler()

    async def scenario_manager(callback):
        if not _private(callback):
            raise CancelHandler()
        manager = getattr(app, "_private_scenario_manager", None)
        if manager is None:
            await callback.answer("❌ مدیریت سناریو در دسترس نیست.", show_alert=True)
            raise CancelHandler()
        try:
            await manager.menu(callback)
        except Exception:
            logging.exception("private v7 scenario manager failed")
            await callback.answer("❌ بازگشت به مدیریت سناریو انجام نشد.", show_alert=True)
        raise CancelHandler()

    async def profile_advanced(callback):
        if not _private(callback):
            raise CancelHandler()
        enhancement = getattr(app, "profile_enhancements", None)
        advanced = getattr(enhancement, "advanced_profile", None) if enhancement else None
        if advanced is None:
            await callback.answer("❌ آمار و امتیازات در دسترس نیست.", show_alert=True)
            raise CancelHandler()
        try:
            parts = callback.data.split(":")
            method_name = "advanced" if len(parts) == 2 else parts[2]
            method = getattr(advanced, method_name, None)
            if method is None:
                await callback.answer("❌ این بخش آمار در دسترس نیست.", show_alert=True)
            else:
                await method(callback)
        except Exception:
            logging.exception("private v7 advanced profile failed: %s", callback.data)
            await callback.answer("❌ نمایش آمار انجام نشد.", show_alert=True)
        raise CancelHandler()

    async def profile_gender(callback):
        if not _private(callback):
            raise CancelHandler()
        enhancement = getattr(app, "profile_enhancements", None)
        method = getattr(enhancement, "gender_menu", None) if enhancement else None
        if method is None:
            await callback.answer("❌ انتخاب جنسیت در دسترس نیست.", show_alert=True)
            raise CancelHandler()
        try:
            await method(callback)
        except Exception:
            logging.exception("private v7 gender menu failed")
            await callback.answer("❌ انتخاب جنسیت انجام نشد.", show_alert=True)
        raise CancelHandler()

    async def gender_set(callback):
        if not _private(callback):
            raise CancelHandler()
        enhancement = getattr(app, "profile_enhancements", None)
        method = getattr(enhancement, "set_gender", None) if enhancement else None
        if method is None:
            await callback.answer("❌ تغییر جنسیت در دسترس نیست.", show_alert=True)
            raise CancelHandler()
        try:
            await method(callback)
        except Exception:
            logging.exception("private v7 gender save failed")
            await callback.answer("❌ ذخیره جنسیت انجام نشد.", show_alert=True)
        raise CancelHandler()

    # V7 is loaded last in production, so it also owns /start ordering. This
    # prevents a persisted ScenarioForm.roles state from consuming /start.
    dp.register_message_handler(canonical_start, commands={"start"}, state="*")
    mh = getattr(dp.message_handlers, "handlers", None)
    promoted_start = _promote(mh, lambda h: getattr(_fn(h), "__name__", "") == "canonical_start")

    routes = [
        (home, lambda c: c.data in {"final:start", "private:start", "fp:panel", "up:menu"}),
        (profile, lambda c: c.data == "up:profile"),
        (profile_settings, lambda c: c.data == "profile:settings"),
        (scenario_manager, lambda c: c.data == "sm2:menu"),
        (profile_advanced, lambda c: c.data == "profile:advanced" or c.data.startswith("profile:advanced:")),
        (profile_gender, lambda c: c.data == "profile:gender"),
        (gender_set, lambda c: c.data in {"profile:gender:female", "profile:gender:male"}),
    ]
    for fn, filt in routes:
        dp.register_callback_query_handler(fn, filt, state="*")

    owned = {fn for fn, _ in routes}
    current = list(handlers)
    matches = [h for h in current if getattr(h, "handler", None) in owned]
    handlers[:] = matches + [h for h in current if h not in matches]

    app._private_ui_recovery_v7 = True
    logging.info("PRIVATE UI RECOVERY V7 ACTIVE start_promoted=%s", promoted_start)
    return True
