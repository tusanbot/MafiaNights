"""MafiaNights clean production entry point.

The legacy implementation remains in ``main1.py`` as a rollback/reference
source. Production no longer imports or depends on it.

Architecture:
    MafiaApplicationV4 -> persistent runtime/state authority -> Telegram UI

Persistence is installed before startup so FSM, scenarios and addons use the
same durable storage boundary as gameplay state.
"""
from __future__ import annotations

import logging
import os

from main_refactored_v4 import MafiaApplicationV4
from runtime.final_persistence import install as install_persistence


TOKEN = os.getenv("API_TOKEN")
if not TOKEN:
    raise ValueError("API_TOKEN environment variable is not set!")

logging.basicConfig(level=logging.INFO)

app = MafiaApplicationV4(TOKEN)
bot = app.bot
dp = app.dp

persistence_status = install_persistence(app)


async def on_startup(dp):
    logging.info("MafiaNights clean runtime startup; persistence=%s", persistence_status)
    await app.startup()


async def on_shutdown(dp):
    await app.shutdown()


if __name__ == "__main__":
    from aiogram.utils import executor

    executor.start_polling(
        dp,
        skip_updates=True,
        on_startup=on_startup,
        on_shutdown=on_shutdown,
    )
