"""MafiaNights production entry point."""
from __future__ import annotations

import logging
import os

from main_refactored_v4 import MafiaApplicationV4
from runtime.final_persistence import install as install_persistence
from runtime.game_management import GameManagement
from runtime.game_management_compat import install as install_management_compat
from runtime.game_lifecycle import install as install_game_lifecycle
from runtime.management_navigation import install as install_management_navigation
from runtime.lobby import install as install_lobby
from runtime.role_distribution import install as install_role_distribution
from runtime.lobby_management_fix import install as install_lobby_management_fix
from runtime.stable_round_engine import install as install_stable_round_engine
from runtime.speaker_order_authority import install as install_speaker_order_authority
from runtime.final_identity_authority import install as install_final_identity_authority
from runtime.voting_end_game_patch import install as install_voting_end_game_patch
from runtime.voting_runtime import install as install_voting_runtime
from runtime.voting_timer_patch import install as install_voting_timer_patch
from runtime.voting_serverless_patch import install as install_voting_serverless_patch
from runtime.voting_end_target_patch import install as install_voting_end_target_patch
from runtime.voting_postfix import install as install_voting_postfix
from runtime.user_stats import install as install_user_stats
from runtime.player_scoring import install as install_player_scoring
from runtime.end_game_control import install as install_end_game_control

TOKEN = os.getenv("API_TOKEN")
if not TOKEN:
    raise ValueError("API_TOKEN environment variable is not set!")

logging.basicConfig(level=logging.INFO)

app = MafiaApplicationV4(TOKEN)
bot = app.bot
dp = app.dp

persistence_status = install_persistence(app)
management = GameManagement(app)
# One canonical management owner. Downstream installers use this reference.
app.game_management = management
install_management_navigation(app, management)
game_lifecycle_status = install_game_lifecycle(app, management)
management.install()
install_management_compat(app, management)
lobby_status = install_lobby(app)
role_distribution_status = install_role_distribution(app)
app._canonical_distribute_roles = app._role_distribution_handler
lobby_management_fix_status = install_lobby_management_fix(app, management)
stable_round_status = install_stable_round_engine(app)
voting_end_game_status = install_voting_end_game_patch(app)
voting_runtime_status = install_voting_runtime(app)
voting_timer_status = install_voting_timer_patch(app)
voting_serverless_status = install_voting_serverless_patch(app)
voting_end_target_status = install_voting_end_target_patch(app)
voting_postfix_status = install_voting_postfix(app)
speaker_order_status = install_speaker_order_authority(app)
final_identity_status = install_final_identity_authority(app)
user_stats_status = install_user_stats(app)
player_scoring_status = install_player_scoring(app)
# This installer activates the final management surface, manual completion,
# confirmed cancellation and final-message/history handlers on the real dispatcher.
end_game_control_status = install_end_game_control(app)
logging.info(
    "PRODUCTION_RUNTIME_ACTIVE persistent=%s lifecycle=%s lobby=%s management=canonical game_end_control=%s role_distribution=%s lobby_management_fix=%s stable_round=%s speaker_order=%s final_identity=%s voting_end_game=%s voting=%s voting_timer=%s voting_serverless=%s voting_end_target=%s voting_postfix=%s user_stats=%s scoring=%s",
    persistence_status, game_lifecycle_status, lobby_status, end_game_control_status, role_distribution_status, lobby_management_fix_status, stable_round_status, speaker_order_status, final_identity_status, voting_end_game_status, voting_runtime_status, voting_timer_status, voting_serverless_status, voting_end_target_status, voting_postfix_status, user_stats_status, player_scoring_status,
)


async def on_startup(dp):
    logging.info(
        "MafiaNights production startup; persistence=%s lifecycle=%s lobby=%s management=canonical game_end_control=%s role_distribution=%s lobby_management_fix=%s stable_round=%s speaker_order=%s final_identity=%s voting_end_game=%s voting=%s voting_timer=%s voting_serverless=%s voting_end_target=%s voting_postfix=%s user_stats=%s scoring=%s",
        persistence_status, game_lifecycle_status, lobby_status, end_game_control_status, role_distribution_status, lobby_management_fix_status, stable_round_status, speaker_order_status, final_identity_status, voting_end_game_status, voting_runtime_status, voting_timer_status, voting_serverless_status, voting_end_target_status, voting_postfix_status, user_stats_status, player_scoring_status,
    )
    await app.startup()
    try:
        allowed_group_id = int(os.getenv("ALLOWED_GROUP_ID", "-1002356353761"))
        active_game = app.runtime.state.active_game(allowed_group_id)
        if active_game:
            app.group_chat_id = allowed_group_id
            app.ui.group_chat_id = allowed_group_id
            rows = app.runtime.lobby_snapshot(allowed_group_id).get("players") or []
            app.player_slots = {int(row["seat"]): int(row["player_id"]) for row in rows if row.get("seat") is not None and str(row.get("status") or "active") not in {"removed", "dead"}}
            app.moderator_id = int(active_game.get("moderator_id") or 0) or None
            app.game_running = str(active_game.get("status") or "") in {"running", "paused", "turn"}
            state = dict(active_game.get("state") or {})
            app.turn_order = [int(x) for x in state.get("turn_order") or sorted(app.player_slots)]
            app.current_turn_index = int(active_game.get("current_turn_index") or 0)
        else:
            app.game_running = False
            app.round_active = False
            app.lobby_active = False
    except Exception:
        logging.exception("Failed to restore active Telegram game context")


async def on_shutdown(dp):
    await app.shutdown()


if __name__ == "__main__":
    from aiogram.utils import executor
    executor.start_polling(dp, skip_updates=True, on_startup=on_startup, on_shutdown=on_shutdown)
