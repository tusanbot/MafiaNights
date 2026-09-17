"""MafiaNights production entry point."""
from __future__ import annotations

import logging
import os

from main_refactored_v4 import MafiaApplicationV4
from runtime.final_persistence import install as install_persistence
from runtime.game_management import GameManagement
from runtime.game_lifecycle import install as install_game_lifecycle
from runtime.lobby_ui_final import install as install_lobby_ui
from runtime.management_surface_final import install as install_management_surface
from runtime.role_distribution import install as install_role_distribution
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
from runtime.mafia_progress_events import install as install_mafia_progress_events
from runtime.end_game_control import install as install_end_game_control
from runtime.production_consistency_loader import install as install_production_consistency
from runtime.dual_winner_support import install as install_dual_winner_support

TOKEN = os.getenv("API_TOKEN")
if not TOKEN:
    raise ValueError("API_TOKEN environment variable is not set!")

logging.basicConfig(level=logging.INFO)
app = MafiaApplicationV4(TOKEN)
bot = app.bot
dp = app.dp

persistence_status = install_persistence(app)
management = GameManagement(app)
app.game_management = management
install_game_lifecycle(app, management)
management.install()
install_lobby_ui(app)
install_management_surface(app)

install_role_distribution(app)
app._canonical_distribute_roles = app._role_distribution_handler
if getattr(app, "_render_final_lobby", None):
    app._render_production_lobby = app._render_final_lobby

install_stable_round_engine(app)
install_voting_end_game_patch(app)
install_voting_runtime(app)
install_voting_timer_patch(app)
install_voting_serverless_patch(app)
install_voting_end_target_patch(app)
install_voting_postfix(app)
install_speaker_order_authority(app)
install_final_identity_authority(app)
install_user_stats(app)
install_player_scoring(app)
install_mafia_progress_events(app)

# The progress module intentionally registers its private FSM handler first.
# Keep the group publication command ahead of that private-state fallback.
for _item in list(getattr(dp.message_handlers, "handlers", [])):
    _callback = getattr(_item, "callback", None) or getattr(_item, "handler", None)
    if getattr(_callback, "__name__", "") == "group_incidents":
        dp.message_handlers.handlers.remove(_item)
        dp.message_handlers.handlers.insert(0, _item)
        break

install_end_game_control(app)
install_production_consistency(app)
install_dual_winner_support(app)

logging.info("PRODUCTION_RUNTIME_ACTIVE lobby=runtime.lobby_ui_final management=game_management+management_surface_final progress=achievements+tags+events+incidents")


async def on_startup(dp):
    logging.info("MafiaNights production startup")
    await app.startup()
    try:
        allowed_group_id = int(os.getenv("ALLOWED_GROUP_ID", "-1002356353761"))
        active_game = app.runtime.state.active_game(allowed_group_id)
        if active_game:
            app.group_chat_id = allowed_group_id
            app.ui.group_chat_id = allowed_group_id
            rows = app.runtime.lobby_snapshot(allowed_group_id).get("players") or []
            app.player_slots = {
                int(row["seat"]): int(row["player_id"])
                for row in rows
                if row.get("seat") is not None and str(row.get("status") or "active") not in {"removed", "dead"}
            }
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
