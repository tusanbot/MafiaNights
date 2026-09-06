"""Make the canonical production lobby handlers win aiogram dispatch order."""
from __future__ import annotations

import logging
from typing import Any


# production_lobby.install() currently appends 14 canonical callback handlers
# after MafiaApplicationV4's legacy handlers. Aiogram dispatches first match, so
# simply registering the new handlers was not enough. This helper moves exactly
# those canonical handlers to the front without disturbing non-lobby handlers.
CANONICAL_HANDLER_COUNT = 14


def install(app: Any) -> bool:
    dp = app.dp
    table = getattr(dp.callback_query_handlers, "handlers", None)
    if table is None or len(table) < CANONICAL_HANDLER_COUNT:
        logging.error("CANONICAL_LOBBY_PRIORITY failed: handler table too small")
        return False

    tail = table[-CANONICAL_HANDLER_COUNT:]
    del table[-CANONICAL_HANDLER_COUNT:]
    table[0:0] = tail
    logging.info(
        "CANONICAL_LOBBY_PRIORITY_ACTIVE moved=%d total=%d",
        CANONICAL_HANDLER_COUNT,
        len(table),
    )
    return True
