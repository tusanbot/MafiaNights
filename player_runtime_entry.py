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

from runtime.lobby_flow_fix import install as install_lobby_flow_fix
install_lobby_flow_fix(main)

from runtime.lobby_ui_v2 import install as install_lobby_ui_v2
install_lobby_ui_v2(main)

from runtime.lobby_ui_v3 import install as install_lobby_ui_v3
install_lobby_ui_v3(main)

# Exact-prefix guards must be registered last so callbacks such as
# v3_scenario_menu are never swallowed by v3_scenario_<index>.
from runtime.lobby_ui_v3_guards import install as install_lobby_ui_v3_guards
install_lobby_ui_v3_guards(main)

_original_startup = main.on_startup


async def on_startup(dp):
    results = await persistent_startup(main, _original_startup)
    logging.info("Persistent runtime startup recovery completed: %s", results)


if __name__ == "__main__":
    main.executor.start_polling(
        main.dp,
        skip_updates=True,
        on_startup=on_startup,
    )
