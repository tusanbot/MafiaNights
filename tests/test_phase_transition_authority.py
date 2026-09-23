from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def src(path):
    return (ROOT / path).read_text(encoding="utf-8")


def test_phase_transition_authority_is_installed_in_production():
    source = src("player_runtime_entry.py")
    assert "phase_transition_authority" in source
    assert "install_phase_transition_authority(main)" in source


def test_phase_transition_removes_legacy_night_day_handlers():
    source = src("runtime/phase_transition_authority.py")
    assert 'legacy_names = {"start_night", "start_new_day"}' in source
    assert 'callback_data="start_new_day"' in source


def test_night_transition_persists_durable_phase():
    source = src("runtime/phase_transition_authority.py")
    section = source[source.index("async def start_night"):source.index("    async def start_new_day")]
    assert 'state["round_phase"] = "night"' in section
    assert 'update_game(game["id"], state=state)' in section


def test_next_day_clears_stale_voting_and_head_state():
    source = src("runtime/phase_transition_authority.py")
    section = source[source.index("async def start_new_day"):source.index("    # Remove legacy owners")]
    assert 'state.pop("head_seat", None)' in section
    assert 'state.pop("voting", None)' in section
    assert 'state["round_phase"] = "day_setup"' in section


def test_manual_end_game_accepts_active_runtime_statuses():
    source = Path("runtime/game_end.py").read_text(encoding="utf-8")
    assert 'not in {"running", "paused", "turn"}' in source
    assert 'callback_data="end_game"' in Path("runtime/voting_runtime.py").read_text(encoding="utf-8")


def test_voting_end_does_not_finalize_game_automatically():
    source = Path("runtime/voting_runtime.py").read_text(encoding="utf-8")
    start = source.index("async def _end(main, callback):")
    end = source.index("async def _noop", start)
    block = source[start:end]
    assert 'status="finished"' not in block
    assert 'update_game' not in block
    assert 'callback_data="end_game"' in block
    assert 'callback_data="start_night"' in block


def test_manual_end_game_command_remains_available():
    source = Path("runtime/end_game_control.py").read_text(encoding="utf-8")
    assert '"/endgame"' in source
    assert '"اتمام بازی"' in source
    assert 'status") or "") not in {"running", "paused", "turn"}' in source


def test_next_day_controls_use_canonical_head_and_round_callbacks():
    source = Path("runtime/phase_transition_authority.py").read_text(encoding="utf-8")
    assert 'callback_data=f"day:{int(game[\'id\'])}:head"' in source
    assert 'callback_data="start_round"' in source
    assert 'callback_data="choose_head"' not in source
    assert 'callback_data="start_turn"' not in source


def test_role_distribution_rolls_back_partial_persistence():
    source = Path("runtime/role_distribution.py").read_text(encoding="utf-8")
    assert 'previous_roles = {int(p["player_id"]): p.get("role") for p in players}' in source
    assert "if save_failures:" in source
    assert "Role assignment is a pre-game transaction" in source
    assert "rolled back" in source


def test_role_distribution_never_enters_running_before_all_role_writes_succeed():
    source = Path("runtime/role_distribution.py").read_text(encoding="utf-8")
    failure = source.index("if save_failures:")
    running = source.index('status="running"')
    assert failure < running


def test_start_round_treats_day_setup_as_authoritative():
    source = Path("runtime/stable_round_engine.py").read_text(encoding="utf-8")
    assert 'round_phase = str((game.get("state") or {}).get("round_phase") or "").strip().lower()' in source
    assert 'if round_phase == "day_setup":' in source
    assert 'main._stable_day_ended = False' in source
    assert '"round_phase": "day_active"' in source


def test_day_end_persists_terminal_phase():
    source = Path("runtime/stable_round_engine.py").read_text(encoding="utf-8")
    assert '"round_phase": "day_finished"' in source
