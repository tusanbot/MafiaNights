"""Canonical private (PV) router for MafiaNights.

Owns top-level PV navigation and explicitly promotes the small set of routes
that otherwise can be shadowed by older handlers registered earlier.
"""
from __future__ import annotations

import logging
from aiogram.dispatcher.handler import CancelHandler
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.exceptions import MessageNotModified

LEGACY_PRIVATE_MODULES = {
    "runtime.private_navigation_authority",
    "runtime.private_start_guard_v2",
    "runtime.private_ui_hotfix",
    "runtime.start_profile_patch",
}


def _fn(item):
    return getattr(item, "handler", None) or getattr(item, "callback", None)


def _remove_legacy(app):
    removed = 0
    for name in ("message_handlers", "callback_query_handlers"):
        collection = getattr(app.dp, name, None)
        handlers = getattr(collection, "handlers", None)
        if handlers is None:
            continue
        kept = []
        for item in list(handlers):
            module = getattr(_fn(item), "__module__", "")
            if module in LEGACY_PRIVATE_MODULES:
                removed += 1
            else:
                kept.append(item)
        handlers[:] = kept
    return removed


def _private(message):
    return bool(message and getattr(message.chat, "type", None) == "private")


def _group_id(app):
    for key in ("ALLOWED_GROUP_ID", "GROUP_ID", "group_chat_id", "group_id"):
        value = getattr(app, key, None)
        if value:
            try:
                return int(value)
            except Exception:
                pass
    return None


async def _allowed(app, callback):
    if not _private(callback.message):
        raise CancelHandler()
    uid = int(callback.from_user.id)
    if uid == int(getattr(app, "moderator_id", 0) or 0):
        return
    cached = set()
    for obj in (app, getattr(app, "addons", None)):
        for key in ("admins", "group_admins"):
            for x in getattr(obj, key, None) or []:
                try:
                    cached.add(int(getattr(getattr(x, "user", None), "id", x)))
                except (TypeError, ValueError):
                    pass
    if uid in cached:
        return
    gid = _group_id(app)
    if gid:
        try:
            admins = await app.bot.get_chat_administrators(gid)
            ids = {int(a.user.id) for a in admins}
            app.admins = ids
            app.group_admins = list(ids)
            if uid in ids:
                return
        except Exception:
            logging.exception("private PV: admin lookup failed")
    await callback.answer("⛔ فقط گرداننده یا مدیر گروه دسترسی دارد.", show_alert=True)
    raise CancelHandler()


def _start_keyboard():
    from runtime.final_private_ui import start_keyboard
    return start_keyboard()


def _scenario_keyboard():
    from runtime.final_private_ui import scenario_keyboard
    return scenario_keyboard()


def _promote(handlers, predicate):
    if handlers is None:
        return 0
    matches = [h for h in list(handlers) if predicate(h)]
    if not matches:
        return 0
    rest = [h for h in list(handlers) if h not in matches]
    handlers[:] = matches + rest
    return len(matches)


def _handler_name(item):
    fn = _fn(item)
    return getattr(fn, "__name__", "")


