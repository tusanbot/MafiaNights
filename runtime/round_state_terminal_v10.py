"""Terminal race/idempotency guard for the MafiaNights round state machine.

This layer does not introduce another turn algorithm. It makes the v8/v9
state machine single-transition and idempotent so duplicate callbacks,
repeated start_turn calls, and timer races cannot create multiple turns or
skip the day-end transition.
"""
from __future__ import annotations

import asyncio
import time
from functools import wraps
from aiogram.dispatcher.handler import CancelHandler


def _handler(item):
    return getattr(item, "handler", None)


def _ensure(main):
    if not hasattr(main, "_gm_transition_lock"):
        main._gm_transition_lock = asyncio.Lock()
    if not hasattr(main, "_gm_start_guard"):
        main._gm_start_guard = None
    if not hasattr(main, "_gm_day_generation"):
        main._gm_day_generation = 0
    if not hasattr(main, "_gm_day_ended"):
        main._gm_day_ended = False


def install(main):
    _ensure(main)
    dp = getattr(main, "dp", None)
    registry = getattr(getattr(dp, "callback_query_handlers", None), "handlers", None)
    if registry is None or getattr(main, "_round_state_terminal_v10", False):
        return False

    # 1) Serialize the terminal V8 Next transition. There must never be two
    # concurrent transitions of current_turn_index.
    v8_next = None
    for item in list(registry):
        fn = _handler(item)
        if getattr(fn, "_v8_next", False):
            v8_next = fn
            break

    if v8_next is not None:
        # Remove only the V8 handler; leave challenge handlers untouched.
        registry[:] = [x for x in registry if _handler(x) is not v8_next]

        async def next_terminal(callback):
            _ensure(main)
            async with main._gm_transition_lock:
                # A Telegram callback can be delivered more than once. The
                # V8 handler already validates the clicked seat against the
                # current seat; serializing here makes that validation atomic
                # with the index increment.
                return await v8_next(callback)

        next_terminal._v10_next = True
        dp.register_callback_query_handler(
            next_terminal,
            lambda c: str(getattr(c, "data", "") or "").startswith("next_"),
            state="*",
        )
        # Terminal handler must be first.
        for i, item in enumerate(list(registry)):
            if _handler(item) is next_terminal:
                registry.insert(0, registry.pop(i))
                break

    # 2) Guard start_turn. The same logical turn may only be started once.
    old_start = getattr(main, "start_turn", None)
    if old_start is not None and not getattr(old_start, "_v10_start", False):
        @wraps(old_start)
        async def start_terminal(seat, duration=120, is_challenge=False):
            _ensure(main)
            try:
                seat = int(seat)
            except Exception:
                return await old_start(seat, duration=duration, is_challenge=is_challenge)

            phase = (
                "challenge" if is_challenge else
                "extra" if getattr(main, "_gm_extra_turn_active", False) or getattr(main, "_gm_extra_phase", False) else
                "normal"
            )
            idx = int(getattr(main, "current_turn_index", 0))
            generation = int(getattr(main, "_gm_day_generation", 0))
            key = (generation, phase, seat, idx)

            # Do not suppress a legitimate transition to a different phase,
            # seat, or index. Suppress only an exact duplicate start.
            if main._gm_start_guard == key:
                current_msg = getattr(main, "current_turn_message_id", None)
                if current_msg:
                    return current_msg
                # If there is no message, allow recovery from a failed send.

            main._gm_start_guard = key
            return await old_start(seat, duration=duration, is_challenge=is_challenge)

        start_terminal._v10_start = True
        main.start_turn = start_terminal

    # 3) Reset is a day boundary. Increment generation and clear all transient
    # idempotency state. Pending NEXT-DAY mute remains owned by v8 and survives.
    old_reset = getattr(main, "reset_round_data", None)
    if old_reset is not None and not getattr(old_reset, "_v10_reset", False):
        @wraps(old_reset)
        def reset_terminal(*args, **kwargs):
            result = old_reset(*args, **kwargs)
            _ensure(main)
            main._gm_day_generation += 1
            main._gm_start_guard = None
            main._gm_day_ended = False
            return result
        reset_terminal._v10_reset = True
        main.reset_round_data = reset_terminal

    main._round_state_terminal_v10 = True
    return True
