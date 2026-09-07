"""Make the canonical production lobby handlers win aiogram dispatch order."""
from __future__ import annotations

import logging
from typing import Any


# These are the callback function names created by runtime.production_lobby.
# Do not rely on a hard-coded tail count: new gameplay handlers are installed
# after the lobby, so a fixed count can accidentally move unrelated handlers.
CANONICAL_LOBBY_HANDLER_NAMES = {
    "new_game",
    "join",
    "leave",
    "choose_scenario",
    "scenario_selected",
    "moderator_selected",
    "seat",
    "reserve",
    "change_scenario",
    "change_moderator",
    "cancel_game",
}


def _callback_name(item: Any) -> str:
    callback = getattr(item, "callback", None)
    if callback is None and isinstance(item, dict):
        callback = item.get("callback")
    return str(getattr(callback, "__name__", ""))


def install(app: Any) -> bool:
    dp = app.dp
    table = getattr(dp.callback_query_handlers, "handlers", None)
    if table is None:
        logging.error("CANONICAL_LOBBY_PRIORITY failed: handler table unavailable")
        return False

    canonical = [item for item in table if _callback_name(item) in CANONICAL_LOBBY_HANDLER_NAMES]
    if not canonical:
        logging.error("CANONICAL_LOBBY_PRIORITY failed: canonical handlers not found")
        return False

    canonical_ids = {id(item) for item in canonical}
    kept = [item for item in table if id(item) not in canonical_ids]
    table[:] = canonical + kept

    logging.info(
        "CANONICAL_LOBBY_PRIORITY_ACTIVE moved=%d total=%d",
        len(canonical),
        len(table),
    )
    return True
