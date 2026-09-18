"""Production entry point for the persistent MafiaNights runtime."""

import html
import logging
from types import SimpleNamespace

import main1 as main

from runtime.production_bridge import install as install_persistent_bridge, startup as persistent_startup
from player_service import player_service
from runtime.webhook_safety import install_latency, install_safe_callback_answer

install_safe_callback_answer()
_bridge = install_persistent_bridge(main)
main.player_service = player_service
install_latency(main.dp)
logging.info("PERSISTENCE_OPTIMIZATION_ACTIVE pool=serverless-safe identity-cache=60s active-game-cache=0.75s")

from runtime.postgres_fsm_storage import install as install_postgres_fsm_storage
install_postgres_fsm_storage(main)
from runtime.scenario_persistence_patch import install as install_scenario_persistence_patch
install_scenario_persistence_patch(main)
from runtime.game_ui_bugfixes import install as install_game_ui_bugfixes
install_game_ui_bugfixes(main)
from runtime.production_fastpath import install as install_production_fastpath
install_production_fastpath(main)

# Canonical lobby owner.
from runtime.lobby_ui_final import install as install_final_lobby
install_final_lobby(main)

# Canonical /start owner for the production Dispatcher. Keep this route here,
# outside the lobby/private UI modules, so later feature installers cannot leave
# /start without a single deterministic handler for either chat type.
from aiogram.dispatcher.handler import CancelHandler
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def _remove_conflicting_start_handlers():
    registry = getattr(getattr(main.dp, "message_handlers", None), "handlers", None)
    if registry is None:
        return 0
    names = {"start_cmd", "start_command", "canonical_start", "start_message", "show_start", "start_with_profile"}
    kept = []
    removed = 0
    for item in list(registry):
        fn = getattr(item, "handler", None) or getattr(item, "callback", None)
        if getattr(fn, "__name__", "") in names:
            removed += 1
            continue
        kept.append(item)
    registry[:] = kept
    return removed


async def _production_start(message):
    if message.chat.type in {"group", "supergroup"}:
        kb = InlineKeyboardMarkup(row_width=1).add(
            InlineKeyboardButton("🎮 بازی جدید", callback_data="fl_new")
        )
        await message.reply("🏠 <b>منوی اصلی Mafia Nights</b>", parse_mode="HTML", reply_markup=kb)
    elif message.chat.type == "private":
        from runtime.final_private_ui import start_keyboard
        await message.answer(
            "🎭 <b>Mafia Nights</b>\\n\\nیک گزینه را انتخاب کنید:",
            reply_markup=start_keyboard(),
            parse_mode="HTML",
        )
    else:
        raise CancelHandler()
    logging.info("PRODUCTION /START handled chat_type=%s user_id=%s", message.chat.type, message.from_user.id)
    return


def _install_production_start():
    _remove_conflicting_start_handlers()
    main.dp.register_message_handler(_production_start, commands=["start"], state="*", content_types=["text"])
    registry = getattr(getattr(main.dp, "message_handlers", None), "handlers", None)
    if registry:
        for i, item in enumerate(registry):
            fn = getattr(item, "handler", None) or getattr(item, "callback", None)
            if fn is _production_start:
                registry.insert(0, registry.pop(i))
                break
    logging.info("PRODUCTION /START authority armed")


_install_production_start()

# Canonical management owners: GameManagement is business logic and
# management_surface_final is the only management UI surface.
from runtime.game_management import GameManagement
main.game_management = GameManagement(main)
main.game_management.install()
from runtime.management_surface_final import install as install_management_surface
install_management_surface(main)

from runtime.end_game_control import install as install_manual_end_game
install_manual_end_game(main)
if not hasattr(main, "ui") or main.ui is None:
    main.ui = SimpleNamespace()

from runtime.role_distribution import install as install_role_distribution
install_role_distribution(main)
main._canonical_distribute_roles = main._role_distribution_handler
if getattr(main, "_render_final_lobby", None):
    main._render_production_lobby = main._render_final_lobby

from runtime.game_flow_ui_v2 import install as install_game_flow_ui_v2
install_game_flow_ui_v2(main)
from runtime.game_flow_authority import install as install_game_flow_authority
game_flow_authority = install_game_flow_authority(main)
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
from runtime.profile_schema_compat import install as install_profile_schema_compat
install_profile_schema_compat(main)
from runtime.profile_enhancements_fixed import install as install_profile_enhancements
profile_enhancements = install_profile_enhancements(main, user_panel)
main.profile_enhancements = profile_enhancements
from runtime.profile_db_compat import install as install_profile_db_compat
install_profile_db_compat(profile_enhancements)
from runtime.progress_schema_compat import install as install_progress_schema_compat
install_progress_schema_compat(main)
from commands import register_commands as register_text_commands
register_text_commands(main)
from runtime.command_surface_v2 import install as install_command_surface_v2
install_command_surface_v2(main)
from runtime.addons_persistence_patch import install as install_addons_persistence_patch
install_addons_persistence_patch(main)
from runtime.addons_menu_v2 import install as install_addons_menu_v2
install_addons_menu_v2(main)
from runtime.private_scenario_crud import install as install_private_scenario_crud
install_private_scenario_crud(main)
from runtime.progress_features_v4 import install as install_progress_features
_progress_features_runtime = install_progress_features(main)
main._progress_features_runtime = _progress_features_runtime

