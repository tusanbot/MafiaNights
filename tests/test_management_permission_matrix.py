"""Permission matrix contracts for active-game management mutations."""
from runtime.game_management import GameManagement


def test_active_game_mutation_is_moderator_only():
    game = {"status": "running", "moderator_id": 10}
    assert GameManagement._moderator_only(game, 10) is True
    assert GameManagement._moderator_only(game, 20) is False


def test_lobby_admin_is_not_moderator_for_sensitive_actions():
    game = {"status": "lobby", "moderator_id": 10}
    assert GameManagement._moderator_only(game, 20) is False


def test_missing_moderator_never_grants_sensitive_game_ownership():
    assert GameManagement._moderator_only({"status": "running"}, 10) is False
