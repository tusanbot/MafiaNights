"""Production entry point for the staged persistent-runtime cut-over."""

import logging
import main1 as main
from player_runtime_bridge import install as install_player_bridge
from runtime.production_bridge import install as install_persistent_bridge, startup as persistent_startup
from player_service import player_service

install_player_bridge(main)
_bridge = install_persistent_bridge(main)
main.player_service = player_service

from runtime.game_ui_bugfixes import install as install_game_ui_bugfixes
install_game_ui_bugfixes(main)

# The lobby must remain usable even while the legacy SQLAlchemy DSN is broken.
# v6 keeps setup/lobby state in the bot runtime and owns the Telegram message flow.
from runtime.lobby_ui_v6 import install as install_lobby_ui
install_lobby_ui(main)

# Exact-message commands must run before the legacy catch-all message handler.
from runtime.lobby_ui_v7_patch import install as install_lobby_v7_patch
install_lobby_v7_patch(main)

# Old group messages may survive a deployment and still contain legacy callback
# data (new_game / choose_scenario / scenario_* / choose_moderator / moderator_*).
# Route those callbacks into v6 so no stale message can reopen the old lobby UI.
from runtime.lobby_legacy_bridge import install as install_lobby_legacy_bridge
install_lobby_legacy_bridge(main)

_original_startup = main.on_startup

async def on_startup(dp):
    results = await persistent_startup(main, _original_startup)
    logging.info("Persistent runtime startup recovery completed: %s", results)

if __name__ == "__main__":
    main.executor.start_polling(main.dp, skip_updates=True, on_startup=on_startup)
