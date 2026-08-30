"""MafiaNights clean migration target, feature-parity v4."""
from __future__ import annotations

import os

from main_refactored import MafiaApplication
from runtime.feature_parity_v4 import FeatureParityV4


class MafiaApplicationV4(MafiaApplication):
    def __init__(self, token: str):
        super().__init__(token)
        self.feature_parity = FeatureParityV4(self)
        self.feature_parity.register()


TOKEN = os.getenv("API_TOKEN")
if not TOKEN:
    raise ValueError("API_TOKEN environment variable is not set!")

app = MafiaApplicationV4(TOKEN)
bot = app.bot
dp = app.dp


async def on_startup(dp):
    await app.startup()


async def on_shutdown(dp):
    await app.shutdown()


if __name__ == "__main__":
    from aiogram.utils import executor
    executor.start_polling(dp, skip_updates=True, on_startup=on_startup, on_shutdown=on_shutdown)
