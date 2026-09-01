"""Production entry point for the staged persistent-runtime cut-over."""

import logging

# ``main.py`` was intentionally removed so Vercel would not auto-detect the
# legacy polling entrypoint. ``main1.py`` is the preserved legacy application
# and is the module that the persistent-runtime bridges must wrap.
import main1 as main

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
