"""Hard cutover of legacy lobby callback handlers to the persistent lobby owner."""
from __future__ import annotations

import logging


def install(main):
    dp = main.dp
    handlers = getattr(dp.callback_query_handlers, "handlers", [])
    by_name = {}
    for item in handlers:
        fn = getattr(item, "callback", None)
        if fn is not None:
            by_name.setdefault(getattr(fn, "__name__", ""), fn)

    v6_new = by_name.get("new")
    if v6_new is None:
        logging.error("lobby callback cutover: v6 new handler not found")
        return False

    # The old main1 handlers must not merely be lower priority: aiogram v2
    # keeps a large legacy handler table and later registrations can be
    # reordered by other runtime patches. Rebind the legacy callback handler
    # objects themselves to the persistent implementation.
    legacy_to_owner = {
        "start_game": v6_new,
        "choose_scenario": by_name.get("scenario"),
        "choose_moderator": by_name.get("moderator"),
    }
    rebound = []
    for item in handlers:
        fn = getattr(item, "callback", None)
        name = getattr(fn, "__name__", "")
        owner = legacy_to_owner.get(name)
        if owner is not None and fn is not owner:
            item.callback = owner
            rebound.append(name)

    def front(fn):
        current = getattr(dp.callback_query_handlers, "handlers", [])
        for i, item in enumerate(current):
            if getattr(item, "callback", None) is fn:
                current.insert(0, current.pop(i))
                return

    # Keep compatibility for stale messages whose callback_data uses the old
    # names, but make the callback itself the canonical v6 implementation.
    async def legacy_new(callback):
        await v6_new(callback)

    async def legacy_choose_scenario(callback):
        owner = by_name.get("scenario")
        if owner:
            await owner(callback)
        else:
            await v6_new(callback)

    async def legacy_choose_moderator(callback):
        owner = by_name.get("moderator")
        if owner:
            await owner(callback)
        else:
            await v6_new(callback)

    aliases = [
        (legacy_new, lambda c: c.data == "new_game"),
        (legacy_choose_scenario, lambda c: c.data == "choose_scenario"),
        (legacy_choose_moderator, lambda c: c.data == "choose_moderator"),
    ]
    for fn, flt in aliases:
        dp.register_callback_query_handler(fn, flt)
        front(fn)

    logging.info("CANONICAL_LOBBY_CALLBACK_CUTOVER_ACTIVE rebound=%s", rebound)
    return True
