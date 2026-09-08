"""Enforce the canonical production lobby dispatch boundary."""
from __future__ import annotations

import logging
from typing import Any


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

# These are the lobby entry/configuration methods on the old MafiaApplication
# surface.  They must never remain ahead of the canonical production flow.
LEGACY_LOBBY_HANDLER_NAMES = {
    "new_game",
    "join",
    "leave",
    "choose_scenario",
    "scenario_selected",
    "set_event_number",
    "_event_number_input",
}
LEGACY_APP_MODULE = "main_refactored"


def _callback(item: Any) -> Any:
    callback = getattr(item, "callback", None)
    if callback is None and isinstance(item, dict):
        callback = item.get("callback")
    return callback


def _callback_name(item: Any) -> str:
    return str(getattr(_callback(item), "__name__", ""))


def _is_legacy_app_handler(item: Any) -> bool:
    callback = _callback(item)
    if callback is None:
        return False
    name = str(getattr(callback, "__name__", ""))
    owner = getattr(callback, "__self__", None)
    owner_module = str(getattr(owner.__class__, "__module__", "")) if owner is not None else ""
    return name in LEGACY_LOBBY_HANDLER_NAMES and owner_module == LEGACY_APP_MODULE


def install(app: Any) -> bool:
    dp = app.dp
    table = getattr(dp.callback_query_handlers, "handlers", None)
    if table is None:
        logging.error("CANONICAL_LOBBY_PRIORITY failed: handler table unavailable")
        return False

    # Hard boundary: remove the old application's lobby entry/configuration
    # callbacks entirely. Merely moving the canonical handlers to the front is
    # insufficient when another callback can create/render the old lobby.
    before = len(table)
    table[:] = [item for item in table if not _is_legacy_app_handler(item)]
    purged = before - len(table)

    canonical = [item for item in table if _callback_name(item) in CANONICAL_LOBBY_HANDLER_NAMES]
    if not canonical:
        logging.error("CANONICAL_LOBBY_PRIORITY failed: canonical handlers not found")
        return False

    canonical_ids = {id(item) for item in canonical}
    kept = [item for item in table if id(item) not in canonical_ids]
    table[:] = canonical + kept
    logging.info(
        "CANONICAL_LOBBY_PRIORITY_ACTIVE moved=%d purged_legacy=%d total=%d",
        len(canonical), purged, len(table),
    )
    return True
