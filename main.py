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
from runtime.progress_features_v4 import install as install_progress_features
from runtime.end_game_control import install as install_end_game_control
from runtime.production_consistency_loader import install as install_production_consistency
from runtime.dual_winner_support import install as install_dual_winner_support
from runtime.assistant_admin_panel import install as install_assistant_admin_panel
from runtime.chat_locks import install as install_chat_locks
from runtime.pv_menu_callbacks import install as install_pv_menu_callbacks
from commands import register_commands as register_canonical_commands

TOKEN=os.getenv("API_TOKEN")
if not TOKEN:raise ValueError("API_TOKEN environment variable is not set!")
logging.basicConfig(level=logging.INFO)
app=MafiaApplicationV4(TOKEN);bot=app.bot;dp=app.dp
persistence_status=install_persistence(app)
management=GameManagement(app);app.game_management=management
install_game_lifecycle(app,management);management.install();install_lobby_ui(app);install_management_surface(app)
install_role_distribution(app);app._canonical_distribute_roles=app._role_distribution_handler
if getattr(app,"_render_final_lobby",None):app._render_production_lobby=app._render_final_lobby
install_stable_round_engine(app);install_voting_end_game_patch(app);install_voting_runtime(app);install_voting_timer_patch(app);install_voting_serverless_patch(app);install_voting_end_target_patch(app);install_voting_postfix(app);install_speaker_order_authority(app);install_final_identity_authority(app);install_user_stats(app);install_player_scoring(app);install_progress_features(app)

# Keep the group publication command ahead of the private FSM fallback.
for _item in list(getattr(dp.message_handlers,"handlers",[])):
    _callback=getattr(_item,"callback",None) or getattr(_item,"handler",None)
    if getattr(_callback,"__name__","")=="group_command":
        dp.message_handlers.handlers.remove(_item);dp.message_handlers.handlers.insert(0,_item);break

install_end_game_control(app);install_production_consistency(app);install_dual_winner_support(app);app.assistant_admin_panel=install_assistant_admin_panel(app)
install_chat_locks(app)
install_pv_menu_callbacks(app)

# Canonical text-command authority:
# all game/user text commands are registered exactly once from commands.py.
# Legacy command handlers remain available in source for compatibility, but
# their message registrations are removed here so they cannot shadow or
# duplicate the canonical registry.
register_canonical_commands(app)
_legacy_command_modules = {
    "runtime.text_commands",
    "runtime.command_surface_v2",
    "runtime.command_surface_v3",
    "runtime.command_authority_final",
    "runtime.telegram_commands",
    "runtime.end_game_control",
    "runtime.user_stats",
    "runtime.lobby_ui_final",
    "runtime.player_kick",
}
for _item in list(getattr(dp.message_handlers, "handlers", [])):
    _fn = getattr(_item, "callback", None) or getattr(_item, "handler", None)
    if getattr(_fn, "__module__", "") in _legacy_command_modules:
        try:
            dp.message_handlers.handlers.remove(_item)
        except ValueError:
            pass
# Re-register the single canonical handler after legacy registrations have been
# removed, then keep it at the front of the message chain.
register_canonical_commands(app)
try:
    _handlers = getattr(dp.message_handlers, "handlers", [])
    _canonical = [x for x in _handlers if getattr(getattr(x, "handler", None) or getattr(x, "callback", None), "__module__", "") == "commands"]
    _guard = next((x for x in _handlers if getattr(getattr(x, "handler", None) or getattr(x, "callback", None), "__name__", "") == "chat_lock_message_guard"), None)
    for _x in _canonical:
        try: _handlers.remove(_x)
        except ValueError: pass
    if _guard in _handlers:
        _pos = _handlers.index(_guard) + 1
        for _x in _canonical:
            _handlers.insert(_pos, _x); _pos += 1
    else:
        for _x in reversed(_canonical):
            _handlers.insert(0, _x)
except Exception:
    logging.exception("Failed to prioritize canonical text command handler")

logging.info("PRODUCTION_RUNTIME_ACTIVE canonical_text_commands=commands.py locks=runtime.chat_locks pv_menu_callbacks=runtime.pv_menu_callbacks")

async def on_startup(dp):
    logging.info("MafiaNights production startup");await app.startup()
    try:
        if getattr(app, "_register_telegram_commands", None):
            await app._register_telegram_commands()
    except Exception:
        logging.exception("Canonical Telegram command menu startup failed")
    try:
        allowed_group_id=int(os.getenv("ALLOWED_GROUP_ID","-1002356353761"));active_game=app.runtime.state.active_game(allowed_group_id)
        if active_game:
            app.group_chat_id=allowed_group_id;app.ui.group_chat_id=allowed_group_id;rows=app.runtime.lobby_snapshot(allowed_group_id).get("players") or []
            app.player_slots={int(row["seat"]):int(row["player_id"]) for row in rows if row.get("seat") is not None and str(row.get("status") or "active") not in {"removed","dead"}}
            app.moderator_id=int(active_game.get("moderator_id") or 0) or None;app.game_running=str(active_game.get("status") or "") in {"running","paused","turn"};state=dict(active_game.get("state") or {});app.turn_order=[int(x) for x in state.get("turn_order") or sorted(app.player_slots)];app.current_turn_index=int(active_game.get("current_turn_index") or 0)
        else:app.game_running=False;app.round_active=False;app.lobby_active=False
    except Exception:logging.exception("Failed to restore active Telegram game context")

async def on_shutdown(dp):await app.shutdown()

if __name__=="__main__":
    from aiogram.utils import executor
    executor.start_polling(dp,skip_updates=True,on_startup=on_startup,on_shutdown=on_shutdown)
