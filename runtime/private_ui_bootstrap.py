"""Import-time bootstrap for the private UI on webhook runtimes.

Vercel imports ``player_runtime_entry`` for each webhook invocation and does not
run aiogram's polling startup hook first.  This module therefore installs the
private entry points immediately.  Detailed private management handlers are
lazily materialized on their first callback, then the callback is dispatched to
``final_private_ui``'s real handler.  This keeps one authoritative implementation
instead of duplicating the whole management menu here.
"""
from __future__ import annotations

import html
import logging

from aiogram.dispatcher.handler import CancelHandler
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def _private(callback):
    return bool(callback.message and callback.message.chat.type == "private")


def _group_id(app):
    for obj in (app, getattr(app, "addons", None)):
        for key in ("ALLOWED_GROUP_ID", "GROUP_ID", "group_chat_id", "group_id"):
            value = getattr(obj, key, None)
            if value:
                try:
                    return int(value)
                except (TypeError, ValueError):
                    pass
    return None


def _moderator_id(app):
    for obj in (app, getattr(app, "addons", None)):
        value = getattr(obj, "moderator_id", None)
        if value is not None:
            try:
                return int(value)
            except (TypeError, ValueError):
                pass
    return None


def _keyboard_start():
    from runtime.final_private_ui import start_keyboard
    return start_keyboard()


def _management_keyboard():
    from runtime.final_private_ui import management_keyboard
    return management_keyboard()


def _scenario_keyboard():
    # Use the callback namespace owned by final_private_ui.  In webhook mode
    # these are lazy-dispatched to that module on first click.
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(
        InlineKeyboardButton("➕ افزودن سناریو", callback_data="final:scenario:add"),
        InlineKeyboardButton("➖ حذف سناریو", callback_data="final:scenario:remove"),
        InlineKeyboardButton("✏️ ویرایش سناریو", callback_data="final:scenario:edit"),
        InlineKeyboardButton("📋 لیست سناریوها", callback_data="final:scenario:list"),
        InlineKeyboardButton("⬅️ بازگشت", callback_data="final:start"),
    )
    return kb


def install(app):
    if getattr(app, "_private_ui_bootstrap_installed", False):
        return False
    registry = getattr(getattr(app.dp, "callback_query_handlers", None), "handlers", None)
    if registry is None:
        logging.error("private UI bootstrap: callback registry unavailable")
        return False

    async def allowed(callback):
        if not _private(callback):
            raise CancelHandler()
        uid = int(callback.from_user.id)
        if _moderator_id(app) == uid:
            return True
        gid = _group_id(app)
        if gid:
            try:
                admins = await app.bot.get_chat_administrators(gid)
                if uid in {int(a.user.id) for a in admins}:
                    return True
            except Exception:
                logging.exception("private UI bootstrap: group admin lookup failed for %s", gid)
        await callback.answer("⛔ فقط گرداننده یا مدیر گروه دسترسی دارد.", show_alert=True)
        raise CancelHandler()

    async def start(callback):
        if not _private(callback):
            raise CancelHandler()
        await callback.message.edit_text(
            "🎭 <b>Mafia Nights</b>\n\nیک گزینه را انتخاب کنید:",
            reply_markup=_keyboard_start(), parse_mode="HTML",
        )
        await callback.answer()
        raise CancelHandler()

    async def management(callback):
        await allowed(callback)
        from runtime.final_private_ui import management_report
        await callback.message.edit_text(
            management_report(app), reply_markup=_management_keyboard(), parse_mode="HTML"
        )
        await callback.answer()
        raise CancelHandler()

    async def scenarios(callback):
        await allowed(callback)
        await callback.message.edit_text(
            "⚙️ <b>مدیریت سناریو</b>\n\nاز این بخش سناریوها را مدیریت کنید:",
            reply_markup=_scenario_keyboard(), parse_mode="HTML",
        )
        await callback.answer()
        raise CancelHandler()

    async def lazy_final_private_ui(callback):
        """Install final_private_ui now, then execute its matching handler.

        aiogram 2.x dispatches the first matching handler only.  Because the
        final UI normally installs during on_startup (which webhook runtimes do
        not call), this bridge materializes it during the first private
        management click and manually runs the exact matching final handler.
        """
        if not _private(callback):
            raise CancelHandler()
        from runtime import final_private_ui
        if not getattr(app, "_final_private_ui_installed", False):
            await final_private_ui.install(app)

        current_registry = getattr(
            getattr(app.dp, "callback_query_handlers", None), "handlers", []
        )
        for item in list(current_registry):
            fn = getattr(item, "handler", None)
            if fn is None or fn is lazy_final_private_ui:
                continue
            if getattr(fn, "__module__", "") != "runtime.final_private_ui":
                continue
            try:
                matched, data = await item.check_filters(callback)
            except TypeError:
                matched, data = await item.check_filters(callback=callback)
            if matched:
                await fn(callback, **(data or {}))
                raise CancelHandler()

        await callback.answer("⚠️ این گزینه در نسخه فعلی ثبت نشده است.", show_alert=True)
        raise CancelHandler()

    regs = [
        (start, lambda c: c.data in {"private:start", "final:start"}),
        (management, lambda c: c.data == "manage_game"),
        (scenarios, lambda c: c.data in {"private:scenarios", "final:scenarios", "manage_scenarios", "change_scenario"}),
        # All detailed management/scenario callbacks are owned by final_private_ui.
        # Registering one lazy bridge here prevents webhook mode from falling
        # through to legacy handlers before on_startup has run.
        (lazy_final_private_ui, lambda c: str(c.data or "").startswith("finalgm:")),
        (lazy_final_private_ui, lambda c: str(c.data or "").startswith("final:scenario:")),
    ]
    for fn, filt in regs:
        app.dp.register_callback_query_handler(fn, filt, state="*")

    owned = [h for h in list(registry) if getattr(getattr(h, "handler", None), "__module__", "") == __name__]
    others = [h for h in list(registry) if h not in owned]
    registry[:] = owned + others
    app._private_ui_bootstrap_installed = True
    logging.info("Private UI bootstrap installed before async startup: handlers=%d", len(registry))
    return True
