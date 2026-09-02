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

# IMPORTANT: only one lobby UI layer is installed. The previous lobby_flow_fix,
# lobby_ui_v3, guards and management modules registered overlapping callbacks
# and caused scenario/moderator/create-game transitions to race each other.
from runtime.lobby_ui_v2 import install as install_lobby_ui
install_lobby_ui(main)

_original_startup = main.on_startup


async def on_startup(dp):
    results = await persistent_startup(main, _original_startup)
    logging.info("Persistent runtime startup recovery completed: %s", results)


if __name__ == "__main__":
    main.executor.start_polling(main.dp, skip_updates=True, on_startup=on_startup)
