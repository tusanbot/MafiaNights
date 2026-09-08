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
from runtime.production_lobby_priority import install as install_lobby_priority
from runtime.new_game_guard import install as install_new_game_guard
from runtime.role_distribution import install as install_role_distribution
from runtime.stable_round_engine import install as install_stable_round_engine
from runtime.voting_runtime import install as install_voting_runtime


TOKEN = os.getenv("API_TOKEN")
if not TOKEN:
    raise ValueError("API_TOKEN environment variable is not set!")

logging.basicConfig(level=logging.INFO)

app = MafiaApplicationV4(TOKEN)
bot = app.bot
dp = app.dp

persistence_status = install_persistence(app)
production_lobby_status = install_production_lobby(app)
production_lobby_priority_status = install_lobby_priority(app)
new_game_guard_status = install_new_game_guard(app)
role_distribution_status = install_role_distribution(app)
stable_round_status = install_stable_round_engine(app)
voting_runtime_status = install_voting_runtime(app)
logging.info(
    "PRODUCTION_RUNTIME_ACTIVE persistent=%s canonical_lobby=%s priority=%s new_game_guard=%s role_distribution=%s stable_round=%s voting=%s",
    persistence_status,
    production_lobby_status,
    production_lobby_priority_status,
    new_game_guard_status,
    role_distribution_status,
    stable_round_status,
    voting_runtime_status,
)


async def on_startup(dp):
    logging.info(
        "MafiaNights clean runtime startup; persistence=%s canonical_lobby=%s priority=%s new_game_guard=%s role_distribution=%s stable_round=%s voting=%s",
        persistence_status,
        production_lobby_status,
        production_lobby_priority_status,
        new_game_guard_status,
        role_distribution_status,
        stable_round_status,
        voting_runtime_status,
    )
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

            # Rehydrate the legacy-compatible fields consumed by the stable
            # round engine. The database remains authoritative; these fields
            # are only the Telegram-facing runtime bridge.
            rows = app.runtime.lobby_snapshot(allowed_group_id).get("players") or []
            app.player_slots = {
                int(row["seat"]): int(row["player_id"])
                for row in rows
                if row.get("seat") is not None
                and str(row.get("status") or "active") not in {"removed", "dead"}
            }
            app.moderator_id = int(active_game.get("moderator_id") or 0) or None
            app.group_chat_id = allowed_group_id
            app.game_running = str(active_game.get("status") or "") in {"running", "paused", "turn"}
            state = dict(active_game.get("state") or {})
            app.turn_order = [int(x) for x in state.get("turn_order") or sorted(app.player_slots)]
            app.current_turn_index = int(active_game.get("current_turn_index") or 0)
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