from runtime.stable_round_engine import install as install_stable_round_engine
from runtime.live_controls_v2 import install as install_live_controls_v2
from runtime.lobby_challenge_v2 import install as install_lobby_challenge_v2
from runtime.stable_round_policy import install as install_stable_round_policy
from runtime.stable_challenge_button_guard import install as install_stable_challenge_button_guard
from runtime.transition_ui_dedup import install as install_transition_ui_dedup
from runtime.voting_runtime import install as install_voting_runtime
install_stable_round_engine(main)
install_live_controls_v2(main)
install_lobby_challenge_v2(main)
install_stable_round_policy(main)
install_stable_challenge_button_guard(main)
install_transition_ui_dedup(main)
install_voting_runtime(main)

from runtime.game_info_security_v2 import install as install_game_info_security_v2
install_game_info_security_v2(main)

# Final runtime authorities are armed only after all feature installers have
# completed. No lobby/management implementation is installed here.
from runtime import production_cutover_final
production_cutover_final.install()


def _rearm_canonical_new_game():
    """Make the final lobby the sole owner of both new-game entry routes."""
    callbacks = getattr(getattr(main.dp, "callback_query_handlers", None), "handlers", [])
    messages = getattr(getattr(main.dp, "message_handlers", None), "handlers", [])

    # Even if a compatibility installer re-registered the legacy main1 callback,
    # it must delegate to the canonical lobby instead of creating its own UI.
    callbacks[:] = [
        item for item in callbacks
        if getattr(getattr(item, "handler", None) or getattr(item, "callback", None), "__name__", "") != "start_game"
    ]

    canonical = getattr(main, "_canonical_new_game_handler", None)
    if canonical is not None:
        for i, item in enumerate(callbacks):
            fn = getattr(item, "handler", None) or getattr(item, "callback", None)
            if fn is canonical:
                callbacks.insert(0, callbacks.pop(i))
                break

    # «بازی جدید» text is allowed to be handled by TextCommands, but that
    # handler now delegates to the same canonical callback. Prefer the final
    # lobby's direct text adapter when present.
    for i, item in enumerate(messages):
        fn = getattr(item, "handler", None) or getattr(item, "callback", None)
        if getattr(fn, "__name__", "") == "new_game_text":
            messages.insert(0, messages.pop(i))
            break
    logging.info("CANONICAL NEW_GAME rearmed: legacy_start_removed final_owner=%s",
                 bool(canonical))


_rearm_canonical_new_game()

_original_startup = main.on_startup

async def on_startup(dp):
    try:
        results = await persistent_startup(main, _original_startup)
        logging.info("Persistent runtime startup recovery completed: %s", results)
    except Exception:
        logging.exception("Persistent runtime startup recovery failed; continuing webhook startup")
    try:
        configured_gid = getattr(main, "ALLOWED_GROUP_ID", None)
        if configured_gid:
            main.group_chat_id = int(configured_gid)
            admins = await main.bot.get_chat_administrators(main.group_chat_id)
            main.admins = {a.user.id for a in admins}
            main.group_admins = list(main.admins)
    except Exception:
        logging.exception("Failed to initialize private UI group/admin authorization")
    from runtime.final_private_ui import install as install_final_private_ui
    await install_final_private_ui(main)
    from runtime.private_pv_authority_v2 import install as install_canonical_private_pv
    await install_canonical_private_pv(main)
    from runtime.pv_route_priority_v2 import install as install_pv_route_priority
    await install_pv_route_priority(main)
    from runtime.private_ui_recovery_v3 import install as install_private_ui_recovery_v3
    await install_private_ui_recovery_v3(main)
    from runtime.private_ui_recovery_v5 import install as install_private_ui_recovery_v5
    await install_private_ui_recovery_v5(main)
    from runtime.private_ui_recovery_v6 import install as install_private_ui_recovery_v6
    await install_private_ui_recovery_v6(main)
    from runtime.private_ui_recovery_v7 import install as install_private_ui_recovery_v7
    await install_private_ui_recovery_v7(main)
    from runtime.private_ui_recovery_v8 import install as install_private_ui_recovery_v8
    await install_private_ui_recovery_v8(main)
    # Private UI recovery layers register their own /start routes. Re-arm the single\n    # production owner after those installers so neither PV nor group /start can be shadowed.\n    _install_production_start()\n    # Re-apply progress UI after final private-UI authorities replace the start keyboard.
    try:
        progress_runtime = getattr(main, "_progress_features_runtime", None)
        if progress_runtime is not None:
            progress_runtime._patch_ui()
            progress_runtime.rearm()
            logging.info("PROGRESS UI AND HANDLERS REARMED AFTER PRIVATE UI AUTHORITIES")
    except Exception:
        logging.exception("Failed to re-apply progress UI after private UI authorities")

    from runtime.faceoff import install as install_faceoff
    await install_faceoff(main)

main.on_startup = on_startup
