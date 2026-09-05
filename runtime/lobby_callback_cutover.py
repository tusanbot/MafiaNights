"""Compatibility aliases that force old lobby buttons through lobby_ui_v6.

Telegram messages sent before a deployment can contain the old callback_data
values (new_game/choose_scenario/etc.). They must not revive main1's legacy
lobby handlers. This module discovers the already-registered v6 callbacks and
places small aliases in front of legacy routes.
"""
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
    v6_home = by_name.get("home")
    v6_back_s = by_name.get("back_s")

    if v6_new is None:
        logging.error("lobby callback cutover: v6 new handler not found")
        return False

    def front(fn):
        current = getattr(dp.callback_query_handlers, "handlers", [])
        for i, item in enumerate(current):
            if getattr(item, "callback", None) is fn:
                current.insert(0, current.pop(i))
                return

    async def legacy_new(callback):
        await v6_new(callback)

    async def legacy_choose_scenario(callback):
        await v6_new(callback)

    async def legacy_scenario(callback):
        # A stale scenario button cannot safely be mapped to an index without
        # rebuilding the v6 keyboard. Start the canonical flow instead.
        await v6_new(callback)

    async def legacy_choose_moderator(callback):
        await v6_new(callback)

    async def legacy_moderator(callback):
        await v6_new(callback)

    aliases = [
        (legacy_new, lambda c: c.data == "new_game"),
        (legacy_choose_scenario, lambda c: c.data == "choose_scenario"),
        (legacy_scenario, lambda c: str(c.data).startswith("scenario_")),
        (legacy_choose_moderator, lambda c: c.data == "choose_moderator"),
        (legacy_moderator, lambda c: str(c.data).startswith("moderator_")),
    ]
    for fn, flt in aliases:
        dp.register_callback_query_handler(fn, flt)
        front(fn)

    # Do not let an older bridge remain ahead of these aliases.
    logging.info("CANONICAL_LOBBY_CALLBACK_CUTOVER_ACTIVE")
    return True
