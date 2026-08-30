from runtime.day_runtime import PersistentDayRuntime


class Games:
    def __init__(self):
        self.game = {"id": "g1", "group_chat_id": 1, "status": "running", "state": {"day_number": 2}}
        self.updated = []

    def get_active_game(self, group_id):
        return self.game

    def update_game(self, game_id, **fields):
        self.game.update(fields)
        self.updated.append(fields)
        return True


class State:
    def __init__(self):
        self.games = Games()

    def active_game(self, group_id):
        return self.games.get_active_game(group_id)


def test_start_new_day_is_persisted():
    runtime = PersistentDayRuntime(State())
    result = runtime.start_new_day(1)
    assert result["day"] == 3
    assert result["phase"] == "day"


def test_start_night_preserves_day_number():
    runtime = PersistentDayRuntime(State())
    result = runtime.start_night(1)
    assert result["day"] == 2
    assert result["phase"] == "night"
