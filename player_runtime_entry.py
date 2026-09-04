"""Production entry point for the persistent MafiaNights runtime."""

import logging
import main1 as main
from player_runtime_bridge import install as install_player_bridge
from runtime.production_bridge import install as install_persistent_bridge, startup as persistent_startup
from player_service import player_service

install_player_bridge(main)
_bridge = install_persistent_bridge(main)
main.player_service = player_service

# Core game/lobby engines. These are state/flow layers, not private-menu owners.
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

# User dashboard and the existing add-ons controller remain separate from game/lobby UI.
from runtime.user_panel import install as install_user_panel
user_panel = install_user_panel(main)
from runtime.start_profile_patch import install as install_start_profile_patch
install_start_profile_patch(main)
from runtime.user_panel_back_patch import install as install_user_panel_back_patch
install_user_panel_back_patch(main, user_panel)
from runtime.addons_menu_v2 import install as install_addons_menu_v2
install_addons_menu_v2(main)

# Webhook requests import this module directly and do not depend on aiogram's
# polling startup hook. Bootstrap the private entry-point handlers immediately.
from runtime.private_ui_bootstrap import install as install_private_ui_bootstrap
install_private_ui_bootstrap(main)

# Final import-time navigation authority. It is intentionally installed after
# every legacy/bridge layer so its routes win in webhook mode as well.
from runtime.private_navigation_authority import install as install_private_navigation_authority
install_private_navigation_authority(main)

# Scenario CRUD uses the existing main1 API, but scenario persistence must not
# crash on Vercel's read-only deployment filesystem.
from runtime.scenario_persistence_patch import install as install_scenario_persistence_patch
install_scenario_persistence_patch(main)

# The richer private menu remains available for polling/startup environments.
from runtime.final_private_ui import install as install_final_private_ui

from runtime.stable_round_engine import install as install_stable_round_engine
from runtime.stable_round_policy import install as install_stable_round_policy
from runtime.stable_challenge_button_guard import install as install_stable_challenge_button_guard
from runtime.transition_ui_dedup import install as install_transition_ui_dedup
from runtime.role_distribution_notice import install as install_role_distribution_notice

_original_startup = main.on_startup

async def on_startup(dp):
    results = await persistent_startup(main, _original_startup)
    logging.info("Persistent runtime startup recovery completed: %s", results)

    # The private UI must know the configured game group even before a lobby exists.
    try:
        configured_gid = getattr(main, "ALLOWED_GROUP_ID", None)
        if configured_gid:
            main.group_chat_id = int(configured_gid)
            admins = await main.bot.get_chat_administrators(main.group_chat_id)
            main.admins = {a.user.id for a in admins}
            main.group_admins = list(main.admins)
            logging.info(
                "Private UI authorization synced: group=%s admins=%d",
                main.group_chat_id,
                len(main.admins),
            )
    except Exception:
        logging.exception("Failed to initialize private UI group/admin authorization")

    # StableRoundEngine is the sole authority for start/next/challenge/day
    # transitions. The policy module only applies pre-day mute state and the
    # muted-challenge restriction; it does not implement another turn engine.
    install_stable_round_engine(main)
    install_stable_round_policy(main)
    install_stable_challenge_button_guard(main)
    install_transition_ui_dedup(main)
    logging.info("Stable round engine installed as the sole turn/round authority")

    # Final private UI is installed last and moved to the front of the aiogram 2.x registries.
    await install_final_private_ui(main)
    install_role_distribution_notice(main)
    logging.info("FINAL UI AUTHORITY ACTIVE: private start + management are isolated from lobby")


if __name__ == "__main__":
    main.executor.start_polling(main.dp, skip_updates=True, on_startup=on_startup)