async def install(app):
    if getattr(app, "_canonical_private_pv_installed", False):
        return False
    removed = _remove_legacy(app)
    dp = app.dp

    async def show_start(message):
        if not _private(message):
            raise CancelHandler()
        await message.answer("🎭 <b>Mafia Nights</b>\n\nیک گزینه را انتخاب کنید:", reply_markup=_start_keyboard(), parse_mode="HTML")
        raise CancelHandler()

    async def start_callback(callback):
        if not _private(callback):
            raise CancelHandler()
        try:
            await callback.message.edit_text("🎭 <b>Mafia Nights</b>\n\nیک گزینه را انتخاب کنید:", reply_markup=_start_keyboard(), parse_mode="HTML")
        except MessageNotModified:
            pass
        await callback.answer()
        raise CancelHandler()

    async def manage_game(callback):
        await _allowed(app, callback)
        from runtime.final_private_ui import management_report, management_keyboard
        try:
            await callback.message.edit_text(management_report(app), reply_markup=management_keyboard(), parse_mode="HTML")
        except MessageNotModified:
            pass
        await callback.answer()
        raise CancelHandler()

    async def manage_game_back(callback):
        await _allowed(app, callback)
        from runtime.final_private_ui import management_report, management_keyboard
        try:
            await callback.message.edit_text(management_report(app), reply_markup=management_keyboard(), parse_mode="HTML")
        except MessageNotModified:
            pass
        await callback.answer("↩️")
        raise CancelHandler()

    async def scenarios(callback):
        await _allowed(app, callback)
        try:
            await callback.message.edit_text("⚙️ <b>مدیریت سناریو</b>\n\nیک گزینه را انتخاب کنید:", reply_markup=_scenario_keyboard(), parse_mode="HTML")
        except MessageNotModified:
            pass
        await callback.answer()
        raise CancelHandler()

    async def addons(callback):
        await _allowed(app, callback)
        from runtime.addons_menu_v2 import AddonsMenuV2
        await AddonsMenuV2(app).menu(callback)
        raise CancelHandler()

    async def addons_back(callback):
        await _allowed(app, callback)
        try:
            await callback.message.edit_text("🎭 <b>Mafia Nights</b>\n\nیک گزینه را انتخاب کنید:", reply_markup=_start_keyboard(), parse_mode="HTML")
        except MessageNotModified:
            pass
        await callback.answer("↩️")
        raise CancelHandler()

    async def profile(callback):
        if not _private(callback):
            raise CancelHandler()
        enhancement = getattr(app, "profile_enhancements", None)
        if enhancement is not None:
            await enhancement.profile(callback)
        else:
            from runtime.user_panel import profile_menu
            await profile_menu(callback)
        raise CancelHandler()

    async def profile_settings(callback):
        if not _private(callback):
            raise CancelHandler()
        enhancement = getattr(app, "profile_enhancements", None)
        if enhancement is None:
            await callback.answer("⚠️ تنظیمات پروفایل در دسترس نیست.", show_alert=True)
            raise CancelHandler()
        await enhancement.settings(callback)
        raise CancelHandler()

    async def help_menu(callback):
        if not _private(callback):
            raise CancelHandler()
        try:
            await callback.message.edit_text(
                "📚 <b>راهنمای Mafia Nights</b>\n\nبرای شروع بازی از گروه استفاده کنید.\nمدیریت بازی و سناریو فقط برای گرداننده یا مدیر گروه در دسترس است.",
                reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton("⬅️ بازگشت", callback_data="final:start")),
                parse_mode="HTML",
            )
        except MessageNotModified:
            pass
        await callback.answer()
        raise CancelHandler()

    dp.register_message_handler(show_start, commands={"start"}, state="*")
    dp.register_callback_query_handler(start_callback, lambda c: c.data in {"final:start", "private:start"}, state="*")
    dp.register_callback_query_handler(manage_game, lambda c: c.data == "manage_game", state="*")
    dp.register_callback_query_handler(manage_game_back, lambda c: c.data == "finalgm:back", state="*")
    dp.register_callback_query_handler(scenarios, lambda c: c.data == "final:scenarios", state="*")
    dp.register_callback_query_handler(addons, lambda c: c.data == "addons_menu", state="*")
    dp.register_callback_query_handler(addons_back, lambda c: c.data == "addons:back", state="*")
    dp.register_callback_query_handler(profile, lambda c: c.data in {"up:menu", "up:profile"}, state="*")
    dp.register_callback_query_handler(profile_settings, lambda c: c.data == "profile:settings", state="*")
    dp.register_callback_query_handler(help_menu, lambda c: c.data == "final:help", state="*")

    cq = getattr(dp.callback_query_handlers, "handlers", None)
    mh = getattr(dp.message_handlers, "handlers", None)
    canonical_names = {"start_callback", "manage_game", "manage_game_back", "scenarios", "addons", "addons_back", "profile", "profile_settings", "help_menu"}
    _promote(cq, lambda h: _handler_name(h) in canonical_names)
    _promote(mh, lambda h: _handler_name(h) == "show_start")

    app._canonical_private_pv_installed = True
    logging.info("CANONICAL PRIVATE PV AUTHORITY ACTIVE removed_legacy_handlers=%s", removed)
    return True
