"""Hardening for the unified lobby/management navigation and role distribution."""
from __future__ import annotations

import logging
from typing import Any

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def _put_first(dp, callback, predicate) -> None:
    dp.register_callback_query_handler(callback, predicate, state="*")
    table = getattr(dp.callback_query_handlers, "handlers", [])
    if table:
        table.insert(0, table.pop())


def install(app: Any, management: Any) -> bool:
    def panel(game_id: int) -> InlineKeyboardMarkup:
        kb = InlineKeyboardMarkup(row_width=3)
        items = [
            ("🔢 شماره بازی", "event"), ("📝 تغییر سناریو", "scenario"), ("🗑 حذف بازیکن", "remove"),
            ("🎟 لغو رزرو", "unreserve"), ("🔄 جایگزین بازیکن", "replace"), ("✅ حاضری", "attendance"),
            ("🎂 تولد بازیکن", "birthday"), ("⚔ وضعیت چالش", "challenge"), ("⏭ مدیریت نکست", "next"),
            ("🚫 لغو بازی", "cancel"), ("⬅️ بازگشت به لابی", "return_lobby"),
        ]
        for i in range(0, len(items), 3):
            kb.row(*(InlineKeyboardButton(text, callback_data=f"mgmt:{game_id}:{action}") for text, action in items[i:i + 3]))
        return kb

    management.panel = panel

    async def return_lobby(callback):
        gid = int(callback.message.chat.id)
        game = management._game(gid)
        if not game or not await management._allowed(callback, gid, game):
            await callback.answer("⛔ دسترسی ندارید یا بازی فعال نیست.", show_alert=True)
            return
        if str(game.get("status") or "") != "lobby":
            await callback.answer("❌ بازگشت به لابی فقط در وضعیت لابی امکان‌پذیر است.", show_alert=True)
            return
        renderer = getattr(app, "_render_production_lobby", None)
        if not renderer:
            await callback.answer("❌ موتور لابی در دسترس نیست.", show_alert=True)
            return
        try:
            ok = bool(await renderer(gid, game))
        except Exception:
            logging.exception("management return-to-lobby failed game=%s group=%s", game.get("id"), gid)
            ok = False
        await callback.answer("⬅️ به لابی برگشتید." if ok else "❌ بازگشت به لابی انجام نشد.", show_alert=not ok)

    _put_first(
        app.dp,
        return_lobby,
        lambda c: str(c.data or "").startswith("mgmt:") and len(str(c.data or "").split(":")) == 3 and str(c.data).split(":")[2] == "return_lobby",
    )

    async def role_distribution_bridge(callback):
        handler = getattr(app, "_canonical_distribute_roles", None) or getattr(app, "_role_distribution_handler", None)
        if not handler:
            await callback.answer("❌ سرویس پخش نقش در دسترس نیست.", show_alert=True)
            return
        try:
            await handler(callback)
        except Exception:
            logging.exception("role distribution callback failed game=%s", callback.data)
            await callback.answer("❌ پخش نقش انجام نشد؛ خطا در اجرای سرویس پخش نقش.", show_alert=True)

    _put_first(
        app.dp,
        role_distribution_bridge,
        lambda c: (lambda p: len(p) == 4 and p[0] == "lobby" and p[2] == "distribute")(str(c.data or "").split(":")),
    )

    logging.info("LOBBY_MANAGEMENT_FIX installed management_return_lobby=active role_distribution_bridge=active")
    return True
