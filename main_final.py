"""Clean MafiaNights production candidate.

Phase 1 cutover candidate only. The existing ``player_runtime_entry.py`` and
``main1.py`` remain untouched as rollback/reference implementations.

Architecture:
    main_refactored + FeatureParityV4
        -> unified persistent storage
        -> aiogram polling/webhook application

This file intentionally does not install the legacy production bridge or its
patch/guard chain. Gameplay ownership therefore stays in the clean runtime.
Further proven production fixes are to be merged into their owning runtime
before this becomes the Docker entrypoint.
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

# Persistence is installed after application construction (handlers are already
# registered) but before startup, so every runtime update sees the durable FSM
# and database-backed scenario/add-on stores.
persistence_status = install_persistence(app)


async def on_startup(dp):
    logging.info("Clean runtime startup; persistence=%s", persistence_status)
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
