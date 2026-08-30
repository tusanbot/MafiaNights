"""Production entry point for the staged persistent-runtime cut-over."""

import asyncio
import logging

import main
from player_runtime_bridge import install as install_player_bridge
from runtime.production_bridge import install as install_persistent_bridge, startup as persistent_startup


install_player_bridge(main)
_bridge = install_persistent_bridge(main)
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
