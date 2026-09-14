"""Final PV route-priority pass.

The project has accumulated several generations of private UI handlers. This
module is intentionally small: it does not implement features, it only makes
the canonical routes win handler dispatch and makes back/profile navigation
safe.
"""
from __future__ import annotations

import logging
from aiogram.dispatcher.handler import CancelHandler
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.exceptions import MessageNotModified


def _handler(item):
    return getattr(item, "handler", None) or getattr(item, "callback", None)


def _name(item):
    return getattr(_handler(item), "__name__", "")


def _promote(handlers, predicate):
    if handlers is None:
        return
    current = list(handlers)
    matches = [h for h in current if predicate(h)]
    if matches:
        handlers[:] = matches + [h for h in current if h not in matches]


def _private(callback):
    return bool(callback.message and callback.message.chat.type == "private")


async def install(app):
    dp = app.dp
    cq = getattr(getattr(dp, "callback_query_handlers", None), "handlers", None)
    mh = getattr(getattr(dp, "message_handlers", None), "handlers", None)
    if cq is None:
        return False

    async def management_back(callback):
        if not _private(callback):
            raise CancelHandler()
        from runtime.private_pv_authority_v2 import _allowed
        await _allowed(app, callback)
        from runtime.final_private_ui import management_report, management_keyboard
        try:
            await callback.message.edit_text(
                management_report(app),
                reply_markup=management_keyboard(),
                parse_mode="HTML",
            )
        except MessageNotModified:
            pass
        await callback.answer()
        raise CancelHandler()

    async def profile(callback):
        if not _private(callback):
            raise CancelHandler()
        try:
            enhancement = getattr(app, "profile_enhancements", None)
            if enhancement is None:
                from runtime.user_panel import UserPanel
                enhancement = UserPanel(app)
            await enhancement.profile(callback)
        except Exception:
            logging.exception("PV priority: profile failed")
            await callback.answer("❌ نمایش پروفایل انجام نشد.", show_alert=True)
        raise CancelHandler()

    async def profile_settings(callback):
        if not _private(callback):
            raise CancelHandler()
        try:
            enhancement = getattr(app, "profile_enhancements", None)
            if enhancement is None:
                raise RuntimeError("profile enhancement unavailable")
            await enhancement.settings(callback)
        except Exception:
            logging.exception("PV priority: profile settings failed")
            await callback.answer("❌ تنظیمات پروفایل در دسترس نیست.", show_alert=True)
        raise CancelHandler()

    async def addons_back(callback):
        if not _private(callback):
            raise CancelHandler()
        from runtime.private_pv_authority_v2 import _allowed
        await _allowed(app, callback)
        from runtime.final_private_ui import start_keyboard
        try:
            await callback.message.edit_text(
                "🎭 <b>Mafia Nights</b>\n\nیک گزینه را انتخاب کنید:",
                reply_markup=start_keyboard(),
                parse_mode="HTML",
            )
        except MessageNotModified:
            pass
        await callback.answer()
        raise CancelHandler()

    # Register fresh handlers, then put them at the absolute front.
    dp.register_callback_query_handler(management_back, lambda c: c.data == "finalgm:back", state="*")
    dp.register_callback_query_handler(profile, lambda c: c.data in {"up:menu", "up:profile"}, state="*")
    dp.register_callback_query_handler(profile_settings, lambda c: c.data == "profile:settings", state="*")
    dp.register_callback_query_handler(addons_back, lambda c: c.data == "addons:back", state="*")

    _promote(cq, lambda h: _handler(h) in {management_back, profile, profile_settings, addons_back})

    # Scenario CRUD is already implemented by one manager. It must precede
    # broad callback handlers and its FSM message handlers must also win.
    manager = getattr(app, "_private_scenario_manager", None)
    if manager is not None:
        scenario_callbacks = {"menu", "view", "start_add", "start_edit", "delete_menu", "delete", "delete_confirm", "challenge_mode"}
        scenario_states = {"name", "description", "min_players", "max_players", "roles", "role_sides", "challenge_limit", "settings"}
        _promote(cq, lambda h: getattr(_handler(h), "__self__", None) is manager and _name(h) in scenario_callbacks)
        _promote(mh, lambda h: getattr(_handler(h), "__self__", None) is manager and _name(h) in scenario_states)

    app._pv_route_priority_v2_installed = True
    logging.info("PV ROUTE PRIORITY V2 ACTIVE")
    return True
