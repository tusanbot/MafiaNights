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

from runtime.lobby_ui_v6 import install as install_lobby_ui
install_lobby_ui(main)

from runtime.lobby_ui_v7_patch import install as install_lobby_v7_patch
install_lobby_v7_patch(main)

from runtime.lobby_legacy_bridge import install as install_lobby_legacy_bridge
install_lobby_legacy_bridge(main)

from runtime.game_flow_ui_v2 import install as install_game_flow_ui_v2
install_game_flow_ui_v2(main)

authoritative_game_flow = None
from runtime.game_flow_authority import install as install_game_flow_authority
authoritative_game_flow = install_game_flow_authority(main)

from runtime.challenge_authority import install as install_challenge_authority
install_challenge_authority(main)

from runtime.callback_authorization import install as install_callback_authorization
install_callback_authorization(main)

# Final authoritative layer. It uses aiogram 2.25.1's real HandlerObj.handler
# field and replaces the legacy challenge/round callbacks after every bridge.
from runtime.final_game_flow_authority import install as install_final_game_flow_authority
install_final_game_flow_authority(main)

# Security boundary must run before the final lifecycle layer so the latter can
# apply the definitive actor checks and remain the last callback authority.
from runtime.final_runtime_guard import install as install_final_runtime_guard
install_final_runtime_guard(main)

# V3 captures the real turn message, repairs generic turn names, and handles
# challenge lifecycle cleanup.
from runtime.final_turn_challenge_v3 import install as install_final_turn_challenge_v3
install_final_turn_challenge_v3(main)

# V4 is the final lifecycle boundary for names, Next and challenge keyboards.
from runtime.final_turn_challenge_v4 import install as install_final_turn_challenge_v4
install_final_turn_challenge_v4(main)

# V5 is the terminal Next authority. It preserves the V4 permission model,
# but calls the original main1 next_turn directly so stale V3 seat validation
# cannot reject an accepted AFTER challenge.
from runtime.final_next_authority_v5 import install as install_final_next_authority_v5
install_final_next_authority_v5(main)

# Seat selection visual polish must be installed after the authoritative lobby
# layer so its seat_menu callback is the one users actually receive.
from runtime.seat_emoji_patch import install as install_seat_emoji_patch
install_seat_emoji_patch(main)

_original_startup = main.on_startup

async def on_startup(dp):
    results = await persistent_startup(main, _original_startup)
    logging.info("Persistent runtime startup recovery completed: %s", results)

if __name__ == "__main__":
    main.executor.start_polling(main.dp, skip_updates=True, on_startup=on_startup)
