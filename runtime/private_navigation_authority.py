"""Final import-time router for private navigation on webhook runtimes.

The webhook path must not depend on aiogram startup hooks. This module is the
last private-navigation layer installed during import, so it owns the routing
entry points and delegates detailed screens to the established UI handlers.
"""
from __future__ import annotations

import logging

from aiogram.dispatcher.handler import CancelHandler
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def install(app):
    dp = app.dp
    cq = getattr(getattr(dp, "callback_query_handlers", None), "handlers", [])
    mh = getattr(getattr(dp, "message_handlers", None), "handlers", [])

    if getattr(app, "_private_navigation_authority_installed", False):
        return False

    def is_private(callback):
        return bool(callback.message and callback.message.chat.type == "private")

    def handler_fn(item):
        return getattr(item, "handler", None) or getattr(item, "callback", None)

    async def allowed(callback):
        if not is_private(callback):
            raise CancelHandler()
        uid = int(callback.from_user.id)
        moderator = getattr(app, "moderator_id", None)
        if moderator is not None and uid == int(moderator):
            return True
        gid = getattr(app, "group_chat_id", None) or getattr(app, "ALLOWED_GROUP_ID", None)
        if gid:
            try:
                admins = await app.bot.get_chat_administrators(int(gid))
                if uid in {int(a.user.id) for a in admins}:
                    return True
            except Exception:
                logging.exception("private navigation: admin lookup failed")
        await callback.answer("⛔ فقط گرداننده یا مدیر گروه دسترسی دارد.", show_alert=True)
        raise CancelHandler()

    def scenario_keyboard():
        kb = InlineKeyboardMarkup(row_width=1)
        kb.add(
            InlineKeyboardButton("➕ افزودن سناریو", callback_data="private_scenario:add"),
            InlineKeyboardButton("➖ حذف سناریو", callback_data="private_scenario:remove"),
            InlineKeyboardButton("✏️ ویرایش سناریو", callback_data="private_scenario:edit"),
            InlineKeyboardButton("📋 لیست سناریوها", callback_data="private_scenario:list"),
            InlineKeyboardButton("⬅️ بازگشت", callback_data="private:start"),
        )
        return kb

    async def scenarios(callback):
        await allowed(callback)
        await callback.message.edit_text(
            "⚙️ <b>مدیریت سناریو</b>\n\nیک گزینه را انتخاب کنید:",
            reply_markup=scenario_keyboard(),
            parse_mode="HTML",
        )
        await callback.answer()
        raise CancelHandler()

    async def private_start(callback):
        if not is_private(callback):
            raise CancelHandler()
        from runtime.final_private_ui import start_keyboard
        await callback.message.edit_text(
            "🎭 <b>Mafia Nights</b>\n\nیک گزینه را انتخاب کنید:",
            reply_markup=start_keyboard(),
            parse_mode="HTML",
        )
        await callback.answer()
        raise CancelHandler()

    async def addons_back(callback):
        await allowed(callback)
        from runtime.final_private_ui import start_keyboard
        await callback.message.edit_text(
            "🎭 <b>Mafia Nights</b>\n\nیک گزینه را انتخاب کنید:",
            reply_markup=start_keyboard(),
            parse_mode="HTML",
        )
        await callback.answer()
        raise CancelHandler()

    async def dispatch_final(callback):
        """Materialize final_private_ui and dispatch once without recursive routing."""
        if not is_private(callback):
            raise CancelHandler()
        from runtime import final_private_ui
        await final_private_ui.install(app)

        # Remove this router's own entries temporarily. aiogram's notify() can
        # then run the exact final_private_ui HandlerObj normally, including its
        # FSM/state data and CancelHandler semantics.
        own = [h for h in list(cq) if handler_fn(h) in {
            dispatch_final, scenarios, private_start, addons_back
        }]
        try:
            for h in own:
                if h in cq:
                    cq.remove(h)
            await dp.callback_query_handlers.notify(callback)
        finally:
            for h in reversed(own):
                cq.insert(0, h)
        raise CancelHandler()

    async def group_start(message):
        if message.chat.type not in ("group", "supergroup"):
            return
        try:
            app.group_chat_id = int(message.chat.id)
        except Exception:
            return
        try:
            keyboard = app.main_menu_keyboard()
        except Exception:
            keyboard = InlineKeyboardMarkup().add(
                InlineKeyboardButton("🎮 بازی جدید", callback_data="lv6_new")
            )
        await message.answer(
            "🎭 <b>Mafia Nights</b>\n\nبرای شروع بازی از دکمه زیر استفاده کنید:",
            reply_markup=keyboard,
            parse_mode="HTML",
        )
        raise CancelHandler()

    # Navigation entry points. The authority is deliberately installed after
    # all legacy/bridge modules, then moved to the front of both registries.
    dp.register_callback_query_handler(scenarios, lambda c: c.data == "final:scenarios", state="*")
    dp.register_callback_query_handler(private_start, lambda c: c.data == "private:start", state="*")
    dp.register_callback_query_handler(addons_back, lambda c: c.data == "addons:back", state="*")
    dp.register_callback_query_handler(dispatch_final, lambda c: str(c.data or "").startswith("finalgm:"), state="*")
    dp.register_message_handler(group_start, commands=["start"], state="*")

    # Support both aiogram 2.x HandlerObj.handler and compatibility layers
    # exposing HandlerObj.callback.
    owned_callbacks = {scenarios, private_start, addons_back, dispatch_final}
    for i in range(len(cq) - 1, -1, -1):
        if handler_fn(cq[i]) in owned_callbacks:
            cq.insert(0, cq.pop(i))
    for i in range(len(mh) - 1, -1, -1):
        if handler_fn(mh[i]) is group_start:
            mh.insert(0, mh.pop(i))
            break

    app._private_navigation_authority_installed = True
    logging.info("Private navigation authority installed: handlers=%d", len(cq))
    return True
