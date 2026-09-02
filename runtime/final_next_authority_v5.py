from __future__ import annotations

import logging
from functools import wraps

from aiogram.dispatcher.handler import CancelHandler


def _handler(item):
    return getattr(item, "handler", None)


def _active_seat(main):
    """Return the single seat that owns the currently actionable turn."""
    if getattr(main, "challenge_mode", False):
        active = list(getattr(main, "active_challenger_seats", set()) or set())
        return active[0] if len(active) == 1 else None
    try:
        return main.turn_order[main.current_turn_index]
    except Exception:
        return None


async def _delete_message(main, message_id):
    if not message_id or not getattr(main, "group_chat_id", None):
        return
    try:
        await main.bot.delete_message(main.group_chat_id, message_id)
    except Exception:
        pass


def install(main):
    dp = getattr(main, "dp", None)
    registry = getattr(getattr(dp, "callback_query_handlers", None), "handlers", None)
    if registry is None:
        logging.error("V5: callback registry unavailable")
        return

    # Keep the actual main1 state machine, but remove every registered wrapper
    # named next_turn. Earlier runtime layers could leave a stale HandlerObj
    # behind, which made it possible for an old seat check to win.
    core_next_turn = getattr(main, "next_turn", None)
    if core_next_turn is None:
        logging.error("V5: main.next_turn is missing")
        return

    # Record the challenge seat at the exact moment start_turn(...,
    # is_challenge=True) is called. This is the authoritative challenge state.
    start = getattr(main, "start_turn", None)
    if start is not None and not getattr(start, "_v5_start", False):
        @wraps(start)
        async def start_turn_v5(seat, duration=120, is_challenge=False):
            if is_challenge:
                if not isinstance(getattr(main, "active_challenger_seats", None), set):
                    main.active_challenger_seats = set()
                main.active_challenger_seats.clear()
                main.active_challenger_seats.add(seat)
            else:
                active = getattr(main, "active_challenger_seats", None)
                if isinstance(active, set):
                    active.clear()
            return await start(seat, duration=duration, is_challenge=is_challenge)

        start_turn_v5._v5_start = True
        main.start_turn = start_turn_v5

    removed = 0
    kept = []
    for item in list(registry):
        fn = _handler(item)
        if getattr(fn, "__name__", "") == "next_turn":
            removed += 1
        else:
            kept.append(item)
    registry[:] = kept

    async def next_authoritative(callback):
        uid = getattr(getattr(callback, "from_user", None), "id", None)
        active_seat = _active_seat(main)
        moderator = getattr(main, "moderator_id", None)
        owner = (getattr(main, "player_slots", {}) or {}).get(active_seat)

        # Only the active player or selected moderator can press Next.
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

        if active_seat is None:
            await callback.answer("⚠️ وضعیت نوبت چالش مشخص نیست. دوباره تلاش کنید.", show_alert=True)
            raise CancelHandler()

        if clicked_seat != active_seat:
            await callback.answer("⚠️ این نوبت دیگر فعال نیست.", show_alert=True)
            raise CancelHandler()

        old_turn_id = getattr(main, "current_turn_message_id", None) or getattr(
            getattr(callback, "message", None), "message_id", None
        )
        await _delete_message(main, old_turn_id)
        main.current_turn_message_id = None

        # Execute the legacy state machine directly. For an accepted AFTER
        # challenge it consumes pending_challenges[active_seat], enables
        # challenge_mode, and starts the challenger turn. The start_turn
        # wrapper above records that challenger as the only active seat.
        try:
            result = await core_next_turn(callback)
        finally:
            if not getattr(main, "challenge_mode", False):
                active = getattr(main, "active_challenger_seats", None)
                if isinstance(active, set):
                    active.clear()
        return result

    next_authoritative.__name__ = "next_turn"
    next_authoritative._v5_next = True
    dp.register_callback_query_handler(
        next_authoritative,
        lambda c: str(getattr(c, "data", "") or "").startswith("next_"),
    )

    registry = getattr(dp.callback_query_handlers, "handlers", [])
    for i, item in enumerate(registry):
        if _handler(item) is next_authoritative:
            registry.insert(0, registry.pop(i))
            break

    main._final_next_authority_v5 = True
    logging.info("V5: installed ONE terminal Next handler; removed %s stale handlers", removed)
