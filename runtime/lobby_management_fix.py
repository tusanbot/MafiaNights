"""Canonical lobby-management lifecycle controls.

This module no longer replaces the management panel or duplicates role
handlers.  It only removes the obsolete refresh/close/cancel registrations,
adds the single return-to-lobby action, and owns cancellation semantics.
"""
from __future__ import annotations

import logging
from typing import Any

from aiogram.types import InlineKeyboardButton


OBSOLETE_ACTIONS = {"refresh", "close", "cancel"}


def _remove_handlers(dp, *, management=None) -> int:
    table = getattr(getattr(dp, "callback_query_handlers", None), "handlers", [])
    kept = []
    removed = 0
    for item in table:
        fn = getattr(item, "callback", None)
        name = getattr(fn, "__name__", "")
        owner = getattr(fn, "__self__", None)
        if management is not None and owner is management and name in OBSOLETE_ACTIONS:
            removed += 1
            continue
        kept.append(item)
    table[:] = kept
    return removed


def _add_return_button(kb, game_id):
    """Remove obsolete navigation buttons and append the canonical return action."""
    rows = []
    for row in getattr(kb, "inline_keyboard", []) or []:
        kept = [
            button for button in row
            if not str(getattr(button, "callback_data", "") or "").endswith(":refresh")
            and not str(getattr(button, "callback_data", "") or "").endswith(":close")
        ]
        if kept:
            rows.append(kept)
    kb.inline_keyboard = rows
    kb.row(InlineKeyboardButton("⬅️ بازگشت به لابی", callback_data=f"mgmt:{game_id}:return_lobby"))
    return kb


def install(app: Any, management: Any) -> bool:
    dp = app.dp
    removed = _remove_handlers(dp, management=management)

    original_panel = management.panel
    if not getattr(management, "_canonical_lifecycle_panel", False):
        def panel(game_id):
            return _add_return_button(original_panel(game_id), game_id)
        management.panel = panel
        management._canonical_lifecycle_panel = True

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
            logging.exception("return-to-lobby failed game=%s group=%s", game.get("id"), gid)
            ok = False
        await callback.answer("⬅️ به لابی برگشتید." if ok else "❌ بازگشت به لابی انجام نشد.", show_alert=not ok)

    async def cancel(callback):
        gid = int(callback.message.chat.id)
        game = management._game(gid)
        if not game or not await management._allowed(callback, gid, game):
            await callback.answer("⛔ دسترسی ندارید.", show_alert=True)
            return
        status = str(game.get("status") or "")
        if status not in {"lobby", "running", "paused"}:
            await callback.answer("❌ این بازی دیگر قابل لغو نیست.", show_alert=True)
            return
        state = management._state(game)
        state["cancelled"] = True
        state["cancelled_at"] = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
        state["cancel_reason"] = "manual"
        state["cancelled_from_status"] = status
        # IMPORTANT: keep the complete game/player snapshot.  Cancellation is
        # archival data, but it is never a finished game and never contributes
        # to rating/history/achievements.
        ok = app.runtime.state.games.update_game(game["id"], status="cancelled", state=state)
        if not ok:
            await callback.answer("❌ لغو بازی ثبت نشد.", show_alert=True)
            return
        for attr in ("turn_timer_task", "voting_timer_task", "day_timer_task"):
            task = getattr(getattr(app, "ui", None), attr, None)
            if task and not task.done():
                try:
                    task.cancel()
                except Exception:
                    logging.exception("failed to cancel task %s", attr)
        lid = state.get("lobby_message_id")
        if lid:
            try:
                await app.bot.edit_message_text("🚫 <b>این بازی لغو شد.</b>\n\nاطلاعات بازی در بایگانی بازی‌های لغوشده نگهداری شد.", gid, int(lid), parse_mode="HTML", reply_markup=None)
            except Exception:
                pass
        try:
            await callback.message.edit_text("🚫 <b>بازی لغو شد.</b>\n\nاین بازی در تاریخچه بازی‌های انجام‌شده ثبت نمی‌شود.", parse_mode="HTML")
        except Exception:
            pass
        await callback.answer("🚫 بازی لغو شد؛ امتیاز و سابقه تغییر نکرد.")

    # Remove the old GameManagement.cancel registration before adding the
    # canonical one.  This prevents two cancellation implementations from
    # competing for the same callback.
    table = getattr(getattr(dp, "callback_query_handlers", None), "handlers", [])
    kept = []
    for item in table:
        fn = getattr(item, "callback", None)
        if getattr(fn, "__self__", None) is management and getattr(fn, "__name__", "") == "cancel":
            continue
        kept.append(item)
    table[:] = kept

    dp.register_callback_query_handler(
        return_lobby,
        lambda c: (lambda p: len(p) == 3 and p[0] == "mgmt" and p[2] == "return_lobby")(str(c.data or "").split(":")),
        state="*",
    )
    dp.register_callback_query_handler(
        cancel,
        lambda c: (lambda p: len(p) == 3 and p[0] == "mgmt" and p[2] == "cancel")(str(c.data or "").split(":")),
        state="*",
    )

    logging.info("LOBBY_LIFECYCLE_CANONICAL removed=%d return_lobby=active cancel=active", removed)
    return True
