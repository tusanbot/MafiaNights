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
from runtime.final_game_flow_authority import install as install_final_game_flow_authority
install_final_game_flow_authority(main)
from runtime.final_runtime_guard import install as install_final_runtime_guard
install_final_runtime_guard(main)
from runtime.final_turn_challenge_v3 import install as install_final_turn_challenge_v3
install_final_turn_challenge_v3(main)
from runtime.final_turn_challenge_v4 import install as install_final_turn_challenge_v4
install_final_turn_challenge_v4(main)
from runtime.final_next_authority_v5 import install as install_final_next_authority_v5
install_final_next_authority_v5(main)
from runtime.seat_emoji_patch import install as install_seat_emoji_patch
install_seat_emoji_patch(main)

# Unified private user dashboard.
from runtime.user_panel import install as install_user_panel
user_panel = install_user_panel(main)

# Connect the legacy private /start menu to the user dashboard.
from runtime.start_profile_patch import install as install_start_profile_patch
install_start_profile_patch(main)

# Add a return button from the dashboard to the legacy private start menu.
from runtime.user_panel_back_patch import install as install_user_panel_back_patch
install_user_panel_back_patch(main, user_panel)

# Normalize group-admin resolution for private management menus before those
# menus are instantiated and registered.
from runtime.admin_access_patch import install as install_admin_access_patch
install_admin_access_patch(main)

# Restore the complete legacy game-management menu while keeping the private
# menu as a controller; actual game/lobby creation happens in the configured group.
from runtime.game_management_menu_patch import install as install_game_management_menu_patch
install_game_management_menu_patch(main)

# Add player-list management, next-round silence and post-round extra turns.
from runtime.round_player_controls_patch import install as install_round_player_controls
install_round_player_controls(main)

# Authoritative private admin/scenario menus and updated help.
from runtime.admin_menus_v2 import install as install_admin_menus_v2
install_admin_menus_v2(main)
from runtime.addons_menu_v2 import install as install_addons_menu_v2
install_addons_menu_v2(main)
from runtime.admin_menu_cancel_patch import install as install_admin_menu_cancel_patch
install_admin_menu_cancel_patch(main)

# Re-run the authorization pass so handlers registered by the menu patches
# receive the same execution-time security boundary.
install_callback_authorization(main)

# Prevent stale role information from being exposed through the private
# "نقش من" command after a game or to non-participants.
from runtime.role_security_patch import install as install_role_security_patch
install_role_security_patch(main)

_original_startup = main.on_startup

async def on_startup(dp):
    results = await persistent_startup(main, _original_startup)
    logging.info("Persistent runtime startup recovery completed: %s", results)

if __name__ == "__main__":
    main.executor.start_polling(main.dp, skip_updates=True, on_startup=on_startup)
