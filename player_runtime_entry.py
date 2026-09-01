"""Production entry point for the staged persistent-runtime cut-over."""

import logging

# ``main.py`` was intentionally removed so Vercel would not auto-detect the
# legacy polling entrypoint. ``main1.py`` is the preserved legacy application
# and is the module that the persistent-runtime bridges must wrap.
import main1 as main

from player_runtime_bridge import install as install_player_bridge
from runtime.production_bridge import install as install_persistent_bridge, startup as persistent_startup
from player_service import player_service


install_player_bridge(main)
_bridge = install_persistent_bridge(main)
main.player_service = player_service

# Hotfixes are installed after the legacy module and both compatibility
# bridges are initialized, so they can safely replace the broken callback
# handlers and keep the persistent state authoritative.
from runtime.game_ui_bugfixes import install as install_game_ui_bugfixes
install_game_ui_bugfixes(main)

# Lobby-flow hotfix: moderator selection is configuration only; after choosing
# the moderator the UI must return to the game menu so scenario selection can
# still happen before any role distribution/start action.
from runtime.lobby_flow_fix import install as install_lobby_flow_fix
install_lobby_flow_fix(main)

_original_startup = main.on_startup


async def on_startup(dp):
    """Keep the legacy Telegram bootstrap, then recover persisted games."""
    results = await persistent_startup(main, _original_startup)
    logging.info("Persistent runtime startup recovery completed: %s", results)


if __name__ == "__main__":
    main.executor.start_polling(
        main.dp,
        skip_updates=True,
        on_startup=on_startup,
    )
