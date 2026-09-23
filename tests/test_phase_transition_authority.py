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
