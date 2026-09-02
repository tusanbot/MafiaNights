from __future__ import annotations

import logging
from functools import wraps

from aiogram.dispatcher.handler import CancelHandler
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def _handler(item):
    return getattr(item, "handler", None)


def _find(registry, name):
    for item in registry:
        if getattr(_handler(item), "__name__", "") == name:
            return item
    return None


async def _delete(main, message_id):
    if not message_id or not getattr(main, "group_chat_id", None):
        return
    try:
        await main.bot.delete_message(main.group_chat_id, message_id)
    except Exception:
        pass


async def _next_keyboard(main, message_id, seat):
    if not message_id or seat is None:
        return
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(InlineKeyboardButton("⏭ نکست", callback_data=f"next_{seat}"))
    try:
        await main.bot.edit_message_reply_markup(
            chat_id=main.group_chat_id,
            message_id=message_id,
            reply_markup=kb,
        )
    except Exception:
        logging.debug("V4: cannot restore next keyboard", exc_info=True)


async def _refresh_name(main, uid):
    try:
        member = await main.bot.get_chat_member(main.group_chat_id, uid)
        full_name = getattr(getattr(member, "user", None), "full_name", None)
        if full_name and isinstance(getattr(main, "players", None), dict):
            main.players[uid] = full_name
        return full_name
    except Exception:
        return None


async def _is_admin(main, uid):
    if not getattr(main, "group_chat_id", None):
        return False
    try:
        admins = await main.bot.get_chat_administrators(main.group_chat_id)
        return any(a.user.id == uid for a in admins)
    except Exception:
        return False


def _active_turn_seat(main):
    """Return the seat whose player owns the current turn, including challenges."""
    if getattr(main, "challenge_mode", False):
        # A challenge turn belongs to the challenger seat. The existing runtime
        # tracks those seats explicitly, so use the sole active challenger when
        # available. Fall back to the current normal turn only if necessary.
        active = list(getattr(main, "active_challenger_seats", set()) or set())
        if len(active) == 1:
            return active[0]
    try:
        return main.turn_order[main.current_turn_index]
    except Exception:
        return None


def _actor_can_next(main, uid, active_seat):
    """Only the active turn owner OR the selected moderator may press Next."""
    if uid == getattr(main, "moderator_id", None):
        return True
    if active_seat is None:
        return False
    owner_uid = (getattr(main, "player_slots", {}) or {}).get(active_seat)
    return uid == owner_uid


def install(main):
    registry = getattr(getattr(main.dp, "callback_query_handlers", None), "handlers", None)
    if registry is None:
        logging.error("V4: callback registry unavailable")
        return

    start = getattr(main, "start_turn", None)
    if start is not None and not getattr(start, "_v4_name_refresh", False):
        @wraps(start)
        async def start_turn_v4(seat, duration=120, is_challenge=False):
            uid = (getattr(main, "player_slots", {}) or {}).get(seat)
            if uid:
                await _refresh_name(main, uid)
            return await start(seat, duration=duration, is_challenge=is_challenge)
        start_turn_v4._v4_name_refresh = True
        main.start_turn = start_turn_v4

    item = _find(registry, "handle_challenge_response")
    if item is not None:
        original = _handler(item)
        if not getattr(original, "_v4_response", False):
            @wraps(original)
            async def response_v4(callback, _original=original):
                data = str(getattr(callback, "data", "") or "")
                parts = data.split("_")
                target_id = None
                if len(parts) >= 3:
                    try:
                        target_id = int(parts[-1])
                    except Exception:
                        pass
                target_seat = next((s for s, uid in (getattr(main, "player_slots", {}) or {}).items() if uid == target_id), None)
                old_turn_id = getattr(main, "current_turn_message_id", None)
                try:
                    result = await _original(callback)
                except CancelHandler:
                    if parts and parts[0] == "reject" and target_seat is not None:
                        await _next_keyboard(main, old_turn_id, target_seat)
                    raise

                if parts and parts[0] == "accept" and target_seat is not None:
                    timing = parts[1] if len(parts) > 1 else ""
                    if timing == "after":
                        await _next_keyboard(main, old_turn_id, target_seat)
                    elif timing == "before":
                        await _delete(main, old_turn_id)
                return result
            response_v4._v4_response = True
            item.handler = response_v4

    item = _find(registry, "next_turn")
    if item is not None:
        original = _handler(item)
        if not getattr(original, "_v4_next", False):
            @wraps(original)
            async def next_v4(callback, _original=original):
                uid = getattr(getattr(callback, "from_user", None), "id", None)
                active_seat = _active_turn_seat(main)

                # IMPORTANT: Telegram group administrator status is NOT a Next
                # permission. Only the configured moderator or the player who
                # owns the active turn may advance it. This prevents an admin
                # who is merely a player from skipping everybody else's turns.
                if not _actor_can_next(main, uid, active_seat):
                    await callback.answer("⛔ فقط صاحب نوبت یا گرداننده می‌تواند نکست بزند.", show_alert=True)
                    raise CancelHandler()

                try:
                    clicked_seat = int(str(callback.data).split("_", 1)[1])
                except Exception:
                    await callback.answer("⚠️ نوبت نامعتبر است.", show_alert=True)
                    raise CancelHandler()

                if active_seat is not None and clicked_seat != active_seat:
                    await callback.answer("⚠️ این نوبت دیگر فعال نیست.", show_alert=True)
                    raise CancelHandler()

                clicked_id = getattr(callback.message, "message_id", None)
                current_id = getattr(main, "current_turn_message_id", None)
                old_id = current_id or clicked_id

                await _delete(main, old_id)
                main.current_turn_message_id = None
                return await _original(callback)
            next_v4._v4_next = True
            item.handler = next_v4

    for wanted in ("next_turn", "handle_challenge_response"):
        item = _find(registry, wanted)
        if item is not None:
            registry.insert(0, registry.pop(registry.index(item)))

    main._final_turn_challenge_v4 = True
    logging.info("V4 turn/challenge lifecycle installed: Next = active player or moderator only")
