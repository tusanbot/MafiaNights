"""Explicit manual game completion for MafiaNights.

A running game must never be auto-finished when a new lobby is requested.  The
moderator/admin needs an explicit, durable action to finish the current game.
This module adds that action to the existing management panel and exposes a
small text-command fallback for cases where the inline keyboard is unavailable.
"""
from __future__ import annotations

import logging
from typing import Any

from aiogram import types
from aiogram.types import InlineKeyboardButton


ALIASES = {
    "اتمام بازی",
    "/اتمام_بازی",
    "/پایان_بازی",
    "/end_game",
    "/endgame",
}


def install(app: Any) -> bool:
    if getattr(app, "_manual_end_game_installed", False):
        return False

    management = getattr(app, "game_management", None)
    if management is not None and not getattr(management, "_manual_finish_panel_patched", False):
        original_panel = management.panel

        def panel(game_id):
            kb = original_panel(game_id)
            kb.row(InlineKeyboardButton("🏁 اتمام بازی", callback_data=f"mgmt:{game_id}:finish"))
            return kb

        management.panel = panel
        management._manual_finish_panel_patched = True

    async def finish_game(callback: types.CallbackQuery):
        gid = int(callback.message.chat.id)
        game = app.runtime.state.active_game(gid)
        if not game:
            await callback.answer("ℹ️ بازی فعالی وجود ندارد.", show_alert=True)
            return

        uid = int(callback.from_user.id)
        moderator = int(game.get("moderator_id") or 0)
        allowed = uid == moderator
        if not allowed:
            try:
                member = await app.bot.get_chat_member(gid, uid)
                allowed = member.status in {"creator", "administrator"}
            except Exception:
                allowed = False
        if not allowed:
            await callback.answer("⛔ فقط گرداننده یا مدیر گروه می‌تواند بازی را تمام کند.", show_alert=True)
            return

        game_id = game["id"]
        state = dict(game.get("state") or {})
        ok = app.runtime.state.games.update_game(game_id, status="finished", state={})
        if not ok:
            await callback.answer("❌ اتمام بازی انجام نشد.", show_alert=True)
            return

        # Close the durable current turn, if one exists. This does not alter
        # scores/results and prevents startup recovery from reopening the turn.
        try:
            turn = app.runtime.state.turns.current_turn(game_id)
            if turn:
                app.runtime.state.turns.finish_turn(turn["id"], state={"finished_manually": True})
        except Exception:
            logging.exception("manual game finish: current turn cleanup failed game=%s", game_id)

        for owner, attr in ((getattr(app, "ui", None), "turn_timer_task"), (app, "_voting_task")):
            task = getattr(owner, attr, None) if owner is not None else None
            if task is not None and hasattr(task, "done") and not task.done():
                task.cancel()

        lobby_message_id = state.get("lobby_message_id")
        if lobby_message_id:
            try:
                await app.bot.edit_message_text(
                    "🏁 <b>این بازی به‌صورت دستی به پایان رسید.</b>",
                    gid,
                    int(lobby_message_id),
                    parse_mode="HTML",
                    reply_markup=None,
                )
            except Exception:
                logging.info("finished game message could not be edited game=%s", game_id)

        await callback.message.edit_text(
            f"🏁 <b>بازی شماره {int(game.get('event_number') or 1)} به پایان رسید.</b>\n"
            "اکنون می‌توانید «بازی جدید» را ایجاد کنید.",
            parse_mode="HTML",
        )
        await callback.answer("🏁 بازی تمام شد.")

    async def finish_command(message: types.Message):
        gid = int(message.chat.id)
        game = app.runtime.state.active_game(gid)
        if not game:
            await message.reply("ℹ️ بازی فعالی برای اتمام وجود ندارد.")
            return

        uid = int(message.from_user.id)
        moderator = int(game.get("moderator_id") or 0)
        allowed = uid == moderator
        if not allowed:
            try:
                member = await app.bot.get_chat_member(gid, uid)
                allowed = member.status in {"creator", "administrator"}
            except Exception:
                allowed = False
        if not allowed:
            await message.reply("⛔ فقط گرداننده یا مدیر گروه می‌تواند بازی را تمام کند.")
            return

        game_id = game["id"]
        state = dict(game.get("state") or {})
        ok = app.runtime.state.games.update_game(game_id, status="finished", state={})
        if not ok:
            await message.reply("❌ اتمام بازی انجام نشد.")
            return

        try:
            turn = app.runtime.state.turns.current_turn(game_id)
            if turn:
                app.runtime.state.turns.finish_turn(turn["id"], state={"finished_manually": True})
        except Exception:
            logging.exception("manual game finish command: current turn cleanup failed game=%s", game_id)

        for owner, attr in ((getattr(app, "ui", None), "turn_timer_task"), (app, "_voting_task")):
            task = getattr(owner, attr, None) if owner is not None else None
            if task is not None and hasattr(task, "done") and not task.done():
                task.cancel()

        lobby_message_id = state.get("lobby_message_id")
        if lobby_message_id:
            try:
                await app.bot.edit_message_text(
                    "🏁 <b>این بازی به‌صورت دستی به پایان رسید.</b>",
                    gid,
                    int(lobby_message_id),
                    parse_mode="HTML",
                    reply_markup=None,
                )
            except Exception:
                logging.info("finished game message could not be edited game=%s", game_id)

        await message.reply(
            f"🏁 <b>بازی شماره {int(game.get('event_number') or 1)} به پایان رسید.</b>\n"
            "اکنون می‌توانید «بازی جدید» را ایجاد کنید.",
            parse_mode="HTML",
        )

    app.dp.register_callback_query_handler(
        finish_game,
        lambda c: str(c.data or "").startswith("mgmt:") and str(c.data or "").split(":")[2:3] == ["finish"],
        state="*",
    )
    app.dp.register_message_handler(
        finish_command,
        lambda message: (message.text or "").strip().lower() in ALIASES,
        content_types=types.ContentTypes.TEXT,
        state="*",
    )
    app._manual_end_game_installed = True
    logging.info("MANUAL_END_GAME installed: inline management button + commands")
    return True
