"""Make canonical production lobby handlers win aiogram dispatch order."""
from __future__ import annotations

import logging
from typing import Any


# Every callback owner defined by runtime.production_lobby is kept together so
# legacy handlers cannot intercept production lobby callbacks first.
CANONICAL_LOBBY_HANDLER_NAMES = {
    "new_game",
    "scenario_selected",
    "moderator_selected",
    "toggle_join",
    "seat",
    "reserve",
    "change_scenario",
    "change_moderator",
    "management",
    "event_number_menu",
    "event_number_adjust",
    "refresh_lobby",
    "back_lobby",
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
    logging.info("CANONICAL_LOBBY_PRIORITY_ACTIVE moved=%d total=%d", len(canonical), len(table))
    return True
