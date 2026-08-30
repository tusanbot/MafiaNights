"""Player identity middleware for the legacy aiogram v2 runtime.

This module is intentionally isolated so main.py can adopt the identity layer
without duplicating profile creation logic in every handler.
"""

import logging

from aiogram.dispatcher.middlewares import BaseMiddleware

from player_service import ensure_player


class PlayerIdentityMiddleware(BaseMiddleware):
    """Persist/update the Telegram user's profile before handler execution."""

    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger("mafia.identity")

    async def on_pre_process_update(self, update, data):
        user = None
        try:
            if getattr(update, "message", None) is not None:
                user = update.message.from_user
            elif getattr(update, "callback_query", None) is not None:
                user = update.callback_query.from_user
            elif getattr(update, "inline_query", None) is not None:
                user = update.inline_query.from_user
        except Exception:
            user = None

        if user is None:
            return

        try:
            ensure_player(user)
        except Exception:
            # Profile persistence must never take the bot down.
            self.logger.exception("player profile sync failed for user %s", getattr(user, "id", "?"))
