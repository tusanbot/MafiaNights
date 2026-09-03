"""Private-only entry point for game management.

The private admin panel is intentionally isolated from group/lobby handlers.
No callback rendered by this module points to a group/lobby callback.
"""
from __future__ import annotations

from aiogram.dispatcher.handler import CancelHandler
from runtime.stable_game_management import _gid, _render_management


def install(app):
    if getattr(app, "_stable_game_management_entry_installed", False):
        return False
    handlers = getattr(getattr(app.dp, "callback_query_handlers", None), "handlers", None)
    if handlers is None:
        return False

    async def _can_manage(uid):
        if uid == getattr(app, "moderator_id", None):
            return True
        gid = _gid(app)
        if not gid:
            return False
        try:
            return uid in {a.user.id for a in await app.bot.get_chat_administrators(gid)}
        except Exception:
            return False

    async def manage_game(callback):
        if not callback.message or callback.message.chat.type != "private":
            await callback.answer("این پنل فقط در پیوی ربات قابل استفاده است.", show_alert=True)
            raise CancelHandler()
        if not await _can_manage(callback.from_user.id):
            await callback.answer("⛔ فقط گرداننده یا مدیر گروه دسترسی دارد.", show_alert=True)
            raise CancelHandler()
        await _render_management(app, callback)
        raise CancelHandler()

    app.dp.register_callback_query_handler(
        manage_game, lambda c: c.data == "manage_game", state="*"
    )
    for i, item in enumerate(handlers):
        if getattr(item, "handler", None) is manage_game:
            handlers.insert(0, handlers.pop(i))
            break
    app._stable_game_management_entry_installed = True
    return True
