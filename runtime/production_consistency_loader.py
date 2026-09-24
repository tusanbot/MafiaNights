"""Synchronous loader for the production consistency runtime patch."""
from __future__ import annotations

import html
from typing import Any

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.dispatcher.handler import CancelHandler

from runtime.production_consistency_v4 import install as _install_async


def _handler(item: Any):
    return getattr(item, "handler", None) or getattr(item, "callback", None)


def _move_module_handlers_front(dp: Any, module_name: str) -> dict[str, int]:
    moved = {"callback": 0, "message": 0}
    for registry_name, key in (("callback_query_handlers", "callback"), ("message_handlers", "message")):
        registry = getattr(getattr(dp, registry_name, None), "handlers", None)
        if registry is None:
            continue
        selected = []
        remaining = []
        for item in registry:
            fn = _handler(item)
            if getattr(fn, "__module__", "") == module_name:
                selected.append(item)
            else:
                remaining.append(item)
        if selected:
            registry[:] = selected + remaining
            moved[key] = len(selected)
    return moved


def _final_markup(game_id: int) -> InlineKeyboardMarkup:
    gid = int(game_id)
    return InlineKeyboardMarkup(row_width=2).add(
        InlineKeyboardButton("📊 نتیجه بازی", callback_data=f"game_end:{gid}:result"),
        InlineKeyboardButton("📝 اتفاقات بازی", callback_data=f"game_end:{gid}:events"),
        InlineKeyboardButton("📚 بازی‌های گذشته", callback_data=f"game_history:list:{gid}"),
        InlineKeyboardButton("✖️ بستن", callback_data=f"game_end:{gid}:close"),
    )


