from __future__ import annotations

import logging
from functools import wraps

from aiogram.dispatcher.handler import CancelHandler


def _handler(item):
    return getattr(item, "handler", None)


def _find(registry, name):
    for item in registry:
        if getattr(_handler(item), "__name__", "") == name:
            return item
    return None


def _active_seat(main):
    # During an active challenge, the challenger owns the actionable Next.
    active = list(getattr(main, "active_challenger_seats", set()) or set())
    if getattr(main, "challenge_mode", False) and len(active) == 1:
        return active[0]
    try:
        return main.turn_order[main.current_turn_index]
    except Exception:
        return None


def _owner_uid(main, seat):
    return (getattr(main, "player_slots", {}) or {}).get(seat)


def _delete_message(main, message_id):
    if not message_id or not getattr(main, "group_chat_id", None):
        return
    try:
        return main.bot.delete_message(main.group_chat_id, message_id)
    except Exception:
        return None


def install(main):
    registry = getattr(getattr(main.dp, "callback_query_handlers", None), "handlers", None)
    if registry is None:
        logging.error("V5: callback registry unavailable")
        return

    item = _find(registry, "next_turn")
    if item is None:
        logging.error("V5: next_turn handler not found")
        return

    original = _handler(item)
    if getattr(original, "_v5_next", False):
        return

    @wraps(original)
    async def next_v5(callback, _original=original):
        uid = getattr(getattr(callback, "from_user", None), "id", None)
        active_seat = _active_seat(main)
        moderator = getattr(main, "moderator_id", None)
        owner = _owner_uid(main, active_seat)

        # Definitive permission rule: active player OR selected moderator.
        if uid != moderator and uid != owner:
            await callback.answer(
                "⛔ فقط صاحب نوبت یا گرداننده می‌تواند نکست بزند.",
                show_alert=True,
            )
            raise CancelHandler()

        try:
            clicked_seat = int(str(callback.data).split("_", 1)[1])
        except Exception:
            await callback.answer("⚠️ نوبت نامعتبر است.", show_alert=True)
            raise CancelHandler()

        if active_seat is not None and clicked_seat != active_seat:
            await callback.answer("⚠️ این نوبت دیگر فعال نیست.", show_alert=True)
            raise CancelHandler()

        old_turn_id = getattr(main, "current_turn_message_id", None) or getattr(
            callback.message, "message_id", None
        )
        await _delete_message(main, old_turn_id)
        main.current_turn_message_id = None

        # Call the original main1 handler directly. This deliberately bypasses
        # V3/V4 registry wrappers whose stale seat guard caused false
        # "این نوبت دیگر فعال نیست" errors after accepted AFTER challenges.
        try:
            result = await main.next_turn(callback)
        finally:
            # A completed challenge must not leave its challenger seat marked
            # active for the following normal turn.
            if not getattr(main, "challenge_mode", False):
                active = getattr(main, "active_challenger_seats", None)
                if isinstance(active, set):
                    active.clear()
        return result

    next_v5._v5_next = True
    item.handler = next_v5

    # Put the final authority first in aiogram's handler registry.
    try:
        registry.insert(0, registry.pop(registry.index(item)))
    except ValueError:
        pass

    main._final_next_authority_v5 = True
    logging.info("V5 Next authority installed: active player/moderator only; challenge-safe")
