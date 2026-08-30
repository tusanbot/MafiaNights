import pytest

from services.challenge_service import ChallengeService
from runtime.challenge_runtime import PersistentChallengeRuntime


class FakeChallengeRepo:
    def __init__(self):
        self.created = None
        self.resolved = None
        self.rows = []

    def create_challenge(self, **kwargs):
        self.created = kwargs
        row = {"id": "challenge-1", **kwargs}
        self.rows.append(row)
        return "challenge-1"

    def resolve_challenge(self, challenge_id, status):
        self.resolved = (challenge_id, status)
        return True

    def list_challenges(self, game_id):
        return [row for row in self.rows if row["game_id"] == game_id]


def test_challenge_rejects_self_target():
    with pytest.raises(ValueError):
        ChallengeService(FakeChallengeRepo()).create(
            game_id="game-1", challenger_id=10, target_id=10, mode="before"
        )


def test_challenge_rejects_unknown_mode():
    with pytest.raises(ValueError):
        ChallengeService(FakeChallengeRepo()).create(
            game_id="game-1", challenger_id=10, target_id=11, mode="invalid"
        )


def test_challenge_delegates_create_and_resolve():
    repo = FakeChallengeRepo()
    service = ChallengeService(repo)
    assert service.create(
        game_id="game-1", challenger_id=10, target_id=11, mode="after"
    ) == "challenge-1"
    assert service.resolve("challenge-1", "accepted") is True
    assert repo.resolved == ("challenge-1", "accepted")


def test_runtime_module_exists_without_telegram_dependency():
    assert PersistentChallengeRuntime is not None
