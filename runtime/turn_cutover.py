"""Runtime cut-over helpers for legacy turn/timer callbacks."""
from __future__ import annotations

import asyncio
import html
import logging
import time
from typing import Any

from runtime.migration_adapter import MigrationAdapter


async def persistent_countdown(legacy: Any, adapter: MigrationAdapter, seat: int, duration: int, message_id: int, is_challenge: bool = False) -> None:
    """Render the legacy timer while deriving its lifetime from persisted state."""
    group_id = getattr(legacy, "group_chat_id", None)
    if not group_id:
        return
    try:
        recovery = adapter.recover_turn(int(group_id))
        deadline = recovery.get("deadline_epoch") or (time.time() + int(duration))
        while True:
            remaining = max(0, int(round(deadline - time.time())))
            user_id = (getattr(legacy, "player_slots", {}) or {}).get(seat)
            player_name = (getattr(legacy, "players", {}) or {}).get(user_id, "بازیکن")
            mention = f"<a href='tg://user?id={user_id}'>{html.escape(str(player_name))}</a>"
            prefix = ""
            try:
                prefix = legacy.addons.settings.get("color", {}).get("timer_prefix", "")
            except Exception:
                pass
            text = f"{prefix} ⏳ {remaining // 60:02d}:{remaining % 60:02d}\n🎙 نوبت صحبت {mention} است. ({remaining} ثانیه)"
            try:
                await legacy.bot.edit_message_text(text, chat_id=int(group_id), message_id=message_id, parse_mode="HTML", reply_markup=legacy.turn_keyboard(seat, is_challenge))
            except Exception:
                pass
            if remaining <= 0:
                break
            await asyncio.sleep(min(5, remaining))
        adapter.finish_current_turn(int(group_id), reason="timer_expired")
        try:
            await legacy.send_temp_message(int(group_id), f"⏳ زمان {mention} به پایان رسید.", delay=5)
        except Exception:
            logging.exception("persistent timer expiry notification failed")
    except asyncio.CancelledError:
        raise


async def bridged_next_turn(legacy: Any, adapter: MigrationAdapter, callback: Any, original: Any):
    """Persist completion of the active turn before executing legacy transition/UI."""
    group_id = getattr(legacy, "group_chat_id", None)
    if group_id:
        try:
            adapter.finish_current_turn(int(group_id), reason="next")
        except Exception:
            logging.exception("persistent current-turn completion failed")
            await callback.answer("⚠️ ثبت پایان نوبت انجام نشد؛ نکست اجرا نشد.", show_alert=True)
            return
    return await original(callback)


def _replace_callback(dp: Any, function_name: str, replacement: Any) -> bool:
    registry = getattr(dp, "callback_query_handlers", None)
    handlers = getattr(registry, "handlers", None)
    if handlers is None:
        return False
    replaced = False
    for item in handlers:
        callback = getattr(item, "callback", None)
        if callback is None and isinstance(item, dict):
            callback = item.get("callback")
        if getattr(callback, "__name__", None) != function_name:
            continue
        if hasattr(item, "callback"):
            item.callback = replacement
        elif isinstance(item, dict):
            item["callback"] = replacement
        replaced = True
    return replaced


def install_legacy_turn_cutover(legacy: Any, adapter: MigrationAdapter) -> dict[str, bool]:
    """Install next-turn and timer bridges without rewriting the legacy main module."""
    result = {"next_turn": False, "countdown": False}
    original_countdown = getattr(legacy, "countdown", None)
    if original_countdown is not None and not getattr(original_countdown, "_persistent_bridge", False):
        async def countdown(seat, duration, message_id, is_challenge=False):
            return await persistent_countdown(legacy, adapter, seat, duration, message_id, is_challenge)
        countdown._persistent_bridge = True
        countdown._legacy_original = original_countdown
        legacy.countdown = countdown
        result["countdown"] = True
    original_next = getattr(legacy, "next_turn", None)
    dp = getattr(legacy, "dp", None)
    if original_next is not None and dp is not None and not getattr(original_next, "_persistent_bridge", False):
        async def next_turn(callback):
            return await bridged_next_turn(legacy, adapter, callback, original_next)
        next_turn._persistent_bridge = True
        next_turn._legacy_original = original_next
        result["next_turn"] = _replace_callback(dp, "next_turn", next_turn)
    return result
