"""Final callback registry guard for the day/turn lifecycle.

The production entry point installs round_player_controls_v3 during startup,
which historically registered a second ``next_`` handler whose ``advance``
function started another normal round after the last speaker. V11 makes the
V10 terminal handler the only handler allowed to consume ``next_*`` callbacks.
It deliberately does not change challenge or admin-control behavior.
"""
from __future__ import annotations

from aiogram.dispatcher.handler import CancelHandler


def _handler(item):
    return getattr(item, "handler", None)


def install(main):
    dp = getattr(main, "dp", None)
    registry = getattr(getattr(dp, "callback_query_handlers", None), "handlers", None)
    if registry is None or getattr(main, "_round_state_terminal_v11", False):
        return False

    # V10 wraps the V8 state machine and marks its handler with _v10_next.
    # Every other next_* callback is legacy/secondary and must not be able to
    # restart the normal speaking round.
    v10_next = None
    for item in list(registry):
        fn = _handler(item)
        if getattr(fn, "_v10_next", False):
            v10_next = fn
            break

    if v10_next is None:
        raise RuntimeError("V11 requires the V10 terminal next handler")

    removed = 0
    kept = []
    for item in list(registry):
        fn = _handler(item)
        if fn is v10_next:
            kept.append(item)
            continue
        try:
            data_probe = getattr(fn, "_callback_prefix", "")
        except Exception:
            data_probe = ""
        name = getattr(fn, "__name__", "")
        # Remove known next handlers by identity/marker/name. The broad
        # callback predicate is handled below by the surviving V10 handler.
        if name in {"next_turn", "next_v3", "next_v6", "next_v7", "next_authoritative", "next_terminal"} or getattr(fn, "_v5_next", False) or getattr(fn, "_v8_next", False) or getattr(fn, "_v10_next", False):
            removed += 1
            continue
        kept.append(item)
    registry[:] = kept

    # V10 is the sole next transition authority and must be first.
    try:
        registry.insert(0, registry.pop(registry.index(next(item for item in registry if _handler(item) is v10_next))))
    except (StopIteration, ValueError):
        pass

    main._round_state_terminal_v11 = True
    main._round_state_terminal_v11_removed = removed
    return True
