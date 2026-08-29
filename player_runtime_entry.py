"""Production entry point that installs the player-profile bridge before polling."""

import main
from player_runtime_bridge import install

install(main)

if __name__ == "__main__":
    main.executor.start_polling(
        main.dp,
        skip_updates=True,
        on_startup=main.on_startup,
    )
