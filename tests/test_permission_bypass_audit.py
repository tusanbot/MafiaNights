"""Regression contracts for the final moderator permission boundary."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return (ROOT / path).read_text(encoding="utf-8")


def test_sensitive_text_commands_do_not_fallback_to_group_admins():
    source = read("commands.py")
    start = source.index("async def _simple_phase")
    end = source.index("async def _attendance_text")
    block = source[start:end]
    assert "await _manager(app, message, game)" not in block
    assert "_authorized(app, message)" in block


def test_finish_and_cancel_text_surfaces_are_moderator_only():
    source = read("runtime/end_game_control.py")
    assert 'allowed = uid == int(game.get("moderator_id") or 0)' in source
    assert 'get_chat_member(gid, uid)' not in source[source.index("async def finish_command"):source.index("async def _allowed")]

    source = read("runtime/cancel_command.py")
    assert 'uid != moderator' in source
    assert 'get_chat_member(gid, uid)' not in source


def test_legacy_callback_authorization_marks_sensitive_controls_moderator_only():
    source = read("runtime/callback_authorization.py")
    block = source[source.index("_MODERATOR_ONLY_EXACT"):source.index("_MODERATOR_ONLY_PREFIXES")]
    for name in ("choose_head", "challenge_toggle", "speaker_auto", "speaker_manual"):
        assert f'"{name}"' in block


def test_command_surface_v3_requires_moderator_for_sensitive_commands():
    source = read("runtime/command_surface_v3.py")
    assert 'if c in {"vote","end","chief","start"} and not await moderator(m,g):' in source
    assert 'str(g.get("status") or "") != "lobby" and not await moderator(m,g)' in source


def test_challenge_has_one_canonical_runtime_owner():
    entry = read("player_runtime_entry.py")
    engine = read("runtime/stable_round_engine.py")
    assert "install_challenge_authority" not in entry
    assert "install_lobby_challenge_v2" not in entry
    assert "_stable_challenge_request_handler = challenge_request" in engine
    assert "_stable_challenge_choice_handler = challenge_choice" in engine
    assert "_rearm_single_owner_challenge_handlers()" in entry


def test_challenge_legacy_response_executor_is_removed_by_final_cutover():
    entry = read("player_runtime_entry.py")
    assert 'if name == "handle_challenge_response":' in entry
    assert 'if name == "challenge_request" and module == "main1":' in entry


def test_production_entry_cuts_legacy_main1_game_executors():
    source = read("player_runtime_entry.py")
    assert "_rearm_single_owner_legacy_game_handlers()" in source
    assert '"start_round_handler"' in source
    assert '"next_turn"' in source
    assert '"start_night"' in source
    assert '"start_new_day"' in source
    assert '"global_message_control"' in source
    assert '"text_commands_handler"' in source


def test_legacy_cutover_does_not_remove_runtime_challenge_policy_wrappers():
    source = read("player_runtime_entry.py")
    block = source[source.index("def _rearm_single_owner_challenge_handlers"):source.index("def _rearm_single_owner_legacy_game_handlers")]
    assert 'module == "main1"' in block


def test_text_command_surface_delegates_lobby_membership_to_canonical_authority():
    source = read("commands.py")
    for call in ("app.lobby_membership.join", "app.lobby_membership.leave", "app.lobby_membership.assign_seat", "app.lobby_membership.promote_waiting"):
        assert call in source
    assert "app.runtime.state.lobby.join" not in source
    assert "app.runtime.state.lobby.leave" not in source
    assert "app.runtime.state.lobby.assign_seat" not in source


def test_text_cancel_is_a_thin_adapter_to_canonical_end_game_owner():
    source = read("commands.py")
    block = source[source.index("async def _cancel_game_text"):source.index("async def _player_state_action")]
    assert "_confirm_cancel_game" in block
    assert "update_game(" not in block
    assert "clear_game_players" not in block
    assert "cancel_text:" not in block


def test_final_command_authority_cancel_is_also_a_thin_adapter():
    source = read("runtime/command_authority_final.py")
    block = source[source.index("async def _cancel_text"):source.index("\ndef install")]
    assert "_confirm_cancel_game" in block
    assert "update_game(" not in block
    assert "get_chat_member" not in block


def test_final_production_cutover_does_not_install_duplicate_game_end_executor():
    source = read("runtime/production_cutover_final.py")
    assert "production_consistency_loader" not in source
    assert "production_consistency_v4" not in source
    assert "game-end=single" in source


def test_private_scenario_crud_is_the_live_scenario_form_owner():
    entry = read("player_runtime_entry.py")
    source = read("runtime/private_scenario_crud.py")
    form = read("runtime/scenario_form_v5.py")
    assert "install_private_scenario_crud(main)" in entry
    assert "ScenarioFormV5" in source
    assert "ScenarioManagementV3" in form
    assert "FeatureParityV" not in entry


def test_scenario_persistence_patch_is_adapter_only():
    source = read("runtime/scenario_persistence_patch.py")
    assert "ScenarioRepository" in source
    assert "register_callback_query_handler" not in source
    assert "register_message_handler" not in source


def test_single_owner_cutover_helpers_are_defined_before_invocation():
    source = read("player_runtime_entry.py")
    invoke = source.index("_rearm_single_owner_challenge_handlers()\n_rearm_single_owner_legacy_game_handlers()")
    challenge_def = source.index("def _rearm_single_owner_challenge_handlers")
    legacy_def = source.index("def _rearm_single_owner_legacy_game_handlers")
    assert challenge_def < invoke
    assert legacy_def < invoke


def test_legacy_dispatcher_cutover_only_removes_main1_executors():
    source = read("player_runtime_entry.py")
    block = source[source.index("def _rearm_single_owner_legacy_game_handlers"):source.index("def _rearm_canonical_new_game")]
    assert '__module__", "") == "main1"' in block
