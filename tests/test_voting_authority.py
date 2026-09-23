import inspect

from runtime import voting_runtime
from runtime import voting_end_game_patch, voting_postfix, voting_timer_patch


def test_voting_uses_persistent_moderator_authority():
    source = inspect.getsource(voting_runtime._is_mod)
    assert 'game = _game(main)' in source
    assert 'game.get("moderator_id")' in source


def test_vote_is_durable_before_ui_confirmation():
    source = inspect.getsource(voting_runtime._cast)
    db_pos = source.index('_VOTES.cast(')
    ui_pos = source.index('_edit_vote_message(')
    assert db_pos < ui_pos
    assert 'inserted' in source


def test_legacy_timer_does_not_register_competing_handlers():
    source = inspect.getsource(voting_timer_patch.install)
    assert 'register_callback_query_handler' not in source


def test_voting_followups_use_persistent_moderator():
    for module in (voting_end_game_patch, voting_postfix):
        source = inspect.getsource(module)
        assert 'voting_runtime._game(main)' in source
