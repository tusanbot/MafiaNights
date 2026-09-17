"""Production game-end and command entrypoint.

The production webhook runs through player_runtime_entry/main1. This module
bridges the newer game-end and command surfaces into that real dispatcher
without replacing the desktop lobby implementation.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from aiogram import types
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

ALIASES = {"اتمام بازی", "/اتمام_بازی", "/پایان_بازی", "/end_game", "/endgame"}


def _handler(item):
    return getattr(item, "handler", None) or getattr(item, "callback", None)


def _message_registry(dp):
    return getattr(getattr(dp, "message_handlers", None), "handlers", [])


def _callback_registry(dp):
    return getattr(getattr(dp, "callback_query_handlers", None), "handlers", [])


def _move_front(registry, predicate) -> int:
    selected = [item for item in registry if predicate(_handler(item))]
    for item in reversed(selected):
        try:
            registry.remove(item)
            registry.insert(0, item)
        except ValueError:
            pass
    return len(selected)


def _clear_runtime_flags(app: Any) -> None:
    app.game_running = False
    app.round_active = False
    app.lobby_active = False
    app.current_turn_index = 0
    app.current_turn_seat = None
    app.turn_order = []
    app.player_slots = {}
    app.pending_challenges = {}
    app.active_challenger_seats = set()
    app._stable_day_active = False
    app._stable_day_ended = False
    app._stable_phase = "normal"
    for owner, attr in ((getattr(app, "ui", None), "turn_timer_task"), (getattr(app, "ui", None), "voting_timer_task"), (getattr(app, "ui", None), "day_timer_task"), (app, "_voting_task")):
        task = getattr(owner, attr, None) if owner is not None else None
        if task is not None and hasattr(task, "done") and not task.done():
            try: task.cancel()
            except Exception: pass


def install(app: Any) -> bool:
    if getattr(app, "_manual_end_game_installed", False):
        return False

    from runtime.game_end import install as install_game_end
    install_game_end(app)

    from runtime.management_surface_final import install as install_management_surface_final
    install_management_surface_final(app)

    from runtime.final_game_result_guard import install as install_final_game_result_guard
    install_final_game_result_guard(app)

    games = app.runtime.state.games
    original_update_game = getattr(games, "update_game", None)
    if original_update_game and not getattr(games, "_production_terminal_guard", False):
        def guarded_update_game(game_id, **changes):
            result = original_update_game(game_id, **changes)
            status = str(changes.get("status") or "").lower()
            if result and status in {"finished", "cancelled"}:
                _clear_runtime_flags(app)
            return result
        games.update_game = guarded_update_game
        games._production_terminal_guard = True

    from runtime.text_commands import install as install_text_commands
    from runtime.command_surface_v3 import install as install_command_surface_v3
    from runtime.player_kick import install as install_player_discipline
    install_text_commands(app)
    install_command_surface_v3(app)
    install_player_discipline(app)

    async def finish_command(message: types.Message):
        gid = int(message.chat.id)
        game = app.runtime.state.active_game(gid)
        if not game:
            await message.reply("ℹ️ بازی فعالی برای اتمام وجود ندارد.")
            return
        uid = int(message.from_user.id)
        allowed = uid == int(game.get("moderator_id") or 0)
        if not allowed:
            try:
                allowed = (await app.bot.get_chat_member(gid, uid)).status in {"creator", "administrator"}
            except Exception:
                allowed = False
        if not allowed:
            await message.reply("⛔ فقط گرداننده یا مدیر گروه می‌تواند بازی را تمام کند.")
            return
        if str(game.get("status") or "") not in {"running", "paused", "turn"}:
            await message.reply("❌ فقط بازی در حال اجرا قابل اتمام است.")
            return
        from runtime.game_end import _main_markup, _summary_text
        state = dict(game.get("state") or {})
        await message.reply(_summary_text(game), parse_mode="HTML", reply_markup=_main_markup(int(game["id"]), state.get("game_result"), bool((state.get("game_events") or {}).get("enabled"))))

    async def _allowed(obj, gid=None, game=None):
        gid = int(gid or obj.message.chat.id)
        game = game or app.runtime.state.active_game(gid)
        if not game:
            return False
        uid = int(obj.from_user.id)
        if uid == int(game.get("moderator_id") or 0):
            return True
        try:
            return (await app.bot.get_chat_member(gid, uid)).status in {"creator", "administrator"}
        except Exception:
            return False

    async def cancel_confirm(callback: types.CallbackQuery):
        gid = int(callback.message.chat.id)
        game = app.runtime.state.active_game(gid)
        if not game or not await _allowed(callback, gid, game):
            await callback.answer("⛔ دسترسی ندارید یا بازی فعال نیست.", show_alert=True)
            return
        await callback.message.edit_text(
            "⚠️ <b>تأیید لغو بازی</b>\n\n"
            "با تأیید، بازی فعلی لغو می‌شود و دیگر بازی فعال محسوب نخواهد شد.\n"
            "این عملیات قابل بازگشت نیست.\n\nآیا مطمئن هستید؟",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(row_width=2).add(
                InlineKeyboardButton("🚫 بله، لغو بازی", callback_data=f"mgmt:{int(game['id'])}:cancel_confirm"),
                InlineKeyboardButton("⬅️ بازگشت", callback_data=f"mgmt:{int(game['id'])}:open"),
            ),
        )
        await callback.answer()

    app._confirm_cancel_game = cancel_confirm

    async def cancel_confirmed(callback: types.CallbackQuery):
        gid = int(callback.message.chat.id)
        game = app.runtime.state.active_game(gid)
        if not game or not await _allowed(callback, gid, game):
            await callback.answer("⛔ دسترسی ندارید یا بازی فعال نیست.", show_alert=True)
            return
        status = str(game.get("status") or "")
        if status not in {"lobby", "running", "paused", "turn"}:
            await callback.answer("ℹ️ این بازی دیگر فعال نیست.", show_alert=True)
            return
        state = dict(game.get("state") or {})
        now = datetime.now(timezone.utc)
        state.update({"cancelled": True, "cancelled_from_status": status, "cancel_reason": "management_confirmed", "cancelled_at": now.isoformat()})
        try:
            ok = app.runtime.state.games.update_game(game["id"], status="cancelled", state=state, finished_at=now)
        except Exception:
            logging.exception("confirmed cancellation failed game=%s", game.get("id"))
            ok = False
        if not ok:
            await callback.answer("❌ لغو بازی انجام نشد.", show_alert=True)
            return
        _clear_runtime_flags(app)
        lid = state.get("lobby_message_id") or state.get("control_message_id")
        if lid:
            try:
                await app.bot.edit_message_text("🚫 <b>این بازی لغو شد.</b>\n\nبازی دیگر فعال نیست و می‌توانید بازی جدید را شروع کنید.", gid, int(lid), parse_mode="HTML", reply_markup=None)
            except Exception: logging.info("cancelled game message edit failed game=%s", game.get("id"))
        await callback.message.edit_text("🚫 <b>بازی لغو شد.</b>\n\nبازی جدید اکنون قابل ایجاد است.", parse_mode="HTML")
        await callback.answer("🚫 بازی با موفقیت لغو شد.")

    dp = app.dp
    dp.register_callback_query_handler(cancel_confirm, lambda c: str(c.data or "").startswith("mgmt:") and str(c.data or "").split(":")[2:3] == ["cancel"], state="*")
    dp.register_callback_query_handler(cancel_confirmed, lambda c: str(c.data or "").startswith("mgmt:") and str(c.data or "").split(":")[2:3] == ["cancel_confirm"], state="*")
    dp.register_message_handler(finish_command, lambda m: (m.text or "").strip().casefold() in {x.casefold() for x in ALIASES}, content_types=types.ContentTypes.TEXT, state="*")

    _move_front(_message_registry(dp), lambda fn: getattr(getattr(fn, "__self__", None), "__class__", type(None)).__name__ == "TextCommands")
    _move_front(_message_registry(dp), lambda fn: getattr(getattr(fn, "__self__", None), "__class__", type(None)).__name__ == "PlayerDiscipline")
    _move_front(_message_registry(dp), lambda fn: getattr(fn, "__name__", "") == "finish_command")
    _move_front(_callback_registry(dp), lambda fn: getattr(fn, "__name__", "") in {"cancel_confirm", "cancel_confirmed", "finish_menu"})

    app._manual_end_game_installed = True
    logging.info("MANUAL_END_GAME installed: finish/archive + confirmed cancel + text command surfaces + final management + result guard")
    return True
