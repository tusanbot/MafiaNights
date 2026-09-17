"""Canonical separation of lobby-management and live-game management.

This module is the single lifecycle/navigation layer for the central management
panel. It does not create a second lobby implementation: it only shapes the
existing management panel according to the authoritative game status.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


LOBBY_ONLY_ACTIONS = {
    "unreserve",
    "unreserve_pick",
    "refresh",
    "close",
    "scenario",
    "scenario_pick",
    "moderator_pick",
}
LIVE_OBSOLETE_ACTIONS = {
    "unreserve",
    "unreserve_pick",
    "refresh",
    "close",
    "scenario",
    "scenario_pick",
    "moderator_pick",
}


def _remove_management_handlers(dp, management: Any) -> int:
    table = getattr(getattr(dp, "callback_query_handlers", None), "handlers", [])
    kept = []
    removed = 0
    for item in table:
        fn = getattr(item, "callback", None)
        if getattr(fn, "__self__", None) is management and getattr(fn, "__name__", "") in {"refresh", "close", "cancel"}:
            removed += 1
            continue
        kept.append(item)
    table[:] = kept
    return removed


def _filter_panel(kb, status: str, game_id: int):
    """Keep one coherent action surface for each game phase."""
    rows = []
    hidden = LIVE_OBSOLETE_ACTIONS if status in {"running", "paused", "turn"} else set()
    for row in getattr(kb, "inline_keyboard", []) or []:
        kept = []
        for button in row:
            data = str(getattr(button, "callback_data", "") or "")
            action = data.split(":")[2] if data.startswith("mgmt:") and len(data.split(":")) >= 3 else ""
            if action in hidden:
                continue
            if status in {"running", "paused", "turn"} and data.startswith("game_history:"):
                continue
            if status in {"running", "paused", "turn"} and data.endswith(":return_lobby"):
                continue
            kept.append(button)
        if kept:
            rows.append(kept)
    kb.inline_keyboard = rows

    if status in {"running", "paused", "turn"}:
        kb.row(InlineKeyboardButton("⬅️ بازگشت", callback_data=f"mgmt:{game_id}:back_live"))
    else:
        kb.row(InlineKeyboardButton("⬅️ بازگشت به لابی", callback_data=f"mgmt:{game_id}:return_lobby"))
    return kb


def _live_control_markup(game_id: int):
    return InlineKeyboardMarkup(row_width=2).add(
        InlineKeyboardButton("🎩 انتخاب سردست", callback_data=f"day:{int(game_id)}:head"),
        InlineKeyboardButton("⚔ وضعیت چالش", callback_data=f"mgmt:{int(game_id)}:challenge"),
        InlineKeyboardButton("▶️ شروع دور", callback_data="start_round"),
        InlineKeyboardButton("⚙️ مدیریت بازی", callback_data=f"mgmt:{int(game_id)}:open"),
    )


def install(app: Any, management: Any) -> bool:
    dp = app.dp
    removed = _remove_management_handlers(dp, management)

    original_panel = management.panel
    if not getattr(management, "_canonical_phase_panel", False):
        def panel(game_id):
            game = management._game(int(app.group_chat_id)) if getattr(app, "group_chat_id", None) else None
            if not game:
                try:
                    game = management._game(int(game_id))
                except Exception:
                    game = None
            status = str((game or {}).get("status") or "lobby")
            return _filter_panel(original_panel(game_id), status, int(game_id))

        management.panel = panel
        management._canonical_phase_panel = True

    async def return_lobby(callback):
        gid = int(callback.message.chat.id)
        game = management._game(gid)
        if not game or not await management._allowed(callback, gid, game):
            await callback.answer("⛔ دسترسی ندارید یا بازی فعال نیست.", show_alert=True)
            return
        if str(game.get("status") or "") != "lobby":
            await callback.answer("❌ این دکمه فقط برای مدیریت لابی است.", show_alert=True)
            return
        renderer = getattr(app, "_render_production_lobby", None) or getattr(app, "_render_final_lobby", None)
        if not renderer:
            await callback.answer("❌ موتور لابی در دسترس نیست.", show_alert=True)
            return
        try:
            ok = bool(await renderer(gid, game))
        except Exception:
            logging.exception("return-to-lobby failed game=%s group=%s", game.get("id"), gid)
            ok = False
        await callback.answer("⬅️ به لابی برگشتید." if ok else "❌ بازگشت به لابی انجام نشد.", show_alert=not ok)

    async def back_live(callback):
        gid = int(callback.message.chat.id)
        game = management._game(gid)
        if not game or not await management._allowed(callback, gid, game):
            await callback.answer("⛔ دسترسی ندارید یا بازی فعال نیست.", show_alert=True)
            return
        if str(game.get("status") or "") not in {"running", "paused", "turn"}:
            await callback.answer("❌ بازی در حال اجرا نیست.", show_alert=True)
            return
        state = dict(game.get("state") or {})
        head = state.get("head_seat")
        text = "🌅 <b>شروع روز</b>\n\n🎭 پخش نقش انجام شد.\n\n"
        if head:
            text += f"🎩 سردست انتخاب شد: <b>صندلی {int(head)}</b>\n\n"
        text += "گرداننده می‌تواند سردست را انتخاب کند یا دور اول را شروع کند."
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=_live_control_markup(int(game["id"])))
        await callback.answer("⬅️ به پیام شروع بازی برگشتید.")

    async def cancel(callback):
        gid = int(callback.message.chat.id)
        game = management._game(gid)
        if not game or not await management._allowed(callback, gid, game):
            await callback.answer("⛔ دسترسی ندارید", show_alert=True)
            return
        status = str(game.get("status") or "")
        if status not in {"lobby", "running", "paused", "turn"}:
            await callback.answer("❌ این بازی دیگر قابل لغو نیست.", show_alert=True)
            return
        state = management._state(game)
        state["cancelled"] = True
        state["cancelled_at"] = datetime.now(timezone.utc).isoformat()
        state["cancel_reason"] = "manual"
        state["cancelled_from_status"] = status
        ok = app.runtime.state.games.update_game(game["id"], status="cancelled", state=state)
        if not ok:
            await callback.answer("❌ لغو بازی ثبت نشد.", show_alert=True)
            return
        lid = state.get("lobby_message_id") or state.get("control_message_id")
        if lid:
            try:
                await app.bot.edit_message_text("🚫 <b>این بازی لغو شد.</b>\n\nاطلاعات بازی حفظ شد و بازی دیگر فعال نیست.", gid, int(lid), parse_mode="HTML", reply_markup=None)
            except Exception:
                logging.info("cancelled game message could not be edited game=%s", game.get("id"))
        try:
            await callback.message.edit_text("🚫 <b>بازی لغو شد.</b>\n\nاین بازی در تاریخچه بازی‌های انجام‌شده ثبت نمی‌شود و امتیازی برای آن محاسبه نمی‌شود.", parse_mode="HTML")
        except Exception:
            pass
        await callback.answer("🚫 بازی لغو شد؛ بازی جدید قابل شروع است.")

    table = getattr(getattr(dp, "callback_query_handlers", None), "handlers", [])
    table[:] = [
        item for item in table
        if not (
            getattr(getattr(item, "callback", None), "__self__", None) is management
            and getattr(getattr(item, "callback", None), "__name__", "") == "cancel"
        )
    ]

    dp.register_callback_query_handler(
        return_lobby,
        lambda c: (lambda p: len(p) == 3 and p[0] == "mgmt" and p[2] == "return_lobby")(str(c.data or "").split(":")),
        state="*",
    )
    dp.register_callback_query_handler(
        back_live,
        lambda c: (lambda p: len(p) == 3 and p[0] == "mgmt" and p[2] == "back_live")(str(c.data or "").split(":")),
        state="*",
    )
    dp.register_callback_query_handler(
        cancel,
        lambda c: (lambda p: len(p) == 3 and p[0] == "mgmt" and p[2] == "cancel")(str(c.data or "").split(":")),
        state="*",
    )

    handlers = getattr(getattr(dp, "callback_query_handlers", None), "handlers", [])
    for item in handlers:
        fn = getattr(item, "callback", None)
        if getattr(fn, "__name__", "") != "new":
            continue
        if getattr(fn, "_authoritative_guard", False):
            break
        original_new = fn

        async def guarded_new(callback, _original=original_new):
            gid = int(callback.message.chat.id)
            active = app.runtime.state.active_game(gid)
            status = str((active or {}).get("status") or "")
            if status in {"lobby", "running", "paused", "turn"}:
                if status in {"running", "paused", "turn"}:
                    app.game_running = True
                    app.round_active = status == "turn"
                    await callback.answer("⚠️ بازی در حال اجراست.", show_alert=True)
                else:
                    app.game_running = False
                    app.round_active = False
                    await callback.answer("⚠️ یک لابی فعال وجود دارد.", show_alert=True)
                return
            app.game_running = False
            app.round_active = False
            app.lobby_active = False
            app.current_turn_index = 0
            app.current_turn_seat = None
            app.turn_order = []
            app.player_slots = {}
            await _original(callback)

        guarded_new.__name__ = "authoritative_new"
        guarded_new._authoritative_guard = True
        item.callback = guarded_new
        break

    logging.info("LOBBY_MANAGEMENT_CANONICAL phase-aware panel installed removed=%d", removed)
    return True
