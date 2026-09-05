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
from runtime.production_lobby import install as install_production_lobby


TOKEN = os.getenv("API_TOKEN")
if not TOKEN:
    raise ValueError("API_TOKEN environment variable is not set!")

logging.basicConfig(level=logging.INFO)

app = MafiaApplicationV4(TOKEN)
bot = app.bot
dp = app.dp

persistence_status = install_persistence(app)
production_lobby_status = install_production_lobby(app)
logging.info("PRODUCTION_RUNTIME_ACTIVE persistent=1 canonical_lobby=%s", production_lobby_status)


async def on_startup(dp):
    logging.info("MafiaNights clean runtime startup; persistence=%s canonical_lobby=%s", persistence_status, production_lobby_status)
    await app.startup()

    # Rehydrate the Telegram-facing group context from durable state. Without
    # this, admin/game-management callbacks that rely on app.ui would be blind
    # after a process restart until a new-game action happened.
    try:
        allowed_group_id = int(os.getenv("ALLOWED_GROUP_ID", "-1002356353761"))
        active_game = app.runtime.state.active_game(allowed_group_id)
        if active_game:
            app.ui.group_chat_id = allowed_group_id
            logging.info("Restored active game context for group %s", allowed_group_id)
    except Exception:
        logging.exception("Failed to restore active Telegram game context")


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
