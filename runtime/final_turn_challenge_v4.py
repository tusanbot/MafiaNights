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


def _seat_for_uid(main, uid):
    if uid is None:
        return None
    return next(
        (seat for seat, player_uid in (getattr(main, "player_slots", {}) or {}).items() if player_uid == uid),
        None,
    )


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

    # V4 owns challenge-response UI only. Accepting an AFTER challenge does
    # not transfer the active turn yet: the target must press Next first.
    item = _find(registry, "handle_challenge_response")
    if item is not None:
        original = _handler(item)
        if not getattr(original, "_v4_response", False):
            @wraps(original)
            async def response_v4(callback, _original=original):
                data = str(getattr(callback, "data", "") or "")
                parts = data.split("_")
                target_id = None
                if len(parts) >= 4:
                    try:
                        target_id = int(parts[3])
                    except Exception:
                        pass

                target_seat = _seat_for_uid(main, target_id)
                old_turn_id = getattr(main, "current_turn_message_id", None)
                try:
                    result = await _original(callback)
                except CancelHandler:
                    raise

                if parts and parts[0] == "accept" and target_seat is not None:
                    if not isinstance(getattr(main, "challenge_target_locked", None), set):
                        main.challenge_target_locked = set()
                    main.challenge_target_locked.add(target_seat)
                    timing = parts[1] if len(parts) > 1 else ""
                    if timing == "after":
                        # pending_challenges[target_seat] is consumed by the
                        # legacy next_turn handler when the target presses Next.
                        await _next_keyboard(main, old_turn_id, target_seat)
                    elif timing == "before":
                        await _delete(main, old_turn_id)
                return result
            response_v4._v4_response = True
            item.handler = response_v4

    main._final_turn_challenge_v4 = True
    logging.info("V4 challenge UI installed; Next authority delegated to V5")
