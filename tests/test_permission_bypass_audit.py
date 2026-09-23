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
