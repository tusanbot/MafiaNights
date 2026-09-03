"""Production entry point for the persistent MafiaNights runtime."""

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

# Game-flow/persistence layers remain active; the speaking-turn lifecycle is
# intentionally NOT assembled from the historical v2/v3/v8/v9/v10/v11 stack.
authoritative_game_flow = None
from runtime.game_flow_authority import install as install_game_flow_authority
authoritative_game_flow = install_game_flow_authority(main)
from runtime.challenge_authority import install as install_challenge_authority
install_challenge_authority(main)
from runtime.callback_authorization import install as install_callback_authorization
install_callback_authorization(main)
from runtime.final_game_flow_authority import install as install_final_game_flow_authority
install_final_game_flow_authority(main)
from runtime.final_runtime_guard import install as install_final_runtime_guard
install_final_runtime_guard(main)
from runtime.seat_emoji_patch import install as install_seat_emoji_patch
install_seat_emoji_patch(main)

from runtime.user_panel import install as install_user_panel
user_panel = install_user_panel(main)
from runtime.start_profile_patch import install as install_start_profile_patch
install_start_profile_patch(main)
from runtime.user_panel_back_patch import install as install_user_panel_back_patch
install_user_panel_back_patch(main, user_panel)
from runtime.admin_access_patch import install as install_admin_access_patch
install_admin_access_patch(main)
from runtime.game_management_menu_patch import install as install_game_management_menu_patch
install_game_management_menu_patch(main)
from runtime.admin_menus_v2 import install as install_admin_menus_v2
install_admin_menus_v2(main)
from runtime.addons_menu_v2 import install as install_addons_menu_v2
install_addons_menu_v2(main)
from runtime.admin_menu_cancel_patch import install as install_admin_menu_cancel_patch
install_admin_menu_cancel_patch(main)
install_callback_authorization(main)
from runtime.role_security_patch import install as install_role_security_patch
install_role_security_patch(main)

from runtime.stable_round_engine import install as install_stable_round_engine

_original_startup = main.on_startup

async def on_startup(dp):
    results = await persistent_startup(main, _original_startup)
    logging.info("Persistent runtime startup recovery completed: %s", results)

    # IMPORTANT: this is the only round/turn/challenge transition layer.
    # It removes legacy next/start/challenge callback handlers from the
    # dispatcher and installs one deterministic finite-state engine.
    install_stable_round_engine(main)
    logging.info("Stable round engine is the sole turn/challenge authority")


if __name__ == "__main__":
    main.executor.start_polling(main.dp, skip_updates=True, on_startup=on_startup)
