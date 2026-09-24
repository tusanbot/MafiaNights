from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _source(path):
    return (ROOT / path).read_text(encoding="utf-8")


def test_voting_uses_persistent_moderator_authority():
    source = _source("runtime/voting_runtime.py")
    start = source.index("def _is_mod")
    end = source.index("\n\n", start)
    section = source[start:end]
    assert "game = _game(main)" in section
    assert 'game.get("moderator_id")' in section


def test_vote_is_durable_before_ui_confirmation():
    source = _source("runtime/voting_runtime.py")
    start = source.index("async def _cast")
    end = source.index("\n\nasync def _manual_start", start)
    section = source[start:end]
    assert section.index("_VOTES.cast(") < section.index("_edit_vote_message(")
    assert "inserted" in section


def test_legacy_timer_does_not_register_competing_handlers():
    source = _source("runtime/voting_timer_patch.py")
    assert "register_callback_query_handler" not in source


def test_voting_followups_use_persistent_moderator():
    for path in ("runtime/voting_end_game_patch.py", "runtime/voting_postfix.py"):
        source = _source(path)
        assert "voting_runtime._game(main)" in source
