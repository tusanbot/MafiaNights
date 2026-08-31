"""Telegram transport adapter for aiogram 2.x.

This adapter owns Telegram-specific update parsing and delegates game logic to
an injected application object. It intentionally contains no Rubika/Bale code.
"""
from __future__ import annotations

from typing import Any, Mapping

from .base import PlatformAdapter


class TelegramAdapter(PlatformAdapter):
    name = "telegram"

    def __init__(self, application: Any):
        self.application = application

    async def handle_update(self, update: Mapping[str, Any]) -> Any:
        """Handle normalized updates when invoked by a webhook bridge.

        Native aiogram Dispatcher webhook handling remains the preferred path;
        this method exists as a narrow transport boundary for tests and future
        multi-platform dispatch.
        """
        return await self.application.handle_telegram_update(update)
