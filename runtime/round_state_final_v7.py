"""Small terminal compatibility fix for challenge-turn actor resolution."""
from __future__ import annotations

from functools import wraps

from aiogram.dispatcher.handler import CancelHandler


def _handler(item):
    return getattr(item, "handler", None)


def install(main):
    registry = getattr(getattr(main.dp, "callback_query_handlers", None), "handlers", None)
    if registry is None or getattr(main, "_round_state_final_v7", False):
        return False

    for item in list(registry):
        fn = _handler(item)
        if not getattr(fn, "_v6_next", False) or getattr(fn, "_v7_actor", False):
            continue

        original = fn

        @wraps(original)
        async def next_v7(callback, _original=original):
            # During a challenge the actual actionable actor is the challenger,
            # while turn_order/current_turn_index still point at the paused target.
            if getattr(main, "challenge_mode", False):
                active_challengers = list(getattr(main, "active_challenger_seats", set()) or set())
                if len(active_challengers) == 1:
                    challenger_seat = int(active_challengers[0])
                    order = getattr(main, "turn_order", None)
                    index = getattr(main, "current_turn_index", None)
                    if isinstance(order, list) and isinstance(index, int) and 0 <= index < len(order):
                        saved = order[index]
                        order[index] = challenger_seat
                        try:
                            return await _original(callback)
                        finally:
                            order[index] = saved
            return await _original(callback)

        next_v7._v7_actor = True
        item.handler = next_v7
        registry.insert(0, registry.pop(registry.index(item)))
        break

    main._round_state_final_v7 = True
    return True
