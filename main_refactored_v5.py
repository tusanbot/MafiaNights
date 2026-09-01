"""MafiaNights production compatibility wrapper (v5).

This module keeps the existing v4 implementation intact while fixing a Python
attribute/name collision in aiogram v2 handler registration: MafiaApplication
uses ``roles`` both as a callback handler method and as a per-group dictionary.

The base constructor registers handlers before the dictionary is needed, so we
temporarily remove the instance dictionary during registration. The bound
handler method is then safely registered, and the dictionary is restored for
runtime role storage.
"""
from __future__ import annotations

import os
from typing import Any

from main_refactored_v4 import MafiaApplicationV4


class MafiaApplicationV5(MafiaApplicationV4):
    def _register_handlers(self) -> None:
        role_store: Any = getattr(self, "roles", None)
        if isinstance(role_store, dict):
            delattr(self, "roles")
        try:
            super()._register_handlers()
        finally:
            self.roles = role_store if isinstance(role_store, dict) else {}


TOKEN = os.getenv("API_TOKEN")
if not TOKEN:
    raise ValueError("API_TOKEN environment variable is not set!")

app = MafiaApplicationV5(TOKEN)
bot = app.bot
dp = app.dp


async def on_startup(dp):
    await app.startup()


async def on_shutdown(dp):
    await app.shutdown()
