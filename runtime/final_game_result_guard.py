from __future__ import annotations

import html
import logging

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def _handler(item):
    return getattr(item, "handler", None) or getattr(item, "callback", None)


def _registry(dp):
    return getattr(getattr(dp, "callback_query_handlers", None), "handlers", [])


def _move_front(reg, fn):
    for i, item in enumerate(reg):
        if _handler(item) is fn:
            reg.insert(0, reg.pop(i)); return


def install(app):
    if getattr(app, "_final_game_result_guard", False): return False
    reg = _registry(app.dp)
    original_game_end = next((_handler(x) for x in reg if getattr(_handler(x), "__name__", "") == "game_end"), None)
    original_history = next((_handler(x) for x in reg if getattr(_handler(x), "__name__", "") == "game_history"), None)
    if original_game_end is None or original_history is None:
        logging.warning("FINAL GAME RESULT: game_end/game_history handlers not found")
        return False

    from runtime.game_end import _events_message, _events_state, _final_text, _history_markup, _result_label

    async def finalized_game_end(callback):
        data = str(callback.data or "")
        parts = data.split(":")
        if len(parts) < 3 or parts[0] != "game_end":
            return await original_game_end(callback)
        action = parts[2]
        if action not in {"result", "events"}:
            return await original_game_end(callback)
        try:
            game_id = int(parts[1])
            game = app.runtime.state.games.get_finished_game(game_id)
        except Exception:
            game = None
        if not game:
            return await original_game_end(callback)
        state = dict(game.get("state") or {})
        if action == "result":
            rows = app.runtime.state.games.list_players(game_id)
            await callback.message.edit_text(_final_text(game, rows), parse_mode="HTML", reply_markup=_final_markup(game_id))
            await callback.answer()
            return
        events = _events_state(game)
        await callback.message.edit_text(_events_message(events), parse_mode="HTML", reply_markup=_final_markup(game_id))
        await callback.answer()

    def _final_markup(game_id):
        return InlineKeyboardMarkup(row_width=2).add(
            InlineKeyboardButton("📊 نتیجه بازی", callback_data=f"game_end:{int(game_id)}:result"),
            InlineKeyboardButton("📝 اتفاقات بازی", callback_data=f"game_end:{int(game_id)}:events"),
            InlineKeyboardButton("📚 بازی‌های گذشته", callback_data=f"game_history:list:{int(game_id)}"),
            InlineKeyboardButton("✖️ بستن", callback_data=f"game_end:{int(game_id)}:close"),
        )

    async def finalized_history(callback):
        parts = str(callback.data or "").split(":")
        if len(parts) < 3 or parts[0] != "game_history":
            return await original_history(callback)
        try:
            reference_id = int(parts[2])
        except Exception:
            await callback.answer("❌ شناسه بازی نامعتبر است.", show_alert=True); return
        reference = app.runtime.state.games.get_game(reference_id)
        if not reference:
            reference = app.runtime.state.games.get_finished_game(reference_id)
        if not reference:
            await callback.answer("❌ بازی پیدا نشد.", show_alert=True); return
        uid = int(callback.from_user.id)
        allowed = uid == int(reference.get("moderator_id") or 0)
        if not allowed:
            try:
                gid = int(reference.get("group_chat_id") or callback.message.chat.id)
                allowed = (await app.bot.get_chat_member(gid, uid)).status in {"creator", "administrator"}
            except Exception:
                allowed = False
        if not allowed:
            await callback.answer("⛔ فقط گرداننده یا مدیر گروه.", show_alert=True); return
        group_id = int(reference.get("group_chat_id") or callback.message.chat.id)
        if parts[1] == "list":
            games = app.runtime.state.games.list_finished_games(group_id, limit=20)
            if not games:
                await callback.answer("ℹ️ هنوز بازی ثبت نهایی‌شده‌ای وجود ندارد.", show_alert=True); return
            await callback.message.edit_text("📚 <b>بازی‌های گذشته</b>\n\nبازی موردنظر را انتخاب کنید:", parse_mode="HTML", reply_markup=_history_markup(games))
            await callback.answer(); return
        if parts[1] == "view":
            game = app.runtime.state.games.get_finished_game(reference_id)
            if not game:
                await callback.answer("❌ این بازی در آرشیو پیدا نشد.", show_alert=True); return
            rows = app.runtime.state.games.list_players(reference_id)
            await callback.message.edit_text(_final_text(game, rows), parse_mode="HTML", reply_markup=_final_markup(reference_id))
            await callback.answer(); return
        await callback.answer("❌ عملیات نامعتبر است.", show_alert=True)

    for item in reg:
        fn = _handler(item)
        if fn is original_game_end:
            try: item.handler = finalized_game_end
            except Exception: item.callback = finalized_game_end
        elif fn is original_history:
            try: item.handler = finalized_history
            except Exception: item.callback = finalized_history
    _move_front(reg, finalized_history)
    _move_front(reg, finalized_game_end)
    app._final_game_result_guard = True
    logging.info("FINAL GAME RESULT GUARD active: finished result/events/history are callable")
    return True
