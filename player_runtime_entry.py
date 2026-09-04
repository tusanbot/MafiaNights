"""Production entry point for the persistent MafiaNights runtime."""

import logging
import main1 as main
from player_runtime_bridge import install as install_player_bridge
from runtime.production_bridge import install as install_persistent_bridge, startup as persistent_startup
from player_service import player_service

install_player_bridge(main)
_bridge = install_persistent_bridge(main)
main.player_service = player_service

# Webhook workers are short-lived, so FSM, scenarios and settings must use
# persistent storage rather than process memory or the read-only deployment FS.
from runtime.postgres_fsm_storage import install as install_postgres_fsm_storage
install_postgres_fsm_storage(main)
from runtime.scenario_persistence_patch import install as install_scenario_persistence_patch
install_scenario_persistence_patch(main)

from runtime.game_ui_bugfixes import install as install_game_ui_bugfixes
install_game_ui_bugfixes(main)
from runtime.lobby_ui_v6 import install as install_lobby_ui
install_lobby_ui(main)
from runtime.lobby_ui_v7_patch import install as install_lobby_v7_patch
install_lobby_v7_patch(main)
from runtime.lobby_legacy_bridge import install as install_lobby_legacy_bridge
install_lobby_legacy_bridge(main)
from runtime.game_flow_ui_v2 import install as install_game_flow_ui_v2
game_flow_ui_v2 = install_game_flow_ui_v2(main)
from runtime.game_flow_authority import install as install_game_flow_authority
install_game_flow_authority(main)
from runtime.challenge_authority import install as install_challenge_authority
install_challenge_authority(main)
from runtime.callback_authorization import install as install_callback_authorization
install_callback_authorization(main)
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

# Canonical standalone text commands. This must be registered on main1.dp;
# commands.py intentionally no longer owns a second Dispatcher.
from commands import register_commands as register_text_commands
register_text_commands(main)

# MafiaAddons is instantiated by main1 during import. Replace its filesystem
# persistence with PostgreSQL before any add-on UI handler can read/write it.
from runtime.addons_persistence_patch import install as install_addons_persistence_patch
install_addons_persistence_patch(main)
from runtime.addons_menu_v2 import install as install_addons_menu_v2
install_addons_menu_v2(main)

# Do not globally replace main.display_name here. main1 already owns the
# canonical nickname/players resolution and the stable round engine performs
# its own safe fallback. A global wrapper changed the semantics of existing
# turn/challenge surfaces and caused generic names to leak into several UIs.

# SINGLE private-navigation owner for webhook mode. The old bootstrap and
# reorder modules are intentionally not installed: duplicate registrations were
# causing callbacks to fall through to legacy handlers.
from runtime.private_navigation_authority import install as install_private_navigation_authority
install_private_navigation_authority(main)

from runtime.stable_round_engine import install as install_stable_round_engine
from runtime.stable_round_policy import install as install_stable_round_policy
from runtime.stable_challenge_button_guard import install as install_stable_challenge_button_guard
from runtime.transition_ui_dedup import install as install_transition_ui_dedup
from runtime.role_distribution_notice import install as install_role_distribution_notice
from runtime.voting_runtime import install as install_voting_runtime

# These are callback-router/runtime registrations, not polling-only startup
# tasks. Install them at import time so webhook workers and polling both use the
# same authoritative day/turn/voting flow.
install_stable_round_engine(main)
install_stable_round_policy(main)
install_stable_challenge_button_guard(main)
install_transition_ui_dedup(main)
install_voting_runtime(main)

_original_startup = main.on_startup

async def on_startup(dp):
    results = await persistent_startup(main, _original_startup)
    logging.info("Persistent runtime startup recovery completed: %s", results)
    try:
        configured_gid = getattr(main, "ALLOWED_GROUP_ID", None)
        if configured_gid:
            main.group_chat_id = int(configured_gid)
            admins = await main.bot.get_chat_administrators(main.group_chat_id)
            main.admins = {a.user.id for a in admins}
            main.group_admins = list(main.admins)
    except Exception:
        logging.exception("Failed to initialize private UI group/admin authorization")

    # Polling mode only: webhook mode already has the import-time router.
    from runtime.final_private_ui import install as install_final_private_ui
    await install_final_private_ui(main)
    install_role_distribution_notice(main)
    logging.info("FINAL UI AUTHORITY ACTIVE")


if __name__ == "__main__":
    main.executor.start_polling(main.dp, skip_updates=True, on_startup=on_startup)
