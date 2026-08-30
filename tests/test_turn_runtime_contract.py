import pytest

from services.turn_service import TurnService


class FakeRepo:
    def __init__(self):
        self.started = None
        self.finished = None

    def start_turn(self, **kwargs):
        self.started = kwargs
        return {"id": "turn-1", **kwargs}

    def finish_turn(self, turn_id, state=None):
        self.finished = (turn_id, state)
        return True

    def current_turn(self, game_id):
        return None

    def list_turns(self, game_id):
        return []


def test_turn_service_rejects_invalid_turn_number():
    with pytest.raises(ValueError):
        TurnService(FakeRepo()).start("game", 0)


def test_turn_service_rejects_invalid_duration():
    with pytest.raises(ValueError):
        TurnService(FakeRepo()).start("game", 1, duration_seconds=0)


def test_turn_service_delegates_start_and_finish():
    repo = FakeRepo()
    service = TurnService(repo)
    created = service.start("game", 1, seat=3, player_id=99, duration_seconds=120,
                            current_turn_index=0, state={"phase": "day"})
    assert created["id"] == "turn-1"
    assert repo.started["seat"] == 3
    assert service.finish("turn-1", {"phase": "done"}) is True
    assert repo.finished == ("turn-1", {"phase": "done"})
