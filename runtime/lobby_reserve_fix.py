from __future__ import annotations

from aiogram import types
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def _front(dp, fn):
    handlers = getattr(getattr(dp, "callback_query_handlers", None), "handlers", None)
    if not isinstance(handlers, list):
        return
    for i, h in enumerate(handlers):
        if getattr(h, "callback", None) is fn:
            handlers.insert(0, handlers.pop(i))
            return


def install(main):
    dp = main.dp
    bot = main.bot

    async def cancel_reserve(c: types.CallbackQuery):
        game = None
        try:
            game = main.persistent_runtime.state.active_game(int(main.group_chat_id))
        except Exception:
            pass
        if not game:
            await c.answer("⚠️ بازی فعالی وجود ندارد.", show_alert=True)
            return
        rows = main.persistent_runtime.state.games.list_players(game["id"])
        row = next((r for r in rows if int(r["player_id"]) == c.from_user.id and r.get("is_substitute")), None)
        if not row:
            await c.answer("ℹ️ شما در لیست رزرو نیستید.", show_alert=True)
            return
        main.persistent_runtime.state.games.remove_player(game["id"], c.from_user.id)
        await c.answer("✅ رزرو شما لغو شد")
        try:
            await c.message.edit_text("🎟 رزرو شما لغو شد.")
        except Exception:
            pass

    async def reserve_control(c: types.CallbackQuery):
        try:
            game = main.persistent_runtime.state.active_game(int(main.group_chat_id))
            rows = main.persistent_runtime.state.games.list_players(game["id"]) if game else []
            row = next((r for r in rows if int(r["player_id"]) == c.from_user.id and r.get("is_substitute")), None)
        except Exception:
            row = None
        if not row:
            return
        kb = InlineKeyboardMarkup().add(InlineKeyboardButton("❌ لغو رزرو", callback_data="lobby_cancel_reserve"))
        try:
            await bot.send_message(c.from_user.id, "🎟 شما در لیست رزرو هستید.", reply_markup=kb)
        except Exception:
            pass

    dp.register_callback_query_handler(cancel_reserve, lambda c: c.data == "lobby_cancel_reserve")
    dp.register_callback_query_handler(reserve_control, lambda c: c.data == "lobby_reserve")
    _front(dp, cancel_reserve)
    _front(dp, reserve_control)
