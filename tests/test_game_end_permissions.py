"""Regression tests for the game-end permission boundary."""
from runtime.game_end import _is_moderator_id


def test_game_end_moderator_owns_sensitive_actions():
    game = {"moderator_id": 1001}
    assert _is_moderator_id(game, 1001) is True


def test_game_end_group_admin_is_not_game_moderator():
    game = {"moderator_id": 1001}
    assert _is_moderator_id(game, 2002) is False


def test_game_end_missing_moderator_denies_sensitive_actions():
    assert _is_moderator_id({}, 1001) is False
