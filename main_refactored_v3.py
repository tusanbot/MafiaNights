"""MafiaNights clean migration target with feature parity.

`main.py` is intentionally untouched and remains the rollback/reference
implementation. `main_refactored.py` is the clean baseline; this file adds
all migrated user-facing compatibility features through a dedicated service.
"""
from __future__ import annotations

import os

from main_refactored import MafiaApplication
from runtime.feature_parity_v3 import FeatureParityV3


class MafiaApplicationV3(MafiaApplication):
    def __init__(self, token: str):
        super().__init__(token)
        self.feature_parity = FeatureParityV3(self)
        self.feature_parity.register()


TOKEN = os.getenv("API_TOKEN")
if not TOKEN:
    raise ValueError("API_TOKEN environment variable is not set!")

app = MafiaApplicationV3(TOKEN)
bot = app.bot
dp = app.dp


async def on_startup(dp):
    await app.startup()


async def on_shutdown(dp):
    await app.shutdown()


if __name__ == "__main__":
    from aiogram.utils import executor
    executor.start_polling(dp, skip_updates=True, on_startup=on_startup, on_shutdown=on_shutdown)
