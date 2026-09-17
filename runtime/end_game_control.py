"""Production game-end entrypoint.

The old implementation finalized a game immediately from the management button,
which bypassed the winner/events/finalization flow.  This module now delegates
the actual completion UI to runtime.game_end and only owns the production entry
aliases plus the explicit cancellation confirmation.
"""
from __future__ import annotations

import logging
from typing import Any

from aiogram import types
from aiogram.dispatcher.handler import CancelHandler
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


ALIASES = {
    "اتمام بازی",
    "/اتمام_بازی",
    "/پایان_بازی",
    "/end_game",
    "/endgame",
}


def _handler(item):
    return getattr(item, "handler", None) or getattr(item, "callback", None)


def _move_front(dp, predicate) -> int:
    registry = getattr(getattr(dp, "callback_query_handlers", None), "handlers", [])
    selected = [item for item in registry if predicate(_handler(item))]
    for item in reversed(selected):
        try:
            registry.remove(item)
            registry.insert(0, item)
        except ValueError:
            pass
    return len(selected)


def install(app: Any) -> bool:
    if getattr(app, "_manual_end_game_installed", False):
        return False

    # Install the complete winner/events/finalization flow in the production
    # dispatcher.  It provides its own confirmation before final persistence.
    from runtime.game_end import install as install_game_end
    install_game_end(app)

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
        await message.reply(
            _summary_text(game),
            parse_mode="HTML",
            reply_markup=_main_markup(int(game["id"]), state.get("game_result"), bool((state.get("game_events") or {}).get("enabled"))),
        )

    async def cancel_confirm(callback: types.CallbackQuery):
        gid = int(callback.message.chat.id)
        game = app.runtime.state.active_game(gid)
        if not game or not await _allowed(callback, gid, game):
            await callback.answer("⛔ دسترسی ندارید یا بازی فعال نیست.", show_alert=True)
            return
        await callback.message.edit_text(
            "⚠️ <b>تأیید لغو بازی</b>\n\n"
            "با تأیید، بازی فعلی لغو می‌شود و دیگر بازی فعال محسوب نخواهد شد.\n"
            "این عملیات قابل بازگشت نیست.\n\n"
            "آیا مطمئن هستید؟",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(row_width=2).add(
                InlineKeyboardButton("🚫 بله، لغو بازی", callback_data=f"mgmt:{int(game['id'])}:cancel_confirm"),
                InlineKeyboardButton("⬅️ بازگشت", callback_data=f"mgmt:{int(game['id'])}:open"),
            ),
        )
        await callback.answer()

    async def cancel_abort(callback: types.CallbackQuery):
        gid = int(callback.message.chat.id)
        game = app.runtime.state.active_game(gid)
        if not game or not await _allowed(callback, gid, game):
            await callback.answer("⛔ دسترسی ندارید یا بازی فعال نیست.", show_alert=True)
            return
        await callback.answer("لغو بازی انجام نشد.")
        try:
            await app.game_management.open(callback)
        except Exception:
            logging.exception("cancel abort management render failed")

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
        state["cancelled"] = True
        state["cancelled_from_status"] = status
        state["cancel_reason"] = "management_confirmed"
        try:
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc)
            state["cancelled_at"] = now.isoformat()
            ok = app.runtime.state.games.update_game(game["id"], status="cancelled", state=state, finished_at=now)
        except Exception:
            logging.exception("confirmed game cancellation failed game=%s", game.get("id"))
            ok = False
        if not ok:
            await callback.answer("❌ لغو بازی انجام نشد.", show_alert=True)
            return

        # Clear all process-local state so a new game is immediately allowed.
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
        for owner, attr in ((getattr(app, "ui", None), "turn_timer_task"), (getattr(app, "ui", None), "voting_timer_task"), (app, "_voting_task")):
            task = getattr(owner, attr, None) if owner is not None else None
            if task is not None and hasattr(task, "done") and not task.done():
                try: task.cancel()
                except Exception: pass

        lid = state.get("lobby_message_id") or state.get("control_message_id")
        if lid:
            try:
                await app.bot.edit_message_text(
                    "🚫 <b>این بازی لغو شد.</b>\n\nبازی دیگر فعال نیست و می‌توانید بازی جدید را شروع کنید.",
                    gid, int(lid), parse_mode="HTML", reply_markup=None,
                )
            except Exception:
                logging.info("cancelled game message could not be edited game=%s", game.get("id"))
        await callback.message.edit_text(
            f"🚫 <b>بازی شماره {int(game.get('event_number') or 1)} لغو شد.</b>\n\n"
            "بازی جدید اکنون قابل ایجاد است.",
            parse_mode="HTML",
        )
        await callback.answer("🚫 بازی با موفقیت لغو شد.")

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

    dp = app.dp
    dp.register_callback_query_handler(
        cancel_confirm,
        lambda c: str(c.data or "").startswith("mgmt:") and str(c.data or "").split(":")[2:3] == ["cancel"],
        state="*",
    )
    dp.register_callback_query_handler(
        cancel_confirmed,
        lambda c: str(c.data or "").startswith("mgmt:") and str(c.data or "").split(":")[2:3] == ["cancel_confirm"],
        state="*",
    )
    dp.register_callback_query_handler(
        cancel_abort,
        lambda c: str(c.data or "").startswith("mgmt:") and str(c.data or "").split(":")[2:3] == ["cancel_abort"],
        state="*",
    )
    dp.register_message_handler(
        finish_command,
        lambda message: (message.text or "").strip().casefold() in {x.casefold() for x in ALIASES},
        content_types=types.ContentTypes.TEXT,
        state="*",
    )

    # The production dispatcher is ordered; these handlers must own the
    # lifecycle callbacks before the old immediate-finish/cancel handlers.
    _move_front(dp, lambda fn: getattr(fn, "__name__", "") in {"cancel_confirm", "cancel_confirmed", "cancel_abort", "finish_menu"})

    app._manual_end_game_installed = True
    logging.info("MANUAL_END_GAME installed: canonical finish menu + confirmed cancel")
    return True
