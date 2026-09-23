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


def test_head_selection_is_moderator_only():
    source = Path("runtime/role_distribution.py").read_text(encoding="utf-8")
    assert 'فقط گرداننده بازی می‌تواند سردست را انتخاب کند' in source
    assert 'get_chat_member(group_id, int(callback.from_user.id))' not in source


def test_role_distribution_is_moderator_only():
    source = Path("runtime/role_distribution.py").read_text(encoding="utf-8")
    block = source[source.index("    async def distribute_roles"):source.index("    app._role_distribution_handler")]
    assert 'allowed = uid == int(game.get("moderator_id") or 0)' in block
    assert 'فقط گرداننده بازی می‌تواند نقش‌ها را پخش کند' in block
    assert 'status not in {"creator", "administrator"}' not in block


def test_role_distribution_rolls_back_if_game_transition_fails():
    source = Path("runtime/role_distribution.py").read_text(encoding="utf-8")
    transition = source.index('status="running"')
    rollback = source.index("role distribution rollback after status transition failure")
    assert transition < rollback


def test_round_start_uses_durable_challenge_setting():
    source = Path("runtime/stable_round_engine.py").read_text(encoding="utf-8")
    assert 'main.challenge_active = bool(settings.get("enabled", True))' in source
    assert 'main.challenge_active = bool(getattr(main, "challenge_enabled"' not in source


def test_next_restores_active_challenge_from_durable_state():
    source = Path("runtime/stable_round_engine.py").read_text(encoding="utf-8")
    assert 'runtime_state = dict((game or {}).get("state") or {}).get("challenge_runtime") or {}' in source
    assert 'main.challenge_mode = True' in source
    assert 'main.active_challenger_seats = {int(challenger_seat)}' in source


def test_voting_start_requires_durable_day_finished_phase():
    source = Path("runtime/voting_runtime.py").read_text(encoding="utf-8")
    assert "def _voting_phase_allowed(main):" in source
    assert 'phase in {"day_finished", "voting"}' in source
    assert 'رأی‌گیری فقط پس از پایان فاز روز قابل شروع است' in source


def test_voting_settings_reject_stale_buttons_outside_day():
    source = Path("runtime/voting_runtime.py").read_text(encoding="utf-8")
    section = source[source.index("async def _settings_handler"):source.index("async def _round2_handler")]
    assert "_voting_phase_allowed(main)" in section
    assert "تنظیمات رأی‌گیری در این مرحله در دسترس نیست" in section


def test_start_night_rejects_stale_button_from_wrong_round_phase():
    source = Path("runtime/phase_transition_authority.py").read_text(encoding="utf-8")
    section = source[source.index("async def start_night"):source.index("    async def start_new_day")]
    assert 'round_phase not in {"day_finished", "voting", ""}' in section
    assert "stale" in section


def test_start_night_accepts_finished_voting_without_requiring_day_active():
    source = Path("runtime/phase_transition_authority.py").read_text(encoding="utf-8")
    section = source[source.index("async def start_night"):source.index("    async def start_new_day")]
    assert 'round_phase not in {"day_finished", "voting", ""}' in section
    assert 'not in {"round_finished", "finished", ""}' in section


def test_night_transition_clears_stale_challenge_runtime():
    source = Path("runtime/phase_transition_authority.py").read_text(encoding="utf-8")
    section = source[source.index("async def start_night"):source.index("    async def start_new_day")]
    assert 'state.pop("challenge_requests", None)' in section
    assert 'state.pop("challenge_runtime", None)' in section


def test_new_day_clears_stale_challenge_runtime_and_requests():
    source = Path("runtime/phase_transition_authority.py").read_text(encoding="utf-8")
    section = source[source.index("async def start_new_day"):source.index("    # Remove legacy owners")]
    assert 'state.pop("challenge_requests", None)' in section
    assert 'state.pop("challenge_runtime", None)' in section


def test_accepted_challenge_removes_durable_request_before_runtime_creation():
    source = Path("runtime/stable_round_engine.py").read_text(encoding="utf-8")
    marker = 'state["challenge_runtime"] = {'
    section = source[source.index("    async def challenge_choice"):source.index("    main._stable_round_start_handler")]
    assert 'requests = dict((state.get("challenge_requests") or {}))' in section
    assert 'requests.pop(str(target_seat), None)' in section
    assert marker in section


