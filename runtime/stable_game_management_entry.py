"""Make the stable private game-management screen the first matching handler."""
from __future__ import annotations

from aiogram.dispatcher.handler import CancelHandler
from runtime.stable_game_management import _render_management


def install(app):
    if getattr(app, "_stable_game_management_entry_installed", False):
        return False
    handlers = getattr(getattr(app.dp, "callback_query_handlers", None), "handlers", None)
    if handlers is None:
        return False

    async def manage_game(callback):
        if not callback.message or callback.message.chat.type != "private":
            await callback.answer("این بخش فقط در پیوی قابل استفاده است.", show_alert=True)
            raise CancelHandler()
        moderator = getattr(app, "moderator_id", None)
        uid = callback.from_user.id
        allowed = uid == moderator
        if not allowed:
            try:
                gid = int(getattr(app, "group_chat_id", 0) or 0)
                if gid:
                    allowed = uid in {a.user.id for a in await app.bot.get_chat_administrators(gid)}
            except Exception:
                allowed = False
        if not allowed:
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True)
            raise CancelHandler()
        await _render_management(app, callback)
        raise CancelHandler()

    app.dp.register_callback_query_handler(manage_game, lambda c: c.data == "manage_game", state="*")
    for i, item in enumerate(handlers):
        if getattr(item, "handler", None) is manage_game:
            handlers.insert(0, handlers.pop(i))
            break
    app._stable_game_management_entry_installed = True
    return True