def install(app: Any) -> bool:
    """Install consistency after every production runtime installer."""
    # Webhook dispatch already runs inside an active asyncio loop. The underlying
    # consistency installer only registers handlers/state, so it must be called
    # synchronously instead of nesting asyncio.run() inside the webhook loop.
    installed = bool(_install_async(app))

    dp = app.dp
    from runtime import game_end

    async def _finished_game(game_id):
        repo = app.runtime.state.games
        try:
            return repo.get_finished_game(int(game_id)) or repo.get_game(int(game_id))
        except Exception:
            return None

    async def _hydrate_moderator_name(game):
        if not game:
            return game
        state = dict(game.get("state") or {})
        if state.get("moderator_name"):
            return game
        uid = int(game.get("moderator_id") or 0)
        gid = int(game.get("group_chat_id") or 0)
        if not uid or not gid:
            return game
        try:
            member = await app.bot.get_chat_member(gid, uid)
            user = getattr(member, "user", None)
            name = getattr(user, "full_name", None) or getattr(user, "first_name", None) or getattr(user, "username", None)
            if name:
                state["moderator_name"] = str(name)
                game["state"] = state
                try:
                    app.runtime.state.games.update_game(game["id"], state=state)
                except Exception:
                    pass
        except Exception:
            pass
        return game

    async def final_result(callback):
        p = str(callback.data or "").split(":")
        if len(p) != 3 or p[0] != "game_end" or p[2] != "result":
            return
        game = await _finished_game(p[1])
        if not game:
            await callback.answer("❌ بازی در آرشیو پیدا نشد.", show_alert=True)
            return
        game = await _hydrate_moderator_name(game)
        rows = app.runtime.state.games.list_players(int(game["id"]))
        await callback.message.edit_text(game_end._final_text(game, rows), parse_mode="HTML", reply_markup=_final_markup(int(game["id"])))
        await callback.answer()
        raise CancelHandler()

    async def final_events(callback):
        p = str(callback.data or "").split(":")
        if len(p) != 3 or p[0] != "game_end" or p[2] != "events":
            return
        game = await _finished_game(p[1])
        if not game:
            await callback.answer("❌ بازی در آرشیو پیدا نشد.", show_alert=True)
            return
        state = dict(game.get("state") or {})
        events = dict(state.get("game_events") or {})
        text = str(events.get("text") or "").strip()
        body = html.escape(text) if text else "فعلاً اتفاقات بازی ثبت نشده است."
        await callback.message.edit_text(
            f"📝 <b>اتفاقات بازی {int(game.get('event_number') or 0)}</b>\n\n{body}",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(row_width=1).add(
                InlineKeyboardButton("⬅️ بازگشت به نتیجه", callback_data=f"game_end:{int(game['id'])}:result")
            ),
        )
        await callback.answer()
        raise CancelHandler()

    async def final_history(callback):
        p = str(callback.data or "").split(":")
        if len(p) != 3 or p[:2] != ["game_history", "list"]:
            return
        ref = await _finished_game(p[2])
        if not ref:
            await callback.answer("❌ بازی پیدا نشد.", show_alert=True)
            return
        gid = int(ref.get("group_chat_id") or callback.message.chat.id)
        games = app.runtime.state.games.list_finished_games(gid, limit=20) or []
        if not games:
            await callback.answer("ℹ️ هنوز بازی ثبت نهایی‌شده‌ای وجود ندارد.", show_alert=True)
            return
        kb = InlineKeyboardMarkup(row_width=1)
        for game in games:
            state = dict(game.get("state") or {})
            label = str(state.get("game_result_label") or state.get("game_result") or "بدون نتیجه")
            kb.add(InlineKeyboardButton(f"📓 بازی {int(game.get('event_number') or 0)} — {label}", callback_data=f"game_history:view:{int(game['id'])}"))
        kb.add(InlineKeyboardButton("✖️ بستن", callback_data=f"game_end:{int(ref['id'])}:close"))
        await callback.message.edit_text("📚 <b>بازی‌های گذشته</b>\n\nبازی موردنظر را انتخاب کنید:", parse_mode="HTML", reply_markup=kb)
        await callback.answer()
        raise CancelHandler()

    async def final_history_view(callback):
        p = str(callback.data or "").split(":")
        if len(p) != 3 or p[:2] != ["game_history", "view"]:
            return
        game = await _finished_game(p[2])
        if not game:
            await callback.answer("❌ این بازی در آرشیو پیدا نشد.", show_alert=True)
            return
        game = await _hydrate_moderator_name(game)
        rows = app.runtime.state.games.list_players(int(game["id"]))
        await callback.message.edit_text(game_end._final_text(game, rows), parse_mode="HTML", reply_markup=_final_markup(int(game["id"])))
        await callback.answer()
        raise CancelHandler()

    async def final_close(callback):
        p = str(callback.data or "").split(":")
        if len(p) != 3 or p[0] != "game_end" or p[2] != "close":
            return
        try:
            await callback.message.delete()
        except Exception:
            pass
        await callback.answer()
        raise CancelHandler()

    dp.register_callback_query_handler(final_history_view, lambda c: str(c.data or "").startswith("game_history:view:"), state="*")
    dp.register_callback_query_handler(final_history, lambda c: str(c.data or "").startswith("game_history:list:"), state="*")
    dp.register_callback_query_handler(final_result, lambda c: (lambda p: len(p) == 3 and p[0] == "game_end" and p[2] == "result")(str(c.data or "").split(":")), state="*")
    dp.register_callback_query_handler(final_events, lambda c: (lambda p: len(p) == 3 and p[0] == "game_end" and p[2] == "events")(str(c.data or "").split(":")), state="*")
    dp.register_callback_query_handler(final_close, lambda c: (lambda p: len(p) == 3 and p[0] == "game_end" and p[2] == "close")(str(c.data or "").split(":")), state="*")

    # These exact handlers must beat every broad legacy game_end/history handler.
    reg = getattr(getattr(dp, "callback_query_handlers", None), "handlers", [])
    names = {"final_result", "final_events", "final_history", "final_history_view", "final_close"}
    selected = [item for item in reg if getattr(_handler(item), "__name__", "") in names]
    rest = [item for item in reg if getattr(_handler(item), "__name__", "") not in names]
    reg[:] = selected + rest

    moved = _move_module_handlers_front(dp, "runtime.production_consistency_v4")
    app._production_consistency_handler_priority = moved
    game_end._final_markup = _final_markup
    return installed