def test_challenge_request_requires_durable_write_before_local_lock():
    source = Path("runtime/stable_round_engine.py").read_text(encoding="utf-8")
    section = source[source.index("    async def challenge_request"):source.index("    async def challenge_choice")]
    assert 'if not main.runtime.state.games.update_game(game["id"], state=state):' in section
    assert section.index('update_game(game["id"], state=state)') < section.index("main._stable_challenge_requests[target_seat] = challenger_id")


def test_challenge_choice_uses_durable_request_as_authority():
    source = Path("runtime/stable_round_engine.py").read_text(encoding="utf-8")
    section = source[source.index("    async def challenge_choice"):source.index("    main._stable_round_start_handler")]
    assert 'persisted = dict((game or {}).get("state") or {}).get("challenge_requests") or {}' in section
    assert "درخواست چالش منقضی یا پیدا نشد" in section


def test_accepted_challenge_persists_runtime_before_local_activation():
    source = Path("runtime/stable_round_engine.py").read_text(encoding="utf-8")
    section = source[source.index("    async def challenge_choice"):source.index("    main._stable_round_start_handler")]
    assert 'state["challenge_runtime"] = {' in section
    assert 'if not main.runtime.state.games.update_game(game["id"], state=state):' in section
    assert section.index('state["challenge_runtime"] = {') < section.index("main.challenge_mode = True")


def test_text_phase_commands_delegate_to_canonical_phase_authority():
    source = Path("commands.py").read_text(encoding="utf-8")
    section = source[source.index("async def _simple_phase"):source.index("async def _callback_answer")]
    assert "_start_night_handler" in section
    assert "_start_new_day_handler" in section
    assert "app.runtime.days.start_night" not in section
    assert "app.runtime.days.start_new_day" not in section


def test_phase_authority_exposes_canonical_text_entry_handlers():
    source = Path("runtime/phase_transition_authority.py").read_text(encoding="utf-8")
    assert "app._start_night_handler = start_night" in source
    assert "app._start_new_day_handler = start_new_day" in source


def test_challenge_toggle_persists_durable_game_state_before_success():
    source = Path("commands.py").read_text(encoding="utf-8")
    section = source[source.index("async def _challenge_toggle_text"):source.index("async def _attendance_text")]
    assert 'state["challenge_enabled"] = bool(enabled)' in section
    assert 'if not app.runtime.state.games.update_game(game["id"], state=state):' in section


def test_chat_lock_uses_durable_turn_authority_before_local_fallback():
    source = Path("runtime/chat_locks.py").read_text(encoding="utf-8")
    section = source[source.index("def _current_turn_uid"):source.index("def _full_permissions")]
    assert 'authority = getattr(main, "turn_round_authority", None)' in section
    assert "snapshot = authority.snapshot(gid)" in section


def test_chat_lock_precedence_is_night_then_turn_then_chat():
    source = Path("runtime/chat_locks.py").read_text(encoding="utf-8")
    section = source[source.index("    if night_lock:"):source.index("def install")]
    assert section.index("if night_lock:") < section.index("if turn_lock:")
    assert section.index("if turn_lock:") < section.index("if chat_lock:")


def test_text_command_reference_includes_lock_unlock_commands():
    source = Path("commands.py").read_text(encoding="utf-8")
    assert '"chatunlock"' in source
    assert '"nightunlock"' in source
    assert '"turnunlock"' in source
    assert 'BotCommand("chatunlock"' in source
    assert 'BotCommand("nightunlock"' in source
    assert 'BotCommand("turnunlock"' in source


def test_start_round_text_command_has_no_local_state_fallback():
    source = Path("commands.py").read_text(encoding="utf-8")
    section = source[source.index("async def _start_round_text"):source.index("async def _next_text")]
    assert 'app.runtime.state.games.update_game(game["id"], state=state, current_turn_index=0)' not in section
    assert 'handler = getattr(app, "_stable_round_start_handler", None)' in section
    assert 'مسیر اصلی شروع دور در دسترس نیست' in section


def test_next_text_command_delegates_without_local_turn_authority():
    source = Path("commands.py").read_text(encoding="utf-8")
    section = source[source.index("async def _next_text"):source.index("async def _end_game_text")]
    assert 'getattr(app, "turn_order"' not in section
    assert 'getattr(app, "current_turn_index"' not in section
    assert 'handler = getattr(app, "_stable_next_handler", None)' in section
    assert 'next_canonical' in section
