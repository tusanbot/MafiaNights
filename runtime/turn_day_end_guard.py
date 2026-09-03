"""Final guard for the normal-turn -> day-end boundary.

The terminal round implementation intentionally supports administrator-selected
extra turns.  A challenge must never manufacture an extra-turn phase, however.
This guard records whether an extra turn was explicitly pending before the
terminal Next transition.  If the transition enters the extra phase without
such a pending selection, it is treated as a leaked/stale state: the transient
turn is cancelled and the normal day-end message is emitted immediately.
"""
from __future__ import annotations

import asyncio
import logging
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def _handler(item):
    return getattr(item, "handler", None)


def _gid(main):
    for obj in (main, getattr(main, "addons", None)):
        for attr in ("group_chat_id", "ALLOWED_GROUP_ID", "GROUP_ID", "group_id"):
            value = getattr(obj, attr, None)
            if value:
                try:
                    return int(value)
                except (TypeError, ValueError):
                    pass
    return None


async def _cancel_timer(main):
    task = getattr(main, "turn_timer_task", None)
    if task and not task.done():
        task.cancel()


async def _delete_current_turn(main):
    gid = _gid(main)
    mid = getattr(main, "current_turn_message_id", None)
    if gid and mid:
        try:
            await main.bot.delete_message(gid, int(mid))
        except Exception:
            pass
    main.current_turn_message_id = None


async def _force_day_end(main):
    """Terminate the day without invoking another turn transition."""
    await _cancel_timer(main)
    await _delete_current_turn(main)
    main._gm_extra_turn_active = False
    main._gm_extra_phase = False
    if isinstance(getattr(main, "_gm_extra_seats", None), set):
        main._gm_extra_seats.clear()
    main._gm_normal_round_finished = True

    gid = _gid(main)
    if not gid:
        return
    kb = InlineKeyboardMarkup(row_width=1).add(
        InlineKeyboardButton("🌙 شروع فاز شب", callback_data="start_night")
    )
    await main.bot.send_message(
        gid,
        "✅ همه بازیکنا صحبت کردن. فاز روز تموم شد.",
        reply_markup=kb,
    )


def install(main):
    if getattr(main, "_turn_day_end_guard_installed", False):
        return False

    dp = getattr(main, "dp", None)
    registry = getattr(getattr(dp, "callback_query_handlers", None), "handlers", None)
    if registry is None:
        logging.error("Day-end guard: callback registry unavailable")
        return False

    terminal = None
    for item in list(registry):
        fn = _handler(item)
        if getattr(fn, "_v10_next", False):
            terminal = fn
            break

    if terminal is None:
        logging.error("Day-end guard: V10 terminal Next handler not found")
        return False

    registry[:] = [item for item in registry if _handler(item) is not terminal]

    async def guarded_next(callback):
        # Only an explicitly selected admin extra turn may open the extra phase.
        explicit_extras = {
            int(x)
            for x in (getattr(main, "_gm_extra_next_round", set()) or set())
        }
        normal_phase_before = not bool(getattr(main, "_gm_extra_phase", False))
        result = await terminal(callback)

        if (
            normal_phase_before
            and not explicit_extras
            and bool(getattr(main, "_gm_extra_phase", False))
        ):
            logging.warning(
                "Day-end guard: leaked extra phase detected after normal turns; forcing day end"
            )
            # V8 has already sent the accidental extra-turn message. Remove it
            # and replace it with the canonical day-end transition.
            await _force_day_end(main)
        return result

    guarded_next.__name__ = "next_turn_day_end_guard"
    guarded_next._day_end_guard = True
    dp.register_callback_query_handler(
        guarded_next,
        lambda c: str(getattr(c, "data", "") or "").startswith("next_"),
        state="*",
    )

    handlers = getattr(dp.callback_query_handlers, "handlers", [])
    for i, item in enumerate(handlers):
        if _handler(item) is guarded_next:
            handlers.insert(0, handlers.pop(i))
            break

    main._turn_day_end_guard_installed = True
    logging.info("Final normal-turn/day-end guard installed")
    return True
